"""RO/04 §1-§7 — the invocation governor (RO/05 §10 blueprint group G5, "the
core"). `run_attempts` is the single place the OS crosses the quarantine
boundary (RO-E1): Initiated checks, one crossing per attempt, mapping the
boundary's closed-four return to a recovery, mechanical F8 conformance,
budget bookkeeping that never overdrafts, and the bounded retry loop.

Every attempt seals its own immutable `outcome.SealedOutcomeRecord`
(RO-E4); `run_attempts` returns the FULL ordered tuple, last = final. The
Request is never mutated across attempts (RO-E5) — callers can assert
`request_content_hash(request)` is identical before and after.

Two more entry points close out RO/04 §4: `retry_with_substitution` (same
Request, next eligible provider, valid only for policy-declared
substitution classes) and `escalation_directive` (escalation is a new
preparation cycle's business, never an automatic loop — this module only
hands the caller a frozen directive to take back through RO/03's
`prepare()`, RO-P7).
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from . import matching_selection as _matching_selection
from . import outcome as _outcome
from . import renderer as _renderer
from .budget import _envelope_hash as _budget_envelope_hash
from .cancellation import ORIGINS as CANCELLATION_ORIGINS
from .engine_boundary import CrossingPayload
from .execution_policy import derive_timeout_class
from .outcome import FAILURE_CLASSES
from .request import ProviderResolution, content_hash as _artifact_content_hash

# RO/03 §9 constraint categories — local mirror of renderer._CONSTRAINT_
# CATEGORIES (that tuple is renderer-module-private; duplicating six
# strings here is cheaper and less coupling than exporting it, mirrors
# renderer.py's own precedent of locally mirroring request.py's
# _deep_unfreeze rather than importing a private helper).
_CONSTRAINT_CATEGORIES = (
    "allowed_scope", "output_form", "forbidden_behaviors",
    "determinism_expectations", "policy_constraints", "verification_expectations",
)


class InvocationRefusal(Exception):
    """Base for invocation-governor refusals (never for a governed
    outcome — those seal an F6/F3/etc. record instead, RO/04 §2)."""


class SubstitutionRefusedError(InvocationRefusal):
    """RO/04 §4: retry-with-substitution is valid only for policy-declared
    substitution classes."""


def _constraints_ref(constraints):
    payload = json.dumps(_outcome._unfreeze(constraints), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _check_initiation(request, resolution):
    """RO/04 §2 Initiated: budget attached, constraints present (all six
    categories), resolution coordinates match the request's. Returns a
    tuple of reason strings — empty means initiation passed."""
    reasons = []
    if request.budget is None:
        reasons.append("missing_budget")
    missing = [c for c in _CONSTRAINT_CATEGORIES if c not in request.constraints]
    if missing:
        reasons.append("missing_constraints:" + ",".join(missing))
    if dict(resolution.preparation_coordinates) != dict(request.preparation_coordinates):
        reasons.append("coordinates_mismatch")
    if resolution.resolved_for_request_hash != _artifact_content_hash(request):
        reasons.append("resolution_not_for_request")
    return tuple(reasons)


def _parse_f8(raw_output, request):
    """RO/04 §5 F8 — mechanical conformance only (RO-E8): parse as JSON,
    require an object, require every declared `output_form.required_fields`
    key present. No semantic judgment of the parsed content."""
    if raw_output is None:
        return False, "missing_output", None
    if isinstance(raw_output, (bytes, bytearray)):
        try:
            raw_text = raw_output.decode("utf-8")
        except UnicodeDecodeError:
            return False, "undecodable_bytes", None
    elif isinstance(raw_output, str):
        raw_text = raw_output
    else:
        return False, "not_bytes_or_str", None
    try:
        parsed = json.loads(raw_text)
    except ValueError:
        return False, "unparseable", None
    if not isinstance(parsed, dict):
        return False, "not_an_object", None
    required = request.constraints["output_form"]["required_fields"]
    missing = [f for f in required if f not in parsed]
    if missing:
        return False, "missing_fields:" + ",".join(missing), parsed
    return True, None, parsed


def run_attempts(request, resolution, boundary, policy, *, request_form="prompt_text",
                  latency_constraint="standard", cancellation_signals=()):
    """RO/04's full attempt lifecycle. Returns a tuple of `SealedOutcomeRecord`,
    last = final. `request_form`/`latency_constraint` are the resolved
    provider's declared render form (records.DescriptorRow.request_form)
    and the workflow's sealed latency constraint (RO/03 §5) respectively —
    both closed-vocabulary data the caller already holds from preparation;
    this module has no other way to learn them since `ProviderResolution`
    carries neither field (interpretation call, see report)."""
    req_hash = _artifact_content_hash(request)
    res_hash = _artifact_content_hash(resolution)

    initiation_reasons = _check_initiation(request, resolution)
    if initiation_reasons:
        budget_ceiling = request.budget.ceiling if request.budget is not None else 0
        return (_outcome.build_sealed_outcome(
            request_content_hash=req_hash, resolution_content_hash=res_hash,
            preparation_coordinates=request.preparation_coordinates,
            attempt_index=1, attempt_history_refs=(),
            recovery_kind="FAILED", failure_class="F6",
            provider_id=resolution.provider_id,
            budget_consumed=0, budget_remaining=budget_ceiling,
            metadata={"initiation_refusal_reasons": list(initiation_reasons)},
        ),)

    budget_ceiling = request.budget.ceiling
    consumed_total = 0
    records = []
    attempt_index = 1
    complexity_rung = request.required_rung

    def _seal(**kwargs):
        return _outcome.build_sealed_outcome(
            request_content_hash=req_hash, resolution_content_hash=res_hash,
            preparation_coordinates=request.preparation_coordinates,
            attempt_index=attempt_index,
            attempt_history_refs=tuple(_outcome.content_hash(r) for r in records),
            provider_id=resolution.provider_id, **kwargs,
        )

    def _apply_consumption(consumed):
        nonlocal consumed_total
        if not isinstance(consumed, int) or isinstance(consumed, bool) or consumed < 0:
            raise InvocationRefusal("invocation.bad_consumed:" + repr(consumed))
        overdraft = consumed_total + consumed > budget_ceiling
        if overdraft:
            capped = max(budget_ceiling - consumed_total, 0)
            consumed_total = budget_ceiling
            return capped, True
        consumed_total += consumed
        return consumed, False

    while True:
        timeout_class = derive_timeout_class(policy, latency_constraint, complexity_rung)
        rendered = _renderer.render(request, request_form)
        payload = CrossingPayload(
            rendered=rendered, timeout_class=timeout_class,
            budget_remaining=budget_ceiling - consumed_total,
            constraints_ref=_constraints_ref(request.constraints),
            cancellation_signals=tuple(cancellation_signals),
        )
        entry = boundary(payload)
        kind = entry["kind"]

        if kind == "returned":
            actual, overdraft = _apply_consumption(entry.get("consumed", 0))
            if overdraft:
                rec = _seal(recovery_kind="FAILED", failure_class="F3",
                            budget_consumed=actual, budget_remaining=0,
                            metadata={"reason": "boundary_overdraft"})
                records.append(rec)
                break
            race = None
            if cancellation_signals:
                race = {"pending_signal_ids": [s.signal_id for s in cancellation_signals],
                        "resolution": "returned_first"}
            conforms, reason, parsed = _parse_f8(entry.get("output"), request)
            timing = entry.get("timing", {})
            if conforms:
                metadata = {"race": race} if race else {}
                rec = _seal(recovery_kind="RETURNED", timing=timing,
                            budget_consumed=actual, budget_remaining=budget_ceiling - consumed_total,
                            output=parsed, metadata=metadata)
                records.append(rec)
                break
            metadata = {"conformance_reason": reason, "nonconforming_output": _to_jsonable(entry.get("output"))}
            if race:
                metadata["race"] = race
            rec = _seal(recovery_kind="FAILED", failure_class="F8", timing=timing,
                        budget_consumed=actual, budget_remaining=budget_ceiling - consumed_total,
                        metadata=metadata)
            records.append(rec)
            disposition = _retry_disposition("F8", policy, attempt_index, consumed_total, budget_ceiling)
            if disposition == "retry":
                attempt_index += 1
                continue
            if disposition == "exhausted_budget":
                attempt_index += 1
                records.append(_seal_exhaustion(_seal))
            break

        if kind == "failed":
            failure_class = entry.get("failure_class")
            if failure_class not in FAILURE_CLASSES or failure_class == "F7":
                raise InvocationRefusal("invocation.bad_failure_class:" + str(failure_class))
            actual, overdraft = _apply_consumption(entry.get("consumed", 0))
            if overdraft:
                rec = _seal(recovery_kind="FAILED", failure_class="F3",
                            budget_consumed=actual, budget_remaining=0,
                            metadata={"reason": "boundary_overdraft", "reported_class": failure_class})
                records.append(rec)
                break
            rec = _seal(recovery_kind="FAILED", failure_class=failure_class,
                        timing=entry.get("timing", {}), budget_consumed=actual,
                        budget_remaining=budget_ceiling - consumed_total,
                        metadata=dict(entry.get("metadata", {})))
            records.append(rec)
            disposition = _retry_disposition(failure_class, policy, attempt_index, consumed_total, budget_ceiling)
            if disposition == "retry":
                attempt_index += 1
                continue
            if disposition == "exhausted_budget":
                attempt_index += 1
                records.append(_seal_exhaustion(_seal))
            break

        if kind == "expired":
            actual, overdraft = _apply_consumption(entry.get("consumed", 0))
            if overdraft:
                rec = _seal(recovery_kind="FAILED", failure_class="F3",
                            budget_consumed=actual, budget_remaining=0,
                            metadata={"reason": "boundary_overdraft"})
                records.append(rec)
                break
            metadata = {}
            if entry.get("partial_output") is not None:
                metadata["partial_output"] = _to_jsonable(entry.get("partial_output"))
            rec = _seal(recovery_kind="EXPIRED", failure_class="F7", timing=entry.get("timing", {}),
                        budget_consumed=actual, budget_remaining=budget_ceiling - consumed_total,
                        metadata=metadata)
            records.append(rec)
            disposition = _retry_disposition("F7", policy, attempt_index, consumed_total, budget_ceiling)
            if disposition == "retry":
                attempt_index += 1
                continue
            if disposition == "exhausted_budget":
                attempt_index += 1
                records.append(_seal_exhaustion(_seal))
            break

        # kind == "cancelled" (engine_boundary already refused any fifth kind)
        origin = entry.get("origin")
        if origin not in CANCELLATION_ORIGINS:
            raise InvocationRefusal("invocation.bad_cancellation_origin:" + str(origin))
        actual, overdraft = _apply_consumption(entry.get("consumed", 0))
        metadata = {}
        if entry.get("partial_output") is not None:
            metadata["partial_output"] = _to_jsonable(entry.get("partial_output"))
        if cancellation_signals:
            metadata["race"] = {"pending_signal_ids": [s.signal_id for s in cancellation_signals],
                                 "resolution": "cancelled_first"}
        rec = _seal(recovery_kind="CANCELLED", cancellation_origin=origin,
                    timing=entry.get("timing", {}), budget_consumed=actual,
                    budget_remaining=budget_ceiling - consumed_total, metadata=metadata)
        records.append(rec)
        break  # cancellation is always terminal (RO/04 §7) — never retried

    return tuple(records)


def _to_jsonable(value):
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return repr(value)
    return value


def _retry_disposition(failure_class, policy, attempt_index, consumed_total, budget_ceiling):
    """RETRY-EXHAUSTION NOTE: distinguishes three outcomes for a just-sealed
    retryable-or-not failure/expiry:

      "retry"           — class is policy-retryable, attempt ceiling not
                           reached, budget not exhausted -> loop again.
      "exhausted_budget"— class WOULD have retried (retryable, ceiling not
                           reached) but the envelope is out of budget ->
                           seal one additional terminal F3 record (budget
                           exhaustion is its own governed outcome, RO/04
                           §4 "an envelope exhausted by retries is
                           exhausted").
      "terminal"         — either the class isn't policy-retryable, or the
                           attempt ceiling is reached; the just-sealed
                           record's OWN class stands as final — ceiling
                           exhaustion is visible from attempt_index alone,
                           never by rewriting the class.
    """
    retryable = failure_class in policy.retryable_classes
    under_ceiling = attempt_index < policy.attempt_ceiling
    if not (retryable and under_ceiling):
        return "terminal"
    return "retry" if consumed_total < budget_ceiling else "exhausted_budget"


def _seal_exhaustion(seal):
    # ponytail: tiny closure-shaped helper kept inline-adjacent to `_seal`
    # (which closes over the real `attempt_index` via nonlocal in
    # run_attempts) — used only for the one extra terminal F3 record sealed
    # when a retryable failure exhausts the budget before the attempt
    # ceiling does.
    return seal(recovery_kind="FAILED", failure_class="F3", budget_consumed=0, budget_remaining=0,
                metadata={"reason": "budget_exhausted_before_retry"})


def retry_with_substitution(request, failed_resolution, descriptor_rows, *, policy, failure_class,
                             descriptor_space_version, privacy_domain_required="public",
                             required_compliance_tags=(), locality_required=None,
                             declared_preference=()):
    """RO/04 §4 retry-with-substitution: same Request (never touched here),
    a new `ProviderResolution` excluding the indicted provider. Valid only
    when `failure_class` is one of `policy.substitution_classes` — refused
    loud otherwise (RO-E5's "never against the request" extends to: never a
    silent substitution either)."""
    if failure_class not in policy.substitution_classes:
        raise SubstitutionRefusedError(
            "invocation.non_substitution_class:" + str(failure_class))

    filtered_rows = tuple(r for r in descriptor_rows if r.provider_id != failed_resolution.provider_id)
    candidate_set = _matching_selection.build_candidate_set(
        filtered_rows, request.capability_id, request.required_rung)
    total_bytes = sum(len(item["content"].encode("utf-8")) for item in request.context)
    size_class = _matching_selection.derive_size_class(total_bytes)
    resolved_row, exclusions, justification = _matching_selection.select_provider(
        candidate_set, privacy_domain_required=privacy_domain_required,
        required_compliance_tags=required_compliance_tags, request_size_class=size_class,
        locality_required=locality_required, declared_preference=declared_preference)

    return ProviderResolution(
        provider_id=resolved_row.provider_id,
        descriptor_space_version=descriptor_space_version,
        policy_version=failed_resolution.policy_version,
        eligibility_exclusions=exclusions,
        selection_justification=MappingProxyType(justification),
        preparation_coordinates=request.preparation_coordinates,
        resolved_for_request_hash=_artifact_content_hash(request),
    )


@dataclass(frozen=True)
class EscalationDirective:
    reason: str
    parent_envelope_ref: str
    required_new_preparation: bool
    rung_guidance: str
    final_record_refs: tuple


def escalation_directive(final_records, parent_envelope, *, reason, rung_guidance):
    """RO/04 §4 "Escalation != retry": a frozen directive naming the parent
    envelope (RO-P7) and the rung guidance for a NEW preparation cycle.
    Never wires an automatic loop — the caller takes this back through
    RO/03's `prepare()` (`parent_budget=parent_envelope`)."""
    return EscalationDirective(
        reason=reason, parent_envelope_ref=_budget_envelope_hash(parent_envelope),
        required_new_preparation=True, rung_guidance=rung_guidance,
        final_record_refs=tuple(_outcome.content_hash(r) for r in final_records),
    )


def to_dict(directive):
    return {"reason": directive.reason, "parent_envelope_ref": directive.parent_envelope_ref,
            "required_new_preparation": directive.required_new_preparation,
            "rung_guidance": directive.rung_guidance,
            "final_record_refs": list(directive.final_record_refs)}


def canonical(directive):
    return json.dumps(to_dict(directive), sort_keys=True, separators=(",", ":")).encode()


def content_hash(directive):
    return hashlib.sha256(canonical(directive)).hexdigest()


if __name__ == "__main__":
    from types import MappingProxyType as _MPT

    from .budget import allocate_budget
    from .decision_gate import DecisionRecord
    from .engine_boundary import ScriptedEngineDouble
    from .execution_policy import build_execution_policy_view
    from .records import build_capability, build_descriptor_row
    from .request import prepare
    from .schemas import SchemaRegistry

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "medium",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, lifecycle="active")
    approved = DecisionRecord(
        outcome="REASONING_APPROVED", justification=_MPT({"passed": ("x",)}),
        decided_from=_MPT({}), approved_capability_id="ro.cap.summarize", approved_required_rung="C1",
        approved_scope=_MPT({"description": "summarize", "granularity": "single_demand", "narrowing": None}),
    )
    rqm = {"core": ({"id": "c1", "content": "alpha", "provenance": "doc:1"},),
           "supporting": ({"id": "s1", "content": "beta", "provenance": "doc:2"},)}
    row = build_descriptor_row(
        "ro.provider.x", {"ro.cap.summarize": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )

    class _Policy:
        policy_version = 1

    registry = SchemaRegistry()
    registry.register("ro.schema.summary", 1, ("summary",))

    req, res = prepare(
        approved, rqm=rqm, capability_record=cap, descriptor_rows=[row],
        descriptor_space_version=5, policy_view=_Policy(), priors_version=2,
        schema_registry=registry, schema_id="ro.schema.summary", schema_version=1,
        budget_ceiling=10_000, budget_source_policy_version=1,
        verification_expectations={"must_cite": True},
    )

    policy = build_execution_policy_view(policy_version=1, attempt_ceiling=3,
                                          retryable_classes={"F1", "F5", "F7", "F8"})

    double = ScriptedEngineDouble([
        {"kind": "returned", "output": b'{"summary": "ok"}', "consumed": 100, "timing": {"units": 3}},
    ])
    before_hash = _artifact_content_hash(req)
    records = run_attempts(req, res, double, policy)
    assert _artifact_content_hash(req) == before_hash  # request never mutated (RO-E5)
    assert len(records) == 1
    assert records[0].recovery_kind == "RETURNED"
    assert records[0].output == {"summary": "ok"}
    assert records[0].attempt_index == 1

    # F6 initiation refusal: mismatched coordinates -> sealed, not raised
    bad_res = ProviderResolution(
        provider_id=res.provider_id, descriptor_space_version=res.descriptor_space_version,
        policy_version=res.policy_version, eligibility_exclusions=res.eligibility_exclusions,
        selection_justification=res.selection_justification,
        preparation_coordinates=MappingProxyType({}), resolved_for_request_hash=res.resolved_for_request_hash,
    )
    f6_records = run_attempts(req, bad_res, ScriptedEngineDouble([]), policy)
    assert len(f6_records) == 1
    assert f6_records[0].recovery_kind == "FAILED" and f6_records[0].failure_class == "F6"

    # retry then success; attempt indices + history chain
    double2 = ScriptedEngineDouble([
        {"kind": "failed", "failure_class": "F1", "consumed": 10},
        {"kind": "returned", "output": b'{"summary": "ok"}', "consumed": 20, "timing": {}},
    ])
    seq = run_attempts(req, res, double2, policy)
    assert [r.attempt_index for r in seq] == [1, 2]
    assert seq[1].attempt_history_refs == (_outcome.content_hash(seq[0]),)
    assert seq[-1].recovery_kind == "RETURNED"

    # substitution valid for F1, refused for a non-indicting class
    new_res = retry_with_substitution(
        req, res, [row, build_descriptor_row(
            "ro.provider.y", {"ro.cap.summarize": ("C1",)}, context_capacity_class="large",
            cost_class="low", latency_class="fast", determinism_class="low_variance",
            deployment_locality="local", privacy_domain="internal")],
        policy=policy, failure_class="F1", descriptor_space_version=5)
    assert new_res.provider_id == "ro.provider.y"
    assert _artifact_content_hash(req) == before_hash
    try:
        retry_with_substitution(req, res, [row], policy=policy, failure_class="F4",
                                 descriptor_space_version=5)
        raise SystemExit("non-substitution class accepted")
    except SubstitutionRefusedError:
        pass

    # escalation directive
    parent_env = allocate_budget(10_000, source_policy_version=1)
    directive = escalation_directive(seq, parent_env, reason="F1 persisted", rung_guidance="C2")
    assert directive.required_new_preparation is True
    assert directive.parent_envelope_ref == _budget_envelope_hash(parent_env)
    assert directive.final_record_refs == tuple(_outcome.content_hash(r) for r in seq)

    print("invocation selftest ok")
