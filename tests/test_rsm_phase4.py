"""RSM Milestone 4 suite — RSM/05-implementation-spec.md M4.

Covers: RSM-I11 eviction ordering (all 2^3 - 1 partial-precondition
combinations must NOT evict, exhaustively, plus the real store/evict_gate
integration for the combinations the state machine can actually reach);
checkpoint prefix correctness (a checkpoint's persisted prefix, replayed
alone through a fresh pipeline, reproduces the same block state the live
record held at that checkpoint's sequence number); late-tolerant
`cost.recorded` arriving after terminal and after persisted (applies,
re-triggers a journal-index write, does not block or reverse eviction
eligibility for the other two preconditions).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rsm.store import Store, eviction_allowed
from rsm.journal import Journal
from rsm.ingest import Ingest, make_event, APPLIED
from rsm import persistence
from rsm import transitions
from ums.storage_double import StorageDouble


class FakeClock:
    """Injectable zero-arg time source (no sleep, no wall-clock reads)."""

    def __init__(self, start=0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _drive_birth(ing, request_id, event_id="e0"):
    return ing.process(make_event(event_id, "request.received", request_id, 1,
                                   {"declared_type": "a", "origin": "fe"}))


def _drive_to_terminal(ing, request_id):
    _drive_birth(ing, request_id)
    ing.process(make_event("t-" + request_id, "request.completed", request_id, 1, {}))


class EvictionPreconditionPropertyTests(unittest.TestCase):
    """RSM-I11: eviction requires all three of terminal, persisted,
    retention elapsed. Property test over all 2^3 - 1 partial combinations
    (RSM/05 M4) — every combination except all-True must NOT evict."""

    def test_all_eight_combinations_only_all_true_evicts(self):
        for terminal in (False, True):
            for persisted in (False, True):
                for retention_elapsed in (False, True):
                    with self.subTest(terminal=terminal, persisted=persisted,
                                       retention_elapsed=retention_elapsed):
                        allowed = eviction_allowed(terminal, persisted, retention_elapsed)
                        expect_evict = terminal and persisted and retention_elapsed
                        self.assertIs(allowed, expect_evict)
                        if not expect_evict:
                            self.assertFalse(allowed)

    def test_seven_partial_combinations_enumerated_explicitly(self):
        # Belt-and-suspenders: name every one of the seven "not all three"
        # rows so a regression that flips exactly one row's meaning still
        # fails a readably-named case, not just the loop above.
        partial_combos = [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
        ]
        self.assertEqual(len(partial_combos), 7)
        for terminal, persisted, retention_elapsed in partial_combos:
            self.assertFalse(eviction_allowed(terminal, persisted, retention_elapsed))
        self.assertTrue(eviction_allowed(True, True, True))

    def test_evict_gate_refuses_while_only_terminal_reached(self):
        # terminal=True, persisted=False, retention_elapsed=False (the
        # elapsed check is meaningless without a persisted_at, so it's also
        # effectively False) — the one combination the real state machine
        # reaches naturally before persistence ever runs.
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        clock = FakeClock(0)
        _drive_to_terminal(ing, "r1")
        self.assertFalse(store.evict_gate("r1", clock, retention_window=0))
        self.assertEqual(store.state_of("r1"), transitions.TERMINAL)

    def test_evict_gate_refuses_while_persisted_but_not_elapsed(self):
        # terminal=True, persisted=True, retention_elapsed=False.
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        clock = FakeClock(0)
        _drive_to_terminal(ing, "r1")
        persistence.persist_terminal(storage, journal, store, "r1", clock)
        self.assertEqual(store.state_of("r1"), transitions.PERSISTED)

        clock.advance(9)
        self.assertFalse(store.evict_gate("r1", clock, retention_window=10))
        self.assertEqual(store.state_of("r1"), transitions.PERSISTED)

    def test_evict_gate_fires_only_once_all_three_hold(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        clock = FakeClock(0)
        _drive_to_terminal(ing, "r1")
        persistence.persist_terminal(storage, journal, store, "r1", clock)

        clock.advance(10)
        self.assertTrue(store.evict_gate("r1", clock, retention_window=10))
        self.assertEqual(store.state_of("r1"), transitions.EVICTED)


class CheckpointPrefixCorrectnessTests(unittest.TestCase):
    """A checkpoint's persisted prefix, replayed alone through a fresh
    store/journal/ingest, reproduces the same block state the live record
    held at that checkpoint's sequence number (RSM/03 §11, RSM/05 M4)."""

    def _script(self, request_id):
        """Fixed event sequence, kept as the test's own record of what was
        published — the checkpoint document stores a block-state snapshot,
        not the raw events (RSM/05 §3: journal holds ids, not payloads), so
        a "replay the prefix" check needs the original event stream from
        somewhere. This is the test fixture playing that role."""
        return [
            make_event("e0", "request.received", request_id, 1,
                       {"declared_type": "a", "origin": "fe"}),
            make_event("e1", "task.scheduled", request_id, 1,
                       {"task_id": "t1", "budget_granted": 10}),
            make_event("e2", "cost.recorded", request_id, 1, {"amount": 3}),
            make_event("e3", "task.started", request_id, 1, {"task_id": "t1"}),
            make_event("e4", "cost.recorded", request_id, 1, {"amount": 2}),
            make_event("e5", "task.completed", request_id, 1, {"task_id": "t1"}),
        ]

    def test_checkpoint_at_seq_reproduces_live_state_at_that_seq(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        events = self._script("r1")

        checkpoint_docs = []
        for event in events:
            self.assertEqual(ing.process(event), APPLIED)
            doc = persistence.maybe_checkpoint(storage, journal, store, "r1", checkpoint_n=3)
            if doc is not None:
                checkpoint_docs.append(doc)

        self.assertEqual(len(checkpoint_docs), 2)  # 6 events, N=3 -> seq 2 and seq 5
        doc = checkpoint_docs[0]
        self.assertEqual(doc["seq"], 2)
        prefix_ids = [entry[0] for entry in doc["journal_prefix"]]
        self.assertEqual(prefix_ids, ["e0", "e1", "e2"])

        # replay the prefix alone through a fresh pipeline
        replay_store, replay_journal = Store(), Journal()
        replay_ing = Ingest(replay_store, replay_journal)
        for event in events:
            if event["event_id"] in prefix_ids:
                self.assertEqual(replay_ing.process(event), APPLIED)

        replayed_record = replay_store.get("r1")
        checkpoint_record = persistence.record_from_checkpoint(doc)
        self.assertEqual(replayed_record.work, checkpoint_record.work)
        self.assertEqual(replayed_record.budget, checkpoint_record.budget)
        self.assertEqual(replayed_record.lifecycle, checkpoint_record.lifecycle)
        self.assertEqual(replayed_record.version, checkpoint_record.version)

    def test_second_checkpoint_prefix_also_reproduces_live_state(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        events = self._script("r2")

        docs = []
        for event in events:
            ing.process(event)
            doc = persistence.maybe_checkpoint(storage, journal, store, "r2", checkpoint_n=3)
            if doc is not None:
                docs.append(doc)

        second = docs[1]
        self.assertEqual(second["seq"], 5)
        prefix_ids = [entry[0] for entry in second["journal_prefix"]]
        self.assertEqual(prefix_ids, ["e0", "e1", "e2", "e3", "e4", "e5"])

        replay_store, replay_journal = Store(), Journal()
        replay_ing = Ingest(replay_store, replay_journal)
        for event in events:
            replay_ing.process(event)

        replayed_record = replay_store.get("r2")
        checkpoint_record = persistence.record_from_checkpoint(second)
        self.assertEqual(replayed_record.work, checkpoint_record.work)
        self.assertEqual(replayed_record.lifecycle, {})  # r2's script never terminates
        self.assertEqual(checkpoint_record.lifecycle, {})
        self.assertEqual(replayed_record.budget, checkpoint_record.budget)


class LateTolerantAfterTerminalAndPersistedTests(unittest.TestCase):
    """Late-tolerant `cost.recorded` arriving after terminal, and again
    after persisted: applies, re-triggers a journal-index write, does not
    block or reverse eviction eligibility of the other two preconditions
    (RSM/03 §3 "persisted is not read-only-yet-mutable-again")."""

    def test_cost_recorded_after_terminal_applies_and_stays_terminal(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e2", "request.completed", "r1", 1, {}))
        self.assertEqual(store.state_of("r1"), transitions.TERMINAL)

        result = ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 4}))
        self.assertEqual(result, APPLIED)
        self.assertEqual(store.get("r1").budget, {"granted": 10, "consumed": 4})
        self.assertEqual(store.state_of("r1"), transitions.TERMINAL)  # unchanged

    def test_cost_recorded_after_persisted_applies_and_re_triggers_journal_write(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        clock = FakeClock(0)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e2", "request.completed", "r1", 1, {}))
        persistence.persist_terminal(storage, journal, store, "r1", clock)
        self.assertEqual(store.state_of("r1"), transitions.PERSISTED)

        journal_before = persistence.read_journal_index(storage, "r1")
        self.assertEqual(len(journal_before["entries"]), 3)  # birth, scheduled, terminal

        result = ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 7}))
        self.assertEqual(result, APPLIED)
        self.assertEqual(store.get("r1").budget, {"granted": 10, "consumed": 7})
        self.assertEqual(store.state_of("r1"), transitions.PERSISTED)  # unchanged

        # persisted journal index is stale until re-triggered
        journal_still_stale = persistence.read_journal_index(storage, "r1")
        self.assertEqual(len(journal_still_stale["entries"]), 3)

        persistence.reapply_journal_index(storage, journal, "r1")
        journal_after = persistence.read_journal_index(storage, "r1")
        self.assertEqual(len(journal_after["entries"]), 4)
        self.assertEqual(journal_after["entries"][3][0], "e3")

        # terminal snapshot is untouched by the late re-trigger (RSM/03 §2:
        # it's a snapshot of the terminal moment, not a running mirror)
        terminal_snapshot = persistence.read_terminal_snapshot(storage, "r1")
        self.assertEqual(terminal_snapshot.budget, {"granted": 10})

    def test_late_cost_recorded_does_not_block_or_reverse_eviction_eligibility(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        clock = FakeClock(0)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e2", "request.completed", "r1", 1, {}))
        persistence.persist_terminal(storage, journal, store, "r1", clock)

        # late-tolerant apply lands mid-retention-window
        clock.advance(3)
        ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 1}))
        persistence.reapply_journal_index(storage, journal, "r1")

        # still not evictable — retention window (measured from the
        # original persisted_at, not reset by the late apply) hasn't elapsed
        self.assertFalse(store.evict_gate("r1", clock, retention_window=10))
        self.assertEqual(store.state_of("r1"), transitions.PERSISTED)

        # once the (unreset) window elapses, eviction still fires normally —
        # the late apply neither blocked nor permanently reversed eligibility
        clock.advance(7)
        self.assertTrue(store.evict_gate("r1", clock, retention_window=10))
        self.assertEqual(store.state_of("r1"), transitions.EVICTED)


if __name__ == "__main__":
    unittest.main()
