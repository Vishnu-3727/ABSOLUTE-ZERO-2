"""RO Phase 4 suite — RO/04-execution-governance.md, execution governance
(RO/05 §10 blueprint group G5). Covers: end-to-end successful invocation;
every failure class F1-F8 shaped correctly; expiry retryable then success;
cancellation from all four origins; race resolution (returned-despite-
pending-signal); retry request-identity/attempt-index/history-chain/
determinism; retry-envelope enforcement + retry-vs-budget-exhaustion
distinction; substitution (new resolution, refused for non-indicting
class); escalation directive + a full re-`prepare()` round trip through the
parent envelope; sealed-record immutability; composite patterns
(sequential/parallel/ensemble/specialist/review/debate), failure semantics,
one-parent-envelope threading, provider/engine isolation; replay (valid
chain, tampered chain, premature-termination); RO-E3 boundary-return
invariants; static AST scan of the seven Phase 4 modules for
time/random/datetime imports.
"""
import ast
import json
import os
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ro.decision_gate import DecisionRecord
from ro.records import build_capability, build_descriptor_row
from ro.schemas import SchemaRegistry
from ro.budget import allocate_budget
from ro.request import prepare, content_hash as request_content_hash, ProviderResolution
from ro.outcome import (
    build_sealed_outcome,
    content_hash as outcome_content_hash,
    canonical as outcome_canonical,
    InconsistentOutcomeError,
    RECOVERY_KINDS,
    FAILURE_CLASSES,
)
from ro.cancellation import (
    build_cancellation_signal,
    UnknownOriginError,
    ORIGINS as CANCELLATION_ORIGINS,
)
from ro.execution_policy import (
    build_execution_policy_view,
    derive_timeout_class,
    TIMEOUT_CLASSES,
)
from ro.engine_boundary import (
    ScriptedEngineDouble,
    ScriptExhaustedError,
    MalformedBoundaryReturnError,
)
from ro.invocation import (
    run_attempts,
    retry_with_substitution,
    escalation_directive,
    SubstitutionRefusedError,
)
from ro.composite import (
    ConstituentSpec,
    build_composite_plan,
    run_composite,
    MissingAggregationRuleError,
    EmptyConstituentsError,
    CompositeRefusal,
)
from ro.execution_replay import replay_attempts, ReplayRefusal


_CHARS = {
    "inference_depth": "moderate", "context_sensitivity": "medium",
    "determinism_tolerance": "medium", "knowledge_dependency": "medium",
    "creativity_requirement": "low", "reasoning_complexity": "C1",
    "verification_difficulty": "low", "expected_output_structure": "bounded",
}


def _capability(cap_id="ro.cap.summarize", rung="C1"):
    chars = dict(_CHARS, reasoning_complexity=rung)
    return build_capability(cap_id, "INTERPRETIVE", chars, lifecycle="active")


def _approved_decision(cap_id="ro.cap.summarize", rung="C1"):
    return DecisionRecord(
        outcome="REASONING_APPROVED",
        justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({}),
        approved_capability_id=cap_id, approved_required_rung=rung,
        approved_scope=MappingProxyType({
            "description": "summarize", "granularity": "single_demand", "narrowing": None,
        }),
    )


def _rqm():
    return {
        "core": ({"id": "c1", "content": "alpha fact", "provenance": "doc:1"},),
        "supporting": ({"id": "s1", "content": "beta detail", "provenance": "doc:2"},),
    }


def _row(provider_id="ro.provider.x", cap_id="ro.cap.summarize", rung="C1", **kw):
    defaults = dict(
        context_capacity_class="large", cost_class="low", latency_class="fast",
        determinism_class="low_variance", deployment_locality="local",
        privacy_domain="internal",
    )
    defaults.update(kw)
    return build_descriptor_row(provider_id, {cap_id: (rung,)}, **defaults)


class _Policy:
    policy_version = 1


def _registry():
    reg = SchemaRegistry()
    reg.register("ro.schema.summary", 1, ("summary",))
    return reg


def _prepare(**overrides):
    kwargs = dict(
        decision_record=_approved_decision(), rqm=_rqm(), capability_record=_capability(),
        descriptor_rows=[_row()], descriptor_space_version=5, policy_view=_Policy(),
        priors_version=2, schema_registry=_registry(), schema_id="ro.schema.summary",
        schema_version=1, budget_ceiling=1_000, budget_source_policy_version=1,
        verification_expectations={"must_cite": True},
    )
    kwargs.update(overrides)
    return prepare(**kwargs)


def _exec_policy(**overrides):
    kwargs = dict(policy_version=1, attempt_ceiling=3, retryable_classes={"F1", "F5", "F7", "F8"})
    kwargs.update(overrides)
    return build_execution_policy_view(**kwargs)


def _returned_entry(fields=("summary",), consumed=50, **extra):
    body = {f: "val" for f in fields}
    entry = {"kind": "returned", "output": json.dumps(body).encode("utf-8"),
              "consumed": consumed, "timing": {"units": 1}}
    entry.update(extra)
    return entry


# ---------------------------------------------------------------------------
# end-to-end success
# ---------------------------------------------------------------------------

class EndToEndTests(unittest.TestCase):
    def test_successful_invocation_seals_returned(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([_returned_entry()])
        records = run_attempts(req, res, double, _exec_policy())
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.recovery_kind, "RETURNED")
        self.assertIsNone(rec.failure_class)
        self.assertEqual(rec.output, {"summary": "val"})
        self.assertEqual(rec.attempt_index, 1)
        self.assertEqual(rec.attempt_history_refs, ())
        self.assertEqual(rec.provider_id, res.provider_id)

    def test_metadata_completeness(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([_returned_entry()])
        rec = run_attempts(req, res, double, _exec_policy())[0]
        self.assertEqual(rec.request_content_hash, request_content_hash(req))
        self.assertEqual(rec.resolution_content_hash, request_content_hash(res))
        self.assertTrue(dict(rec.preparation_coordinates))
        self.assertIsInstance(rec.attempt_index, int)
        self.assertIsInstance(rec.attempt_history_refs, tuple)
        self.assertIn(rec.recovery_kind, RECOVERY_KINDS)
        self.assertIsInstance(dict(rec.timing), dict)
        self.assertIsInstance(rec.budget_consumed, int)
        self.assertIsInstance(rec.budget_remaining, int)
        self.assertEqual(rec.provider_id, res.provider_id)  # audit-only reference present


# ---------------------------------------------------------------------------
# failure classes F1-F8
# ---------------------------------------------------------------------------

class FailureClassTests(unittest.TestCase):
    def test_f6_initiation_refusal_mismatched_coordinates(self):
        req, res = _prepare()
        bad_res = ProviderResolution(
            provider_id=res.provider_id, descriptor_space_version=res.descriptor_space_version,
            policy_version=res.policy_version, eligibility_exclusions=res.eligibility_exclusions,
            selection_justification=res.selection_justification,
            preparation_coordinates=MappingProxyType({}),
            resolved_for_request_hash=res.resolved_for_request_hash,
        )
        records = run_attempts(req, bad_res, ScriptedEngineDouble([]), _exec_policy())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].recovery_kind, "FAILED")
        self.assertEqual(records[0].failure_class, "F6")

    def test_f1_provider_unavailable_shape(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F1", "consumed": 5}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.recovery_kind, "FAILED")
        self.assertEqual(rec.failure_class, "F1")

    def test_f2_provider_refusal_shape(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F2", "consumed": 5}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.failure_class, "F2")

    def test_f3_budget_exhaustion_via_overdraft(self):
        req, res = _prepare(budget_ceiling=100)
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F1", "consumed": 500}])
        rec = run_attempts(req, res, double, _exec_policy())[0]
        self.assertEqual(rec.recovery_kind, "FAILED")
        self.assertEqual(rec.failure_class, "F3")
        self.assertEqual(rec.budget_remaining, 0)

    def test_f3_budget_exhaustion_via_retry_exhaustion(self):
        req, res = _prepare(budget_ceiling=100)
        # first attempt consumes the whole envelope with a retryable class;
        # policy allows retry and attempt_ceiling isn't reached -> the
        # governor must seal an explicit terminal F3 record rather than
        # silently stopping (RETRY-EXHAUSTION NOTE).
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F1", "consumed": 100}])
        policy = _exec_policy(attempt_ceiling=5, retryable_classes={"F1"})
        records = run_attempts(req, res, double, policy)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].failure_class, "F1")
        self.assertEqual(records[1].recovery_kind, "FAILED")
        self.assertEqual(records[1].failure_class, "F3")
        self.assertEqual(records[1].attempt_index, 2)

    def test_f7_attempt_ceiling_exhaustion_keeps_own_class(self):
        # distinct from F3: exhaustion by ATTEMPT CEILING keeps the
        # terminal record's own failure class (visible via attempt_index).
        req, res = _prepare(budget_ceiling=100_000)
        double = ScriptedEngineDouble([
            {"kind": "expired", "consumed": 1, "timing": {}},
            {"kind": "expired", "consumed": 1, "timing": {}},
        ])
        policy = _exec_policy(attempt_ceiling=2, retryable_classes={"F7"})
        records = run_attempts(req, res, double, policy)
        self.assertEqual(len(records), 2)  # no extra F3 record: ceiling, not budget, was the limiter
        self.assertEqual(records[-1].recovery_kind, "EXPIRED")
        self.assertEqual(records[-1].failure_class, "F7")
        self.assertEqual(records[-1].attempt_index, 2)

    def test_f4_request_invalid_shape(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F4", "consumed": 1}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.failure_class, "F4")

    def test_f5_execution_failure_shape(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F5", "consumed": 1}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.failure_class, "F5")

    def test_f8_unparseable_output(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "returned", "output": b"not json", "consumed": 1}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.recovery_kind, "FAILED")
        self.assertEqual(rec.failure_class, "F8")
        self.assertIsNone(rec.output)
        self.assertIn("nonconforming_output", dict(rec.metadata))

    def test_f8_non_object_output(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "returned", "output": b"[1,2,3]", "consumed": 1}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.failure_class, "F8")

    def test_f8_missing_required_field(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "returned", "output": b'{"wrong_field": 1}', "consumed": 1}])
        rec = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))[0]
        self.assertEqual(rec.failure_class, "F8")
        self.assertIn("missing_fields", dict(rec.metadata)["conformance_reason"])


# ---------------------------------------------------------------------------
# expiry
# ---------------------------------------------------------------------------

class ExpiryTests(unittest.TestCase):
    def test_expiry_retryable_then_success(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "expired", "consumed": 5, "timing": {"waited": 1}, "partial_output": b"half"},
            _returned_entry(consumed=10),
        ])
        records = run_attempts(req, res, double, _exec_policy(retryable_classes={"F7"}))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].recovery_kind, "EXPIRED")
        self.assertEqual(records[0].failure_class, "F7")
        self.assertIsNone(records[0].output)
        self.assertEqual(dict(records[0].metadata)["partial_output"], "half")
        self.assertEqual(records[1].recovery_kind, "RETURNED")


# ---------------------------------------------------------------------------
# cancellation
# ---------------------------------------------------------------------------

class CancellationTests(unittest.TestCase):
    def test_all_four_origins_sealed(self):
        for origin in CANCELLATION_ORIGINS:
            with self.subTest(origin=origin):
                req, res = _prepare()
                double = ScriptedEngineDouble([{"kind": "cancelled", "origin": origin, "consumed": 3}])
                rec = run_attempts(req, res, double, _exec_policy())[0]
                self.assertEqual(rec.recovery_kind, "CANCELLED")
                self.assertEqual(rec.cancellation_origin, origin)
                self.assertIsNone(rec.output)

    def test_cancellation_is_terminal_never_retried(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "cancelled", "origin": "kernel", "consumed": 1}])
        records = run_attempts(req, res, double, _exec_policy())
        self.assertEqual(len(records), 1)

    def test_race_returned_wins_over_pending_cancellation(self):
        req, res = _prepare()
        sig = build_cancellation_signal("user", {"request_id": req.request_id}, "sig-1")
        double = ScriptedEngineDouble([_returned_entry(consumed=5)])
        rec = run_attempts(req, res, double, _exec_policy(), cancellation_signals=(sig,))[0]
        self.assertEqual(rec.recovery_kind, "RETURNED")
        self.assertEqual(dict(rec.metadata)["race"]["resolution"], "returned_first")

    def test_race_cancelled_wins(self):
        req, res = _prepare()
        sig = build_cancellation_signal("policy", {"request_id": req.request_id}, "sig-2")
        double = ScriptedEngineDouble([{"kind": "cancelled", "origin": "policy", "consumed": 2}])
        rec = run_attempts(req, res, double, _exec_policy(), cancellation_signals=(sig,))[0]
        self.assertEqual(rec.recovery_kind, "CANCELLED")
        self.assertEqual(dict(rec.metadata)["race"]["resolution"], "cancelled_first")

    def test_unknown_origin_signal_refused(self):
        with self.assertRaises(UnknownOriginError):
            build_cancellation_signal("aliens", {}, "sig-x")


# ---------------------------------------------------------------------------
# retry mechanics
# ---------------------------------------------------------------------------

class RetryMechanicsTests(unittest.TestCase):
    def test_request_identity_unchanged_across_attempts(self):
        req, res = _prepare()
        before = request_content_hash(req)
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 5},
            _returned_entry(consumed=5),
        ])
        run_attempts(req, res, double, _exec_policy(retryable_classes={"F1"}))
        self.assertEqual(request_content_hash(req), before)

    def test_attempt_indices_and_history_chain(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
            _returned_entry(consumed=1),
        ])
        records = run_attempts(req, res, double, _exec_policy(attempt_ceiling=5, retryable_classes={"F1"}))
        self.assertEqual([r.attempt_index for r in records], [1, 2, 3])
        self.assertEqual(records[1].attempt_history_refs, (outcome_content_hash(records[0]),))
        self.assertEqual(records[2].attempt_history_refs,
                          (outcome_content_hash(records[0]), outcome_content_hash(records[1])))

    def test_attempt_ceiling_stops_attempts(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
        ])
        records = run_attempts(req, res, double, _exec_policy(attempt_ceiling=2, retryable_classes={"F1"}))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1].failure_class, "F1")  # own class stands, not rewritten

    def test_retry_determinism_same_script_byte_identical(self):
        req, res = _prepare()
        script = [
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
            _returned_entry(consumed=1),
        ]
        policy = _exec_policy(retryable_classes={"F1"})
        seq_a = run_attempts(req, res, ScriptedEngineDouble(list(script)), policy)
        seq_b = run_attempts(req, res, ScriptedEngineDouble(list(script)), policy)
        self.assertEqual([outcome_content_hash(r) for r in seq_a],
                          [outcome_content_hash(r) for r in seq_b])

    def test_non_retryable_class_stops_immediately(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F4", "consumed": 1}])
        records = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))
        self.assertEqual(len(records), 1)


# ---------------------------------------------------------------------------
# substitution
# ---------------------------------------------------------------------------

class SubstitutionTests(unittest.TestCase):
    def test_substitution_new_provider_request_unchanged(self):
        row_a = _row(provider_id="ro.provider.a")
        row_b = _row(provider_id="ro.provider.b")
        req, res = _prepare(descriptor_rows=[row_a])
        before = request_content_hash(req)
        policy = _exec_policy()
        new_res = retry_with_substitution(
            req, res, [row_a, row_b], policy=policy, failure_class="F1", descriptor_space_version=5)
        self.assertNotEqual(new_res.provider_id, res.provider_id)
        self.assertEqual(new_res.provider_id, "ro.provider.b")
        self.assertEqual(request_content_hash(req), before)

    def test_substitution_refused_for_non_indicting_class(self):
        row_a = _row(provider_id="ro.provider.a")
        row_b = _row(provider_id="ro.provider.b")
        req, res = _prepare(descriptor_rows=[row_a])
        policy = _exec_policy()
        with self.assertRaises(SubstitutionRefusedError):
            retry_with_substitution(req, res, [row_a, row_b], policy=policy,
                                     failure_class="F4", descriptor_space_version=5)


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------

class EscalationTests(unittest.TestCase):
    def test_escalation_directive_and_reprepare_from_parent(self):
        req, res = _prepare(budget_ceiling=500)
        double = ScriptedEngineDouble([{"kind": "failed", "failure_class": "F1", "consumed": 1}])
        records = run_attempts(req, res, double, _exec_policy(retryable_classes=frozenset()))

        parent_env = req.budget
        directive = escalation_directive(records, parent_env, reason="capability insufficient",
                                          rung_guidance="C2")
        self.assertTrue(directive.required_new_preparation)
        self.assertEqual(directive.final_record_refs, tuple(outcome_content_hash(r) for r in records))

        # caller takes the directive back through RO/03's prepare(), child
        # drawn from the SAME parent envelope (RO-P7): the new request's
        # budget parent_ref matches the directive's own parent envelope ref.
        req2, res2 = _prepare(
            budget_ceiling=100, parent_budget=parent_env, already_allocated_from_parent=0)
        self.assertIsNotNone(req2.budget.parent_ref)
        self.assertEqual(req2.budget.parent_ref, directive.parent_envelope_ref)


# ---------------------------------------------------------------------------
# sealed record shape / immutability
# ---------------------------------------------------------------------------

class OutcomeShapeTests(unittest.TestCase):
    def test_returned_with_failure_class_refused(self):
        with self.assertRaises(InconsistentOutcomeError):
            build_sealed_outcome(
                request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
                attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
                provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F1",
            )

    def test_cancelled_without_origin_refused(self):
        with self.assertRaises(InconsistentOutcomeError):
            build_sealed_outcome(
                request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
                attempt_index=1, attempt_history_refs=(), recovery_kind="CANCELLED",
                provider_id="p", budget_consumed=0, budget_remaining=1,
            )

    def test_sealed_record_immutable(self):
        rec = build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
            provider_id="p", budget_consumed=0, budget_remaining=1, output={"a": 1},
        )
        with self.assertRaises(Exception):
            rec.recovery_kind = "FAILED"

    def test_boundary_fifth_kind_refused(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([{"kind": "teleported"}])
        with self.assertRaises(MalformedBoundaryReturnError):
            run_attempts(req, res, double, _exec_policy())

    def test_script_exhaustion_is_loud_not_an_fclass(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 1},
        ])
        policy = _exec_policy(attempt_ceiling=5, retryable_classes={"F1"})
        with self.assertRaises(ScriptExhaustedError):
            run_attempts(req, res, double, policy)

    def test_engine_isolation_no_engine_reference_in_sealed_record(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([_returned_entry()])
        rec = run_attempts(req, res, double, _exec_policy())[0]
        marker = "ScriptedEngineDouble object at"
        self.assertNotIn(marker, outcome_canonical(rec).decode("utf-8", errors="ignore"))
        self.assertNotIn(str(id(double)), outcome_canonical(rec).decode("utf-8", errors="ignore"))


# ---------------------------------------------------------------------------
# timeout-class derivation
# ---------------------------------------------------------------------------

class TimeoutClassTests(unittest.TestCase):
    def test_derivation_is_deterministic_and_monotonic(self):
        policy = _exec_policy()
        order = {"standard": 0, "extended": 1, "long": 2}
        self.assertEqual(derive_timeout_class(policy, "fast", "C0"),
                          derive_timeout_class(policy, "fast", "C0"))
        self.assertLessEqual(order[derive_timeout_class(policy, "fast", "C1")],
                              order[derive_timeout_class(policy, "slow", "C1")])
        self.assertIn(derive_timeout_class(policy, "standard", "C2"), TIMEOUT_CLASSES)


# ---------------------------------------------------------------------------
# composite
# ---------------------------------------------------------------------------

def _final(kind, provider_id, output=None, failure_class=None, cancellation_origin=None):
    return build_sealed_outcome(
        request_content_hash="req-" + provider_id, resolution_content_hash="res-" + provider_id,
        preparation_coordinates={}, attempt_index=1, attempt_history_refs=(),
        recovery_kind=kind, provider_id=provider_id, budget_consumed=1, budget_remaining=9,
        failure_class=failure_class, cancellation_origin=cancellation_origin, output=output,
    )


class CompositeTests(unittest.TestCase):
    def test_sequential_feeds_prior_sealed_output(self):
        seen_inputs = []

        def runner(request, resolution, envelope):
            seen_inputs.append(request)
            idx = len(seen_inputs)
            return (_final("RETURNED", "prov" + str(idx), output={"n": idx}),)

        specs = tuple(
            ConstituentSpec("c" + str(i),
                             prepare=lambda prior: ("req-with-" + str(len(prior)) + "-priors", "res"),
                             budget_ceiling=10)
            for i in range(3)
        )
        plan = build_composite_plan("sequential", specs, "all_required")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner)
        self.assertEqual(seen_inputs, ["req-with-0-priors", "req-with-1-priors", "req-with-2-priors"])
        self.assertEqual(out.failure_semantics_verdict, "satisfied")

    def test_parallel_independence(self):
        def runner(request, resolution, envelope):
            return (_final("RETURNED", "p", output={"a": 1}),)

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(3))
        plan = build_composite_plan("parallel", specs, "any_sufficient")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner)
        self.assertEqual(out.failure_semantics_verdict, "satisfied")

    def test_specialist_pipeline_same_as_sequential(self):
        def runner(request, resolution, envelope):
            return (_final("RETURNED", "p", output={"a": 1}),)

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(2))
        plan = build_composite_plan("specialist_pipeline", specs, "all_required")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner)
        self.assertEqual(out.failure_semantics_verdict, "satisfied")

    def test_review_chain_consumes_sealed_output_only(self):
        captured = []

        def runner(request, resolution, envelope):
            captured.append(request)
            return (_final("RETURNED", "p", output={"verdict": "reviewed"}),)

        first = ConstituentSpec("author", prepare=lambda prior: ("write", "res"), budget_ceiling=10)
        review = ConstituentSpec(
            "reviewer",
            prepare=lambda prior: (("review-of", tuple(f.output for f in prior)), "res"),
            budget_ceiling=10)
        plan = build_composite_plan("review_chain", (first, review), "all_required")
        parent = allocate_budget(1000, source_policy_version=1)
        run_composite(plan, parent, runner)
        # the reviewer's request carries only the prior SEALED OUTPUT — no
        # verification field exists anywhere in that structure (structural:
        # SealedOutcomeRecord has no such field either).
        self.assertEqual(captured[1], ("review-of", ({"verdict": "reviewed"},)))
        self.assertFalse(hasattr(_final("RETURNED", "p"), "verified"))

    def test_ensemble_majority_and_tie_break(self):
        outputs = [{"a": 1}, {"a": 2}, {"a": 1}, None]
        kinds = ["RETURNED", "RETURNED", "RETURNED", "FAILED"]

        def runner_factory():
            calls = []

            def runner(request, resolution, envelope):
                idx = len(calls)
                calls.append(idx)
                fc = "F1" if kinds[idx] == "FAILED" else None
                return (_final(kinds[idx], "p" + str(idx), output=outputs[idx], failure_class=fc),)
            return runner

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(4))
        plan = build_composite_plan("ensemble", specs, "any_sufficient",
                                     aggregation_rule="majority_of_conforming")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner_factory())
        winner = _final("RETURNED", "p0", output={"a": 1})
        self.assertEqual(out.aggregation_result_ref, outcome_content_hash(winner))

    def test_first_conforming_by_stable_order(self):
        outputs = [None, {"a": 9}, {"a": 8}]
        kinds = ["FAILED", "RETURNED", "RETURNED"]

        def runner_factory():
            calls = []

            def runner(request, resolution, envelope):
                idx = len(calls)
                calls.append(idx)
                fc = "F1" if kinds[idx] == "FAILED" else None
                return (_final(kinds[idx], "p" + str(idx), output=outputs[idx], failure_class=fc),)
            return runner

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(3))
        plan = build_composite_plan("ensemble", specs, "any_sufficient",
                                     aggregation_rule="first_conforming_by_stable_order")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner_factory())
        winner = _final("RETURNED", "p1", output={"a": 9})
        self.assertEqual(out.aggregation_result_ref, outcome_content_hash(winner))

    def test_debate_uses_ensemble_rules(self):
        def runner(request, resolution, envelope):
            return (_final("RETURNED", "p", output={"claim": "x"}),)

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(2))
        plan = build_composite_plan("debate", specs, "any_sufficient",
                                     aggregation_rule="majority_of_conforming")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner)
        self.assertIsNotNone(out.aggregation_result_ref)

    def test_failure_semantics_all_required(self):
        kinds = ["RETURNED", "FAILED"]

        def runner_factory():
            calls = []

            def runner(request, resolution, envelope):
                idx = len(calls)
                calls.append(idx)
                fc = "F1" if kinds[idx] == "FAILED" else None
                return (_final(kinds[idx], "p" + str(idx), failure_class=fc),)
            return runner

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(2))
        plan = build_composite_plan("parallel", specs, "all_required")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner_factory())
        self.assertEqual(out.failure_semantics_verdict, "failed")

    def test_failure_semantics_any_sufficient(self):
        kinds = ["FAILED", "RETURNED"]

        def runner_factory():
            calls = []

            def runner(request, resolution, envelope):
                idx = len(calls)
                calls.append(idx)
                fc = "F1" if kinds[idx] == "FAILED" else None
                return (_final(kinds[idx], "p" + str(idx), failure_class=fc),)
            return runner

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(2))
        plan = build_composite_plan("parallel", specs, "any_sufficient")
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner_factory())
        self.assertEqual(out.failure_semantics_verdict, "satisfied")

    def test_failure_semantics_quorum(self):
        kinds = ["RETURNED", "RETURNED", "FAILED"]

        def runner_factory():
            calls = []

            def runner(request, resolution, envelope):
                idx = len(calls)
                calls.append(idx)
                fc = "F1" if kinds[idx] == "FAILED" else None
                return (_final(kinds[idx], "p" + str(idx), failure_class=fc),)
            return runner

        specs = tuple(ConstituentSpec("c" + str(i), prepare=lambda prior: (prior, "res"), budget_ceiling=10)
                       for i in range(3))
        plan = build_composite_plan("parallel", specs, "quorum", quorum_k=2)
        parent = allocate_budget(1000, source_policy_version=1)
        out = run_composite(plan, parent, runner_factory())
        self.assertEqual(out.failure_semantics_verdict, "satisfied")

    def test_one_parent_envelope_sibling_accounting(self):
        seen_ceilings = []

        def runner(request, resolution, envelope):
            seen_ceilings.append(envelope.ceiling)
            return (_final("RETURNED", "p", output={"a": 1}),)

        specs = (
            ConstituentSpec("c0", prepare=lambda prior: (prior, "res"), budget_ceiling=300),
            ConstituentSpec("c1", prepare=lambda prior: (prior, "res"), budget_ceiling=400),
        )
        plan = build_composite_plan("parallel", specs, "all_required")
        parent = allocate_budget(1000, source_policy_version=1)
        run_composite(plan, parent, runner)
        self.assertEqual(seen_ceilings, [300, 400])
        # exceeding the parent's remaining envelope on the second child is refused
        over_specs = (
            ConstituentSpec("c0", prepare=lambda prior: (prior, "res"), budget_ceiling=700),
            ConstituentSpec("c1", prepare=lambda prior: (prior, "res"), budget_ceiling=700),
        )
        over_plan = build_composite_plan("parallel", over_specs, "all_required")
        with self.assertRaises(Exception):
            run_composite(over_plan, allocate_budget(1000, source_policy_version=1), runner)

    def test_provider_isolation_structural(self):
        # ReasoningRequest never carries a provider id (RO-P2); a
        # composite's constituent A therefore structurally cannot leak B's
        # provider id into its own request/context, verified via prepare().
        req_a, res_a = _prepare(descriptor_rows=[_row(provider_id="ro.provider.SECRET_A")])
        self.assertNotIn("ro.provider.SECRET_A", json.dumps(
            {"context": req_a.context, "constraints": dict(req_a.constraints)}, default=str))

    def test_missing_aggregation_rule_refused(self):
        specs = (ConstituentSpec("c0", prepare=lambda prior: (prior, "res"), budget_ceiling=10),)
        with self.assertRaises(MissingAggregationRuleError):
            build_composite_plan("ensemble", specs, "any_sufficient")

    def test_empty_constituents_refused(self):
        with self.assertRaises(EmptyConstituentsError):
            build_composite_plan("parallel", (), "any_sufficient")

    def test_bad_quorum_k_refused(self):
        specs = (ConstituentSpec("c0", prepare=lambda prior: (prior, "res"), budget_ceiling=10),)
        with self.assertRaises(CompositeRefusal):
            build_composite_plan("parallel", specs, "quorum", quorum_k=0)


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

class ReplayTests(unittest.TestCase):
    def test_valid_chain_replays(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 5},
            _returned_entry(consumed=5),
        ])
        records = run_attempts(req, res, double, _exec_policy(retryable_classes={"F1"}))
        self.assertIs(replay_attempts(records), records)

    def test_tampered_record_fails_loud(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([
            {"kind": "failed", "failure_class": "F1", "consumed": 5},
            _returned_entry(consumed=5),
        ])
        records = run_attempts(req, res, double, _exec_policy(retryable_classes={"F1"}))
        tampered_first = build_sealed_outcome(
            request_content_hash=records[0].request_content_hash,
            resolution_content_hash=records[0].resolution_content_hash,
            preparation_coordinates=records[0].preparation_coordinates,
            attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED",
            provider_id=records[0].provider_id, budget_consumed=999, budget_remaining=1,
            failure_class="F1",
        )
        tampered_chain = (tampered_first, records[1])
        with self.assertRaises(ReplayRefusal):
            replay_attempts(tampered_chain)

    def test_replay_reads_answer_as_data_never_regenerates(self):
        req, res = _prepare()
        double = ScriptedEngineDouble([_returned_entry()])
        records = run_attempts(req, res, double, _exec_policy())
        replayed = replay_attempts(records)
        self.assertEqual(replayed[0].output, records[0].output)  # verbatim, not recomputed


# ---------------------------------------------------------------------------
# static invariants
# ---------------------------------------------------------------------------

class StaticInvariantTests(unittest.TestCase):
    _MODULES = ("outcome.py", "cancellation.py", "execution_policy.py",
                "engine_boundary.py", "invocation.py", "composite.py",
                "execution_replay.py")

    def _src_dir(self):
        return Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "ro"))

    def test_no_time_or_random_import_in_phase4_modules(self):
        for name in self._MODULES:
            tree = ast.parse((self._src_dir() / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(imported & {"time", "random", "datetime"}, name)


if __name__ == "__main__":
    unittest.main()
