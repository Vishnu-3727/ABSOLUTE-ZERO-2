"""PRT Declaration bundle — PRT/02 §1: discovery's sole output and
admission's sole input. One Declaration = one candidacy's complete claim
about one provider: a proposed ProviderRecord, proposed CapabilityRecords
(may be empty — a provider binding to capabilities that already exist),
proposed BindingRecords, proposed RelationshipEdges, and the source class
that produced it.

Frozen the same way records.py freezes its four record types:
dataclass(frozen=True) + tuples for the proposed-record collections. No
MappingProxyType field is needed here — every mutable-looking collection
is a tuple of already-frozen records (records.py owns their freezing).

Source class (PRT/02 §1 table) is annotation only: built-in/local/
enterprise/remote never changes what admission checks (PRT-A2) — it is
data admission may read for provenance/logging, never a scrutiny dial.

content_hash is deterministic over the bundle's canonical form, reusing
records.py's to_dict/canonical machinery rather than inventing a second
serialization scheme (PRT-A9: same declaration -> same hash, always).
"""
from dataclasses import dataclass
import hashlib
import json

from .records import ProviderRecord, to_dict

SOURCE_CLASSES = ("built-in", "local", "enterprise", "remote")


def _check_source_class(source_class):
    if source_class not in SOURCE_CLASSES:
        raise ValueError("declarations.unknown_source_class:" + str(source_class))


@dataclass(frozen=True)
class Declaration:
    provider: ProviderRecord
    capabilities: tuple
    bindings: tuple
    relationships: tuple
    source_class: str
    content_hash: str


def _canonical_bundle(provider, capabilities, bindings, relationships, source_class):
    payload = {
        "provider": to_dict(provider),
        "capabilities": [to_dict(c) for c in capabilities],
        "bindings": [to_dict(b) for b in bindings],
        "relationships": [to_dict(r) for r in relationships],
        "source_class": source_class,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def build_declaration(provider, capabilities=(), bindings=(), relationships=(),
                       source_class="local"):
    """Construct one immutable Declaration. Refuses an unknown source class
    loudly (mirrors records.py's construction-time refusal shape); everything
    else is accepted as proposed, unvalidated content — admission (§3), not
    discovery, is where proposed content is judged (PRT-A1)."""
    _check_source_class(source_class)
    capabilities = tuple(capabilities)
    bindings = tuple(bindings)
    relationships = tuple(relationships)
    digest = hashlib.sha256(_canonical_bundle(
        provider, capabilities, bindings, relationships, source_class)).hexdigest()
    return Declaration(
        provider=provider, capabilities=capabilities, bindings=bindings,
        relationships=relationships, source_class=source_class, content_hash=digest,
    )


if __name__ == "__main__":
    from .records import build_binding, build_capability, build_provider

    prov = build_provider("prov.disc.a", "1.0.0")
    cap = build_capability("cap.disc.a", "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    binding = build_binding(cap.id, prov.id)

    decl = build_declaration(prov, capabilities=(cap,), bindings=(binding,),
                             source_class="local")
    assert decl.source_class == "local"
    assert decl.provider is prov
    assert decl.capabilities == (cap,)
    assert len(decl.content_hash) == 64

    # deterministic: identical bundle -> identical hash, every time (PRT-A9)
    decl2 = build_declaration(prov, capabilities=(cap,), bindings=(binding,),
                              source_class="local")
    assert decl.content_hash == decl2.content_hash

    # trust class is data only -- a different source class is a different
    # bundle (different hash) but this is provenance, not a scrutiny knob
    decl3 = build_declaration(prov, capabilities=(cap,), bindings=(binding,),
                              source_class="remote")
    assert decl3.content_hash != decl.content_hash

    # frozen: field reassignment refused
    try:
        decl.source_class = "enterprise"
        raise SystemExit("Declaration field reassignment allowed")
    except AttributeError:
        pass

    # unknown source class refused loudly at construction
    try:
        build_declaration(prov, source_class="drive-by")
        raise SystemExit("unknown source class accepted")
    except ValueError:
        pass

    # empty capabilities/bindings/relationships is legal (provider binding to
    # already-existing capabilities, PRT/02 §1)
    bare = build_declaration(build_provider("prov.bare", "1.0"))
    assert bare.capabilities == () and bare.bindings == () and bare.relationships == ()

    print("declarations selftest ok")
