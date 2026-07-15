"""RO record types — RO/01 (capability model) + RO/03 §3 (descriptor row).

Three frozen record shapes, following the prt/records.py convention exactly
(dataclass(frozen=True), MappingProxyType-frozen mapping fields, a
`build_*` validating factory per record, canonical/content_hash via sorted
JSON). Zero imports from src/prt — RO's descriptor space is its own
authority (RO-I9, RO-C12).

- CapabilityRecord: RO/01 §3-§5. `category` is one of the five closed
  categories (RO-C4). `characteristics` is exactly the eight RO/01 §5
  characteristics, each a categorical band value from a closed,
  module-level band vocabulary (RO-C6/RO-C7 — never numeric). `facets` are
  free tags, stored, never validated for meaning (RO-C4). `lifecycle`
  mirrors CP/01/PRT discipline: proposed/active/deprecated/retired,
  forward-only (enforced in descriptor_space.py, not here).

- RelationshipRecord: RO/01 §7 — exactly three kinds (RO-C8): composition,
  specialization, dependency. `src`/`dst` are capability ids; acyclicity of
  dependency edges is a descriptor_space.py concern (RO-C10), not a
  record-shape constraint.

- DescriptorRow: RO/03 §3 — a provider's declared fulfillment claim.
  `provider_id` is the row's stable identity. `capabilities_claimed` maps
  capability id -> the C0-C4 rungs (RO/01 §6) that provider claims to
  serve for that capability (combines the doc's "capabilities claimed" +
  "capability strength per claim" rows into one field). Every other
  declared field (RO/03 §3 table) is a categorical class drawn from a
  closed, module-level vocabulary. No field may reference a vendor or
  model name by content — that is a shape rule only; content-based
  rejection is law-enforcer territory, out of scope for Phase 1.
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

# -- closed vocabularies (RO/01 + RO/03 §3; band data, not model) -----------

LIFECYCLE_STATES = ("proposed", "active", "deprecated", "retired")

CATEGORIES = ("INTERPRETIVE", "ANALYTIC", "GENERATIVE", "DELIBERATIVE", "INFERENTIAL")

RELATIONSHIP_KINDS = ("composition", "specialization", "dependency")

# RO/01 §6 — the five-level complexity hierarchy; also the closed set of
# rungs a descriptor row may claim strength at (RO/03 §3).
COMPLEXITY_RUNGS = ("C0", "C1", "C2", "C3", "C4")

# RO/01 §5 — eight characteristics, each with its own minimal closed band
# vocabulary. Bands are data (declared here), never numeric thresholds
# (RO-C7). Order fixed by declaration, not runtime dict order.
CHARACTERISTIC_BANDS = {
    "inference_depth": ("shallow", "moderate", "deep"),
    "context_sensitivity": ("low", "medium", "high"),
    "determinism_tolerance": ("low", "medium", "high"),
    "knowledge_dependency": ("low", "medium", "high"),
    "creativity_requirement": ("low", "medium", "high"),
    "reasoning_complexity": COMPLEXITY_RUNGS,
    "verification_difficulty": ("low", "medium", "high"),
    "expected_output_structure": ("strict", "bounded", "open"),
}
CHARACTERISTIC_NAMES = frozenset(CHARACTERISTIC_BANDS)

# RO/03 §3 descriptor row field vocabularies — minimal sensible classes.
CONTEXT_CAPACITY_CLASSES = ("small", "medium", "large", "xlarge")
COST_CLASSES = ("low", "medium", "high")
LATENCY_CLASSES = ("fast", "standard", "slow")
DETERMINISM_CLASSES = ("low_variance", "medium_variance", "high_variance")
DEPLOYMENT_LOCALITY_CLASSES = ("local", "remote")
PRIVACY_DOMAINS = ("public", "internal", "restricted")
RELIABILITY_BASELINE_CLASSES = ("low", "medium", "high")

# RO/03 §11 — the closed vocabulary of request render forms a descriptor row
# may declare (Phase 3 additive field; RO/00 §11.5 bounded extension: a new
# modality is a new tuple entry + renderer, zero shape change here).
REQUEST_FORMS = ("prompt_text",)


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


def _check_lifecycle(lifecycle):
    if lifecycle not in LIFECYCLE_STATES:
        raise ValueError("records.unknown_lifecycle:" + str(lifecycle))


# -- CapabilityRecord ---------------------------------------------------

@dataclass(frozen=True)
class CapabilityRecord:
    id: str
    category: str
    characteristics: MappingProxyType
    facets: tuple
    lifecycle: str


def build_capability(id, category, characteristics, facets=(), lifecycle="proposed"):
    """Construct a CapabilityRecord. Fails loud (ValueError) on: unknown
    category (RO-C4), unknown lifecycle, a characteristics mapping that
    does not declare exactly the eight RO/01 §5 names, or any
    characteristic value outside its closed band (RO-C6/RO-C7)."""
    if category not in CATEGORIES:
        raise ValueError("records.unknown_category:" + str(category))
    _check_lifecycle(lifecycle)
    characteristics = dict(characteristics or {})
    given = frozenset(characteristics)
    if given != CHARACTERISTIC_NAMES:
        missing = CHARACTERISTIC_NAMES - given
        extra = given - CHARACTERISTIC_NAMES
        raise ValueError(
            "records.characteristics_mismatch:missing=" + ",".join(sorted(missing)) +
            ":extra=" + ",".join(sorted(extra)))
    for name, band in characteristics.items():
        if band not in CHARACTERISTIC_BANDS[name]:
            raise ValueError("records.characteristic_band_invalid:" + name + ":" + str(band))
    return CapabilityRecord(
        id=id, category=category, characteristics=_freeze_mapping(characteristics),
        facets=tuple(facets), lifecycle=lifecycle,
    )


# -- RelationshipRecord ---------------------------------------------------

@dataclass(frozen=True)
class RelationshipRecord:
    kind: str
    src: str
    dst: str


def build_relationship(kind, src, dst):
    """RO-C8: exactly three kinds; constructor refuses any other."""
    if kind not in RELATIONSHIP_KINDS:
        raise ValueError("records.unknown_relationship_kind:" + str(kind))
    return RelationshipRecord(kind=kind, src=src, dst=dst)


# -- DescriptorRow ---------------------------------------------------

@dataclass(frozen=True)
class DescriptorRow:
    provider_id: str
    capabilities_claimed: MappingProxyType  # capability id -> tuple of C0-C4 rungs
    context_capacity_class: str
    cost_class: str
    latency_class: str
    determinism_class: str
    deployment_locality: str
    privacy_domain: str
    compliance_tags: tuple
    reliability: MappingProxyType  # {"baseline": class, "priors_version": int|None}
    request_form: str  # RO/03 §11 — closed REQUEST_FORMS vocabulary (Phase 3 additive)


def build_descriptor_row(provider_id, capabilities_claimed, context_capacity_class,
                          cost_class, latency_class, determinism_class,
                          deployment_locality, privacy_domain, compliance_tags=(),
                          reliability=None, request_form="prompt_text"):
    """Construct a DescriptorRow. Every categorical field is checked against
    its closed vocabulary; `capabilities_claimed` must be non-empty and
    every claimed rung must be one of C0-C4 (RO/01 §6). Shape only — this
    does not check the claimed capability ids actually exist or are
    active; that is descriptor_space.py's cross-referencing job.

    `request_form` (RO/03 §11, Phase 3 additive, purely optional/additive —
    defaults to "prompt_text" so every Phase 1/2 call site is unaffected):
    the renderer form this row's engine consumes."""
    if request_form not in REQUEST_FORMS:
        raise ValueError("records.unknown_request_form:" + str(request_form))
    if context_capacity_class not in CONTEXT_CAPACITY_CLASSES:
        raise ValueError("records.unknown_context_capacity_class:" + str(context_capacity_class))
    if cost_class not in COST_CLASSES:
        raise ValueError("records.unknown_cost_class:" + str(cost_class))
    if latency_class not in LATENCY_CLASSES:
        raise ValueError("records.unknown_latency_class:" + str(latency_class))
    if determinism_class not in DETERMINISM_CLASSES:
        raise ValueError("records.unknown_determinism_class:" + str(determinism_class))
    if deployment_locality not in DEPLOYMENT_LOCALITY_CLASSES:
        raise ValueError("records.unknown_deployment_locality:" + str(deployment_locality))
    if privacy_domain not in PRIVACY_DOMAINS:
        raise ValueError("records.unknown_privacy_domain:" + str(privacy_domain))

    capabilities_claimed = dict(capabilities_claimed or {})
    if not capabilities_claimed:
        raise ValueError("records.descriptor_row_claims_nothing:" + str(provider_id))
    frozen_claims = {}
    for cap_id, rungs in capabilities_claimed.items():
        rungs = tuple(sorted(set(rungs)))
        if not rungs:
            raise ValueError("records.descriptor_row_empty_strength:" + str(cap_id))
        for rung in rungs:
            if rung not in COMPLEXITY_RUNGS:
                raise ValueError("records.unknown_complexity_rung:" + str(rung))
        frozen_claims[cap_id] = rungs

    reliability = dict(reliability or {"baseline": "medium", "priors_version": None})
    baseline = reliability.get("baseline")
    if baseline not in RELIABILITY_BASELINE_CLASSES:
        raise ValueError("records.unknown_reliability_baseline:" + str(baseline))
    priors_version = reliability.get("priors_version")
    if priors_version is not None and not isinstance(priors_version, int):
        raise ValueError("records.bad_priors_version:" + str(priors_version))

    return DescriptorRow(
        provider_id=provider_id, capabilities_claimed=_freeze_mapping(frozen_claims),
        context_capacity_class=context_capacity_class, cost_class=cost_class,
        latency_class=latency_class, determinism_class=determinism_class,
        deployment_locality=deployment_locality, privacy_domain=privacy_domain,
        compliance_tags=tuple(compliance_tags),
        reliability=_freeze_mapping({"baseline": baseline, "priors_version": priors_version}),
        request_form=request_form,
    )


# -- canonical serialization (prt/records.py pattern) -----------------

def to_dict(record):
    """Plain-dict view; MappingProxyType/tuple unwrapped. Dispatches on
    record type since the three shapes differ."""
    if isinstance(record, CapabilityRecord):
        return {
            "kind": "capability", "id": record.id, "category": record.category,
            "characteristics": dict(record.characteristics), "facets": list(record.facets),
            "lifecycle": record.lifecycle,
        }
    if isinstance(record, RelationshipRecord):
        return {"kind": "relationship", "relationship_kind": record.kind,
                "src": record.src, "dst": record.dst}
    if isinstance(record, DescriptorRow):
        return {
            "kind": "descriptor_row", "provider_id": record.provider_id,
            "capabilities_claimed": {k: list(v) for k, v in record.capabilities_claimed.items()},
            "context_capacity_class": record.context_capacity_class,
            "cost_class": record.cost_class, "latency_class": record.latency_class,
            "determinism_class": record.determinism_class,
            "deployment_locality": record.deployment_locality,
            "privacy_domain": record.privacy_domain,
            "compliance_tags": list(record.compliance_tags),
            "reliability": dict(record.reliability),
            "request_form": record.request_form,
        }
    raise TypeError("records.unknown_record_type:" + repr(type(record)))


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


if __name__ == "__main__":
    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "low",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }

    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, facets=("text",))
    assert cap.lifecycle == "proposed" and cap.category == "INTERPRETIVE"
    assert cap.characteristics["reasoning_complexity"] == "C1"

    # unknown category refused
    try:
        build_capability("ro.cap.bad", "MADEUP", _CHARS)
        raise SystemExit("unknown category accepted")
    except ValueError:
        pass

    # missing characteristic refused
    incomplete = dict(_CHARS)
    del incomplete["creativity_requirement"]
    try:
        build_capability("ro.cap.bad2", "INTERPRETIVE", incomplete)
        raise SystemExit("incomplete characteristics accepted")
    except ValueError:
        pass

    # extra characteristic refused
    extra = dict(_CHARS)
    extra["made_up"] = "low"
    try:
        build_capability("ro.cap.bad3", "INTERPRETIVE", extra)
        raise SystemExit("extra characteristic accepted")
    except ValueError:
        pass

    # out-of-band characteristic value refused
    bad_band = dict(_CHARS)
    bad_band["inference_depth"] = "infinite"
    try:
        build_capability("ro.cap.bad4", "INTERPRETIVE", bad_band)
        raise SystemExit("out-of-band characteristic value accepted")
    except ValueError:
        pass

    # frozen: field reassignment / mapping mutation both raise
    try:
        cap.category = "ANALYTIC"
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass
    try:
        cap.characteristics["inference_depth"] = "deep"
        raise SystemExit("characteristics mutation allowed")
    except TypeError:
        pass

    edge = build_relationship("dependency", "ro.cap.a", "ro.cap.b")
    assert edge.kind == "dependency"
    for kind in RELATIONSHIP_KINDS:
        build_relationship(kind, "ro.cap.a", "ro.cap.b")
    try:
        build_relationship("alternative", "ro.cap.a", "ro.cap.b")
        raise SystemExit("invented relationship kind accepted")
    except ValueError:
        pass

    row = build_descriptor_row(
        "ro.provider.x", {"ro.cap.summarize": ("C1", "C0", "C1")},
        context_capacity_class="medium", cost_class="low", latency_class="fast",
        determinism_class="low_variance", deployment_locality="local",
        privacy_domain="internal", compliance_tags=("gdpr",),
        reliability={"baseline": "high", "priors_version": 3},
    )
    assert row.capabilities_claimed["ro.cap.summarize"] == ("C0", "C1")  # dedup + sorted
    assert row.reliability["priors_version"] == 3
    assert row.request_form == "prompt_text"  # default, Phase 3 additive field

    # unknown request_form refused
    try:
        build_descriptor_row(
            "ro.provider.badform", {"ro.cap.summarize": ("C1",)}, context_capacity_class="medium",
            cost_class="low", latency_class="fast", determinism_class="low_variance",
            deployment_locality="local", privacy_domain="internal", request_form="carrier_pigeon",
        )
        raise SystemExit("unknown request_form accepted")
    except ValueError:
        pass

    # descriptor row claiming nothing refused
    try:
        build_descriptor_row(
            "ro.provider.bad", {}, context_capacity_class="medium", cost_class="low",
            latency_class="fast", determinism_class="low_variance",
            deployment_locality="local", privacy_domain="internal",
        )
        raise SystemExit("empty-claim descriptor row accepted")
    except ValueError:
        pass

    # unknown rung refused
    try:
        build_descriptor_row(
            "ro.provider.bad2", {"ro.cap.summarize": ("C9",)}, context_capacity_class="medium",
            cost_class="low", latency_class="fast", determinism_class="low_variance",
            deployment_locality="local", privacy_domain="internal",
        )
        raise SystemExit("unknown rung accepted")
    except ValueError:
        pass

    # canonical/content_hash: identical input -> identical bytes
    cap2 = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, facets=("text",))
    assert canonical(cap) == canonical(cap2)
    assert content_hash(cap) == content_hash(cap2)

    print("records selftest ok")
