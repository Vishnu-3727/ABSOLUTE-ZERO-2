"""Request Memory — the frozen, ephemeral artifact CM assembles (blueprint
Phase 1; COMPONENTS/context-management.md "Owns"). Exactly one artifact
type system-wide (CM-I8); CM persists nothing durable (CM-I4) — this is
built fresh per execution and never written to disk here.

Shape: objective, constraints, sections (a CLOSED tuple — symbols, files,
dependency_graph, knowledge, experience; content within each section is
opaque to this module by design, since gather/resolve/dedup/budget don't
exist until Phases 2-4) plus assembly/validation/budget metadata blocks,
themselves opaque dicts stamped by whichever future phase owns them.

Frozen means frozen: unlike RSM's RequestRecord (which evolves to a new
version), Request Memory is built once and never mutated again — there is
no evolve(). Field reassignment raises (dataclass frozen=True) and the
container fields are wrapped in MappingProxyType so in-place mutation of
constraints/sections/*_meta raises too.

Canonical serialization mirrors envelope.canonical (json.dumps sort_keys,
compact separators, encode) so byte-identical replay is exactly the same
guarantee kernel/RSM already provide (CM-I2, Law 6): identical inputs to
build() produce identical bytes and an identical content hash.
"""
import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

SECTION_NAMES = ("symbols", "files", "dependency_graph", "knowledge", "experience")


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


@dataclass(frozen=True)
class RequestMemory:
    request_id: str
    memory_id: str
    spec_hash: str
    objective: str
    constraints: MappingProxyType
    sections: MappingProxyType       # section name -> tuple of opaque items
    assembly_meta: MappingProxyType
    validation_meta: MappingProxyType
    budget_meta: MappingProxyType


def build(request_id, spec_hash, objective, constraints=None, sections=None,
          assembly_meta=None, validation_meta=None, budget_meta=None, memory_id=None):
    """Construct a frozen Request Memory (CM-I2: deterministic — identical
    arguments always produce an identical artifact, verified via content_hash)."""
    sections = sections or {}
    bad = set(sections) - set(SECTION_NAMES)
    if bad:
        raise ValueError("request_memory.unknown_section:" + ",".join(sorted(bad)))
    frozen_sections = MappingProxyType(
        {name: tuple(sections.get(name, ())) for name in SECTION_NAMES})
    mid = memory_id or _derive_memory_id(request_id, spec_hash)
    return RequestMemory(
        request_id=request_id,
        memory_id=mid,
        spec_hash=spec_hash,
        objective=objective,
        constraints=_freeze_mapping(constraints),
        sections=frozen_sections,
        assembly_meta=_freeze_mapping(assembly_meta),
        validation_meta=_freeze_mapping(validation_meta),
        budget_meta=_freeze_mapping(budget_meta),
    )


def _derive_memory_id(request_id, spec_hash):
    # ponytail: deterministic id derived from (request_id, spec_hash) rather
    # than an assigned UUID — Law 6 requires identical inputs to reproduce
    # identical output, and a random id would break that. Upgrade path: if
    # a future phase needs collision-proofing across concurrent assemblies
    # of the same spec, widen the digest or add an explicit assembly nonce
    # to the spec itself (visible, not hidden inside this function).
    return hashlib.sha256((request_id + "|" + spec_hash).encode()).hexdigest()[:24]


def to_dict(rm):
    """Plain-dict view for serialization; MappingProxyType/tuple unwrapped."""
    return {
        "request_id": rm.request_id,
        "memory_id": rm.memory_id,
        "spec_hash": rm.spec_hash,
        "objective": rm.objective,
        "constraints": dict(rm.constraints),
        "sections": {name: list(items) for name, items in rm.sections.items()},
        "assembly_meta": dict(rm.assembly_meta),
        "validation_meta": dict(rm.validation_meta),
        "budget_meta": dict(rm.budget_meta),
    }


def canonical(rm):
    """Canonical byte form for byte-identical comparison (CM-I2, Law 6)."""
    return json.dumps(to_dict(rm), sort_keys=True, separators=(",", ":")).encode()


def content_hash(rm):
    return hashlib.sha256(canonical(rm)).hexdigest()


if __name__ == "__main__":
    rm1 = build("r1", "spec-hash-1", "do the thing",
                constraints={"max_files": 5},
                sections={"symbols": ({"id": "s1"},), "files": ({"id": "f1"},)},
                assembly_meta={"assembled_at": 0},
                validation_meta={"ok": True},
                budget_meta={"budget_tokens": 100, "tokens_used": 10})
    rm2 = build("r1", "spec-hash-1", "do the thing",
                constraints={"max_files": 5},
                sections={"symbols": ({"id": "s1"},), "files": ({"id": "f1"},)},
                assembly_meta={"assembled_at": 0},
                validation_meta={"ok": True},
                budget_meta={"budget_tokens": 100, "tokens_used": 10})

    # byte-identical replay (Law 6 / CM-I2)
    assert canonical(rm1) == canonical(rm2)
    assert content_hash(rm1) == content_hash(rm2)
    assert rm1.memory_id == rm2.memory_id

    # closed section tuple always present, even when not supplied
    assert set(rm1.sections) == set(SECTION_NAMES)
    assert rm1.sections["knowledge"] == ()

    # unknown section rejected structurally
    try:
        build("r1", "h", "x", sections={"not_a_section": ()})
        raise SystemExit("unknown section accepted")
    except ValueError:
        pass

    # frozen: field reassignment raises
    try:
        rm1.objective = "different"
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass

    # frozen: container mutation raises (MappingProxyType)
    try:
        rm1.constraints["max_files"] = 999
        raise SystemExit("constraints mutation allowed")
    except TypeError:
        pass
    try:
        rm1.sections["symbols"] = ()
        raise SystemExit("sections mutation allowed")
    except TypeError:
        pass

    # different input -> different hash
    rm3 = build("r1", "spec-hash-2", "do the thing")
    assert content_hash(rm3) != content_hash(rm1)

    print("request_memory selftest ok")
