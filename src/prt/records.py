"""PRT registry record types — PRT/01 §2 (information categories), §5
(identity/alias), §6 (relationships), §7 (bindings), §8 (constraints).

Four frozen, immutable record types. Frozen the same way rsm/record.py and
cm/request_memory.py are frozen: dataclass(frozen=True) refuses field
reassignment, MappingProxyType refuses in-place mutation of any mapping
field. A `build_*` factory validates and freezes plain-Python inputs into
each dataclass — records are never constructed with unfrozen containers.

- CapabilityRecord: PRT/01 §2 categories except provider bindings/policy.
  `verification_expectations` is mandatory and non-empty at construction
  (PRT-I4, PRT-R9) — a capability without one cannot be built, let alone
  registered; this is the earliest possible enforcement point, admission
  (registry.py) enforces it again as the PRT/01 §9 gate.
  `entry_version` is the per-entry compatible-clarification revision
  (CP/01 §7) — distinct from the registry-global version (PRT-R5); this
  module never touches the global counter.
- ProviderRecord: PRT/01 §2 provider bindings/policy categories. `version`
  is the provider's own version (PRT/00 C10, distinct from PRT-A8 identity)
  — never conflated with entry_version or the registry-global version.
  `load_policy` is stored as data only, never enforced here (PRT/01 §2:
  policy information, enforcement is Execution's per C5).
- BindingRecord: PRT/01 §7 — one provider's declared fulfillment of one
  capability id. Many-to-many is a registry.py property (many bindings
  share a capability_id or a provider_id), not a record-shape constraint.
- RelationshipEdge: PRT/01 §6 / PRT-R7 — exactly the four CP/01 §8 kinds.
  Constructor refuses any other kind structurally, same refusal shape as
  events.py's closed vocabulary.

Lifecycle states (`LIFECYCLE_STATES`) are CP/01 §6's four, shared verbatim
by capabilities and providers alike (PRT/01 §9 "lifecycle legality" binds
both; registry.py enforces forward-only transitions for each).
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

LIFECYCLE_STATES = ("proposed", "active", "deprecated", "retired")
RELATIONSHIP_KINDS = ("dependency", "composition", "alternative", "conflict")


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


def _check_lifecycle(lifecycle):
    if lifecycle not in LIFECYCLE_STATES:
        raise ValueError("records.unknown_lifecycle:" + str(lifecycle))


@dataclass(frozen=True)
class CapabilityRecord:
    id: str
    description: str
    category: str
    facets: tuple
    lifecycle: str
    aliases: tuple
    verification_expectations: tuple
    constraints: MappingProxyType
    entry_version: int
    deprecation_pointer: object  # replacement capability id, or None


def build_capability(id, description, category, facets=(), lifecycle="proposed",
                      aliases=(), verification_expectations=(), constraints=None,
                      entry_version=1, deprecation_pointer=None):
    """Construct a CapabilityRecord. Fails loud (ValueError) without a
    verification expectation (PRT-I4/PRT-R9) or with an unknown lifecycle
    state — both checked here, before registry.py ever sees the record."""
    _check_lifecycle(lifecycle)
    verification_expectations = tuple(verification_expectations)
    if not verification_expectations:
        raise ValueError("records.missing_verification_expectation:" + id)
    return CapabilityRecord(
        id=id, description=description, category=category,
        facets=tuple(facets), lifecycle=lifecycle, aliases=tuple(aliases),
        verification_expectations=verification_expectations,
        constraints=_freeze_mapping(constraints), entry_version=entry_version,
        deprecation_pointer=deprecation_pointer,
    )


@dataclass(frozen=True)
class ProviderRecord:
    id: str
    version: str
    declared_constraints: MappingProxyType
    load_policy: MappingProxyType
    lifecycle: str


def build_provider(id, version, declared_constraints=None, load_policy=None,
                    lifecycle="proposed"):
    _check_lifecycle(lifecycle)
    return ProviderRecord(
        id=id, version=version,
        declared_constraints=_freeze_mapping(declared_constraints),
        load_policy=_freeze_mapping(load_policy), lifecycle=lifecycle,
    )


@dataclass(frozen=True)
class BindingRecord:
    capability_id: str
    provider_id: str
    terms: MappingProxyType  # declared constraints/terms of this specific binding


def build_binding(capability_id, provider_id, terms=None):
    return BindingRecord(capability_id=capability_id, provider_id=provider_id,
                         terms=_freeze_mapping(terms))


@dataclass(frozen=True)
class RelationshipEdge:
    kind: str
    src: str  # source capability id
    dst: str  # destination capability id


def build_relationship(kind, src, dst):
    """PRT-R7: exactly four kinds; constructor refuses any other, no
    exceptions, amending CP/01 first is the only legal way to add a fifth."""
    if kind not in RELATIONSHIP_KINDS:
        raise ValueError("records.unknown_relationship_kind:" + str(kind))
    return RelationshipEdge(kind=kind, src=src, dst=dst)


# -- canonical serialization (cm/request_memory.py pattern) -----------------

def to_dict(record):
    """Plain-dict view; MappingProxyType/tuple unwrapped. Dispatches on
    record type since the four shapes differ."""
    if isinstance(record, CapabilityRecord):
        return {
            "kind": "capability", "id": record.id, "description": record.description,
            "category": record.category, "facets": list(record.facets),
            "lifecycle": record.lifecycle, "aliases": list(record.aliases),
            "verification_expectations": list(record.verification_expectations),
            "constraints": dict(record.constraints), "entry_version": record.entry_version,
            "deprecation_pointer": record.deprecation_pointer,
        }
    if isinstance(record, ProviderRecord):
        return {
            "kind": "provider", "id": record.id, "version": record.version,
            "declared_constraints": dict(record.declared_constraints),
            "load_policy": dict(record.load_policy), "lifecycle": record.lifecycle,
        }
    if isinstance(record, BindingRecord):
        return {"kind": "binding", "capability_id": record.capability_id,
                "provider_id": record.provider_id, "terms": dict(record.terms)}
    if isinstance(record, RelationshipEdge):
        return {"kind": "relationship", "relationship_kind": record.kind,
                "src": record.src, "dst": record.dst}
    raise TypeError("records.unknown_record_type:" + repr(type(record)))


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


if __name__ == "__main__":
    cap = build_capability(
        "cap.summarize.text", "summarize text", "nlp", facets=("text", "summary"),
        verification_expectations=("output non-empty",), constraints={"max_tokens": 4000},
    )
    assert cap.lifecycle == "proposed" and cap.entry_version == 1
    assert cap.constraints["max_tokens"] == 4000

    # missing verification expectation refused at construction (PRT-I4/PRT-R9)
    try:
        build_capability("cap.bad", "d", "nlp", verification_expectations=())
        raise SystemExit("capability without verification expectation accepted")
    except ValueError:
        pass

    # unknown lifecycle refused
    try:
        build_capability("cap.bad2", "d", "nlp", verification_expectations=("x",),
                          lifecycle="banished")
        raise SystemExit("unknown lifecycle accepted")
    except ValueError:
        pass

    # frozen: field reassignment raises
    try:
        cap.description = "different"
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass
    # frozen: container mutation raises
    try:
        cap.constraints["max_tokens"] = 1
        raise SystemExit("constraints mutation allowed")
    except TypeError:
        pass

    prov = build_provider("prov.acme.summarizer", "1.0.0",
                          declared_constraints={"platform": "linux"},
                          load_policy={"isolation": "sandboxed"})
    assert prov.load_policy["isolation"] == "sandboxed"

    binding = build_binding(cap.id, prov.id, terms={"priority": 1})
    assert binding.capability_id == cap.id and binding.provider_id == prov.id

    edge = build_relationship("dependency", "cap.a", "cap.b")
    assert edge.kind == "dependency"

    # PRT-R7: exactly four kinds, no more
    for kind in RELATIONSHIP_KINDS:
        build_relationship(kind, "cap.a", "cap.b")
    try:
        build_relationship("specialization", "cap.a", "cap.b")
        raise SystemExit("invented relationship kind accepted")
    except ValueError:
        pass

    # canonical/content_hash: identical input -> identical bytes (Law 6 style)
    cap2 = build_capability(
        "cap.summarize.text", "summarize text", "nlp", facets=("text", "summary"),
        verification_expectations=("output non-empty",), constraints={"max_tokens": 4000},
    )
    assert canonical(cap) == canonical(cap2)
    assert content_hash(cap) == content_hash(cap2)

    print("records selftest ok")
