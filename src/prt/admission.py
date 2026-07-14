"""PRT admission pipeline — PRT/02 §3 (nine stages), §4 (only PRT admits),
§6 (admission rules), §7 (publication, persist-before-commit), §9 (failure
philosophy: recoverable vs. permanent vs. the one non-terminal infrastructure
failure).

`admit(registry, declaration, bus, storage)` drives one Declaration through
all nine stages and returns the resulting Candidacy. Stages 1-7 are this
module's own pre-checks (cheapest/most-local first, PRT/02 §3 rationale);
stage 8 (consistency validation) delegates to registry.py's `dry_run` --
running the exact same admit_bundle composite mutation registry.py already
knows how to validate, just without committing yet; stage 9 (publication)
persists the serialized bundle through Storage BEFORE calling registry.apply
(the actual commit) -- a Storage refusal leaves the candidacy exactly
VALIDATED and retryable (PRT/02 §9's one non-terminal failure), never
REJECTED.

A failure at any stage 1-8 halts the pipeline for that candidacy immediately
(no stage after a refusal is ever attempted) and records the failing stage
name on the Candidacy (PRT-A12). All nine stages passing is what stage 9
requires before it persists+commits+mints exactly one version for the
WHOLE declaration (PRT-A6/PRT-A10) -- there is no partial admission.

Determinism (PRT-A9): every stage here reads only (registry, declaration,
config) -- no wall-clock, no randomness -- so the same declaration against
the same prior registry version always produces the same Candidacy outcome
and, on admission, the same resulting registry content.
"""
import json

from . import events
from .candidacy import Candidacy
from .records import content_hash as record_content_hash
from .records import to_dict
from .registry import (
    BindingConsistencyError,
    MetadataIncompleteError,
    PermanentRefusal,
    RecoverableRefusal,
    RegistryRefusal,
    RelationshipEndpointError,
    TombstoneReuseError,
    _constraints_compatible,  # reuse Phase 1's equality-on-overlap predicate
)

MATCHABLE_LIFECYCLES = ("active", "deprecated")


# -- Phase 2's own refusal taxonomy (extends registry.py's, never replaces it) --

class IdentityMalformedError(RecoverableRefusal):
    """Declared provider/capability id is not a well-formed identity (empty,
    non-string) -- PRT/02 §3 stage 1, distinct from the tombstone/hijack
    checks stage 1 also performs."""


class SemanticHijackError(PermanentRefusal):
    """Declaration proposes an id that already exists live in the registry
    with DIFFERENT content -- a meaning change under an existing id, which
    PRT/01 §5 and PRT/02 §9 both forbid permanently (a genuinely new meaning
    always needs a new id)."""


class CapabilityReferenceError(RecoverableRefusal):
    """A binding references a capability id that neither exists in the
    registry nor is proposed within this same declaration (PRT/02 §3 stage 2)."""


class ConstraintIncoherenceError(RecoverableRefusal):
    """A binding's declared terms disagree with the provider's or a
    proposed capability's constraints on a shared key (PRT/02 §3 stage 4,
    Phase 1's equality-on-overlap predicate applied at declaration level)."""


class CompatibilityConflictError(RecoverableRefusal):
    """C10: this declaration would silently shadow or collide with already-
    published content (PRT/02 §3 stage 7)."""


def _existing_or_none(registry, record, is_provider):
    return registry.get_provider(record.id) if is_provider else registry.get_capability(record.id)


def _check_identity_conflict(existing, proposed, subject):
    """Stage 1's tombstone-reuse and semantic-hijack checks, shared between
    the provider and every proposed capability (PRT/02 §5, §9). An identical
    live id with IDENTICAL content is left alone here -- that is an ordinary
    duplicate-id resubmission, caught downstream (stage 8/9) as a Recoverable
    DuplicateIdError, not a permanent identity violation."""
    if existing is None:
        return
    if existing.lifecycle == "retired":
        raise TombstoneReuseError("admission.tombstone_reuse:" + subject)
    if record_content_hash(existing) != record_content_hash(proposed):
        raise SemanticHijackError("admission.semantic_hijack:" + subject)


def _proposed_capability_ids(declaration):
    ids = set()
    for cap in declaration.capabilities:
        ids.add(cap.id)
        ids.update(cap.aliases)
    return ids


def _resolve_capability(registry, declaration, capability_id):
    """Would-be-state capability lookup: registry first (alias-transparent),
    else this declaration's own proposed capabilities. None if neither."""
    canonical = registry.resolve(capability_id)
    if canonical is not None:
        return registry.get_capability(canonical)
    for cap in declaration.capabilities:
        if cap.id == capability_id:
            return cap
    return None


# -- stage 1: identity validation ------------------------------------------

def _stage_identity(registry, declaration):
    provider = declaration.provider
    if not isinstance(provider.id, str) or not provider.id:
        raise IdentityMalformedError("admission.malformed_provider_id:" + repr(provider.id))
    _check_identity_conflict(registry.get_provider(provider.id), provider, provider.id)
    for cap in declaration.capabilities:
        if not isinstance(cap.id, str) or not cap.id:
            raise IdentityMalformedError("admission.malformed_capability_id:" + repr(cap.id))
        _check_identity_conflict(registry.get_capability(cap.id), cap, cap.id)


# -- stage 2: capability validation -----------------------------------------

def _stage_capability(registry, declaration):
    proposed_ids = _proposed_capability_ids(declaration)
    for binding in declaration.bindings:
        if registry.resolve(binding.capability_id) is None and \
                binding.capability_id not in proposed_ids:
            raise CapabilityReferenceError(
                "admission.unknown_capability:" + binding.capability_id)


# -- stage 3: metadata validation --------------------------------------------

def _stage_metadata(registry, declaration):
    for cap in declaration.capabilities:
        if not cap.verification_expectations:  # PRT-I4, re-checked at admission
            raise MetadataIncompleteError(
                "admission.missing_verification_expectation:" + cap.id)


# -- stage 4: constraint validation ------------------------------------------

def _stage_constraint(registry, declaration):
    provider = declaration.provider
    proposed_caps = {cap.id: cap for cap in declaration.capabilities}
    for binding in declaration.bindings:
        if not _constraints_compatible(binding.terms, provider.declared_constraints):
            raise ConstraintIncoherenceError(
                "admission.constraint_incoherent:" + binding.capability_id + ":provider")
        cap = proposed_caps.get(binding.capability_id)
        if cap is not None and not _constraints_compatible(binding.terms, cap.constraints):
            raise ConstraintIncoherenceError(
                "admission.constraint_incoherent:" + binding.capability_id + ":capability")


# -- stage 5: relationship validation ----------------------------------------

def _stage_relationship(registry, declaration):
    proposed_ids = _proposed_capability_ids(declaration)
    for edge in declaration.relationships:
        for endpoint in (edge.src, edge.dst):
            if registry.resolve(endpoint) is None and endpoint not in proposed_ids:
                raise RelationshipEndpointError(
                    "admission.dangling_relationship_endpoint:" + endpoint)


# -- stage 6: binding validation (PRT/01 §7 three conditions, would-be state) --

def _stage_binding(registry, declaration):
    provider = declaration.provider
    for binding in declaration.bindings:
        cap = _resolve_capability(registry, declaration, binding.capability_id)
        if cap is None:
            raise BindingConsistencyError(
                "admission.binding_unknown_capability:" + binding.capability_id)
        if cap.lifecycle not in MATCHABLE_LIFECYCLES:
            raise BindingConsistencyError(
                "admission.binding_target_not_matchable:" + cap.id + ":" + cap.lifecycle)
        if binding.provider_id == provider.id:
            bound_provider = provider
        else:
            bound_provider = registry.get_provider(binding.provider_id)
            if bound_provider is None:
                raise BindingConsistencyError(
                    "admission.binding_unregistered_provider:" + binding.provider_id)
        if not _constraints_compatible(cap.constraints, bound_provider.declared_constraints):
            raise BindingConsistencyError(
                "admission.binding_constraint_conflict:" + cap.id + ":" + bound_provider.id)


# -- stage 7: compatibility validation (C10) ---------------------------------

def _stage_compatibility(registry, declaration):
    provider = declaration.provider
    existing_provider = registry.get_provider(provider.id)
    if existing_provider is not None and existing_provider.lifecycle != "retired" and \
            record_content_hash(existing_provider) == record_content_hash(provider):
        raise CompatibilityConflictError("admission.duplicate_live_provider:" + provider.id)
    proposed_ids = {cap.id for cap in declaration.capabilities}
    for cap in declaration.capabilities:
        for alias in cap.aliases:
            if registry.resolve(alias) is not None or alias in proposed_ids:
                raise CompatibilityConflictError("admission.alias_collision:" + alias)


_STAGES = (
    ("identity", _stage_identity),
    ("capability", _stage_capability),
    ("metadata", _stage_metadata),
    ("constraint", _stage_constraint),
    ("relationship", _stage_relationship),
    ("binding", _stage_binding),
    ("compatibility", _stage_compatibility),
)


# -- stage 9: publication (persist-before-commit) ----------------------------

def _build_mutation(declaration):
    return {
        "kind": "admit_bundle",
        "capabilities": declaration.capabilities,
        "provider": declaration.provider,
        "bindings": declaration.bindings,
        "relationships": declaration.relationships,
    }


def _serialize_mutation(mutation):
    """Deterministic bytes for the would-be bundle -- reuses records.py's
    to_dict per-record, same canonical shape records.canonical() uses, just
    across the whole bundle rather than one record."""
    payload = {
        "capabilities": [to_dict(c) for c in mutation["capabilities"]],
        "provider": to_dict(mutation["provider"]),
        "bindings": [to_dict(b) for b in mutation["bindings"]],
        "relationships": [to_dict(r) for r in mutation["relationships"]],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _storage_key(declaration):
    return "prt/admission/" + declaration.content_hash


def admit(registry, declaration, bus, storage):
    """Drive `declaration` through the full nine-stage pipeline against
    `registry`'s current state. Returns the Candidacy -- REJECTED (stage
    name + refusal recorded), VALIDATED (publication/storage failure,
    retryable), or ADMITTED (minted_version set, plugin.registered
    published)."""
    candidacy = Candidacy(declaration)
    candidacy.begin()

    for stage_name, stage_fn in _STAGES:
        try:
            stage_fn(registry, declaration)
        except RegistryRefusal as exc:
            candidacy.reject(stage_name, exc)
            return candidacy
        candidacy.record_pass(stage_name)

    mutation = _build_mutation(declaration)

    # stage 8: consistency validation -- full PRT/01 §9 sweep against the
    # would-be next version, via the SAME admit_bundle handler apply() uses,
    # just without committing (registry.dry_run, PRT-A6: nothing counts
    # until every stage including this one has passed).
    try:
        registry.dry_run(mutation)
    except RegistryRefusal as exc:
        candidacy.reject("consistency", exc)
        return candidacy
    candidacy.record_pass("consistency")
    candidacy.validate()

    # stage 9: publication -- persist BEFORE commit (PRT/02 §7+§9). A Storage
    # refusal mints no version and leaves the candidacy exactly VALIDATED,
    # retryable as-is (the one non-terminal failure).
    try:
        storage.write(_storage_key(declaration), _serialize_mutation(mutation))
    except ConnectionError:
        candidacy.mark_publication_failed()
        return candidacy

    version = registry.apply(mutation)  # re-validates (harmless, state unchanged) + commits
    candidacy.admit(version)
    events.emit(bus, "plugin.registered", declaration.provider.id,
               {"registry_version": version})
    return candidacy


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .declarations import build_declaration
    from .records import build_binding, build_capability, build_provider
    from .registry import Registry
    from .storage_double import StorageDouble

    # happy path: capability + provider + binding, all in one declaration
    reg = Registry()
    bus = BusDouble()
    store = StorageDouble()
    cap = build_capability("cap.adm.a", "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    prov = build_provider("prov.adm.a", "1.0")
    binding = build_binding(cap.id, prov.id)
    decl = build_declaration(prov, capabilities=(cap,), bindings=(binding,))

    candidacy = admit(reg, decl, bus, store)
    assert candidacy.state == "ADMITTED", candidacy.audit_trail
    assert candidacy.minted_version == reg.current_version == 1
    assert reg.get_capability("cap.adm.a").id == "cap.adm.a"
    assert [b.provider_id for b in reg.bindings_for("cap.adm.a")] == ["prov.adm.a"]
    assert len(bus.messages("plugin.registered")) == 1

    # binding a nonexistent capability id: stage 2 recoverable rejection
    reg2 = Registry()
    bad_decl = build_declaration(
        build_provider("prov.adm.b", "1.0"),
        bindings=(build_binding("cap.missing", "prov.adm.b"),))
    c2 = admit(reg2, bad_decl, bus, store)
    assert c2.state == "REJECTED"
    assert c2.failing_stage == "capability"
    assert reg2.current_version == 0  # nothing published

    # metadata incompleteness: a bare CapabilityRecord slipped past
    # construction-time enforcement (defense in depth, mirrors registry.py's
    # own re-check pattern)
    from types import MappingProxyType

    from .records import CapabilityRecord

    bare_cap = CapabilityRecord(id="cap.bare", description="d", category="nlp",
                                facets=(), lifecycle="active", aliases=(),
                                verification_expectations=(),
                                constraints=MappingProxyType({}), entry_version=1,
                                deprecation_pointer=None)
    reg3 = Registry()
    meta_decl = build_declaration(build_provider("prov.adm.c", "1.0"),
                                  capabilities=(bare_cap,))
    c3 = admit(reg3, meta_decl, bus, store)
    assert c3.state == "REJECTED" and c3.failing_stage == "metadata"

    # tombstone reuse: permanent, provider id already retired in the registry
    reg4 = Registry()
    reg4.apply({"kind": "add_provider", "record": build_provider("prov.adm.d", "1.0")})
    reg4.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.adm.d", "to_state": "active"})
    reg4.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.adm.d", "to_state": "deprecated"})
    reg4.apply({"kind": "lifecycle_transition", "entity": "provider",
               "id": "prov.adm.d", "to_state": "retired"})
    tomb_decl = build_declaration(build_provider("prov.adm.d", "2.0"))
    c4 = admit(reg4, tomb_decl, bus, store)
    assert c4.state == "REJECTED" and c4.failing_stage == "identity"
    assert isinstance(c4.refusal, TombstoneReuseError)

    # semantic hijack: same live provider id, different content -- permanent
    reg5 = Registry()
    reg5.apply({"kind": "add_provider", "record": build_provider("prov.adm.e", "1.0")})
    hijack_decl = build_declaration(build_provider("prov.adm.e", "9.9"))  # different version = different content
    c5 = admit(reg5, hijack_decl, bus, store)
    assert c5.state == "REJECTED"
    assert isinstance(c5.refusal, SemanticHijackError)

    # all-or-nothing: a binding-stage failure means zero registry change even
    # though the capability itself would otherwise have been perfectly valid
    reg6 = Registry()
    cap6 = build_capability("cap.adm.f", "d", "nlp", lifecycle="active",
                            verification_expectations=("x",))
    atomic_decl = build_declaration(
        build_provider("prov.adm.f", "1.0"), capabilities=(cap6,),
        bindings=(build_binding("cap.adm.f", "prov.nonexistent"),))
    c6 = admit(reg6, atomic_decl, bus, store)
    assert c6.state == "REJECTED"
    assert reg6.current_version == 0
    assert reg6.get_capability("cap.adm.f") is None  # capability never landed either

    # publication failure: storage refuses -> VALIDATED, retryable, no version
    reg7 = Registry()
    store7 = StorageDouble()
    store7.fail_writes = True
    decl7 = build_declaration(build_provider("prov.adm.g", "1.0"))
    c7 = admit(reg7, decl7, bus, store7)
    assert c7.state == "VALIDATED"
    assert reg7.current_version == 0
    store7.fail_writes = False
    c7_retried = admit_retry = None
    # retry: re-run admit() with storage healed -- PRT/02 §9's retryable path.
    # This phase re-drives the same declaration through admit() again (a
    # fresh Candidacy) since Candidacy.admit()/mark_publication_failed()
    # gate on VALIDATED state, and admit() always starts a fresh pipeline;
    # what matters architecturally is that the registry took zero damage
    # from the failed attempt and the identical declaration succeeds once
    # storage heals.
    c7b = admit(reg7, decl7, bus, store7)
    assert c7b.state == "ADMITTED"
    assert reg7.current_version == 1

    # determinism (PRT-A9): identical declaration against identical prior
    # version yields identical outcome + identical resulting content
    reg8a, reg8b = Registry(), Registry()
    decl8 = build_declaration(build_provider("prov.adm.h", "1.0"))
    r8a = admit(reg8a, decl8, BusDouble(), StorageDouble())
    r8b = admit(reg8b, decl8, BusDouble(), StorageDouble())
    assert r8a.state == r8b.state == "ADMITTED"
    assert r8a.minted_version == r8b.minted_version
    assert reg8a.get_provider("prov.adm.h") == reg8b.get_provider("prov.adm.h")

    print("admission selftest ok")
