"""THE Decision Gate — RO/02, the necessity gate (RO/05 §10 blueprint
group G2). One pure function, `decide(sealed_inputs) -> DecisionRecord`,
evaluating RO/02 §3.1's closed SealedInputs (demand.py) against the five
mutually-exclusive outcomes of RO/02 §4.

Deterministic evaluation order (RO-D4 — first failing condition wins):

  a) STRUCTURAL VALIDITY — every sealed input present, well-typed, and
     internally consistent (n1 claims present with justification, ladder
     coverage complete, capability id matches the demand's required id,
     etc). Any defect -> INSUFFICIENT_INFORMATION (RO/02 §4 outcome 4).
     The gate re-validates independently rather than trusting a caller
     routed a SealedInputs through demand.py's builders (RO-D1: mechanical
     evaluation, never a guess on missing/contradictory evidence).
  b) LADDER (n3) — any D1-D5 rung "untried" -> DETERMINISTIC_CONTINUATION_
     REQUIRED (outcome 3), naming the untried rungs.
  c) NECESSITY n1 — both declared claims (underdetermined,
     generalization_required) true -> continue; either false ->
     REASONING_REJECTED (outcome 2, P3's success case).
  d) NECESSITY n2 — carried by (a)-(c): the gate never reads RQM content,
     only validates the sealed reference exists (checked in (a)). No
     separate probe exists at this level; this step is documentation, not
     code, of RO/02 §1's n2 as seen from the gate.
  e) GOVERNANCE — policy.reasoning_permitted false, OR capability category
     not permitted, OR required rung above the policy ceiling, OR budget
     unavailable, OR capability lifecycle not in ("active", "deprecated")
     -> GOVERNANCE_REFUSED (outcome 5), first failing ground recorded, in
     that listed order.
  f) else -> REASONING_APPROVED (outcome 1), carrying justification, the
     required capability id, required rung, and scope.

RO-D3 (structural, not just conventional): this module never imports or
references DescriptorRow — provider identity/availability are invisible to
the gate. RO-D2/D6: zero mutable state, zero live reads, no wall-clock or
randomness import — decide() is a pure function of its hashable input.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from .demand import (
    RUNGS, LADDER_STATUSES, DemandArtifact, LadderEvidence,
    content_hash as demand_content_hash, ladder_evidence_hash,
)
from .policy_view import PolicyView
from .records import (
    CATEGORIES, COMPLEXITY_RUNGS, LIFECYCLE_STATES, CapabilityRecord,
    content_hash as capability_content_hash,
)

OUTCOMES = (
    "REASONING_APPROVED",
    "REASONING_REJECTED",
    "DETERMINISTIC_CONTINUATION_REQUIRED",
    "INSUFFICIENT_INFORMATION",
    "GOVERNANCE_REFUSED",
)

_ELIGIBLE_LIFECYCLES = ("active", "deprecated")


@dataclass(frozen=True)
class DecisionRecord:
    outcome: str
    justification: MappingProxyType
    decided_from: MappingProxyType
    approved_capability_id: object   # str | None
    approved_required_rung: object   # str | None
    approved_scope: object           # MappingProxyType | None


def _freeze(d):
    return MappingProxyType(dict(d or {}))


def _safe_hash(ok, fn, *args):
    if not ok:
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def _decided_from(sealed):
    demand = sealed.demand
    demand_ok = isinstance(demand, DemandArtifact)
    ladder_ok = isinstance(sealed.ladder_evidence, tuple) and all(
        isinstance(e, LadderEvidence) for e in sealed.ladder_evidence)
    cap = sealed.capability_record
    cap_ok = isinstance(cap, CapabilityRecord)
    policy = sealed.policy
    policy_ok = isinstance(policy, PolicyView)

    return _freeze({
        "demand_content_hash": _safe_hash(demand_ok, demand_content_hash, demand),
        "rqm_content_hash": sealed.rqm_content_hash,
        "ladder_evidence_hash": _safe_hash(ladder_ok, ladder_evidence_hash, sealed.ladder_evidence),
        "workflow_unit_ref": sealed.workflow_unit_ref,
        "capability_content_hash": _safe_hash(cap_ok, capability_content_hash, cap),
        "priors_version": sealed.priors_version,
        "policy_version": policy.policy_version if policy_ok else None,
        "budget_available": sealed.budget_available,
    })


def _structural_defects(sealed):
    """(a) — every defect found, independent of whether builders were used
    upstream. Returns a tuple of defect codes; empty means structurally
    valid."""
    defects = []
    demand = sealed.demand
    if not isinstance(demand, DemandArtifact):
        defects.append("demand_missing_or_malformed")
        return tuple(defects)  # nothing else is checkable without a demand

    if demand.required_rung not in COMPLEXITY_RUNGS:
        defects.append("required_rung_unknown")

    scope = demand.scope
    if not isinstance(scope, Mapping) or not scope.get("description") or not scope.get("granularity"):
        defects.append("scope_incomplete")
    else:
        narrowing = scope.get("narrowing")
        if narrowing is not None and (
                not isinstance(narrowing, Mapping) or not isinstance(narrowing.get("deterministic"), bool)):
            defects.append("narrowing_not_flagged_deterministic")

    for field_name, evidence in (("underdetermined", demand.underdetermined),
                                  ("generalization_required", demand.generalization_required)):
        if not isinstance(evidence, Mapping) or "claim" not in evidence or "justification" not in evidence:
            defects.append("n1_claim_missing:" + field_name)
        elif not isinstance(evidence.get("claim"), bool):
            defects.append("n1_claim_not_bool:" + field_name)
        elif not evidence.get("justification"):
            defects.append("n1_justification_missing:" + field_name)

    ladder = sealed.ladder_evidence
    if not isinstance(ladder, tuple) or not all(isinstance(e, LadderEvidence) for e in ladder):
        defects.append("ladder_evidence_malformed")
    else:
        by_rung = {}
        for entry in ladder:
            if entry.rung not in RUNGS:
                defects.append("ladder_rung_unknown:" + str(entry.rung))
                continue
            if entry.rung in by_rung:
                defects.append("ladder_rung_duplicate:" + entry.rung)
                continue
            by_rung[entry.rung] = entry
            if entry.status not in LADDER_STATUSES:
                defects.append("ladder_status_unknown:" + entry.rung)
            if not entry.justification:
                defects.append("ladder_justification_missing:" + entry.rung)
        missing_rungs = [r for r in RUNGS if r not in by_rung]
        if missing_rungs:
            defects.append("ladder_rungs_missing:" + ",".join(missing_rungs))

    cap = sealed.capability_record
    if not isinstance(cap, CapabilityRecord):
        defects.append("capability_record_missing_or_malformed")
    else:
        if cap.id != demand.required_capability_id:
            defects.append("capability_id_mismatch")
        if cap.lifecycle not in LIFECYCLE_STATES:
            defects.append("capability_lifecycle_unknown")

    if not sealed.rqm_content_hash:
        defects.append("rqm_content_hash_missing")
    if not sealed.workflow_unit_ref:
        defects.append("workflow_unit_ref_missing")
    if not isinstance(sealed.priors_version, int):
        defects.append("priors_version_missing_or_malformed")

    policy = sealed.policy
    if not isinstance(policy, PolicyView):
        defects.append("policy_missing_or_malformed")

    if not isinstance(sealed.budget_available, bool):
        defects.append("budget_available_missing_or_malformed")

    return tuple(defects)


def decide(sealed_inputs):
    """Pure function: identical SealedInputs -> byte-identical DecisionRecord
    (RO-D6/RO-D8's P8 mirror). Zero mutation of sealed_inputs, zero live
    reads beyond its fields."""
    decided_from = _decided_from(sealed_inputs)

    # (a) structural validity
    defects = _structural_defects(sealed_inputs)
    if defects:
        return DecisionRecord(
            outcome="INSUFFICIENT_INFORMATION",
            justification=_freeze({
                "failed_condition": "structural_validity",
                "defects": defects,
            }),
            decided_from=decided_from,
            approved_capability_id=None, approved_required_rung=None, approved_scope=None,
        )

    demand = sealed_inputs.demand
    ladder = sealed_inputs.ladder_evidence
    cap = sealed_inputs.capability_record
    policy = sealed_inputs.policy
    by_rung = {e.rung: e for e in ladder}

    # (b) ladder (n3)
    untried = tuple(r for r in RUNGS if by_rung[r].status == "untried")
    if untried:
        return DecisionRecord(
            outcome="DETERMINISTIC_CONTINUATION_REQUIRED",
            justification=_freeze({
                "failed_condition": "ladder",
                "untried_rungs": untried,
            }),
            decided_from=decided_from,
            approved_capability_id=None, approved_required_rung=None, approved_scope=None,
        )

    # (c) necessity n1
    underdetermined_claim = demand.underdetermined["claim"]
    generalization_claim = demand.generalization_required["claim"]
    if not (underdetermined_claim and generalization_claim):
        return DecisionRecord(
            outcome="REASONING_REJECTED",
            justification=_freeze({
                "failed_condition": "necessity_n1",
                "underdetermined_claim": underdetermined_claim,
                "generalization_required_claim": generalization_claim,
            }),
            decided_from=decided_from,
            approved_capability_id=None, approved_required_rung=None, approved_scope=None,
        )

    # (d) necessity n2 — mechanically satisfied by (a)'s rqm_content_hash
    # presence check; no further evaluation happens at gate level.

    # (e) governance — first failing ground wins, in this listed order
    ground = None
    if not policy.reasoning_permitted:
        ground = "reasoning_not_permitted"
    elif cap.category not in policy.permitted_categories:
        ground = "category_not_permitted"
    elif _rung_index(demand.required_rung) > _ceiling_index(policy.permitted_rungs):
        ground = "rung_above_ceiling"
    elif not sealed_inputs.budget_available:
        ground = "budget_unavailable"
    elif cap.lifecycle not in _ELIGIBLE_LIFECYCLES:
        ground = "capability_lifecycle_ineligible"

    if ground is not None:
        return DecisionRecord(
            outcome="GOVERNANCE_REFUSED",
            justification=_freeze({
                "failed_condition": "governance",
                "ground": ground,
            }),
            decided_from=decided_from,
            approved_capability_id=None, approved_required_rung=None, approved_scope=None,
        )

    # (f) approved
    return DecisionRecord(
        outcome="REASONING_APPROVED",
        justification=_freeze({
            "passed": ("structural_validity", "ladder", "necessity_n1", "necessity_n2", "governance"),
        }),
        decided_from=decided_from,
        approved_capability_id=demand.required_capability_id,
        approved_required_rung=demand.required_rung,
        approved_scope=demand.scope,
    )


def _rung_index(rung):
    return COMPLEXITY_RUNGS.index(rung)


def _ceiling_index(permitted_rungs):
    if not permitted_rungs:
        return -1
    return max(_rung_index(r) for r in permitted_rungs)


# -- canonical serialization (records.py/demand.py pattern) -----------------

def to_dict(record):
    if not isinstance(record, DecisionRecord):
        raise TypeError("decision_gate.unknown_record_type:" + repr(type(record)))
    scope = record.approved_scope
    if scope is not None:
        narrowing = scope.get("narrowing")
        scope_dict = {
            "description": scope["description"], "granularity": scope["granularity"],
            "narrowing": dict(narrowing) if narrowing is not None else None,
        }
    else:
        scope_dict = None
    return {
        "kind": "decision_record", "outcome": record.outcome,
        "justification": _jsonify(dict(record.justification)),
        "decided_from": dict(record.decided_from),
        "approved_capability_id": record.approved_capability_id,
        "approved_required_rung": record.approved_required_rung,
        "approved_scope": scope_dict,
    }


def _jsonify(value):
    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {k: _jsonify(v) for k, v in dict(value).items()}
    if isinstance(value, tuple) or isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


if __name__ == "__main__":
    from .demand import build_demand, build_ladder_evidence, build_sealed_inputs
    from .policy_view import build_policy_view
    from .records import build_capability

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "low",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, lifecycle="active")
    scope = {"description": "summarize the report", "granularity": "single_demand"}
    demand = build_demand(
        "ro.demand.1", "ro.cap.summarize", "C1", scope,
        underdetermined={"claim": True, "justification": "no recorded answer"},
        generalization_required={"claim": True, "justification": "synthesis needed"},
    )
    exhausted_ladder = tuple(
        build_ladder_evidence(r, "exhausted", "tried and failed") for r in RUNGS)
    policy = build_policy_view(True, ("INTERPRETIVE",), ("C0", "C1", "C2"), 1)

    sealed = build_sealed_inputs(
        demand, "rqm.hash.abc", exhausted_ladder, "wf.ref.1", cap,
        priors_version=1, policy=policy, budget_available=True,
    )
    record = decide(sealed)
    assert record.outcome == "REASONING_APPROVED"
    assert record.approved_capability_id == "ro.cap.summarize"
    assert record.approved_required_rung == "C1"

    # determinism: identical inputs -> byte-identical record
    record2 = decide(sealed)
    assert content_hash(record) == content_hash(record2)

    # untried ladder rung wins over a false n1 claim (evaluation order)
    untried_ladder = (build_ladder_evidence("D1", "untried", "not yet tried"),) + exhausted_ladder[1:]
    rejecting_demand = build_demand(
        "ro.demand.2", "ro.cap.summarize", "C1", scope,
        underdetermined={"claim": False, "justification": "recorded answer exists"},
        generalization_required={"claim": True, "justification": "x"},
    )
    sealed_order = build_sealed_inputs(
        rejecting_demand, "rqm.hash.abc", untried_ladder, "wf.ref.1", cap,
        priors_version=1, policy=policy, budget_available=True,
    )
    record3 = decide(sealed_order)
    assert record3.outcome == "DETERMINISTIC_CONTINUATION_REQUIRED"
    assert record3.justification["untried_rungs"] == ("D1",)

    # missing capability record -> INSUFFICIENT_INFORMATION, decided_from still present
    sealed_bad = build_sealed_inputs(
        demand, "rqm.hash.abc", exhausted_ladder, "wf.ref.1", None,
        priors_version=1, policy=policy, budget_available=True,
    )
    record4 = decide(sealed_bad)
    assert record4.outcome == "INSUFFICIENT_INFORMATION"
    assert "capability_record_missing_or_malformed" in record4.justification["defects"]
    assert record4.decided_from["demand_content_hash"] is not None

    # governance refusal: category not permitted
    narrow_policy = build_policy_view(True, ("ANALYTIC",), ("C0", "C1", "C2"), 1)
    sealed_gov = build_sealed_inputs(
        demand, "rqm.hash.abc", exhausted_ladder, "wf.ref.1", cap,
        priors_version=1, policy=narrow_policy, budget_available=True,
    )
    record5 = decide(sealed_gov)
    assert record5.outcome == "GOVERNANCE_REFUSED"
    assert record5.justification["ground"] == "category_not_permitted"

    # frozen
    try:
        record.outcome = "X"
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass

    # RO-D3/RO-D2 structural checks (no provider-row import, no time/random
    # import) are verified by AST scan in tests/test_ro_phase2.py, not here.

    print("decision_gate selftest ok")
