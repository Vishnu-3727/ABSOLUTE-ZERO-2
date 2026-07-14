"""PRT registry persistence — PRT/00 C6 (durable writes via Storage only;
PRT keeps the authoritative in-memory view) wired against an INJECTED
storage port. Boundary ruling: Storage itself is a separate, unbuilt
subsystem; `storage_double.py` is the test-fixture implementation of that
injected port (the same pattern UMS/RSM/CM already shipped) — this module
is the PRT-side seam, not a Storage reimplementation.

`snapshot_bytes(registry)`: deterministic canonical JSON of the registry's
CURRENT-version content (every capability/provider/binding/relationship)
plus the version number, under one stable key.

`persist_registry`/`load_registry`: round-trip through the injected
storage port. registry.py is frozen and has no ordered global mutation
log to replay from (it persists admitted bundles pre-commit under
`prt/admission/<hash>` keys, PRT/02 §7/§9, but that is per-candidacy, not
one global journal) — so reconstruction REPLAYS the persisted CONTENT as
ordinary `add_capability`/`add_provider`/`add_binding`/`add_relationship`
mutations through a fresh `Registry`, i.e. through registry.py's own
single `apply()` writer (PRT-R1/R2 preserved — no second mutation surface
invented).

# ponytail: version-number continuity. Replaying CONTENT (not the
# ORIGINAL mutation sequence — refused mutations, lifecycle_transition
# steps that only changed a record's lifecycle in place, etc. never
# happened in the replay) mints a fresh version counter that generally
# will NOT equal the original registry's version number, even though the
# resulting CONTENT is identical. PRT/01 §4 wants "registry version
# survives restart" as a citable coordinate; the fully-correct answer is
# a real Storage-backed ORDERED journal that replays mutation-for-
# mutation, preserving the exact version sequence — that arrives with the
# real Storage subsystem (out of PRT's ownership wall, boundary ruling).
# Until then: `load_registry` returns `(registry, persisted_version)` —
# content equality (excluding the version field) is asserted; the
# ORIGINAL version number is carried alongside as the citable fact for
# anything (e.g. a Binding Contract) that already recorded it, rather
# than invented from the replay's own differently-numbered counter.
# Upgrade path: real Storage's ordered journal replay.
"""
import json

from .records import build_binding, build_capability, build_provider, build_relationship
from .registry import Registry

SNAPSHOT_KEY = "prt/registry/snapshot"


def _capability_dict(record):
    return {
        "id": record.id, "description": record.description, "category": record.category,
        "facets": list(record.facets), "lifecycle": record.lifecycle,
        "aliases": list(record.aliases),
        "verification_expectations": list(record.verification_expectations),
        "constraints": dict(record.constraints), "entry_version": record.entry_version,
        "deprecation_pointer": record.deprecation_pointer,
    }


def _provider_dict(record):
    return {
        "id": record.id, "version": record.version,
        "declared_constraints": dict(record.declared_constraints),
        "load_policy": dict(record.load_policy), "lifecycle": record.lifecycle,
    }


def _binding_dict(record):
    return {"capability_id": record.capability_id, "provider_id": record.provider_id,
            "terms": dict(record.terms)}


def _relationship_dict(record):
    return {"kind": record.kind, "src": record.src, "dst": record.dst}


def _content(registry, version=None):
    """One canonical view of everything `registry` currently holds, in a
    deterministic order (by id / by (capability_id, provider_id)) so two
    byte-identical registries always produce byte-identical bytes
    regardless of internal dict-iteration order (registry.py makes no
    ordering promise on its own dicts)."""
    capabilities = sorted(registry.all_capabilities(), key=lambda r: r.id)
    providers = sorted(registry.all_providers(), key=lambda r: r.id)
    bindings = sorted(registry.all_bindings(), key=lambda r: (r.capability_id, r.provider_id))
    relationships = sorted(registry.relationships(), key=lambda r: (r.kind, r.src, r.dst))
    return {
        "version": registry.current_version if version is None else version,
        "capabilities": [_capability_dict(r) for r in capabilities],
        "providers": [_provider_dict(r) for r in providers],
        "bindings": [_binding_dict(r) for r in bindings],
        "relationships": [_relationship_dict(r) for r in relationships],
    }


def _content_no_version(content):
    return {k: v for k, v in content.items() if k != "version"}


def snapshot_bytes(registry):
    """Deterministic canonical bytes for `registry`'s current-version
    content + its version number (the citable replay coordinate, PRT/01
    §4)."""
    return json.dumps(_content(registry), sort_keys=True, separators=(",", ":")).encode()


def persist_registry(registry, storage):
    """Write the current registry snapshot to the injected storage port
    under one stable key (PRT/00 C6). Returns the bytes persisted."""
    data = snapshot_bytes(registry)
    storage.write(SNAPSHOT_KEY, data)
    return data


def load_registry(storage):
    """Read the persisted snapshot and rebuild a `Registry` by REPLAYING
    its content as ordinary mutations through `registry.apply()` — the
    single-writer path is preserved end to end. Asserts the replayed
    content (version excluded, see module docstring) matches the persisted
    content byte-for-byte. Returns `(registry, persisted_version)`."""
    content = json.loads(storage.read(SNAPSHOT_KEY))
    registry = Registry()

    for c in content["capabilities"]:
        record = build_capability(
            c["id"], c["description"], c["category"], facets=tuple(c["facets"]),
            lifecycle=c["lifecycle"], aliases=tuple(c["aliases"]),
            verification_expectations=tuple(c["verification_expectations"]),
            constraints=c["constraints"], entry_version=c["entry_version"],
            deprecation_pointer=c["deprecation_pointer"])
        registry.apply({"kind": "add_capability", "record": record})
    for p in content["providers"]:
        record = build_provider(p["id"], p["version"],
                                declared_constraints=p["declared_constraints"],
                                load_policy=p["load_policy"], lifecycle=p["lifecycle"])
        registry.apply({"kind": "add_provider", "record": record})
    for b in content["bindings"]:
        record = build_binding(b["capability_id"], b["provider_id"], terms=b["terms"])
        registry.apply({"kind": "add_binding", "record": record})
    for r in content["relationships"]:
        record = build_relationship(r["kind"], r["src"], r["dst"])
        registry.apply({"kind": "add_relationship", "record": record})

    persisted = _content_no_version(content)
    replayed = _content_no_version(_content(registry))
    assert persisted == replayed, "persistence.replay_content_mismatch"

    return registry, content["version"]


if __name__ == "__main__":
    from .storage_double import StorageDouble

    reg = Registry()
    cap = build_capability("cap.pst.a", "d", "nlp", lifecycle="active",
                           verification_expectations=("x",),
                           aliases=("cap.pst.a.alias",))
    reg.apply({"kind": "add_capability", "record": cap})
    reg.apply({"kind": "add_provider", "record": build_provider("prov.pst.a", "1.0")})
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": "prov.pst.a", "to_state": "active"})
    reg.apply({"kind": "add_binding", "record": build_binding("cap.pst.a", "prov.pst.a")})
    reg.apply({"kind": "add_relationship", "record": build_relationship(
        "dependency", "cap.pst.a", "cap.pst.a")})
    original_version = reg.current_version

    store = StorageDouble()
    persist_registry(reg, store)
    assert store.exists(SNAPSHOT_KEY)

    restored, persisted_version = load_registry(store)
    assert persisted_version == original_version

    # content equality: capabilities/providers/bindings/relationships,
    # including alias resolution, survive the round trip
    assert restored.get_capability("cap.pst.a").id == "cap.pst.a"
    assert restored.resolve("cap.pst.a.alias") == "cap.pst.a"
    assert restored.get_provider("prov.pst.a").lifecycle == "active"
    assert [b.provider_id for b in restored.bindings_for("cap.pst.a")] == ["prov.pst.a"]
    assert len(restored.relationships()) == 1

    # deterministic bytes: same content -> same bytes, twice
    assert snapshot_bytes(reg) == snapshot_bytes(reg)

    # a retired provider's already-removed bindings replay as removed too
    # (retirement happens BEFORE persistence, so current content already
    # reflects it -- nothing "extra" to replay)
    reg2 = Registry()
    cap2 = build_capability("cap.pst.b", "d", "nlp", lifecycle="active",
                            verification_expectations=("x",))
    reg2.apply({"kind": "add_capability", "record": cap2})
    reg2.apply({"kind": "add_provider", "record": build_provider("prov.pst.b", "1.0")})
    reg2.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.pst.b", "to_state": "active"})
    reg2.apply({"kind": "add_binding", "record": build_binding("cap.pst.b", "prov.pst.b")})
    reg2.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.pst.b", "to_state": "deprecated"})
    reg2.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.pst.b", "to_state": "retired"})
    store2 = StorageDouble()
    persist_registry(reg2, store2)
    restored2, v2 = load_registry(store2)
    assert restored2.bindings_for("cap.pst.b") == []
    assert restored2.get_provider("prov.pst.b").lifecycle == "retired"

    print("persistence selftest ok")
