"""RO/03 §4-§5 — Capability Matching + Provider Selection (RO/05 §10
blueprint group G3+G4). Pure set-construction and deterministic resolution
over `records.DescriptorRow`s from the descriptor space (Phase 1); never
re-asks necessity (RO-D territory closed, RO/03 §4 Scope row).

Two stages, strict order (RO/03 §5 "Order of application"):
  1. `build_candidate_set` — capability + rung match only (RO/03 §4).
  2. `select_provider` — eligibility filters (binary, every exclusion
     recorded) THEN preference ranking among eligible rows only.

Empty candidate set or empty eligible set are both loud RO-P12 failures —
never substitution or constraint relaxation (RO/03 §4 "Empty result" row,
RO/03 §5 closing line).
"""
from .records import CONTEXT_CAPACITY_CLASSES, COST_CLASSES

_CAPACITY_INDEX = {cls: i for i, cls in enumerate(CONTEXT_CAPACITY_CLASSES)}
_COST_INDEX = {cls: i for i, cls in enumerate(COST_CLASSES)}
_PRIVACY_ORDER = {"public": 0, "internal": 1, "restricted": 2}

# ponytail: byte-length thresholds for deriving a request's capacity class
# are sane-default config data, not hardcoded judgment; upgrade path = make
# this table policy-supplied once a real per-policy config surface exists
# (RO/03 §5 pre-ruling #8).
_SIZE_CLASS_THRESHOLDS = (
    ("small", 2_000),
    ("medium", 8_000),
    ("large", 32_000),
    # anything above the last threshold is "xlarge"
)


class MatchingRefusal(Exception):
    """Base for RO/03 §4-§5 refusals."""


class EmptyCandidateSetError(MatchingRefusal):
    """RO/03 §4: no descriptor row claims the required capability at
    sufficient strength — loud, never a weaker-capability substitution."""


class EmptyEligibleSetError(MatchingRefusal):
    """RO/03 §5: every candidate was excluded by an eligibility filter —
    loud, never constraint relaxation. Carries every exclusion reason."""

    def __init__(self, message, exclusions):
        super().__init__(message)
        self.exclusions = exclusions


def derive_size_class(byte_length):
    """RO/03 §5 pre-ruling #8: request size class from selected-context byte
    length via closed thresholds."""
    for cls, ceiling in _SIZE_CLASS_THRESHOLDS:
        if byte_length <= ceiling:
            return cls
    return "xlarge"


def build_candidate_set(descriptor_rows, capability_id, required_rung):
    """RO/03 §4: set-construction from declared claims only. `descriptor_rows`
    is an iterable of records.DescriptorRow. Returns a stable-sorted
    (provider_id order) tuple. Raises EmptyCandidateSetError if empty."""
    candidates = tuple(sorted(
        (row for row in descriptor_rows
         if capability_id in row.capabilities_claimed
         and required_rung in row.capabilities_claimed[capability_id]),
        key=lambda r: r.provider_id,
    ))
    if not candidates:
        raise EmptyCandidateSetError(
            "matching_selection.empty_candidate_set:" + capability_id + ":" + required_rung)
    return candidates


def _eligibility_reasons(row, *, privacy_domain_required, required_compliance_tags,
                          request_size_class, locality_required):
    reasons = []
    if _PRIVACY_ORDER[row.privacy_domain] < _PRIVACY_ORDER[privacy_domain_required]:
        reasons.append("privacy_domain_insufficient")
    if not set(required_compliance_tags) <= set(row.compliance_tags):
        reasons.append("compliance_tags_missing")
    if _CAPACITY_INDEX[row.context_capacity_class] < _CAPACITY_INDEX[request_size_class]:
        reasons.append("capacity_insufficient")
    if locality_required is not None and row.deployment_locality != locality_required:
        reasons.append("locality_mismatch")
    return tuple(reasons)


def select_provider(candidate_set, *, privacy_domain_required="public",
                     required_compliance_tags=(), request_size_class="small",
                     locality_required=None, declared_preference=()):
    """RO/03 §5. Returns (resolved_row, exclusions, selection_justification).

    `declared_preference`: optional ordered tuple of provider_ids — policy's
    declared preference, stage 2 of the tie-break (RO/03 §5 table).
    Tie-break order: cheapest-sufficient cost class, then declared
    preference rank, then stable alphabetical provider_id (mirrors PRT/03
    resolution discipline)."""
    eligible = []
    exclusions = []
    for row in candidate_set:
        reasons = _eligibility_reasons(
            row, privacy_domain_required=privacy_domain_required,
            required_compliance_tags=required_compliance_tags,
            request_size_class=request_size_class, locality_required=locality_required)
        if reasons:
            exclusions.append({"provider_id": row.provider_id, "reasons": reasons})
        else:
            eligible.append(row)

    if not eligible:
        raise EmptyEligibleSetError(
            "matching_selection.empty_eligible_set", tuple(exclusions))

    def _pref_rank(provider_id):
        return declared_preference.index(provider_id) if provider_id in declared_preference \
            else len(declared_preference)

    ranked = sorted(
        eligible,
        key=lambda r: (_COST_INDEX[r.cost_class], _pref_rank(r.provider_id), r.provider_id),
    )
    winner = ranked[0]
    justification = {
        "cost_class": winner.cost_class,
        "declared_preference_rank": _pref_rank(winner.provider_id),
        "alphabetical_tiebreak_id": winner.provider_id,
        "eligible_count": len(eligible),
        "candidate_count": len(candidate_set),
    }
    return winner, tuple(exclusions), justification


if __name__ == "__main__":
    from .records import build_descriptor_row

    row_a = build_descriptor_row(
        "ro.provider.a", {"ro.cap.x": ("C1",)}, context_capacity_class="medium",
        cost_class="medium", latency_class="fast", determinism_class="low_variance",
        deployment_locality="remote", privacy_domain="internal", compliance_tags=("gdpr",),
    )
    row_b = build_descriptor_row(
        "ro.provider.b", {"ro.cap.x": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="restricted", compliance_tags=("gdpr", "hipaa"),
    )
    row_c = build_descriptor_row(
        "ro.provider.c", {"ro.cap.y": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="restricted",
    )

    candidates = build_candidate_set([row_a, row_b, row_c], "ro.cap.x", "C1")
    assert [r.provider_id for r in candidates] == ["ro.provider.a", "ro.provider.b"]

    try:
        build_candidate_set([row_a, row_b, row_c], "ro.cap.nope", "C1")
        raise SystemExit("empty candidate set accepted")
    except EmptyCandidateSetError:
        pass

    assert derive_size_class(100) == "small"
    assert derive_size_class(2_000) == "small"
    assert derive_size_class(2_001) == "medium"
    assert derive_size_class(100_000) == "xlarge"

    # cheapest-sufficient wins: b (low) beats a (medium)
    winner, exclusions, justification = select_provider(
        candidates, request_size_class="small")
    assert winner.provider_id == "ro.provider.b"
    assert exclusions == ()

    # eligibility filter: request_size_class too big for row_a (medium capacity)
    winner2, exclusions2, _ = select_provider(
        candidates, request_size_class="large")
    assert winner2.provider_id == "ro.provider.b"
    assert any(e["provider_id"] == "ro.provider.a" for e in exclusions2)
    assert "capacity_insufficient" in [e["reasons"] for e in exclusions2 if e["provider_id"] == "ro.provider.a"][0]

    # privacy filter excludes row_a (internal) when restricted context required
    winner3, exclusions3, _ = select_provider(
        candidates, privacy_domain_required="restricted", request_size_class="small")
    assert winner3.provider_id == "ro.provider.b"
    assert any("privacy_domain_insufficient" in e["reasons"] for e in exclusions3)

    # empty eligible set: nobody admits restricted+hipaa+xlarge+local
    try:
        select_provider(candidates, privacy_domain_required="restricted",
                         required_compliance_tags=("hipaa",), request_size_class="xlarge")
        raise SystemExit("empty eligible set accepted")
    except EmptyEligibleSetError as exc:
        assert len(exc.exclusions) == 2

    # declared preference breaks a cost tie
    row_b2 = build_descriptor_row(
        "ro.provider.b2", {"ro.cap.x": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="restricted",
    )
    tied = build_candidate_set([row_b, row_b2], "ro.cap.x", "C1")
    winner4, _, _ = select_provider(tied, privacy_domain_required="restricted",
                                     declared_preference=("ro.provider.b2", "ro.provider.b"))
    assert winner4.provider_id == "ro.provider.b2"

    # alphabetical fallback with no declared preference
    winner5, _, _ = select_provider(tied, privacy_domain_required="restricted")
    assert winner5.provider_id == "ro.provider.b"

    print("matching_selection selftest ok")
