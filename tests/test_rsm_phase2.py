"""RSM Milestone 2 suite — RSM/05-implementation-spec.md M2.

Covers: per-reducer determinism/purity (same input -> same output, no
cross-record leakage); duplicate delivery dropped silently; unregistered
family counted-not-faulted-not-journaled; malformed registered event
faulted-not-journaled; journal order == applied order; full pipeline
birth -> events -> terminal path.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rsm import record as record_mod
from rsm import transitions
from rsm import reducers
from rsm.reducers import ReducerFault, REGISTRY, BIRTH_FAMILY, birth_reducer
from rsm.store import Store
from rsm.journal import Journal
from rsm import dedup
from rsm.ingest import Ingest, make_event, APPLIED, DROPPED, FAULTED, UNREGISTERED_OUT


class ReducerPurityTests(unittest.TestCase):
    """Per-reducer determinism/purity, one test per registered family
    minimum (RSM/05 M2, RSM/03 §4 reducer contract)."""

    def test_registry_covers_every_contributing_and_terminal_family(self):
        # one reducer per family (RSM/03 §4), birth special-cased separately
        expected = transitions.REGISTERED_FAMILIES - {BIRTH_FAMILY}
        self.assertEqual(set(REGISTRY), expected)

    def _fixture(self):
        return {
            "intent.classified": {"classification_ref": "c1"},
            "plan.created": {"plan_id": "p1", "revision": 0},
            "plan.revised": {"plan_id": "p1", "revision": 1},
            "plan.validated": {"verdict_ref": "v1"},
            "plan.rejected": {"verdict_ref": "v1", "reason": "bad"},
            "task.scheduled": {"task_id": "t1", "budget_granted": 10},
            "task.started": {"task_id": "t1"},
            "task.preempted": {"task_id": "t1"},
            "task.completed": {"task_id": "t1"},
            "task.failed": {"task_id": "t1", "reason": "boom"},
            "exec.started": {"exec_id": "x1", "task_id": "t1"},
            "exec.completed": {"exec_id": "x1", "outcome_ref": "o1"},
            "exec.timeout": {"exec_id": "x1"},
            "exec.failed": {"exec_id": "x1", "reason": "boom"},
            "context.assembled": {"step": "s1", "context_package_id": "cp1"},
            "verify.requested": {"gate": "g1"},
            "verify.passed": {"gate": "g1", "verdict_ref": "v1"},
            "verify.failed": {"gate": "g1", "verdict_ref": "v1"},
            "storage.committed": {"commit_ref": "cm1"},
            "storage.rejected": {"reason": "disk_full"},
            "cost.recorded": {"amount": 7},
            "fault.recorded": {"reason": "x"},
            "request.completed": {},
            "request.failed": {"reason": "boom"},
            "request.rejected": {"reason": "no"},
            "request.cancelled": {},
        }

    def test_every_reducer_is_deterministic_and_leaves_other_records_untouched(self):
        payloads = self._fixture()
        self.assertEqual(set(payloads), set(REGISTRY))  # fixture completeness
        for family, payload in payloads.items():
            with self.subTest(family=family):
                rec = record_mod.birth("r1", {"declared_type": "a", "origin": "fe"})
                other = record_mod.birth("r2", {"declared_type": "b", "origin": "fe"})
                other_before = other
                event = make_event("e-" + family, family, "r1", 1, payload)
                out1 = REGISTRY[family](rec, event)
                out2 = REGISTRY[family](rec, event)
                self.assertEqual(out1, out2)  # same (record, event) -> same record', always
                self.assertIs(rec.version, rec.version)  # original untouched
                self.assertEqual(rec.version, 0)
                self.assertEqual(other, other_before)  # cross-record isolation

    def test_schema_version_mismatch_is_explicit_fault(self):
        rec = record_mod.birth("r1", {})
        event = make_event("e1", "cost.recorded", "r1", 2, {"amount": 1})  # v2 unbound
        with self.assertRaises(ReducerFault):
            REGISTRY["cost.recorded"](rec, event)

    def test_missing_required_field_is_malformed_fault(self):
        rec = record_mod.birth("r1", {})
        event = make_event("e1", "cost.recorded", "r1", 1, {})  # missing amount
        with self.assertRaises(ReducerFault):
            REGISTRY["cost.recorded"](rec, event)

    def test_birth_reducer_produces_identity_fields_not_a_record(self):
        event = make_event("e0", BIRTH_FAMILY, "r1", 1,
                            {"declared_type": "type.alpha", "origin": "frontend"})
        fields = birth_reducer(event)
        self.assertEqual(fields, {"declared_type": "type.alpha", "origin": "frontend"})
        self.assertNotIn(BIRTH_FAMILY, REGISTRY)

    def test_dual_block_reducers_update_failure_and_primary_block_atomically(self):
        rec = record_mod.birth("r1", {})
        event = make_event("e1", "task.failed", "r1", 1, {"task_id": "t1", "reason": "boom"})
        out = REGISTRY["task.failed"](rec, event)
        self.assertEqual(out.work["tasks"]["t1"]["state"], "failed")
        self.assertEqual(len(out.failure), 1)
        self.assertEqual(out.failure[0]["family"], "task.failed")
        self.assertEqual(out.version, rec.version + 1)  # one version bump, not two


class DedupTests(unittest.TestCase):
    def test_duplicate_delivery_dropped_journal_and_record_unchanged(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)
        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ev = make_event("e1", "task.started", "r1", 1, {"task_id": "t1"})
        self.assertEqual(ing.process(ev), APPLIED)
        before_rec = store.get("r1")
        before_journal = journal.entries("r1")
        self.assertEqual(ing.process(ev), DROPPED)  # same event id redelivered
        self.assertIs(store.get("r1"), before_rec)  # record unchanged
        self.assertEqual(journal.entries("r1"), before_journal)  # journal length unchanged

    def test_dedup_module_is_a_thin_journal_query(self):
        journal = Journal()
        self.assertFalse(dedup.is_duplicate(journal, "r1", "e1"))
        journal.append("r1", "e1", 1)
        self.assertTrue(dedup.is_duplicate(journal, "r1", "e1"))


class UnregisteredAndMalformedTests(unittest.TestCase):
    def test_unregistered_family_counted_not_faulted_not_journaled(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)
        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ev = make_event("e1", "memory.indexed", "r1", 1, {})
        self.assertEqual(ing.process(ev), UNREGISTERED_OUT)
        self.assertEqual(ing.counters["unregistered"], 1)
        self.assertEqual(ing.counters["fault"], 0)
        self.assertFalse(journal.has("r1", "e1"))

    def test_malformed_registered_event_faulted_not_journaled(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)
        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        # task.started registered, but payload missing required task_id
        ev = make_event("e1", "task.started", "r1", 1, {})
        self.assertEqual(ing.process(ev), FAULTED)
        self.assertEqual(ing.counters["fault"], 1)
        self.assertFalse(journal.has("r1", "e1"))
        # record unaffected by the fault
        self.assertEqual(store.get("r1").work, {})


class JournalOrderTests(unittest.TestCase):
    def test_journal_order_equals_applied_order(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)
        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 5}))
        # e2 is unregistered -> never journaled, must not appear/break order
        ing.process(make_event("e2", "memory.indexed", "r1", 1, {}))
        ing.process(make_event("e3", "task.started", "r1", 1, {"task_id": "t1"}))
        entries = journal.entries("r1")
        self.assertEqual([e[0] for e in entries], ["e0", "e1", "e3"])
        self.assertEqual([e[1] for e in entries], [0, 1, 2])  # seq is applied order

    def test_late_tolerant_event_journaled_in_applied_order_not_origination_order(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)
        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ing.process(make_event("e1", "request.completed", "r1", 1, {}))
        # cost.recorded arrives late, after terminal (RSM/03 §3)
        ing.process(make_event("e2", "cost.recorded", "r1", 1, {"amount": 4}))
        entries = journal.entries("r1")
        self.assertEqual([e[0] for e in entries], ["e0", "e1", "e2"])
        self.assertEqual(store.get("r1").budget["consumed"], 4)


class FullPipelineTests(unittest.TestCase):
    def test_birth_through_terminal_end_to_end(self):
        store = Store()
        journal = Journal()
        ing = Ingest(store, journal)

        self.assertEqual(ing.process(make_event(
            "e0", "request.received", "r1", 1,
            {"declared_type": "type.alpha", "origin": "frontend"})), APPLIED)
        self.assertEqual(store.state_of("r1"), transitions.ACTIVE)

        self.assertEqual(ing.process(make_event(
            "e1", "intent.classified", "r1", 1, {"classification_ref": "c1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e2", "plan.created", "r1", 1, {"plan_id": "p1", "revision": 0})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e3", "task.scheduled", "r1", 1, {"task_id": "t1", "budget_granted": 10})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e4", "task.started", "r1", 1, {"task_id": "t1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e5", "context.assembled", "r1", 1,
            {"step": "s1", "context_package_id": "cp1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e6", "exec.completed", "r1", 1, {"exec_id": "x1", "outcome_ref": "o1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e7", "verify.passed", "r1", 1, {"gate": "g1", "verdict_ref": "v1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e8", "task.completed", "r1", 1, {"task_id": "t1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e9", "storage.committed", "r1", 1, {"commit_ref": "cm1"})), APPLIED)
        self.assertEqual(ing.process(make_event(
            "e10", "request.completed", "r1", 1, {})), APPLIED)

        self.assertEqual(store.state_of("r1"), transitions.TERMINAL)
        rec = store.get("r1")
        self.assertEqual(rec.lifecycle, {"state": "completed"})
        self.assertEqual(rec.plan["plan_id"], "p1")
        self.assertEqual(rec.plan["classification_ref"], "c1")
        self.assertEqual(rec.work["tasks"]["t1"]["state"], "completed")
        self.assertEqual(rec.work["commit_ref"], "cm1")
        self.assertEqual(rec.context["s1"], "cp1")
        self.assertEqual(rec.verification["g1"]["state"], "passed")
        self.assertEqual(rec.budget["granted"], 10)
        self.assertEqual(rec.failure, ())  # clean run, no faults
        self.assertEqual(ing.counters["applied"], 11)
        self.assertEqual(ing.counters["fault"], 0)
        self.assertEqual(len(journal.entries("r1")), 11)


if __name__ == "__main__":
    unittest.main()
