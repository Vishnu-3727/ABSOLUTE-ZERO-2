"""RO/03 §1-§2, §9, §12 — the Reasoning Request + Provider Resolution
artifacts and the `prepare()` entry point that produces them (RO/05 §10
blueprint group G3+G4, "the artifact"). Wires together descriptor_space.py
(Phase 1), decision_gate.py (Phase 2), context_prep.py, budget.py,
matching_selection.py, and schemas.py — the only new logic here is artifact
assembly + the RO-P8 constraint-completeness check + the RO/03 §12
determinism tuple.

Two-artifact ruling (RO-P2/RO-P3): ReasoningRequest carries zero provider
identity; ProviderResolution carries the resolved provider_id and links
back to the request only by content hash (`resolved_for_request_hash`) —
never merged.
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from . import budget as _budget
from . import context_prep as _context_prep
from . import matching_selection as _matching_selection
from .decision_gate import content_hash as decision_content_hash


class PreparationRefusal(Exception):
    """Base for prepare()-level refusals not already raised by a submodule."""


class UnapprovedDecisionError(PreparationRefusal):
    """RO-P1: preparation begins only from a REASONING_APPROVED outcome."""


class UnconstrainedRequestError(PreparationRefusal):
    """RO-P8: an unconstrained request never leaves preparation."""


def _deep_freeze(value):
    if isinstance(value, dict) or isinstance(value, MappingProxyType):
        return MappingProxyType({k: _deep_freeze(v) for k, v in dict(value).items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _deep_unfreeze(value):
    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {k: _deep_unfreeze(v) for k, v in dict(value).items()}
    if isinstance(value, tuple) or isinstance(value, list):
        return [_deep_unfreeze(v) for v in value]
    return value


@dataclass(frozen=True)
class ReasoningRequest:
    """RO/03 §1-§2: provider-independent, immutable. Never carries a
    provider identifier in any field (RO-P2)."""
    request_id: str
    capability_id: str
    required_rung: str
    context: tuple                    # tuple of context item dicts (id/content/provenance/tier/score)
    context_audit: MappingProxyType   # {"inclusion": tuple, "reduction": tuple} — RO-P5/RO-P6
    constraints: MappingProxyType     # RO/03 §9
    budget: object                    # budget.BudgetEnvelope
    schema_ref: MappingProxyType      # {"schema_id": str, "version": int}
    preparation_coordinates: MappingProxyType  # RO/03 §12 tuple


@dataclass(frozen=True)
class ProviderResolution:
    """RO/03 §2: the selection record. Provider identity lives ONLY here
    (RO-P2/P3)."""
    provider_id: str
    descriptor_space_version: int
    policy_version: int
    eligibility_exclusions: tuple
    selection_justification: MappingProxyType
    preparation_coordinates: MappingProxyType  # RO/03 §12 tuple — same as the request's
    resolved_for_request_hash: str             # links to the request without merging artifacts


def prepare(decision_record, *, rqm, capability_record, descriptor_rows, descriptor_space_version,
            policy_view, priors_version, schema_registry, schema_id, schema_version,
            budget_ceiling, budget_source_policy_version, verification_expectations,
            forbidden_behaviors=(), user_policy=None,
            privacy_domain_required="public", required_compliance_tags=(), locality_required=None,
            declared_preference=(), relevance_threshold=0.0,
            rqm_stale=False, expected_rqm_hash=None,
            parent_budget=None, already_allocated_from_parent=0):
    """RO/03's full preparation pipeline. Sealed inputs in, (ReasoningRequest,
    ProviderResolution) out. Identical sealed inputs -> byte-identical pair
    (RO-P11, RO/03 §12). Every RO-P12 empty/infeasible/stale condition
    raises loud (a submodule-specific *Error, or one of this module's own),
    never degrades silently."""
    if decision_record.outcome != "REASONING_APPROVED":
        raise UnapprovedDecisionError(
            "request.prepare_from_non_approved_outcome:" + str(decision_record.outcome))
    if verification_expectations is None:
        raise UnconstrainedRequestError("request.missing_verification_expectations")

    actual_rqm_hash = _context_prep.check_freshness(rqm, rqm_stale, expected_rqm_hash)

    included, inclusion_records, reduction_records = _context_prep.select_and_reduce(
        rqm, capability_record, relevance_threshold)

    # ponytail: byte length stands in for token count until a real
    # tokenizer surface exists; budget ceilings are token-denominated
    # (RO/03 §8) — upgrade path is swapping this sum for a tokenizer call
    # once one is wired in, with no other change to this pipeline.
    total_bytes = sum(len(item["content"].encode("utf-8")) for item in included)

    envelope = _budget.allocate_budget(
        budget_ceiling, budget_source_policy_version, parent_budget, already_allocated_from_parent)
    _budget.require_fits(envelope, total_bytes)

    candidate_set = _matching_selection.build_candidate_set(
        descriptor_rows, decision_record.approved_capability_id, decision_record.approved_required_rung)
    size_class = _matching_selection.derive_size_class(total_bytes)
    resolved_row, exclusions, selection_justification = _matching_selection.select_provider(
        candidate_set, privacy_domain_required=privacy_domain_required,
        required_compliance_tags=required_compliance_tags, request_size_class=size_class,
        locality_required=locality_required, declared_preference=declared_preference)

    schema_record = schema_registry.require(schema_id, schema_version)

    coords = _deep_freeze({
        "decision_record_content_hash": decision_content_hash(decision_record),
        "rqm_content_hash": actual_rqm_hash,
        "descriptor_space_version": descriptor_space_version,
        "policy_version": policy_view.policy_version,
        "priors_version": priors_version,
        "schema_version": schema_version,
    })

    scope = decision_record.approved_scope
    allowed_scope = _deep_freeze({
        "description": scope["description"], "granularity": scope["granularity"],
        "narrowing": dict(scope["narrowing"]) if scope.get("narrowing") is not None else None,
    })

    constraints = _deep_freeze({
        "allowed_scope": allowed_scope,
        "output_form": {"schema_id": schema_record.schema_id, "version": schema_record.version,
                         "required_fields": schema_record.required_fields},
        "forbidden_behaviors": tuple(forbidden_behaviors),
        "determinism_expectations": capability_record.characteristics["determinism_tolerance"],
        "policy_constraints": {
            "compliance_tags_required": tuple(required_compliance_tags),
            "privacy_domain_required": privacy_domain_required,
            "user_policy": user_policy,
        },
        "verification_expectations": verification_expectations,
    })

    request_id = hashlib.sha256((
        coords["decision_record_content_hash"] + ":" + decision_record.approved_capability_id +
        ":" + schema_id + ":" + str(schema_version)
    ).encode()).hexdigest()

    request = ReasoningRequest(
        request_id=request_id,
        capability_id=decision_record.approved_capability_id,
        required_rung=decision_record.approved_required_rung,
        context=included,
        context_audit=_deep_freeze({"inclusion": inclusion_records, "reduction": reduction_records}),
        constraints=constraints,
        budget=envelope,
        schema_ref=_deep_freeze({"schema_id": schema_id, "version": schema_version}),
        preparation_coordinates=coords,
    )

    resolution = ProviderResolution(
        provider_id=resolved_row.provider_id,
        descriptor_space_version=descriptor_space_version,
        policy_version=policy_view.policy_version,
        eligibility_exclusions=exclusions,
        selection_justification=_deep_freeze(selection_justification),
        preparation_coordinates=coords,
        resolved_for_request_hash=content_hash(request),
    )

    return request, resolution


# -- canonical serialization (records.py/decision_gate.py pattern) --------

def to_dict(record):
    if isinstance(record, ReasoningRequest):
        return {
            "kind": "reasoning_request",
            "request_id": record.request_id,
            "capability_id": record.capability_id,
            "required_rung": record.required_rung,
            "context": [_deep_unfreeze(item) for item in record.context],
            "context_audit": _deep_unfreeze(record.context_audit),
            "constraints": _deep_unfreeze(record.constraints),
            "budget": {"ceiling": record.budget.ceiling,
                       "source_policy_version": record.budget.source_policy_version,
                       "parent_ref": record.budget.parent_ref},
            "schema_ref": _deep_unfreeze(record.schema_ref),
            "preparation_coordinates": _deep_unfreeze(record.preparation_coordinates),
        }
    if isinstance(record, ProviderResolution):
        return {
            "kind": "provider_resolution",
            "provider_id": record.provider_id,
            "descriptor_space_version": record.descriptor_space_version,
            "policy_version": record.policy_version,
            "eligibility_exclusions": _deep_unfreeze(record.eligibility_exclusions),
            "selection_justification": _deep_unfreeze(record.selection_justification),
            "preparation_coordinates": _deep_unfreeze(record.preparation_coordinates),
            "resolved_for_request_hash": record.resolved_for_request_hash,
        }
    raise TypeError("request.unknown_record_type:" + repr(type(record)))


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


if __name__ == "__main__":
    from .decision_gate import DecisionRecord
    from .records import build_capability, build_descriptor_row
    from .schemas import SchemaRegistry

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "medium",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, lifecycle="active")

    approved = DecisionRecord(
        outcome="REASONING_APPROVED",
        justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({}),
        approved_capability_id="ro.cap.summarize", approved_required_rung="C1",
        approved_scope=MappingProxyType({"description": "summarize", "granularity": "single_demand",
                                          "narrowing": None}),
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
    assert res.provider_id == "ro.provider.x"
    assert "ro.provider.x" not in canonical(req).decode()
    assert res.resolved_for_request_hash == content_hash(req)

    # determinism: independently rebuilt inputs -> byte-identical outputs
    req2, res2 = prepare(
        approved, rqm=dict(rqm), capability_record=cap, descriptor_rows=[row],
        descriptor_space_version=5, policy_view=_Policy(), priors_version=2,
        schema_registry=registry, schema_id="ro.schema.summary", schema_version=1,
        budget_ceiling=10_000, budget_source_policy_version=1,
        verification_expectations={"must_cite": True},
    )
    assert content_hash(req) == content_hash(req2)
    assert content_hash(res) == content_hash(res2)

    # non-approved decision refused
    rejected = DecisionRecord(
        outcome="REASONING_REJECTED", justification=MappingProxyType({}),
        decided_from=MappingProxyType({}), approved_capability_id=None,
        approved_required_rung=None, approved_scope=None,
    )
    try:
        prepare(rejected, rqm=rqm, capability_record=cap, descriptor_rows=[row],
                descriptor_space_version=5, policy_view=_Policy(), priors_version=2,
                schema_registry=registry, schema_id="ro.schema.summary", schema_version=1,
                budget_ceiling=10_000, budget_source_policy_version=1,
                verification_expectations={"must_cite": True})
        raise SystemExit("non-approved decision accepted")
    except UnapprovedDecisionError:
        pass

    # missing verification expectations refused
    try:
        prepare(approved, rqm=rqm, capability_record=cap, descriptor_rows=[row],
                descriptor_space_version=5, policy_view=_Policy(), priors_version=2,
                schema_registry=registry, schema_id="ro.schema.summary", schema_version=1,
                budget_ceiling=10_000, budget_source_policy_version=1,
                verification_expectations=None)
        raise SystemExit("unconstrained request accepted")
    except UnconstrainedRequestError:
        pass

    print("request selftest ok")
