"""RSM Milestone 1 suite — RSM/05-implementation-spec.md M1.

Covers: transition-table exhaustive coverage (every (record state, event
family) row from RSM/03-internal-design.md §3, including the "unchanged"
rows — unregistered family, malformed event, evicted-state fault);
duplicate request.received for an already-active id (must not re-create,
RSM-I1); unknown-id fault (any non-birth event against absent produces a
fault outcome, no record created, RSM-I10); birth/terminal wired end to end
at the store level; record immutability/versioning (RSM-I9).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rsm import record as record_mod
from rsm import transitions
from rsm.store import Store
from rsm.transitions import (
    ABSENT, ACTIVE, TERMINAL, PERSISTED, RETAINED, EVICTED, STATES,
    BIRTH_FAMILY, TERMINAL_FAMILIES, LATE_TOLERANT_FAMILIES,
    CONTRIBUTING_FAMILIES, CREATE, APPLY, APPLY_TERMINAL, FAULT, DROP,
    UNREGISTERED, Row, lookup,
)

_TERMINAL_LIKE = (TERMINAL, PERSISTED, RETAINED)
UNREGISTERED_FAMILY = "memory.indexed"  # real family, but no RSM reducer (RSM/03 §4)


def _terminate(store, request_id, lifecycle_update):
    """M2 replaced store.mark_terminal(lifecycle_update) with reducer
    dispatch (RSM/05 M2) — store.apply_terminal now takes the full
    post-reducer record. This test helper plays the terminal reducer's
    role (record.evolve(lifecycle=...)) so M1's store-level coverage keeps
    testing the same store behavior under the new API."""
    rec = store.get(request_id)
    return store.apply_terminal(request_id, rec.evolve(lifecycle=dict(lifecycle_update)))


class RecordTests(unittest.TestCase):
    def test_birth_snapshot(self):
        rec = record_mod.birth("r1", {"declared_type": "type.alpha"})
        self.assertEqual(rec.version, 0)
        self.assertEqual(rec.identity["declared_type"], "type.alpha")
        self.assertEqual(rec.lifecycle, {})
        self.assertEqual(rec.failure, ())

    def test_evolve_produces_new_version_original_untouched(self):
        rec = record_mod.birth("r1", {})
        rec2 = rec.evolve(lifecycle={"state": "executing"})
        self.assertEqual(rec2.version, 1)
        self.assertEqual(rec2.lifecycle, {"state": "executing"})
        # old snapshot is untouched — a reader holding it never sees the mutation (RSM-I9)
        self.assertEqual(rec.version, 0)
        self.assertEqual(rec.lifecycle, {})
        self.assertIsNot(rec2, rec)

    def test_evolve_carries_over_unnamed_blocks(self):
        rec = record_mod.birth("r1", {"declared_type": "type.alpha"})
        rec2 = rec.evolve(work={"current_step": "s1"})
        self.assertEqual(rec2.identity, rec.identity)
        self.assertEqual(rec2.budget, rec.budget)

    def test_evolve_rejects_unknown_block(self):
        rec = record_mod.birth("r1", {})
        with self.assertRaises(ValueError):
            rec.evolve(not_a_block={"x": 1})

    def test_record_is_frozen(self):
        rec = record_mod.birth("r1", {})
        with self.assertRaises(Exception):
            rec.identity = {}

    def test_failure_block_is_append_only_by_convention(self):
        rec = record_mod.birth("r1", {})
        rec2 = rec.evolve(failure=rec.failure + ({"family": "task.failed"},))
        self.assertEqual(rec2.failure, ({"family": "task.failed"},))
        self.assertEqual(rec.failure, ())  # prior version's entry list never grows


class TransitionTableExhaustiveTests(unittest.TestCase):
    """Every (record state, event family) row in RSM/03 §3, at least once."""

    def test_absent_birth_creates(self):
        self.assertEqual(lookup(ABSENT, BIRTH_FAMILY), Row(CREATE, ACTIVE))

    def test_absent_non_birth_recognized_family_faults_no_autocreate(self):
        for family in sorted(CONTRIBUTING_FAMILIES) + sorted(TERMINAL_FAMILIES) + sorted(LATE_TOLERANT_FAMILIES):
            with self.subTest(family=family):
                self.assertEqual(lookup(ABSENT, family), Row(FAULT, ABSENT))

    def test_active_contributing_family_applies_stays_active(self):
        for family in sorted(CONTRIBUTING_FAMILIES):
            with self.subTest(family=family):
                self.assertEqual(lookup(ACTIVE, family), Row(APPLY, ACTIVE))

    def test_active_terminal_family_applies_moves_to_terminal(self):
        for family in sorted(TERMINAL_FAMILIES):
            with self.subTest(family=family):
                self.assertEqual(lookup(ACTIVE, family), Row(APPLY_TERMINAL, TERMINAL))

    def test_active_duplicate_event_id_silent_drop(self):
        for family in sorted(CONTRIBUTING_FAMILIES) + sorted(TERMINAL_FAMILIES):
            with self.subTest(family=family):
                self.assertEqual(lookup(ACTIVE, family, duplicate=True), Row(DROP, ACTIVE))

    def test_active_duplicate_birth_rejected_not_recreated(self):
        # RSM-I1: exactly one record per id. A second request.received for
        # an already-active id must not re-create — it faults.
        self.assertEqual(lookup(ACTIVE, BIRTH_FAMILY), Row(FAULT, ACTIVE))

    def test_terminal_retained_persisted_late_tolerant_applies_unchanged(self):
        for state in _TERMINAL_LIKE:
            for family in sorted(LATE_TOLERANT_FAMILIES):
                with self.subTest(state=state, family=family):
                    self.assertEqual(lookup(state, family), Row(APPLY, state))

    def test_terminal_retained_persisted_other_recognized_family_faults(self):
        for state in _TERMINAL_LIKE:
            for family in sorted(CONTRIBUTING_FAMILIES) + sorted(TERMINAL_FAMILIES):
                with self.subTest(state=state, family=family):
                    self.assertEqual(lookup(state, family), Row(FAULT, state))

    def test_terminal_retained_persisted_duplicate_silent_drop(self):
        for state in _TERMINAL_LIKE:
            with self.subTest(state=state):
                self.assertEqual(
                    lookup(state, "cost.recorded", duplicate=True), Row(DROP, state))

    def test_persisted_same_rules_as_terminal_retained(self):
        # RSM/03 §3: "persisted is not read-only-yet-mutable-again" — late
        # tolerant families still apply and would re-trigger a journal-index
        # write (persistence itself is M4; the table row is M1 scope).
        self.assertEqual(lookup(PERSISTED, "cost.recorded"), Row(APPLY, PERSISTED))
        self.assertEqual(lookup(PERSISTED, "task.scheduled"), Row(FAULT, PERSISTED))

    def test_evicted_any_event_including_birth_faults_no_resurrect(self):
        for family in ([BIRTH_FAMILY] + sorted(CONTRIBUTING_FAMILIES)
                        + sorted(TERMINAL_FAMILIES) + sorted(LATE_TOLERANT_FAMILIES)):
            with self.subTest(family=family):
                self.assertEqual(lookup(EVICTED, family), Row(FAULT, EVICTED))

    def test_any_state_unregistered_family_counted_not_faulted(self):
        for state in STATES:
            with self.subTest(state=state):
                self.assertEqual(lookup(state, UNREGISTERED_FAMILY), Row(UNREGISTERED, state))

    def test_any_state_malformed_event_of_registered_family_faults_unchanged(self):
        cases = [
            (ABSENT, BIRTH_FAMILY, ABSENT),
            (ACTIVE, "task.scheduled", ACTIVE),
            (ACTIVE, "request.completed", ACTIVE),
            (TERMINAL, "cost.recorded", TERMINAL),
            (RETAINED, "cost.recorded", RETAINED),
            (PERSISTED, "cost.recorded", PERSISTED),
        ]
        for state, family, expected_next in cases:
            with self.subTest(state=state, family=family):
                self.assertEqual(
                    lookup(state, family, malformed=True), Row(FAULT, expected_next))

    def test_every_state_x_family_bucket_pair_covered(self):
        # Belt-and-suspenders exhaustiveness: no (state, family-bucket)
        # combination raises or falls through un-asserted.
        buckets = ([BIRTH_FAMILY] + sorted(CONTRIBUTING_FAMILIES)
                   + sorted(TERMINAL_FAMILIES) + sorted(LATE_TOLERANT_FAMILIES)
                   + [UNREGISTERED_FAMILY])
        seen = 0
        for state in STATES:
            for family in buckets:
                row = lookup(state, family)
                self.assertIsInstance(row, Row)
                self.assertIn(row.next_state, STATES)
                seen += 1
        self.assertEqual(seen, len(STATES) * len(buckets))

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            lookup("not-a-real-state", BIRTH_FAMILY)


class StoreBirthTerminalTests(unittest.TestCase):
    """Birth/terminal paths wired end to end at the store level."""

    def test_birth_creates_active_record(self):
        store = Store()
        self.assertEqual(store.state_of("r1"), ABSENT)
        rec = store.create("r1", {"declared_type": "type.alpha"})
        self.assertEqual(store.state_of("r1"), ACTIVE)
        self.assertIs(store.get("r1"), rec)
        self.assertEqual(rec.identity["declared_type"], "type.alpha")

    def test_duplicate_create_rejected(self):
        store = Store()
        store.create("r1", {})
        with self.assertRaises(ValueError):
            store.create("r1", {})
        # state and record are unaffected by the rejected attempt
        self.assertEqual(store.state_of("r1"), ACTIVE)

    def test_unknown_id_fault_outcome_no_record_created(self):
        store = Store()
        row = lookup(store.state_of("never-seen"), "task.scheduled")
        self.assertEqual(row, Row(FAULT, ABSENT))
        self.assertEqual(store.state_of("never-seen"), ABSENT)
        self.assertIsNone(store.get("never-seen"))
        self.assertNotIn("never-seen", store)

    def test_terminal_path_moves_active_to_terminal_new_version(self):
        store = Store()
        rec = store.create("r1", {})
        row = lookup(store.state_of("r1"), "request.completed")
        self.assertEqual(row, Row(APPLY_TERMINAL, TERMINAL))
        term = _terminate(store, "r1", {"state": "completed"})
        self.assertEqual(store.state_of("r1"), TERMINAL)
        self.assertEqual(term.version, rec.version + 1)
        self.assertEqual(term.lifecycle, {"state": "completed"})
        # store now returns the new version, not the stale pre-terminal one
        self.assertIs(store.get("r1"), term)

    def test_mark_terminal_on_non_active_raises(self):
        store = Store()
        with self.assertRaises(ValueError):
            store.apply_terminal("ghost", None)  # state check precedes record use
        store.create("r1", {})
        _terminate(store, "r1", {"state": "completed"})
        with self.assertRaises(ValueError):
            _terminate(store, "r1", {"state": "completed"})  # already terminal

    def test_evict_gate_refuses_before_persisted_m4(self):
        # M4 wired evict_gate to the real three-precondition gate
        # (RSM/05-implementation-spec.md M4; see tests/test_rsm_phase4.py
        # for the full property-test coverage). This module's own
        # concern is just: terminal alone (no persistence yet) never
        # evicts, regardless of the clock/retention_window passed in.
        store = Store()
        store.create("r1", {})
        _terminate(store, "r1", {"state": "completed"})
        self.assertFalse(store.evict_gate("r1", clock=lambda: 0, retention_window=0))


class InvariantSpotChecksTests(unittest.TestCase):
    """M1-scope spot checks for the invariants M1 can actually exercise."""

    def test_rsm_i1_exactly_one_record_per_id(self):
        store = Store()
        store.create("r1", {})
        with self.assertRaises(ValueError):
            store.create("r1", {})
        self.assertEqual(len(store.request_ids()), 1)

    def test_rsm_i9_reader_snapshot_never_torn_by_later_mutation(self):
        store = Store()
        held = store.create("r1", {"declared_type": "a"})
        _terminate(store, "r1", {"state": "completed"})
        # a reference taken before the mutation is provably unaffected
        self.assertEqual(held.version, 0)
        self.assertEqual(held.lifecycle, {})

    def test_rsm_i10_request_received_is_sole_creation_trigger(self):
        store = Store()
        for family in sorted(transitions.CONTRIBUTING_FAMILIES):
            self.assertEqual(lookup(store.state_of("r1"), family), Row(FAULT, ABSENT))
        self.assertEqual(store.state_of("r1"), ABSENT)
        # only request.received creates
        store.create("r1", {})
        self.assertEqual(store.state_of("r1"), ACTIVE)


if __name__ == "__main__":
    unittest.main()
