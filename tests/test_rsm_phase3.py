"""RSM Milestone 3 suite — RSM/05-implementation-spec.md M3.

Covers: reads never torn under interleaved `ingest` applies (RSM-I9);
budget arithmetic (`granted`/`consumed`/`remaining`, incl. zero-grant and
over-consumption-is-reported-not-clamped); D4a-mirror query answers for
evicted vs unknown ids (RSM-I10); enumerate-active correctness across
record states; per-block reads; journal read order.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rsm.store import Store
from rsm.journal import Journal
from rsm.ingest import Ingest, make_event, APPLIED
from rsm import query
from rsm import transitions


def _drive_birth(ing, request_id, event_id="e0"):
    return ing.process(make_event(event_id, "request.received", request_id, 1,
                                   {"declared_type": "a", "origin": "fe"}))


class ReadsNeverTornTests(unittest.TestCase):
    """RSM-I9: a reader holding a snapshot never observes a half-applied
    reducer output, and a fresh read after further applies differs."""

    def test_held_snapshot_unchanged_by_interleaved_applies(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))

        held = query.snapshot(store, "r1")
        self.assertEqual(held.version, 1)
        self.assertEqual(held.work["tasks"]["t1"]["state"], "scheduled")

        # interleave further applies against the same store/journal after
        # the read was taken — simulates a reader mid-inspection while
        # ingest's single-threaded loop keeps folding (RSM/03 §9/§4).
        ing.process(make_event("e2", "task.started", "r1", 1, {"task_id": "t1"}))
        ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 4}))

        # the held reference is a frozen dataclass snapshot: untouched
        self.assertEqual(held.version, 1)
        self.assertEqual(held.work["tasks"]["t1"]["state"], "scheduled")
        self.assertEqual(held.budget, {"granted": 10})

        # a fresh read sees every fold that happened after the hold
        fresh = query.snapshot(store, "r1")
        self.assertEqual(fresh.version, 3)
        self.assertEqual(fresh.work["tasks"]["t1"]["state"], "started")
        self.assertEqual(fresh.budget, {"granted": 10, "consumed": 4})

        # and the originally-held object is still exactly what it was
        self.assertIsNot(fresh, held)
        self.assertEqual(held.version, 1)

    def test_repeated_reads_during_a_long_apply_sequence_never_regress(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        seen_versions = []
        for i in range(5):
            ing.process(make_event("e%d" % (i + 1), "cost.recorded", "r1", 1, {"amount": 1}))
            seen_versions.append(query.snapshot(store, "r1").version)
        self.assertEqual(seen_versions, sorted(seen_versions))  # monotonic, never torn/regressed
        self.assertEqual(query.budget(store, "r1")["consumed"], 5)


class BudgetArithmeticTests(unittest.TestCase):
    def test_zero_grant_zero_consumed(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        self.assertEqual(query.budget(store, "r1"),
                          {"granted": 0, "consumed": 0, "remaining": 0})

    def test_granted_consumed_remaining_hand_computed(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 20}))
        ing.process(make_event("e2", "task.scheduled", "r1", 1,
                                {"task_id": "t2", "budget_granted": 5}))
        ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 6}))
        ing.process(make_event("e4", "cost.recorded", "r1", 1, {"amount": 9}))
        self.assertEqual(query.budget(store, "r1"),
                          {"granted": 25, "consumed": 15, "remaining": 10})

    def test_over_consumption_is_reported_not_clamped(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 5}))
        ing.process(make_event("e2", "cost.recorded", "r1", 1, {"amount": 30}))
        result = query.budget(store, "r1")
        self.assertEqual(result, {"granted": 5, "consumed": 30, "remaining": -25})
        # RSM records, never reacts (RSM/03 §6): the record itself is untouched
        # by the over-consumption, no enforcement/rejection side effect
        self.assertEqual(query.status(store, "r1"), transitions.ACTIVE)

    def test_late_tolerant_cost_after_terminal_still_folds_into_budget(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e2", "request.completed", "r1", 1, {}))
        ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 3}))
        self.assertEqual(query.budget(store, "r1"),
                          {"granted": 10, "consumed": 3, "remaining": 7})


class EvictedVsUnknownTests(unittest.TestCase):
    """D4a-mirror (RSM-I10): evicted and unknown/absent are distinct,
    honestly disclosed answers — never a stale reconstruction, never a
    crash, never conflated."""

    def test_unknown_id_answers_absent_everywhere(self):
        store, journal = Store(), Journal()
        self.assertEqual(query.status(store, "never-seen"), transitions.ABSENT)
        self.assertIsNone(query.snapshot(store, "never-seen"))
        self.assertIsNone(query.block(store, "never-seen", "identity"))
        self.assertIsNone(query.budget(store, "never-seen"))
        self.assertIsNone(query.failures(store, "never-seen"))
        self.assertIsNone(query.journal_read(journal, store, "never-seen"))

    def test_evicted_id_answers_evicted_not_absent(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "request.completed", "r1", 1, {}))
        pre_eviction = query.snapshot(store, "r1")
        self.assertIsNotNone(pre_eviction)

        store.mark_evicted("r1")

        self.assertEqual(query.status(store, "r1"), transitions.EVICTED)
        self.assertNotEqual(query.status(store, "r1"), query.status(store, "never-seen"))
        self.assertIsNone(query.snapshot(store, "r1"))  # never a stale reconstruction
        self.assertIsNone(query.block(store, "r1", "lifecycle"))
        self.assertIsNone(query.budget(store, "r1"))
        self.assertIsNone(query.failures(store, "r1"))
        self.assertIsNone(query.journal_read(journal, store, "r1"))

    def test_evicted_id_never_resurrects_or_crashes_on_further_reads(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "request.completed", "r1", 1, {}))
        store.mark_evicted("r1")
        for _ in range(3):  # repeated reads stay honest, no side effect flips it back
            self.assertEqual(query.status(store, "r1"), transitions.EVICTED)
            self.assertIsNone(query.snapshot(store, "r1"))


class EnumerateActiveTests(unittest.TestCase):
    def test_enumerate_active_across_mixed_states(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)

        _drive_birth(ing, "r1")  # stays active
        _drive_birth(ing, "r2")
        ing.process(make_event("e1", "request.completed", "r2", 1, {}))  # -> terminal
        _drive_birth(ing, "r3")  # stays active
        _drive_birth(ing, "r4")
        ing.process(make_event("e2", "request.completed", "r4", 1, {}))
        store.mark_evicted("r4")  # -> evicted

        self.assertEqual(sorted(query.enumerate_active(store)), ["r1", "r3"])

    def test_enumerate_active_empty_store(self):
        store = Store()
        self.assertEqual(query.enumerate_active(store), [])

    def test_absent_never_appears_in_enumeration(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        self.assertNotIn("ghost", query.enumerate_active(store))


class PerBlockReadTests(unittest.TestCase):
    def test_every_block_readable_individually_and_matches_full_record(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1", "e0")
        ing.process(make_event("e1", "classify.completed", "r1", 1, {"classification_ref": "c1"}))
        ing.process(make_event("e2", "plan.created", "r1", 1, {"plan_id": "p1", "revision": 0}))
        ing.process(make_event("e3", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e4", "context.assembled", "r1", 1,
                                {"step": "s1", "context_package_id": "cp1"}))
        ing.process(make_event("e5", "verify.passed", "r1", 1,
                                {"gate": "g1", "verdict_ref": "v1"}))
        ing.process(make_event("e6", "task.failed", "r1", 1,
                                {"task_id": "t1", "reason": "boom"}))
        ing.process(make_event("e7", "cost.recorded", "r1", 1, {"amount": 4}))

        full = query.snapshot(store, "r1")
        for name in ("identity", "lifecycle", "plan", "work", "context",
                     "verification", "failure", "journal_meta"):
            with self.subTest(block=name):
                self.assertEqual(query.block(store, "r1", name), getattr(full, name))

        # budget is the one derived block: adds `remaining` on top of the raw sub-dict
        self.assertEqual(query.block(store, "r1", "budget"),
                          {"granted": 10, "consumed": 4, "remaining": 6})

    def test_unknown_block_name_raises(self):
        store = Store()
        with self.assertRaises(ValueError):
            query.block(store, "r1", "not_a_real_block")

    def test_block_read_on_absent_id_is_none_not_a_crash(self):
        store = Store()
        self.assertIsNone(query.block(store, "ghost", "identity"))


class FailureListingTests(unittest.TestCase):
    def test_failure_entries_ordered_and_replan_count_derived(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        ing.process(make_event("e1", "plan.created", "r1", 1, {"plan_id": "p1", "revision": 0}))
        ing.process(make_event("e2", "plan.revised", "r1", 1, {"plan_id": "p1", "revision": 1}))
        ing.process(make_event("e3", "task.failed", "r1", 1,
                                {"task_id": "t1", "reason": "boom"}))
        ing.process(make_event("e4", "plan.revised", "r1", 1, {"plan_id": "p1", "revision": 2}))
        ing.process(make_event("e5", "verify.failed", "r1", 1,
                                {"gate": "g1", "verdict_ref": "v1"}))

        result = query.failures(store, "r1")
        self.assertEqual([e["family"] for e in result["entries"]],
                          ["task.failed", "verify.failed"])  # ordered, append-only
        self.assertEqual(result["replan_count"], 2)  # two plan.revised folds

    def test_no_failures_yields_empty_tuple_not_none(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1")
        result = query.failures(store, "r1")
        self.assertEqual(result["entries"], ())
        self.assertEqual(result["replan_count"], 0)


class JournalReadOrderTests(unittest.TestCase):
    def test_journal_read_matches_applied_order_including_late_tolerant(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1", "e0")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 5}))
        ing.process(make_event("e2", "request.completed", "r1", 1, {}))
        ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 1}))  # late-tolerant

        self.assertEqual(query.journal_read(journal, store, "r1"), ("e0", "e1", "e2", "e3"))

    def test_journal_read_works_pre_terminal_not_only_after(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1", "e0")
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 5}))
        self.assertEqual(query.status(store, "r1"), transitions.ACTIVE)
        self.assertEqual(query.journal_read(journal, store, "r1"), ("e0", "e1"))

    def test_journal_read_excludes_unregistered_and_faulted_events(self):
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        _drive_birth(ing, "r1", "e0")
        ing.process(make_event("e1", "memory.indexed", "r1", 1, {}))  # unregistered
        ing.process(make_event("e2", "task.started", "r1", 1, {}))  # malformed -> fault
        ing.process(make_event("e3", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 5}))
        self.assertEqual(query.journal_read(journal, store, "r1"), ("e0", "e3"))


if __name__ == "__main__":
    unittest.main()
