"""VAE Phase 2 suite — VAE/06-implementation-blueprint.md Phase 2 (judgment
core: intake, delegation lifecycle, static checks). Covers: intake dedup by
event id, one-judgment-per-occurrence, terminal-verdict short-circuit;
delegation state machine legal/illegal transitions and deterministic
deadline expiry under injected `now`; VAE-O3's four-row re-dispatch table
(VAE/04 §3.4); late-result handling after expiry; static check
determinism and closed registration surface; judgment closure conditions;
Phase 1 integration (evidence items land append-only with correct
contribution kinds)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from vae import events
from vae import evidence
from vae import intake as intake_mod
from vae import delegation as delegation_mod
from vae import judgment as judgment_mod
from vae.execution_double import ExecutionDouble, UnknownResultOutcomeError
from vae.static_checks import (
    StaticCheckRegistry, DuplicateCheckNameError, UnknownStaticCheckError,
    MalformedCheckResultError,
)


# -- intake -------------------------------------------------------------

class IntakeDedupTests(unittest.TestCase):
    def test_same_event_id_twice_is_one_judgment(self):
        ledger = intake_mod.Intake()
        r1 = ledger.receive("verify.requested", "e1", "artifact:a1", "judgment:a1")
        r2 = ledger.receive("verify.requested", "e1", "artifact:a1", "judgment:a1-dup")
        self.assertEqual(r1.action, intake_mod.OPENED)
        self.assertEqual(r2.action, intake_mod.DEDUPED)

    def test_one_judgment_per_gated_occurrence_across_different_events(self):
        ledger = intake_mod.Intake()
        r1 = ledger.receive("verify.requested", "e1", "artifact:a1", "judgment:a1")
        r2 = ledger.receive("exec.completed", "e2", "artifact:a1", "judgment:a1-second")
        self.assertEqual(r1.action, intake_mod.OPENED)
        self.assertEqual(r2.action, intake_mod.ALREADY_OPEN)
        self.assertEqual(r2.judgment_id, "judgment:a1")

    def test_different_artifacts_open_independent_judgments(self):
        ledger = intake_mod.Intake()
        r1 = ledger.receive("verify.requested", "e1", "artifact:a1", "judgment:a1")
        r2 = ledger.receive("verify.requested", "e2", "artifact:a2", "judgment:a2")
        self.assertEqual(r1.action, intake_mod.OPENED)
        self.assertEqual(r2.action, intake_mod.OPENED)

    def test_terminal_artifact_answered_by_existing_verdict_not_rejudged(self):
        ledger = intake_mod.Intake()
        ledger.receive("verify.requested", "e1", "artifact:a1", "judgment:a1")
        ledger.mark_terminal("artifact:a1", "storage:vae/ev/a1")
        r2 = ledger.receive("plan.created", "e2", "artifact:a1", "judgment:a1-later")
        self.assertEqual(r2.action, intake_mod.ANSWERED_BY_EXISTING_VERDICT)
        self.assertEqual(r2.verdict_ref, "storage:vae/ev/a1")
        self.assertFalse(ledger.is_open("artifact:a1"))

    def test_conflicting_terminal_mark_refused(self):
        ledger = intake_mod.Intake()
        ledger.mark_terminal("artifact:a1", "storage:vae/ev/a1")
        with self.assertRaises(intake_mod.DemandAlreadyTerminalConflictError):
            ledger.mark_terminal("artifact:a1", "storage:vae/ev/a1-other")

    def test_idempotent_terminal_mark_same_ref(self):
        ledger = intake_mod.Intake()
        ledger.mark_terminal("artifact:a1", "storage:vae/ev/a1")
        ledger.mark_terminal("artifact:a1", "storage:vae/ev/a1")  # no raise

    def test_invented_demand_event_name_refused(self):
        ledger = intake_mod.Intake()
        with self.assertRaises(events.UnknownEventError):
            ledger.receive("verify.maybe", "e1", "artifact:a1", "judgment:a1")

    def test_published_only_event_not_accepted_as_demand(self):
        ledger = intake_mod.Intake()
        with self.assertRaises(events.UnknownEventError):
            ledger.receive("verify.passed", "e1", "artifact:a1", "judgment:a1")


# -- delegation state machine -------------------------------------------

class DelegationTransitionTests(unittest.TestCase):
    def test_required_to_dispatched_to_resulted(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("k1", "structural", "artifact:a1", deadline=10)
        self.assertEqual(d.state, delegation_mod.REQUIRED)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        self.assertEqual(d.state, delegation_mod.DISPATCHED)
        exe.script_result("k1", arrival_time=5, outcome="success")
        d = delegation_mod.resolve(d, exe, now=5)
        self.assertEqual(d.state, delegation_mod.RESULTED)
        self.assertEqual(d.result["outcome"], "success")

    def test_deterministic_expiry_under_injected_now(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("k2", "semantic", "artifact:a1", deadline=10)
        d = delegation_mod.dispatch(d, exe, {"check": "semantic"})
        # no result scripted at all: exactly at the deadline -> Expired, deterministically
        before = delegation_mod.resolve(d, exe, now=9)
        self.assertEqual(before.state, delegation_mod.DISPATCHED)
        at_deadline = delegation_mod.resolve(d, exe, now=10)
        self.assertEqual(at_deadline.state, delegation_mod.EXPIRED)
        # replaying the same now twice gives the identical result (Law 6 determinism)
        at_deadline_again = delegation_mod.resolve(d, exe, now=10)
        self.assertEqual(at_deadline_again.state, delegation_mod.EXPIRED)

    def test_resolve_before_dispatch_illegal(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("k3", "structural", "artifact:a1", deadline=10)
        with self.assertRaises(delegation_mod.IllegalTransitionError):
            delegation_mod.resolve(d, exe, now=0)

    def test_terminal_states_never_transition_again(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("k4", "structural", "artifact:a1", deadline=10)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        d = delegation_mod.resolve(d, exe, now=10)  # Expired
        self.assertEqual(d.state, delegation_mod.EXPIRED)
        exe.script_result("k4", arrival_time=1, outcome="success")
        still = delegation_mod.resolve(d, exe, now=999)
        self.assertEqual(still.state, delegation_mod.EXPIRED)


class VaeO3TableTests(unittest.TestCase):
    """VAE/04 §3.4's four rows, exercised at the state-machine level."""

    def test_row1_resulted_delegation_never_redispatched(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("r1", "structural", "artifact:a1", deadline=10)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        exe.script_result("r1", arrival_time=1, outcome="success")
        d = delegation_mod.resolve(d, exe, now=1)
        self.assertEqual(d.state, delegation_mod.RESULTED)
        with self.assertRaises(delegation_mod.ReDispatchRefusedError):
            delegation_mod.dispatch(d, exe, {"check": "structural"})

    def test_row2_delivery_redundancy_permitted_when_no_ack_no_outcome(self):
        exe = ExecutionDouble()
        exe.script_no_ack("r2")
        d = delegation_mod.build_delegation("r2", "structural", "artifact:a1", deadline=10)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        self.assertEqual(d.state, delegation_mod.REQUIRED)  # unacknowledged: unchanged
        d2 = delegation_mod.dispatch(d, exe, {"check": "structural"})  # identical re-issue
        self.assertEqual(d2.state, delegation_mod.DISPATCHED)

    def test_row3_expired_delegation_never_redispatched(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("r3", "structural", "artifact:a1", deadline=5)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        d = delegation_mod.resolve(d, exe, now=5)
        self.assertEqual(d.state, delegation_mod.EXPIRED)
        with self.assertRaises(delegation_mod.ReDispatchRefusedError):
            delegation_mod.dispatch(d, exe, {"check": "structural"})

    def test_row4_multi_sample_is_n_independent_delegations_from_the_outset(self):
        exe = ExecutionDouble()
        # declared multi-sample: two distinct Required delegations, not a retry
        d_run1 = delegation_mod.build_delegation("r4#1", "flaky_check", "artifact:a1", deadline=10)
        d_run2 = delegation_mod.build_delegation("r4#2", "flaky_check", "artifact:a1", deadline=10)
        d_run1 = delegation_mod.dispatch(d_run1, exe, {"check": "flaky_check"})
        d_run2 = delegation_mod.dispatch(d_run2, exe, {"check": "flaky_check"})
        exe.script_result("r4#1", arrival_time=1, outcome="success")
        exe.script_result("r4#2", arrival_time=1, outcome="failure")
        d_run1 = delegation_mod.resolve(d_run1, exe, now=1)
        d_run2 = delegation_mod.resolve(d_run2, exe, now=1)
        self.assertEqual(d_run1.state, delegation_mod.RESULTED)
        self.assertEqual(d_run2.state, delegation_mod.RESULTED)
        self.assertNotEqual(d_run1.result["outcome"], d_run2.result["outcome"])

    def test_pending_dispatched_delegation_also_refuses_redispatch(self):
        exe = ExecutionDouble()
        d = delegation_mod.build_delegation("r5", "structural", "artifact:a1", deadline=10)
        d = delegation_mod.dispatch(d, exe, {"check": "structural"})
        self.assertEqual(d.state, delegation_mod.DISPATCHED)
        with self.assertRaises(delegation_mod.ReDispatchRefusedError):
            delegation_mod.dispatch(d, exe, {"check": "structural"})


# -- static checks --------------------------------------------------------

class StaticCheckTests(unittest.TestCase):
    def test_reference_wellformed_deterministic(self):
        registry = StaticCheckRegistry()
        r1 = registry.run("reference_wellformed", "artifact:a1", {})
        r2 = registry.run("reference_wellformed", "artifact:a1", {})
        self.assertEqual(r1, r2)
        self.assertEqual(r1["outcome"], "pass")
        self.assertEqual(registry.run("reference_wellformed", "not-a-ref", {})["outcome"], "fail")

    def test_unknown_check_refused(self):
        registry = StaticCheckRegistry()
        with self.assertRaises(UnknownStaticCheckError):
            registry.run("nonexistent", "artifact:a1", {})

    def test_duplicate_registration_refused(self):
        registry = StaticCheckRegistry()
        with self.assertRaises(DuplicateCheckNameError):
            registry.register("reference_wellformed", lambda a, m: {"outcome": "pass"})

    def test_malformed_result_refused(self):
        registry = StaticCheckRegistry()
        registry.register("bad", lambda a, m: {"outcome": "maybe"})
        with self.assertRaises(MalformedCheckResultError):
            registry.run("bad", "artifact:a1", {})

    def test_registries_are_independent(self):
        r1 = StaticCheckRegistry()
        r1.register("custom", lambda a, m: {"outcome": "pass"})
        r2 = StaticCheckRegistry()
        with self.assertRaises(UnknownStaticCheckError):
            r2.run("custom", "artifact:a1", {})


class ExecutionDoubleTests(unittest.TestCase):
    def test_unknown_outcome_refused(self):
        exe = ExecutionDouble()
        with self.assertRaises(UnknownResultOutcomeError):
            exe.script_result("k", arrival_time=1, outcome="teleported")

    def test_poll_before_arrival_is_none(self):
        exe = ExecutionDouble()
        exe.script_result("k", arrival_time=10, outcome="success")
        self.assertIsNone(exe.poll("k", now=5))
        self.assertIsNotNone(exe.poll("k", now=10))


# -- judgment aggregate ---------------------------------------------------

def _open(judgment_id="judgment:a1", artifact_ref="artifact:a1", delegated=None, static=None):
    return judgment_mod.open_judgment(
        judgment_id, artifact_ref, rules_version=1,
        delegated_checks=delegated or {}, static_checks_spec=static or {})


class JudgmentClosureTests(unittest.TestCase):
    def test_closed_only_after_all_required_checks_terminal(self):
        exe = ExecutionDouble()
        registry = StaticCheckRegistry()
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}},
                   static={"reference_wellformed": {"level": "reference"}})
        self.assertFalse(judgment_mod.is_closed(j))

        j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
        self.assertFalse(judgment_mod.is_closed(j))  # delegation still pending

        j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result("judgment:a1:structural", arrival_time=3, outcome="success")
        j = judgment_mod.resolve_delegation(j, "structural", exe, now=1)
        self.assertFalse(judgment_mod.is_closed(j))  # not arrived yet

        j = judgment_mod.resolve_delegation(j, "structural", exe, now=3)
        self.assertTrue(judgment_mod.is_closed(j))

        closed = judgment_mod.close(j)
        self.assertTrue(closed.closed)
        # idempotent
        self.assertTrue(judgment_mod.close(closed).closed)

    def test_close_refused_before_ready(self):
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}})
        with self.assertRaises(judgment_mod.JudgmentNotReadyError):
            judgment_mod.close(j)

    def test_expiry_yields_execution_failure_evidence(self):
        exe = ExecutionDouble()
        j = _open(delegated={"semantic": {"deadline": 5, "level": "semantic"}})
        j = judgment_mod.dispatch_delegation(j, "semantic", exe, {"check": "semantic"})
        j = judgment_mod.resolve_delegation(j, "semantic", exe, now=5)
        self.assertTrue(judgment_mod.is_closed(j))
        self.assertEqual(j.record.items[-1].result, "execution_failure")
        self.assertEqual(j.record.items[-1].contribution_kind, judgment_mod.INDEPENDENT)


class LateResultTests(unittest.TestCase):
    def test_late_result_after_expiry_recorded_as_redundant_state_stands(self):
        exe = ExecutionDouble()
        j = _open(delegated={"semantic": {"deadline": 5, "level": "semantic"}})
        j = judgment_mod.dispatch_delegation(j, "semantic", exe, {"check": "semantic"})
        j = judgment_mod.resolve_delegation(j, "semantic", exe, now=5)
        self.assertEqual(j.delegations["semantic"].state, delegation_mod.EXPIRED)
        before_count = len(j.record.items)

        exe.script_result("judgment:a1:semantic", arrival_time=1, outcome="success")
        j2 = judgment_mod.record_late_result(j, "semantic", exe, now=6)

        self.assertEqual(j2.delegations["semantic"].state, delegation_mod.EXPIRED)  # stands
        self.assertEqual(len(j2.record.items), before_count + 1)
        self.assertEqual(j2.record.items[-1].contribution_kind, judgment_mod.REDUNDANT)

    def test_late_result_no_op_when_nothing_new_arrived(self):
        exe = ExecutionDouble()
        j = _open(delegated={"semantic": {"deadline": 5, "level": "semantic"}})
        j = judgment_mod.dispatch_delegation(j, "semantic", exe, {"check": "semantic"})
        j = judgment_mod.resolve_delegation(j, "semantic", exe, now=5)
        j2 = judgment_mod.record_late_result(j, "semantic", exe, now=6)
        self.assertEqual(len(j2.record.items), len(j.record.items))

    def test_late_result_before_terminal_refused(self):
        exe = ExecutionDouble()
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}})
        with self.assertRaises(judgment_mod.LateResultBeforeTerminalError):
            judgment_mod.record_late_result(j, "structural", exe, now=0)


class JudgmentConstructionRefusalTests(unittest.TestCase):
    def test_check_declared_both_delegated_and_static_refused(self):
        with self.assertRaises(judgment_mod.DuplicateCheckNameAcrossKindsError):
            _open(delegated={"x": {"deadline": 1, "level": "x"}}, static={"x": {"level": "x"}})

    def test_unknown_check_refused_on_dispatch(self):
        exe = ExecutionDouble()
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}})
        with self.assertRaises(judgment_mod.UnknownCheckError):
            judgment_mod.dispatch_delegation(j, "nonexistent", exe, {})

    def test_static_check_cannot_run_twice(self):
        registry = StaticCheckRegistry()
        j = _open(static={"reference_wellformed": {"level": "reference"}})
        j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
        with self.assertRaises(judgment_mod.UnknownCheckError):
            judgment_mod.run_static_check(j, "reference_wellformed", registry, {})


# -- Phase 1 integration: evidence lands append-only with correct kinds --

class Phase1IntegrationTests(unittest.TestCase):
    def test_evidence_items_are_real_phase1_items_appended_in_order(self):
        exe = ExecutionDouble()
        registry = StaticCheckRegistry()
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}},
                   static={"reference_wellformed": {"level": "reference"}})

        j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
        j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result("judgment:a1:structural", arrival_time=1, outcome="success")
        j = judgment_mod.resolve_delegation(j, "structural", exe, now=1)

        self.assertIsInstance(j.record, evidence.EvidenceRecord)
        self.assertEqual(len(j.record.items), 2)
        for item in j.record.items:
            self.assertIsInstance(item, evidence.EvidenceItem)
            self.assertIn(item.contribution_kind, evidence.CONTRIBUTION_KINDS)
        # append order preserved: static check ran first
        self.assertEqual(j.record.items[0].source, "static:reference_wellformed")
        self.assertEqual(j.record.items[1].source, "execution:judgment:a1:structural")

    def test_original_record_untouched_by_append(self):
        exe = ExecutionDouble()
        j = _open(delegated={"structural": {"deadline": 10, "level": "structural"}})
        original_items = j.record.items
        j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result("judgment:a1:structural", arrival_time=1, outcome="success")
        j2 = judgment_mod.resolve_delegation(j, "structural", exe, now=1)
        self.assertEqual(original_items, ())
        self.assertEqual(len(j2.record.items), 1)


if __name__ == "__main__":
    unittest.main()
