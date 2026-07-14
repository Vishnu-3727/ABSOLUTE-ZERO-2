"""RO/02 §3.1 sealed decision inputs — the demand artifact, ladder evidence,
and the closed SealedInputs bundle the decision gate (decision_gate.py)
consumes. Follows the records.py convention (dataclass(frozen=True),
MappingProxyType-frozen mapping fields, a `build_*` validating factory per
shape, canonical/content_hash via sorted JSON). Reuses records.py's
COMPLEXITY_RUNGS/CATEGORIES/LIFECYCLE_STATES and the CapabilityRecord shape
itself rather than duplicating any of it (RO-D3: the gate receives the
CapabilityRecord, never a DescriptorRow — provider identity/availability is
structurally invisible here too, this module never imports DescriptorRow).

Builders here validate SHAPE only (types, closed-vocabulary membership on
this module's own fields) — never the cross-field or completeness
semantics RO-D1 assigns to the gate itself (missing/contradictory n1
claims, missing ladder rungs, a capability id mismatch). That evaluation
belongs to decision_gate.py alone, and the gate re-validates independently
rather than trusting a caller routed through these builders (a SealedInputs
can also be hand-assembled by a test to exercise a malformed input the
builders would refuse — the gate must catch it regardless).
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from .records import COMPLEXITY_RUNGS

# RO/02 §5 — the deterministic ladder's five rungs below reasoning (D1-D5);
# rung R (reasoning itself) is not ladder evidence, it is the outcome of
# the decision this evidence feeds.
RUNGS = ("D1", "D2", "D3", "D4", "D5")

LADDER_STATUSES = ("exhausted", "inapplicable", "untried")


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


# -- DemandArtifact ---------------------------------------------------

@dataclass(frozen=True)
class DemandArtifact:
    demand_id: str
    required_capability_id: str
    required_rung: str
    scope: MappingProxyType         # {"description": str, "granularity": str, "narrowing": {..}|None}
    underdetermined: MappingProxyType       # sealed n1 declared evidence: {"claim": bool, "justification": str}
    generalization_required: MappingProxyType  # sealed n1 declared evidence, same shape


def build_demand(demand_id, required_capability_id, required_rung, scope,
                  underdetermined, generalization_required):
    """Shape-only construction. Refuses (ValueError) an unknown
    required_rung and a scope missing its two required string fields or
    carrying a malformed `narrowing`. Does NOT require underdetermined/
    generalization_required to be complete or consistent — a caller may
    legitimately seal incomplete declared evidence, and it is the gate's
    job (RO-D1) to turn that into INSUFFICIENT-INFORMATION, never a guess
    made here."""
    if not demand_id or not isinstance(demand_id, str):
        raise ValueError("demand.bad_demand_id:" + repr(demand_id))
    if not required_capability_id or not isinstance(required_capability_id, str):
        raise ValueError("demand.bad_required_capability_id:" + repr(required_capability_id))
    if required_rung not in COMPLEXITY_RUNGS:
        raise ValueError("demand.unknown_required_rung:" + str(required_rung))

    scope = dict(scope or {})
    if not isinstance(scope.get("description"), str) or not scope.get("description"):
        raise ValueError("demand.scope_missing_description")
    if not isinstance(scope.get("granularity"), str) or not scope.get("granularity"):
        raise ValueError("demand.scope_missing_granularity")
    narrowing = scope.get("narrowing")
    if narrowing is not None:
        if not isinstance(narrowing, dict) or "deterministic" not in narrowing:
            raise ValueError("demand.narrowing_not_flagged_deterministic")
        if not isinstance(narrowing["deterministic"], bool):
            raise ValueError("demand.narrowing_deterministic_flag_not_bool")
    frozen_scope = _freeze_mapping({
        "description": scope["description"], "granularity": scope["granularity"],
        "narrowing": _freeze_mapping(narrowing) if narrowing is not None else None,
    })

    if not isinstance(underdetermined, dict):
        raise ValueError("demand.underdetermined_not_a_mapping:" + repr(underdetermined))
    if not isinstance(generalization_required, dict):
        raise ValueError("demand.generalization_required_not_a_mapping:" + repr(generalization_required))

    return DemandArtifact(
        demand_id=demand_id, required_capability_id=required_capability_id,
        required_rung=required_rung, scope=frozen_scope,
        underdetermined=_freeze_mapping(underdetermined),
        generalization_required=_freeze_mapping(generalization_required),
    )


# -- LadderEvidence ---------------------------------------------------

@dataclass(frozen=True)
class LadderEvidence:
    rung: str
    status: str
    justification: str
    outcome_record_ref: object  # str | None


def build_ladder_evidence(rung, status, justification, outcome_record_ref=None):
    """Shape-only: rung must be one of RUNGS (D1-D5), status one of
    LADDER_STATUSES. Does not require rung coverage across a whole
    SealedInputs (D1-D5 all present) — that completeness check is the
    gate's structural-validity condition (RO-D7), not a single record's."""
    if rung not in RUNGS:
        raise ValueError("demand.unknown_ladder_rung:" + str(rung))
    if status not in LADDER_STATUSES:
        raise ValueError("demand.unknown_ladder_status:" + str(status))
    if not isinstance(justification, str):
        raise ValueError("demand.ladder_justification_not_str:" + repr(justification))
    if outcome_record_ref is not None and not isinstance(outcome_record_ref, str):
        raise ValueError("demand.bad_outcome_record_ref:" + repr(outcome_record_ref))
    return LadderEvidence(rung=rung, status=status, justification=justification,
                           outcome_record_ref=outcome_record_ref)


# -- SealedInputs ---------------------------------------------------

@dataclass(frozen=True)
class SealedInputs:
    """RO/02 §3.1's closed valid-input set. `capability_record` is a Phase 1
    CapabilityRecord (records.py) taken from a descriptor-space snapshot —
    never a DescriptorRow (RO-D3)."""
    demand: DemandArtifact
    rqm_content_hash: object            # str | None — sealed RQM reference, hash only
    ladder_evidence: tuple              # tuple of LadderEvidence
    workflow_unit_ref: object           # str | None — sealed upstream state ref
    capability_record: object           # CapabilityRecord | None
    priors_version: object              # int | None
    policy: object                      # policy_view.PolicyView | None
    budget_available: object            # bool | None — governance fact, never a size


def build_sealed_inputs(demand, rqm_content_hash, ladder_evidence, workflow_unit_ref,
                         capability_record, priors_version, policy, budget_available):
    """Shape-only construction: type-checks each field's container shape.
    Deliberately permissive of missing/incomplete/inconsistent CONTENT
    (absent ladder rungs, a capability id mismatch, a None reference) —
    every such defect is exactly what decision_gate.decide()'s structural
    validity condition exists to catch and report, never to be silently
    guessed at here."""
    if not isinstance(demand, DemandArtifact):
        raise ValueError("demand.sealed_inputs_bad_demand:" + repr(demand))
    if rqm_content_hash is not None and not isinstance(rqm_content_hash, str):
        raise ValueError("demand.sealed_inputs_bad_rqm_hash:" + repr(rqm_content_hash))
    ladder_evidence = tuple(ladder_evidence or ())
    for entry in ladder_evidence:
        if not isinstance(entry, LadderEvidence):
            raise ValueError("demand.sealed_inputs_bad_ladder_entry:" + repr(entry))
    if workflow_unit_ref is not None and not isinstance(workflow_unit_ref, str):
        raise ValueError("demand.sealed_inputs_bad_workflow_unit_ref:" + repr(workflow_unit_ref))
    if priors_version is not None and not isinstance(priors_version, int):
        raise ValueError("demand.sealed_inputs_bad_priors_version:" + repr(priors_version))
    if budget_available is not None and not isinstance(budget_available, bool):
        raise ValueError("demand.sealed_inputs_bad_budget_available:" + repr(budget_available))
    return SealedInputs(
        demand=demand, rqm_content_hash=rqm_content_hash, ladder_evidence=ladder_evidence,
        workflow_unit_ref=workflow_unit_ref, capability_record=capability_record,
        priors_version=priors_version, policy=policy, budget_available=budget_available,
    )


# -- canonical serialization (records.py pattern) -----------------

def to_dict(record):
    if isinstance(record, DemandArtifact):
        narrowing = record.scope.get("narrowing")
        return {
            "kind": "demand", "demand_id": record.demand_id,
            "required_capability_id": record.required_capability_id,
            "required_rung": record.required_rung,
            "scope": {
                "description": record.scope["description"],
                "granularity": record.scope["granularity"],
                "narrowing": dict(narrowing) if narrowing is not None else None,
            },
            "underdetermined": dict(record.underdetermined),
            "generalization_required": dict(record.generalization_required),
        }
    if isinstance(record, LadderEvidence):
        return {
            "kind": "ladder_evidence", "rung": record.rung, "status": record.status,
            "justification": record.justification,
            "outcome_record_ref": record.outcome_record_ref,
        }
    raise TypeError("demand.unknown_record_type:" + repr(type(record)))


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


def ladder_evidence_hash(ladder_evidence):
    """Deterministic single hash over an ordered tuple of LadderEvidence,
    used as one of decided_from's coordinates (RO-D5)."""
    payload = [to_dict(entry) for entry in ladder_evidence]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    scope = {"description": "summarize the attached report", "granularity": "single_demand"}
    demand = build_demand(
        "ro.demand.1", "ro.cap.summarize", "C1", scope,
        underdetermined={"claim": True, "justification": "no recorded answer"},
        generalization_required={"claim": True, "justification": "synthesis needed"},
    )
    assert demand.scope["narrowing"] is None

    # unknown rung refused
    try:
        build_demand("d2", "cap", "C9", scope, {"claim": True, "justification": "x"},
                     {"claim": True, "justification": "x"})
        raise SystemExit("unknown required_rung accepted")
    except ValueError:
        pass

    # missing scope description refused
    try:
        build_demand("d3", "cap", "C1", {"granularity": "single_demand"},
                     {"claim": True, "justification": "x"}, {"claim": True, "justification": "x"})
        raise SystemExit("missing scope description accepted")
    except ValueError:
        pass

    # narrowing without deterministic flag refused
    try:
        build_demand("d4", "cap", "C1",
                     {"description": "x", "granularity": "g", "narrowing": {"description": "sub"}},
                     {"claim": True, "justification": "x"}, {"claim": True, "justification": "x"})
        raise SystemExit("unflagged narrowing accepted")
    except ValueError:
        pass

    # incomplete n1 evidence is ACCEPTED here — gate's job to flag it
    incomplete = build_demand("d5", "cap", "C1", scope, {}, {"claim": False, "justification": "x"})
    assert dict(incomplete.underdetermined) == {}

    ladder = tuple(
        build_ladder_evidence(rung, "exhausted", "tried and failed") for rung in RUNGS
    )
    assert len(ladder) == 5

    try:
        build_ladder_evidence("D9", "exhausted", "x")
        raise SystemExit("unknown ladder rung accepted")
    except ValueError:
        pass

    sealed = build_sealed_inputs(
        demand, "rqm.hash.abc", ladder, "wf.ref.1", capability_record=None,
        priors_version=1, policy=None, budget_available=True,
    )
    assert sealed.ladder_evidence == ladder

    # determinism: identical input -> identical canonical bytes
    demand2 = build_demand(
        "ro.demand.1", "ro.cap.summarize", "C1", scope,
        underdetermined={"claim": True, "justification": "no recorded answer"},
        generalization_required={"claim": True, "justification": "synthesis needed"},
    )
    assert canonical(demand) == canonical(demand2)
    assert content_hash(demand) == content_hash(demand2)
    assert ladder_evidence_hash(ladder) == ladder_evidence_hash(
        tuple(build_ladder_evidence(rung, "exhausted", "tried and failed") for rung in RUNGS))

    # frozen
    try:
        demand.demand_id = "x"
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass

    print("demand selftest ok")
