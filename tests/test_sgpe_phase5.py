"""SGPE Phase 5 suite — System Integration (SGPE/05; the OS weave).

Covers: the uniform consultation contract (§1) exercised by doubles for
all eleven consumers (Kernel, RSM, UMS, CM, CP, WS, PRT, RO, VAE, LIE,
IVS) obeying the §5 consumer obligations; the runtime lifecycle end to
end (§3: authoring → compile → activate → admission → consultations →
approval loop → completion → replay); the consolidated failure law (§5 —
every ruled case that is reachable in-process); observability (§4 event
canon, no parallel audit); and the closing self-audit: an INV-1..12
sweep verifying every SGPE/00 invariant is enforced by implementation or
test (PS/AC/EV/GL/EPR families live in their own phase suites — asserted
present here by module import).

The end-to-end regression follows the required pipeline exactly:
User Request → Kernel Admission → Effective Policy → Capability Planner
→ Workflow Scheduler → Plugin Runtime → Reasoning Orchestrator →
Verification → Learning → Completion, with every consultation recorded
and replayed byte-identically from stamps alone."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sgpe import compiler as compiler_mod
from sgpe import condition as condition_mod
from sgpe import document as document_mod
from sgpe import events as events_mod
from sgpe import manifest as manifest_mod
from sgpe import rule as rule_mod
from sgpe import runtime as runtime_mod
from sgpe import vocabulary as vocabulary_mod
from sgpe.bus_double import BusDouble
from sgpe.compiler import RegenerationMismatchError, TOTALITY_GAP, UNDECIDABLE_CONFLICT
from sgpe.condition import MalformedConditionError
from sgpe.evaluator import (
    Decision,
    IllPosedVerdict,
    build_question,
    decision_bytes,
)
from sgpe.ledger import GrantLedger
from sgpe.resolver import AdmissionRefusedError, EffectivePolicy
from sgpe.runtime import (
    ApprovalRoutingError,
    GovernanceRuntime,
    MalformedRuntimeInputError,
    RequestGovernance,
    UnknownSnapshotVersionError,
    approval_ask_payload,
    resolve_citation,
)
from sgpe.storage_double import StorageDouble
from sgpe.store import PolicyStore

# invariant-family presence: each family's per-invariant suite must exist
import tests.test_sgpe_phase1 as _phase1_suite  # PS-1..10           # noqa: F401
import tests.test_sgpe_phase2 as _phase2_suite  # AC-1..10, R1-R5    # noqa: F401
import tests.test_sgpe_phase3 as _phase3_suite  # EV-1..10           # noqa: F401
import tests.test_sgpe_phase4 as _phase4_suite  # GL-1..7, EPR-1..7  # noqa: F401


OPERATIONS = (
    "execution.run", "token-budget.run",
    "persistence.store", "resource-limit.store",
    "plugin.bind",
    "model.invoke", "token-budget.invoke",
    "resource-limit.dispatch", "retry-limit.dispatch",
    "context-limit.assemble",
    "resource-limit.verify", "approval.waive",
)


def _rule(rule_id, domain, operation, selector, effect_kind, value=None, condition=None, final=False):
    return rule_mod.build_rule(
        rule_id, rule_mod.build_target(domain, operation, selector),
        rule_mod.build_effect(effect_kind, value), condition=condition, final=final)


def _constitution_rules():
    """The deny-by-default constitution (SGPE/05 §3): one total system
    document answering every declared operation."""
    over_budget = condition_mod.build_comparison("usage.tokens", "gte", 1000)
    return (
        _rule("r-exec", "execution", "run", "*", "ALLOW"),
        _rule("r-exec-budget", "token-budget", "run", "*", "LIMIT", 5000),
        _rule("r-persist", "persistence", "store", "*", "ALLOW"),
        _rule("r-retention", "resource-limit", "store", "*", "LIMIT", 30),
        _rule("r-plugin", "plugin", "bind", "*", "REQUIRE_APPROVAL"),
        _rule("r-model", "model", "invoke", "*", "ALLOW"),
        _rule("r-model-cap", "model", "invoke", "*", "DENY", condition=over_budget),
        _rule("r-model-budget", "token-budget", "invoke", "*", "LIMIT", 1000),
        _rule("r-concurrency", "resource-limit", "dispatch", "*", "LIMIT", 4),
        _rule("r-retries", "retry-limit", "dispatch", "*", "LIMIT", 3),
        _rule("r-context", "context-limit", "assemble", "*", "LIMIT", 8000),
        _rule("r-verify-budget", "resource-limit", "verify", "*", "LIMIT", 2),
        _rule("r-no-waiver", "approval", "waive", "*", "DENY", final=True),
    )


def _bootstrap(bus=None, rules=None, operations=OPERATIONS, activate=True):
    """SGPE/05 §3 bootstrap canon, in order: vocabulary v1 + system
    defaults → first compile → first activation. Returns
    (runtime, store, ledger)."""
    store = PolicyStore(StorageDouble(), bus=bus)
    v1 = vocabulary_mod.default_v1()
    store.append_vocabulary(v1)
    store.append_vocabulary(vocabulary_mod.evolve(v1, operations=operations,
                                                    fact_names=("usage.tokens",)))
    prov = document_mod.build_provenance("alice", "epoch-0", "constitution")
    header = document_mod.build_header("system", "constitution", ("execution",), prov, 2, 1)
    store.append_document(document_mod.build_document(header, rules or _constitution_rules()))
    if activate:
        result = compiler_mod.compile_snapshot(store, store.catalog_position(), bus=bus)
        assert result.outcome == "compiled", result.report.errors
        compiler_mod.activate(store, result, bus=bus)
    ledger = GrantLedger(StorageDouble(), bus=bus)
    return GovernanceRuntime(store, ledger, bus=bus), store, ledger


def _q(request_id, domain, operation, resource="res-1", facts=None, principal="alice"):
    return build_question("consumer", request_id, principal, domain, operation, resource, facts or {})


class RsmDouble:
    """SGPE/05 §2 RSM row: a pure custodian — persists the EP stamp and
    per-Decision stamps as request state, never asks a Question."""

    def __init__(self):
        self.ep_stamps = {}       # request_id -> ep stamp dict
        self.consultations = {}   # request_id -> [(question, decision), ...]

    def persist_admission(self, request_id, view):
        self.ep_stamps[request_id] = view.stamp()

    def persist_consultation(self, request_id, question, decision):
        self.consultations.setdefault(request_id, []).append((question, decision))


class IvsDouble:
    """SGPE/05 §2 IVS row: renders asks, captures consent, returns the
    outcome — the Kernel routes the append. Owns no SGPE state."""

    def __init__(self):
        self.rendered = []

    def present_ask(self, payload, resolved_citations):
        self.rendered.append((payload, resolved_citations))
        return {"approved": True, "grantor": "human-operator", "reason": "reviewed and approved"}


class IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.bus = BusDouble()
        self.runtime, self.store, self.ledger = _bootstrap(bus=self.bus)
        self.rsm = RsmDouble()

    def _admitted(self, request_id="req-1", principal="alice", project="proj-x"):
        view = self.runtime.admit(request_id, principal, project)
        self.rsm.persist_admission(request_id, view)
        return view

    def _consult(self, view, question):
        outcome = view.consult(question)
        if isinstance(outcome, Decision):
            self.rsm.persist_consultation(view.effective_policy.request_id, question, outcome)
        return outcome


# -- admission lifecycle (Kernel + RSM) -----------------------------------------

class AdmissionLifecycle(IntegrationTestCase):
    def test_admission_binds_and_rsm_persists_the_stamp(self):
        view = self._admitted()
        self.assertEqual(view.effective_policy,
                          EffectivePolicy(1, 0, "req-1", "alice", "proj-x"))
        self.assertEqual(self.rsm.ep_stamps["req-1"]["snapshot_version"], 1)

    def test_view_rebuilds_from_rsm_stamp(self):
        view = self._admitted()
        rebuilt = self.runtime.view_for(self.rsm.ep_stamps["req-1"])
        self.assertEqual(rebuilt.effective_policy, view.effective_policy)

    def test_admission_before_first_activation_fails_closed(self):
        runtime, _, _ = _bootstrap(activate=False)
        with self.assertRaises(AdmissionRefusedError):
            runtime.admit("req-1", "alice", "proj-x")

    def test_kernel_gate_allow_carries_its_ceilings(self):
        view = self._admitted()
        d = self._consult(view, _q("req-1", "execution", "run"))
        self.assertEqual(d.effect_kind, "ALLOW")
        self.assertEqual(d.constraints, (("token-budget", 5000, (("system", "constitution"), 1,
                                                                   "r-exec-budget")),))


# -- per-subsystem consultations (SGPE/05 §2 rows) ---------------------------------

class SubsystemConsultations(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.view = self._admitted()

    def test_ums_persistence_and_retention(self):
        d = self._consult(self.view, _q("req-1", "persistence", "store", "memory/episode-1"))
        self.assertEqual(d.effect_kind, "ALLOW")
        self.assertEqual(d.constraints[0][:2], ("resource-limit", 30))

    def test_cm_context_limit(self):
        d = self._consult(self.view, _q("req-1", "context-limit", "assemble"))
        self.assertEqual((d.effect_kind, d.effect_value), ("LIMIT", 8000))
        self.assertTrue(d.explanation[0]["winner"])  # citation present for CM display

    def test_cp_planning_answers_do_not_preauthorize_but_match_crossing_answers(self):
        # CP's advisory pass and PRT's crossing-time re-ask under the same
        # frozen EP and position are the same stamps -- same answer, one
        # memo hit (SGPE/05 §2 CP row, D1)
        question = _q("req-1", "plugin", "bind", "plugin://web-search")
        planned = self._consult(self.view, question)
        crossed = self._consult(self.view, question)
        self.assertEqual(planned.effect_kind, "REQUIRE_APPROVAL")
        self.assertIs(planned, crossed)  # memo hit: byte-identical by identity

    def test_ws_scheduling_ceilings(self):
        concurrency = self._consult(self.view, _q("req-1", "resource-limit", "dispatch"))
        retries = self._consult(self.view, _q("req-1", "retry-limit", "dispatch"))
        self.assertEqual((concurrency.effect_kind, concurrency.effect_value), ("LIMIT", 4))
        self.assertEqual((retries.effect_kind, retries.effect_value), ("LIMIT", 3))

    def test_ro_model_permission_with_supplied_usage_facts(self):
        under = self._consult(self.view, _q("req-1", "model", "invoke",
                                              facts={"usage.tokens": 100}))
        self.assertEqual(under.effect_kind, "ALLOW")
        self.assertEqual(under.constraints[0][:2], ("token-budget", 1000))
        over = self._consult(self.view, _q("req-1", "model", "invoke",
                                             facts={"usage.tokens": 1500}))
        self.assertEqual(over.effect_kind, "DENY")  # RO enforces as GOVERNANCE-REFUSED

    def test_vae_verification_budget_and_final_blocked_waiver(self):
        budget = self._consult(self.view, _q("req-1", "resource-limit", "verify"))
        self.assertEqual((budget.effect_kind, budget.effect_value), ("LIMIT", 2))
        waiver = self._consult(self.view, _q("req-1", "approval", "waive"))
        self.assertEqual(waiver.effect_kind, "DENY")
        self.assertTrue(waiver.explanation[0]["final"])  # final-cited (SGPE/05 §2 VAE row)
        self.assertEqual(resolve_citation(self.store, waiver.explanation[0]["winner"])
                          ["rule"]["rule_id"], "r-no-waiver")

    def test_lie_persistence_consultation(self):
        d = self._consult(self.view, _q("req-1", "persistence", "store", "lie/ledger-episode"))
        self.assertEqual(d.effect_kind, "ALLOW")

    def test_consumer_treats_ill_posed_as_no_action(self):
        outcome = self.view.consult(_q("req-1", "model", "invoke", facts={}))  # missing fact
        self.assertIsInstance(outcome, IllPosedVerdict)
        self.assertFalse(hasattr(outcome, "effect_kind"))  # nothing enforceable: no action


# -- approval lifecycle (IVS + Kernel routing) ----------------------------------------

class ApprovalLifecycle(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.view = self._admitted()
        self.ivs = IvsDouble()
        self.question = _q("req-1", "plugin", "bind", "plugin://web-search")

    def _run_approval_loop(self):
        ask = self._consult(self.view, self.question)
        payload = approval_ask_payload(ask)
        citations = [resolve_citation(self.store, step["winner"])
                     for step in ask.explanation if "winner" in step]
        outcome = self.ivs.present_ask(payload, citations)
        grant = self.runtime.route_approval(self.view, ask, outcome["grantor"], outcome["reason"])
        return ask, grant

    def test_full_approval_loop(self):
        ask, grant = self._run_approval_loop()
        self.assertEqual(ask.effect_kind, "REQUIRE_APPROVAL")
        (rendered_payload, rendered_citations) = self.ivs.rendered[0]
        self.assertEqual(rendered_payload["ask_signature"], ask.ask_signature)
        self.assertEqual(rendered_citations[0]["rule"]["rule_id"], "r-plugin")
        self.assertEqual(grant.scope.subject, "req-1")
        reasked = self._consult(self.view, self.question)
        self.assertEqual(reasked.effect_kind, "ALLOW")
        self.assertNotEqual(reasked.grant_slice_position, ask.grant_slice_position)

    def test_emergency_revocation_mid_request(self):
        ask, grant = self._run_approval_loop()
        self.assertEqual(self._consult(self.view, self.question).effect_kind, "ALLOW")
        self.runtime.route_revocation(self.view, ask, grant.record_id, "human-operator", "emergency")
        self.assertEqual(self._consult(self.view, self.question).effect_kind, "REQUIRE_APPROVAL")

    def test_unanswered_ask_never_becomes_a_grant(self):
        ask = self._consult(self.view, self.question)
        # IVS timeout / operator walks away: no route_approval call ever
        # happens -- REQUIRE_APPROVAL keeps meaning forbidden (SGPE/05 §5)
        again = self._consult(self.view, self.question)
        self.assertEqual(again.effect_kind, "REQUIRE_APPROVAL")
        self.assertEqual(self.ledger.position(), 0)
        _ = ask

    def test_routing_validates_the_outcome(self):
        allow = self._consult(self.view, _q("req-1", "execution", "run"))
        with self.assertRaises(ApprovalRoutingError):
            self.runtime.route_approval(self.view, allow, "op", "not an ask")
        with self.assertRaises(ApprovalRoutingError):
            self.runtime.route_approval(self.view, "not a decision", "op", "r")

    def test_approval_payload_rejects_non_asks(self):
        allow = self._consult(self.view, _q("req-1", "execution", "run"))
        with self.assertRaises(MalformedRuntimeInputError):
            approval_ask_payload(allow)


# -- fail-closed behaviour (SGPE/05 §5 consolidated law) ---------------------------------

class FailClosedLaw(IntegrationTestCase):
    def test_unknown_snapshot_version_blocks_consultation(self):
        stamp = {"snapshot_version": 99, "admission_ledger_position": 0,
                  "request_id": "req-x", "principal": "alice", "project": "proj-x"}
        view = self.runtime.view_for(stamp)
        with self.assertRaises(UnknownSnapshotVersionError):
            view.consult(_q("req-x", "execution", "run"))

    def test_corrupt_snapshot_artifact_refuses_regeneration(self):
        # a manifest whose recorded hash cannot be reproduced (artifact
        # corruption) -- consultations cannot proceed, no action (AC-9)
        bad_manifest = manifest_mod.build_manifest(
            2, self.store.catalog_position(), 2, 1,
            ((("system", "constitution"), 1),), "0" * 64)
        self.store.append_manifest(bad_manifest)
        self.store.append_activation(manifest_mod.build_activation(1, 2))
        view = self.runtime.admit("req-2", "alice", "proj-x")  # binds version 2
        with self.assertRaises(RegenerationMismatchError):
            view.consult(_q("req-2", "execution", "run"))

    def test_failed_grant_append_leaves_the_ask_unanswered(self):
        view = self._admitted()
        ask = self._consult(view, _q("req-1", "plugin", "bind"))
        self.ledger._storage.script_reject("sgpe/ledger/1")
        with self.assertRaises(Exception):
            self.runtime.route_approval(view, ask, "op", "approved")
        self.assertEqual(self.ledger.position(), 0)  # nothing landed
        self.assertEqual(self._consult(view, _q("req-1", "plugin", "bind")).effect_kind,
                          "REQUIRE_APPROVAL")  # still forbidden

    def test_no_fallback_snapshot_or_default_allow_exists(self):
        import inspect
        source_runtime = inspect.getsource(runtime_mod)
        for token in ("default_allow", "allow_all", "fail_open", "DEFAULT_SNAPSHOT"):
            self.assertNotIn(token, source_runtime)


# -- observability (SGPE/05 §4: events only, no parallel audit) ------------------------------

class Observability(IntegrationTestCase):
    def test_every_governance_act_is_a_bus_event(self):
        view = self._admitted()
        ask = self._consult(view, _q("req-1", "plugin", "bind"))
        self.runtime.route_approval(view, ask, "op", "approved")
        self._consult(view, _q("req-1", "plugin", "bind"))
        self.view_ill = view.consult(_q("req-1", "model", "invoke", facts={}))

        self.assertTrue(self.bus.messages("policy.authored"))    # bootstrap authoring
        self.assertTrue(self.bus.messages("policy.compiled"))
        self.assertTrue(self.bus.messages("policy.activated"))
        self.assertEqual(len(self.bus.messages("policy.decided")), 2)
        self.assertEqual(len(self.bus.messages("grant.recorded")), 1)
        self.assertEqual(len(self.bus.messages("policy.illposed")), 1)

    def test_diagnostics_answerable_from_events_alone(self):
        # "why was this denied" = citation chain from policy.decided (§4)
        view = self._admitted()
        self._consult(view, _q("req-1", "approval", "waive"))
        event = self.bus.messages("policy.decided")[-1]
        winner = event["payload"]["explanation"][0]["winner"]
        self.assertEqual(resolve_citation(self.store, winner)["rule"]["effect"]["kind"], "DENY")

    def test_sgpe_keeps_no_audit_state_beyond_the_two_records(self):
        self.assertFalse(hasattr(self.runtime, "audit_log"))
        self.assertFalse(hasattr(self.runtime, "metrics"))
        # replay is bus-silent: verification, not a governance act
        view = self._admitted()
        d = self._consult(view, _q("req-1", "execution", "run"))
        before = len(self.bus.messages("policy.decided"))
        view.replay(_q("req-1", "execution", "run"), d.grant_slice_position,
                     d.evaluation_ruleset_version)
        self.assertEqual(len(self.bus.messages("policy.decided")), before)


# -- end-to-end governance regression (required pipeline) --------------------------------------

class EndToEndGovernanceFlow(IntegrationTestCase):
    """User Request → Kernel Admission → EP → CP → WS → PRT → RO → VAE →
    LIE → Completion; every consultation recorded by the RSM double,
    then replayed byte-identically from stamps alone on a REBUILT
    runtime (fresh memo, ledger rebuilt from its log)."""

    def test_pipeline_and_byte_identical_replay(self):
        request_id = "req-e2e"
        ivs = IvsDouble()

        # Kernel admission → EP → RSM persists stamp
        view = self._admitted(request_id)
        kernel_gate = self._consult(view, _q(request_id, "execution", "run"))
        self.assertEqual(kernel_gate.effect_kind, "ALLOW")

        # Capability Planner: advisory pass over candidate capabilities
        plugin_question = _q(request_id, "plugin", "bind", "plugin://web-search")
        planned_plugin = self._consult(view, plugin_question)
        planned_model = self._consult(view, _q(request_id, "model", "invoke",
                                                 facts={"usage.tokens": 0}))
        self.assertEqual(planned_plugin.effect_kind, "REQUIRE_APPROVAL")
        self.assertEqual(planned_model.effect_kind, "ALLOW")

        # the ask surfaces through IVS; Kernel routes the approval
        outcome = ivs.present_ask(approval_ask_payload(planned_plugin), [])
        self.runtime.route_approval(view, planned_plugin, outcome["grantor"], outcome["reason"])

        # Workflow Scheduler: ceilings before dispatch
        concurrency = self._consult(view, _q(request_id, "resource-limit", "dispatch"))
        retries = self._consult(view, _q(request_id, "retry-limit", "dispatch"))
        self.assertEqual((concurrency.effect_value, retries.effect_value), (4, 3))

        # Context Manager: assembly ceiling under the same frozen EP
        context = self._consult(view, _q(request_id, "context-limit", "assemble"))
        self.assertEqual(context.effect_value, 8000)

        # Plugin Runtime: crossing-time re-ask — grant now applies
        crossed_plugin = self._consult(view, plugin_question)
        self.assertEqual(crossed_plugin.effect_kind, "ALLOW")

        # Reasoning Orchestrator: model permission + budget, usage grown
        reasoning = self._consult(view, _q(request_id, "model", "invoke",
                                             facts={"usage.tokens": 400}))
        self.assertEqual(reasoning.effect_kind, "ALLOW")
        self.assertEqual(reasoning.constraints[0][:2], ("token-budget", 1000))

        # Verification: budget ceiling; waiver ask blocked by `final`
        verify_budget = self._consult(view, _q(request_id, "resource-limit", "verify"))
        waiver = self._consult(view, _q(request_id, "approval", "waive"))
        self.assertEqual(verify_budget.effect_value, 2)
        self.assertEqual(waiver.effect_kind, "DENY")

        # Learning: persistence permission with retention ceiling
        learning = self._consult(view, _q(request_id, "persistence", "store", "lie/episode-1"))
        self.assertEqual(learning.effect_kind, "ALLOW")
        self.assertEqual(learning.constraints[0][:2], ("resource-limit", 30))

        # Completion: request ends; EP retired implicitly (EPR §2.4) —
        # nothing to clean up, so nothing to assert absent.

        # Replay: rebuilt runtime (fresh memo), ledger rebuilt from its
        # own log, view rebuilt from the RSM stamp — every recorded
        # consultation must reproduce byte-identical Decisions (EPR-7).
        recorded = self.rsm.consultations[request_id]
        self.assertEqual(len(recorded), 11)
        rebuilt_ledger = GrantLedger.rebuild_from_log(StorageDouble(), self.ledger.export_log())
        rebuilt_runtime = GovernanceRuntime(self.store, rebuilt_ledger)
        rebuilt_view = rebuilt_runtime.view_for(self.rsm.ep_stamps[request_id])
        for question, original in recorded:
            replayed = rebuilt_view.replay(question, original.grant_slice_position,
                                             original.evaluation_ruleset_version)
            self.assertEqual(decision_bytes(replayed), decision_bytes(original))

    def test_policy_propagation_across_activation_boundary(self):
        # a running request keeps its world; the next request sees the new one
        view_old = self._admitted("req-old")
        result = compiler_mod.compile_snapshot(self.store, self.store.catalog_position())
        compiler_mod.activate(self.store, result)
        view_new = self.runtime.admit("req-new", "alice", "proj-x")
        self.assertEqual(view_old.effective_policy.snapshot_version, 1)
        self.assertEqual(view_new.effective_policy.snapshot_version, 2)
        d_old = view_old.consult(_q("req-old", "execution", "run"))
        d_new = view_new.consult(_q("req-new", "execution", "run"))
        self.assertEqual((d_old.snapshot_version, d_new.snapshot_version), (1, 2))


# -- final self-audit: INV-1..12 sweep (SGPE/00 §review gate) -------------------------------------

class INVSweep(IntegrationTestCase):
    """SGPE/00's twelve system invariants, each verified here or mapped
    to the phase suite that owns it (PS/AC/EV/GL/EPR families are
    imported at module top — their absence would fail collection)."""

    def test_inv1_sgpe_decides_never_enforces(self):
        # a Decision is inert data: nothing on it (or the runtime) can act
        view = self._admitted()
        d = self._consult(view, _q("req-1", "execution", "run"))
        for verb in ("enforce", "execute", "apply", "run", "kill", "block"):
            self.assertFalse(hasattr(d, verb))
            self.assertFalse(hasattr(self.runtime, verb))

    def test_inv2_policy_is_declarative_data_only(self):
        with self.assertRaises(MalformedConditionError):
            condition_mod.build_comparison("f", "eq", lambda: True)  # no code in policy

    def test_inv3_evaluation_pure_in_stamps_and_question(self):
        view = self._admitted()
        q = _q("req-1", "execution", "run")
        self.assertEqual(decision_bytes(self._consult(view, q)),
                          decision_bytes(self._consult(view, q)))

    def test_inv4_undecidable_conflicts_rejected_at_compile(self):
        rules = _constitution_rules() + (
            _rule("r-mixed", "execution", "run", "*", "LIMIT", 9),)  # permission vs limit shape
        _, store, _ = _bootstrap(rules=rules, activate=False)
        result = compiler_mod.compile_snapshot(store, store.catalog_position())
        self.assertEqual(result.outcome, "rejected")
        self.assertEqual(result.report.errors[0].code, UNDECIDABLE_CONFLICT)

    def test_inv5_snapshots_immutable_versioned_history_preserved(self):
        result = compiler_mod.compile_snapshot(self.store, self.store.catalog_position())
        compiler_mod.activate(self.store, result)
        self.assertEqual([a.snapshot_version for a in self.store.activations()], [1, 2])
        with self.assertRaises(Exception):
            result.snapshot.entries = ()
        self.assertIsNotNone(self.runtime.snapshot_for(1))  # v1 never destroyed

    def test_inv6_effective_policy_frozen_for_request_lifetime(self):
        view = self._admitted()
        with self.assertRaises(Exception):
            view.effective_policy.snapshot_version = 99
        # external grant isolation is EPR-2's suite; re-checked end to end
        # in ApprovalLifecycle/EndToEndGovernanceFlow above

    def test_inv7_every_decision_carries_citations_from_the_evaluation(self):
        view = self._admitted()
        for domain, op in (("execution", "run"), ("approval", "waive"),
                            ("context-limit", "assemble")):
            d = self._consult(view, _q("req-1", domain, op))
            self.assertTrue(d.explanation[0]["matched"])
            self.assertTrue(d.explanation[0]["winner"])

    def test_inv8_every_governance_act_is_a_bus_event(self):
        for name in ("policy.authored", "policy.deprecated", "policy.compiled", "policy.rejected",
                      "policy.activated", "policy.decided", "policy.illposed",
                      "grant.recorded", "grant.revoked"):
            self.assertIn(name, events_mod.PUBLISHED)

    def test_inv9_grants_append_only_revocation_is_a_new_entry(self):
        view = self._admitted()
        ask = self._consult(view, _q("req-1", "plugin", "bind"))
        grant = self.runtime.route_approval(view, ask, "op", "ok")
        revocation = self.runtime.route_revocation(view, ask, grant.record_id, "op", "revoke")
        self.assertEqual(self.ledger.all(), (grant, revocation))  # both records live forever

    def test_inv10_policy_changes_originate_from_authoring_acts_only(self):
        # nothing in SGPE consumes events or mutates policy reactively
        self.assertEqual(events_mod.CONSUMED, ())
        with self.assertRaises(events_mod.UnknownEventError):
            events_mod.check_consumed("policy.decided")

    def test_inv11_new_domain_needs_zero_sgpe_code_change(self):
        operations = OPERATIONS + ("audit.log",)
        rules = _constitution_rules() + (_rule("r-audit", "audit", "log", "*", "ALLOW"),)
        bus = BusDouble()
        store = PolicyStore(StorageDouble(), bus=bus)
        v1 = vocabulary_mod.default_v1()
        store.append_vocabulary(v1)
        v2 = vocabulary_mod.evolve(v1, domains=vocabulary_mod.INITIAL_DOMAINS + ("audit",),
                                     operations=operations, fact_names=("usage.tokens",))
        store.append_vocabulary(v2)
        prov = document_mod.build_provenance("alice", "epoch-0", "constitution+audit")
        header = document_mod.build_header("system", "constitution", ("execution",), prov, 2, 1)
        store.append_document(document_mod.build_document(header, rules))
        result = compiler_mod.compile_snapshot(store, store.catalog_position())
        self.assertEqual(result.outcome, "compiled")
        compiler_mod.activate(store, result)
        runtime = GovernanceRuntime(store, GrantLedger(StorageDouble()))
        view = runtime.admit("req-1", "alice", "proj-x")
        self.assertEqual(view.consult(_q("req-1", "audit", "log")).effect_kind, "ALLOW")

    def test_inv12_totality_gap_rejected_at_compile(self):
        gapped = tuple(r for r in _constitution_rules() if r.rule_id != "r-exec")
        _, store, _ = _bootstrap(rules=gapped, activate=False)
        result = compiler_mod.compile_snapshot(store, store.catalog_position())
        self.assertEqual(result.outcome, "rejected")
        self.assertEqual(result.report.errors[0].code, TOTALITY_GAP)


if __name__ == "__main__":
    unittest.main()
