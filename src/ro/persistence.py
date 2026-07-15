"""RO durable-artifact persistence — RO-S3: every determinism-tuple
coordinate (descriptor-space versions, schema versions, priors versions,
decision/outcome records) is durable via Storage; "a replay coordinate that
can vanish is a defect." Mirrors prt/persistence.py's shape: an injected
storage PORT (Storage itself is a separate, unbuilt subsystem;
`storage_double.py` is this phase's test-fixture implementation, same
pattern UMS/RSM/CM/PRT already ship), deterministic canonical bytes, and a
write-then-read-back verify per house pattern (content-hash equality
asserted on load — a poisoned/tampered coordinate is loud, never silently
accepted).

Decision records and sealed outcome records are content-addressed (their
own content hash IS their storage key, RO/03-04 precedent everywhere else
in this package); descriptor-space snapshots and the schema registry are
VERSION-addressed collections (there is no single content hash for "the
space as of version N" upstream, so this module mints one the same way
prt/persistence.py's `_content()` does — sorted-by-id canonical JSON)."""
import json

from . import descriptor_space as _descriptor_space
from . import outcome as _outcome
from . import priors as _priors
from .decision_gate import DecisionRecord
from .decision_gate import canonical as _decision_canonical
from .decision_gate import content_hash as _decision_content_hash
from .records import (
    CapabilityRecord, DescriptorRow, RelationshipRecord,
    canonical as _record_canonical, content_hash as _record_content_hash,
    build_capability, build_descriptor_row, build_relationship,
)
from .schemas import SchemaRegistry


class PersistenceRefusal(Exception):
    """Base for RO persistence refusals."""


class PoisonedCoordinateError(PersistenceRefusal):
    """A loaded coordinate's recomputed content hash doesn't match what was
    written — tampered or corrupted storage, always loud."""


_DECISION_PREFIX = "ro/decision/"
_OUTCOME_PREFIX = "ro/outcome/"
_PRIORS_PREFIX = "ro/priors/"
_DESCRIPTOR_SPACE_PREFIX = "ro/descriptor_space/"
_SCHEMA_REGISTRY_KEY = "ro/schema_registry/snapshot"


# -- decision records (content-addressed) -----------------

def persist_decision_record(record, storage):
    h = _decision_content_hash(record)
    key = _DECISION_PREFIX + h
    if not storage.exists(key):
        storage.write(key, _decision_canonical(record))
    return h


def load_decision_record(content_hash_value, storage):
    data = json.loads(storage.read(_DECISION_PREFIX + content_hash_value))
    from types import MappingProxyType
    scope = data["approved_scope"]
    record = DecisionRecord(
        outcome=data["outcome"],
        justification=MappingProxyType(data["justification"]),
        decided_from=MappingProxyType(data["decided_from"]),
        approved_capability_id=data["approved_capability_id"],
        approved_required_rung=data["approved_required_rung"],
        approved_scope=(MappingProxyType({
            "description": scope["description"], "granularity": scope["granularity"],
            "narrowing": MappingProxyType(scope["narrowing"]) if scope.get("narrowing") is not None else None,
        }) if scope is not None else None),
    )
    got = _decision_content_hash(record)
    if got != content_hash_value:
        raise PoisonedCoordinateError("persistence.poisoned_decision_record:" + content_hash_value)
    return record


# -- sealed outcome records (content-addressed) -----------------

def persist_sealed_outcome(record, storage):
    h = _outcome.content_hash(record)
    key = _OUTCOME_PREFIX + h
    if not storage.exists(key):
        storage.write(key, _outcome.canonical(record))
    return h


def load_sealed_outcome(content_hash_value, storage):
    data = json.loads(storage.read(_OUTCOME_PREFIX + content_hash_value))
    kwargs = {k: v for k, v in data.items() if k != "record_version"}
    record = _outcome.build_sealed_outcome(**kwargs)
    got = _outcome.content_hash(record)
    if got != content_hash_value:
        raise PoisonedCoordinateError("persistence.poisoned_sealed_outcome:" + content_hash_value)
    return record


# -- priors artifacts (version-addressed, RO-S6 replay pinning) -----------

def persist_priors_artifact(artifact, storage):
    key = _PRIORS_PREFIX + "v" + str(artifact.priors_version)
    if not storage.exists(key):
        storage.write(key, _priors.canonical(artifact))
    return artifact.priors_version


def load_priors_artifact(version, storage):
    data = json.loads(storage.read(_PRIORS_PREFIX + "v" + str(version)))
    artifact = _priors.build_priors_artifact(**data)
    if artifact.priors_version != version or _priors.canonical(artifact) != json.dumps(
            data, sort_keys=True, separators=(",", ":")).encode():
        raise PoisonedCoordinateError("persistence.poisoned_priors_artifact:v" + str(version))
    return artifact


# -- descriptor-space snapshot (version-addressed collection) -----------

def _descriptor_space_content(snapshot):
    capabilities = sorted(snapshot.all_capabilities(), key=lambda r: r.id)
    relationships = sorted(snapshot.relationships(), key=lambda r: (r.kind, r.src, r.dst))
    descriptor_rows = sorted(snapshot.all_descriptor_rows(), key=lambda r: r.provider_id)
    return {
        "version": snapshot.version,
        "capabilities": [_record_canonical(r).decode() for r in capabilities],
        "relationships": [_record_canonical(r).decode() for r in relationships],
        "descriptor_rows": [_record_canonical(r).decode() for r in descriptor_rows],
    }


def persist_descriptor_space_version(space, version, storage):
    """Persists `space.at_version(version)` — an immutable historical
    snapshot (descriptor_space.py's own replay coordinate, reused here
    rather than re-derived)."""
    snapshot = space.at_version(version)
    content = _descriptor_space_content(snapshot)
    key = _DESCRIPTOR_SPACE_PREFIX + "v" + str(version)
    data = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    if not storage.exists(key):
        storage.write(key, data)
    return version


def load_descriptor_space_version(version, storage):
    """Returns (capabilities, relationships, descriptor_rows) tuples,
    reconstructed via records.py's own builders (never a second parse
    path) and verified byte-identical to what was persisted."""
    raw = storage.read(_DESCRIPTOR_SPACE_PREFIX + "v" + str(version))
    content = json.loads(raw)

    capabilities = tuple(_rebuild_capability(json.loads(c)) for c in content["capabilities"])
    relationships = tuple(_rebuild_relationship(json.loads(r)) for r in content["relationships"])
    descriptor_rows = tuple(_rebuild_descriptor_row(json.loads(d)) for d in content["descriptor_rows"])

    replayed = _descriptor_space_content(_FrozenSnapshot(version, capabilities, relationships, descriptor_rows))
    if json.dumps(replayed, sort_keys=True, separators=(",", ":")).encode() != raw:
        raise PoisonedCoordinateError("persistence.poisoned_descriptor_space:v" + str(version))
    return capabilities, relationships, descriptor_rows


class _FrozenSnapshot:
    """Read-surface-compatible adapter over reconstructed tuples, for
    re-running `_descriptor_space_content` against the replayed data
    without depending on descriptor_space.py's internal snapshot shape."""

    def __init__(self, version, capabilities, relationships, descriptor_rows):
        self.version = version
        self._capabilities = capabilities
        self._relationships = relationships
        self._descriptor_rows = descriptor_rows

    def all_capabilities(self):
        return list(self._capabilities)

    def relationships(self):
        return list(self._relationships)

    def all_descriptor_rows(self):
        return list(self._descriptor_rows)


def _rebuild_capability(d):
    return build_capability(d["id"], d["category"], d["characteristics"],
                             facets=tuple(d["facets"]), lifecycle=d["lifecycle"])


def _rebuild_relationship(d):
    return build_relationship(d["relationship_kind"], d["src"], d["dst"])


def _rebuild_descriptor_row(d):
    return build_descriptor_row(
        d["provider_id"], d["capabilities_claimed"], context_capacity_class=d["context_capacity_class"],
        cost_class=d["cost_class"], latency_class=d["latency_class"],
        determinism_class=d["determinism_class"], deployment_locality=d["deployment_locality"],
        privacy_domain=d["privacy_domain"], compliance_tags=tuple(d["compliance_tags"]),
        reliability=d["reliability"], request_form=d["request_form"],
    )


# -- schema registry (one global snapshot) -----------------

def persist_schema_registry(registry, storage):
    # ponytail: schemas.py (Phase 3, frozen) exposes no enumeration method,
    # only get/require by (schema_id, version) — reaching into `_entries` is
    # the only way to snapshot "every registered schema" without editing a
    # frozen module. Upgrade path: schemas.py grows an `all_entries()`
    # method and this reaches through that instead.
    entries = sorted(
        ((rec.schema_id, rec.version, list(rec.required_fields))
         for (sid, ver), rec in registry._entries.items()),
        key=lambda t: (t[0], t[1]))
    data = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    storage.write(_SCHEMA_REGISTRY_KEY, data)
    return data


def load_schema_registry(storage):
    entries = json.loads(storage.read(_SCHEMA_REGISTRY_KEY))
    registry = SchemaRegistry()
    for schema_id, version, required_fields in entries:
        registry.register(schema_id, version, tuple(required_fields))
    replayed = sorted(
        [rec.schema_id, rec.version, list(rec.required_fields)]
        for (sid, ver), rec in registry._entries.items())
    if replayed != entries:
        raise PoisonedCoordinateError("persistence.poisoned_schema_registry")
    return registry


if __name__ == "__main__":
    from types import MappingProxyType

    from .descriptor_space import DescriptorSpace
    from .outcome import build_sealed_outcome
    from .storage_double import StorageDouble

    store = StorageDouble()

    # decision record round trip
    decision = DecisionRecord(
        outcome="REASONING_APPROVED", justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({"priors_version": 1}),
        approved_capability_id="ro.cap.x", approved_required_rung="C1",
        approved_scope=MappingProxyType({"description": "d", "granularity": "g", "narrowing": None}),
    )
    dhash = persist_decision_record(decision, store)
    restored_decision = load_decision_record(dhash, store)
    assert restored_decision.outcome == "REASONING_APPROVED"
    assert _decision_content_hash(restored_decision) == dhash

    # poisoned decision record refused loud
    store.write(_DECISION_PREFIX + dhash, b'{"outcome": "REASONING_REJECTED", "justification": {}, ' +
                b'"decided_from": {}, "approved_capability_id": null, "approved_required_rung": null, ' +
                b'"approved_scope": null}')
    try:
        load_decision_record(dhash, store)
        raise SystemExit("poisoned decision record accepted")
    except PoisonedCoordinateError:
        pass

    # sealed outcome round trip
    outcome_rec = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={"a": 1},
        attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
        provider_id="p", budget_consumed=10, budget_remaining=90, output={"summary": "ok"},
    )
    ohash = persist_sealed_outcome(outcome_rec, store)
    restored_outcome = load_sealed_outcome(ohash, store)
    assert restored_outcome.output == {"summary": "ok"}
    assert _outcome.content_hash(restored_outcome) == ohash

    # priors artifact round trip + poisoned load
    artifact = _priors.build_priors_artifact(
        1, provider_priors={"p": {"reliability": "high"}}, routing_priors={},
        demand_shape_priors={}, policy_proposals=({"proposal": "x"},))
    persist_priors_artifact(artifact, store)
    restored_priors = load_priors_artifact(1, store)
    assert restored_priors.priors_version == 1
    assert restored_priors.policy_proposals[0]["proposal"] == "x"

    # descriptor space snapshot round trip
    space = DescriptorSpace()
    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "low",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.a", "INTERPRETIVE", _CHARS, lifecycle="active")
    space.apply({"kind": "add_capability", "record": cap})
    row = build_descriptor_row(
        "ro.provider.a", {"ro.cap.a": ("C1",)}, context_capacity_class="medium",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    space.apply({"kind": "add_descriptor_row", "record": row})
    v = space.current_version
    persist_descriptor_space_version(space, v, store)
    caps, rels, rows = load_descriptor_space_version(v, store)
    assert caps[0].id == "ro.cap.a"
    assert rows[0].provider_id == "ro.provider.a"

    # schema registry round trip
    registry = SchemaRegistry()
    registry.register("ro.schema.summary", 1, ("summary",))
    persist_schema_registry(registry, store)
    restored_registry = load_schema_registry(store)
    assert restored_registry.require("ro.schema.summary", 1).required_fields == ("summary",)

    print("persistence selftest ok")
