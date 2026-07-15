"""RO/03 §11 — Serialization Independence (RO/05 §10 blueprint group G4,
"the renderer"). Deterministic, governance-lossless transform from a
`request.ReasoningRequest` into one provider-consumable form named by
`records.REQUEST_FORMS` (closed vocabulary — RO/03 §10 Compatibility
discipline extended to render forms).

Only "prompt_text" exists today. A new modality is a new render function
plus a new REQUEST_FORMS entry (RO/00 §11.5 bounded extension) — zero
change to the request/decision architecture (RO/03 §11 demonstration).

Governance-lossless (RO-P10): every RO/03 §9 constraint category present on
`request.constraints` must appear, textually, in the rendering. A renderer
that silently drops a constraint is defective, not lenient.

The request stays the audit object; a rendering is derivable, non-canonical
output (RO/03 §11 closing line) — `render()` never mutates or extends the
request it consumes.

Provider identity never appears here structurally: `ReasoningRequest`
carries no provider field (RO-P2), so there is nothing for this module to
leak even if a `ProviderResolution` is passed in for descriptor lookups by
future renderer forms.
"""
import json

from .records import REQUEST_FORMS

_CONSTRAINT_CATEGORIES = (
    "allowed_scope", "output_form", "forbidden_behaviors",
    "determinism_expectations", "policy_constraints", "verification_expectations",
)


class RenderRefusal(Exception):
    """Base for renderer-time refusals."""


class UnknownRequestFormError(RenderRefusal):
    """RO/03 §11: request_form is not in the closed REQUEST_FORMS vocabulary."""


def _unfreeze(value):
    # ponytail: local mirror of request.py's _deep_unfreeze — three lines,
    # not worth an import coupling renderer.py to request.py's internals.
    from types import MappingProxyType
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _unfreeze(v) for k, v in dict(value).items()}
    if isinstance(value, (tuple, list)):
        return [_unfreeze(v) for v in value]
    return value


def _canon(value):
    """Deterministic textual fragment for any constraint value — canonical
    sorted-JSON, matching the house content-hash style (records.py/
    decision_gate.py) so the same value always renders identically."""
    return json.dumps(_unfreeze(value), sort_keys=True, separators=(",", ":"))


def _render_prompt_text(request):
    lines = [
        "CAPABILITY: " + request.capability_id,
        "REQUIRED_RUNG: " + request.required_rung,
        "",
        "CONTEXT:",
    ]
    for item in request.context:
        lines.append(
            "- id=" + item["id"] + " provenance=" + item["provenance"] +
            " content=" + item["content"]
        )
    lines.append("")
    lines.append("CONSTRAINTS:")
    for category in _CONSTRAINT_CATEGORIES:
        lines.append(category.upper() + ": " + _canon(request.constraints[category]))
    return "\n".join(lines).encode("utf-8")


_RENDERERS = {
    "prompt_text": _render_prompt_text,
}


def render(request, request_form):
    """RO/03 §11. Deterministic: identical (request, request_form) ->
    byte-identical rendering. Raises UnknownRequestFormError loud for any
    form outside the closed REQUEST_FORMS vocabulary (records.py)."""
    if request_form not in REQUEST_FORMS:
        raise UnknownRequestFormError("renderer.unknown_request_form:" + str(request_form))
    return _RENDERERS[request_form](request)


def assert_lossless(request, rendered):
    """Governance-lossless self-check (RO-P10): every constraint category's
    canonical fragment must be a substring of the rendering. Raises
    AssertionError naming the missing category.

    # ponytail: substring presence over the canonical-JSON fragment is
    # sufficient for the closed set of scalar/tuple/mapping constraint
    # shapes RO/03 §9 defines today; upgrade path = a structured
    # round-trip parse per renderer form if a future form stops being
    # plain text (e.g. a structured API payload) and substring matching
    # stops being a meaningful check.
    """
    text = rendered.decode("utf-8")
    for category in _CONSTRAINT_CATEGORIES:
        fragment = _canon(request.constraints[category])
        assert fragment in text, "renderer.lossy:" + category


if __name__ == "__main__":
    from types import MappingProxyType

    from .decision_gate import DecisionRecord
    from .records import build_capability, build_descriptor_row
    from .schemas import SchemaRegistry
    from .request import prepare

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
        "ro.provider.SECRET_VENDOR_X", {"ro.cap.summarize": ("C1",)}, context_capacity_class="large",
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
        forbidden_behaviors=("no_pii",),
    )

    rendered = render(req, "prompt_text")
    assert isinstance(rendered, bytes)

    # determinism: identical request -> byte-identical rendering
    rendered2 = render(req, "prompt_text")
    assert rendered == rendered2

    # provider identity never appears in a rendering (structural: the
    # request carries none — this is a belt-and-braces check)
    assert "ro.provider.SECRET_VENDOR_X" not in rendered.decode("utf-8")

    # context items present: id, content, provenance
    text = rendered.decode("utf-8")
    for item in req.context:
        assert item["id"] in text
        assert item["content"] in text
        assert item["provenance"] in text

    # capability id + required rung present
    assert req.capability_id in text
    assert req.required_rung in text

    # losslessness: every constraint category's canonical fragment present
    assert_lossless(req, rendered)

    # unknown form refused loud
    try:
        render(req, "carrier_pigeon")
        raise SystemExit("unknown request form accepted")
    except UnknownRequestFormError:
        pass

    print("renderer selftest ok")
