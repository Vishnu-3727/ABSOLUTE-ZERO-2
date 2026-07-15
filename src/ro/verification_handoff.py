"""RO/05 §4 — the absolute boundary between RO and Verification (RO-S5).
RO ends at "sealed outcome record exists"; Verification begins at judging
the conforming output. This module builds exactly what §4's "Crosses the
boundary" row lists: verbatim output, schema version reference,
verification expectations metadata, constraint set, decision justification
chain — and nothing else.

`provider_id` is deliberately EXCLUDED from the handoff artifact (§4
"Never crosses" row: "Provider identity as a judgment input" — audit lives
in the sealed record itself, not in what Verification sees).

RO-E8/RO-S5: RO has no opinion of answer quality and no path exists from a
verdict back into a sealed attempt. Structurally: this module defines no
function that accepts a verdict, and the identifier "verdict" does not
appear anywhere in it (or anywhere in src/ro — law_enforcer.py scans for
that, repo-wide, as the other half of RO-S5)."""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from .outcome import content_hash as outcome_content_hash


class HandoffRefusal(Exception):
    """Base for handoff-construction refusals."""


class NonReturnedRecordError(HandoffRefusal):
    """§4: nothing to judge for a mechanical failure — a handoff is built
    only from a RETURNED sealed record."""


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


@dataclass(frozen=True)
class VerificationHandoff:
    record_content_hash: str
    decision_record_content_hash: object  # str | None
    output: object                         # verbatim, unjudged (RO-E8)
    schema_ref: MappingProxyType
    verification_expectations: object
    constraints: MappingProxyType


def build_handoff(sealed_record, request):
    """`sealed_record` — outcome.SealedOutcomeRecord; `request` —
    request.ReasoningRequest it was invoked from (carries schema_ref,
    constraints, and preparation_coordinates' decision_record_content_hash
    — RO/03 §12 tuple). Refuses loud (NonReturnedRecordError) for any
    recovery_kind other than RETURNED (§4 "mechanical failures never reach
    Verification")."""
    if sealed_record.recovery_kind != "RETURNED":
        raise NonReturnedRecordError(
            "verification_handoff.non_returned_record:" + sealed_record.recovery_kind)
    if sealed_record.request_content_hash != _request_content_hash(request):
        raise HandoffRefusal("verification_handoff.record_not_for_request")

    coords = dict(request.preparation_coordinates)
    return VerificationHandoff(
        record_content_hash=outcome_content_hash(sealed_record),
        decision_record_content_hash=coords.get("decision_record_content_hash"),
        output=sealed_record.output,
        schema_ref=_freeze_mapping(request.schema_ref),
        verification_expectations=request.constraints["verification_expectations"],
        constraints=_freeze_mapping(request.constraints),
    )


def _request_content_hash(request):
    from .request import content_hash
    return content_hash(request)


# -- canonical serialization -----------------

def _unfreeze(value):
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _unfreeze(v) for k, v in dict(value).items()}
    if isinstance(value, (tuple, list)):
        return [_unfreeze(v) for v in value]
    return value


def to_dict(handoff):
    return {
        "record_content_hash": handoff.record_content_hash,
        "decision_record_content_hash": handoff.decision_record_content_hash,
        "output": _unfreeze(handoff.output),
        "schema_ref": _unfreeze(handoff.schema_ref),
        "verification_expectations": _unfreeze(handoff.verification_expectations),
        "constraints": _unfreeze(handoff.constraints),
    }


def canonical(handoff):
    return json.dumps(to_dict(handoff), sort_keys=True, separators=(",", ":")).encode()


def content_hash(handoff):
    return hashlib.sha256(canonical(handoff)).hexdigest()


if __name__ == "__main__":
    from .decision_gate import DecisionRecord
    from .outcome import build_sealed_outcome
    from .records import build_capability, build_descriptor_row
    from .request import prepare, content_hash as request_content_hash
    from .schemas import SchemaRegistry

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "medium",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, lifecycle="active")
    approved = DecisionRecord(
        outcome="REASONING_APPROVED", justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({}), approved_capability_id="ro.cap.summarize",
        approved_required_rung="C1",
        approved_scope=MappingProxyType({"description": "summarize", "granularity": "single_demand",
                                          "narrowing": None}),
    )
    rqm = {"core": ({"id": "c1", "content": "alpha", "provenance": "doc:1"},),
           "supporting": ()}
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

    returned = build_sealed_outcome(
        request_content_hash=request_content_hash(req), resolution_content_hash="resh",
        preparation_coordinates=req.preparation_coordinates, attempt_index=1,
        attempt_history_refs=(), recovery_kind="RETURNED", provider_id="ro.provider.x",
        budget_consumed=10, budget_remaining=90, output={"summary": "ok"},
    )

    handoff = build_handoff(returned, req)
    assert handoff.output == {"summary": "ok"}
    assert handoff.schema_ref["schema_id"] == "ro.schema.summary"
    assert handoff.verification_expectations == {"must_cite": True}
    assert "verification_expectations" in handoff.constraints
    assert handoff.decision_record_content_hash == dict(req.preparation_coordinates)["decision_record_content_hash"]

    # provider_id never crosses (RO-E12)
    assert "ro.provider.x" not in canonical(handoff).decode()
    assert not hasattr(handoff, "provider_id")

    # no verdict-accepting function exists on this module (RO-S5 structural
    # absence — the repo-wide identifier scan lives in law_enforcer.py)
    import inspect
    for name, fn in list(globals().items()):
        if inspect.isfunction(fn) and fn.__module__ == "__main__":
            assert "verdict" not in inspect.signature(fn).parameters

    # non-RETURNED refused loud
    failed = build_sealed_outcome(
        request_content_hash=request_content_hash(req), resolution_content_hash="resh",
        preparation_coordinates=req.preparation_coordinates, attempt_index=1,
        attempt_history_refs=(), recovery_kind="FAILED", failure_class="F1",
        provider_id="ro.provider.x", budget_consumed=10, budget_remaining=90,
    )
    try:
        build_handoff(failed, req)
        raise SystemExit("non-RETURNED record accepted for handoff")
    except NonReturnedRecordError:
        pass

    # determinism
    handoff2 = build_handoff(returned, req)
    assert content_hash(handoff) == content_hash(handoff2)

    print("verification_handoff selftest ok")
