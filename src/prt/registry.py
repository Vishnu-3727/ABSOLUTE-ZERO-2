"""THE Capability Registry — PRT/01 entire document.

Sole capability source in the OS (PRT-R1); every mutation goes through the
single `apply(mutation)` admission entry point — no public method hands
out a mutable dict, so "no direct dict access from outside" is structural,
not a convention (mirrors rsm/store.py's create()/apply() shape, no bare
dict on the object's public surface).

Phase 1 builds only the PRT/01 §9 consistency rules; Phase 2 (admission.py)
wraps `apply` in the full 9-stage admission pipeline (PRT/02 §3) without
changing this module's contract. Every mutation is validated in full
against a *candidate next state* (cloned working copies) before anything
on `self` changes — refused mutations leave version and content bit-for-
bit untouched (PRT-R10), never partially applied (PRT-A6 spirit).

Phase 2 extensions, both additive, neither redesigns the above:
- `admit_bundle` mutation kind + `_handle_admit_bundle`: one candidacy's
  whole proposed record set (capabilities/provider/bindings/relationships)
  applied to one working state via the existing per-kind handlers, so one
  candidacy = exactly one version (PRT-A6/A10).
- `dry_run()`: validate-without-commit, factored out of `apply()` (now
  `_validate()` + commit) so admission.py can run PRT/02 stage 8's
  consistency check before persist-before-commit (§9) without a second,
  premature commit.
- `AliasTargetRetirementError` + a guard in `_handle_lifecycle_transition`:
  a capability may not retire while a live alias still targets it (PRT/01
  §5's "canonical target must be active-or-deprecated", closed as a KNOWN
  SEAM at PRT/02 — alias cleanup must land in the same or an earlier
  mutation).

Version monotonicity (PRT-R4/PRT-R5) is structural rather than checked:
no mutation ever carries a caller-supplied version number, so there is
nothing to roll back or reuse — `self._version` is `apply`'s own
bookkeeping, exactly like rsm/record.py's `evolve()` owns `version`.

# ponytail: historical snapshots (`at_version`) are kept as one full
# snapshot per mutation (list index n = state after version n), not
# deltas. Simplest correct thing for registries this size; the frozen
# records inside each snapshot are shared objects (they never mutate), so
# the real cost is one shallow dict/tuple copy per mutation, not a deep
# copy. Upgrade path: switch to delta+replay if registry size or mutation
# volume ever makes O(versions) memory a real problem.
"""
from dataclasses import replace
from types import MappingProxyType

from .records import LIFECYCLE_STATES, RELATIONSHIP_KINDS

_ORDER = {state: i for i, state in enumerate(LIFECYCLE_STATES)}


# -- refusal taxonomy (PRT/02 §9 taxonomy, consumed here ahead of Phase 2) --

class RegistryRefusal(Exception):
    """Base for every admission-time refusal apply() can raise."""


class RecoverableRefusal(RegistryRefusal):
    """Resubmission (a corrected mutation) can succeed."""


class PermanentRefusal(RegistryRefusal):
    """No resubmission under the same id ever succeeds (tombstone reuse)."""


class DuplicateIdError(RecoverableRefusal):
    """Two live entries would share an id."""


class TombstoneReuseError(PermanentRefusal):
    """Id was already retired; retired ids are never reused (CP/01 §3, §6)."""


class AliasResolutionError(RecoverableRefusal):
    """Alias would collide, double-target, or itself be used as an entry id."""


class RelationshipEndpointError(RecoverableRefusal):
    """A relationship edge references a capability id that doesn't resolve."""


class BindingConsistencyError(RecoverableRefusal):
    """Binding target/provider/constraints fail PRT/01 §7's three conditions."""


class LifecycleTransitionError(RecoverableRefusal):
    """Backward, sideways, or unknown-state lifecycle transition."""


class AliasTargetRetirementError(RecoverableRefusal):
    """PRT/01 §5: a canonical alias target must stay active-or-deprecated.
    Refuses capability retirement while any live alias still resolves to it
    (KNOWN SEAM closed at PRT/02: alias cleanup must land in the same or an
    earlier mutation, never leave a dangling canonical target)."""


class MetadataIncompleteError(RecoverableRefusal):
    """Verification expectation missing (PRT-I4/PRT-R9), re-checked at apply."""


class NotFoundError(RecoverableRefusal):
    """Mutation targets a capability/provider/binding id that doesn't exist."""


class UnknownMutationError(RecoverableRefusal):
    """Mutation shape/kind apply() does not recognize."""


# -- shared read surface (Registry and its frozen snapshots both use it) ---

class _ReadSurface:
    """Reads never mutate (§ read surface). Both the live `Registry` and a
    frozen `RegistrySnapshot` provide `_capabilities`/`_providers`/
    `_bindings`/`_aliases`/`_relationships`/`_by_category`/`_by_facet`, so
    this logic is written once and shared rather than duplicated between
    live and historical views."""

    def resolve(self, capability_id):
        """id -> canonical id (PRT-R6). Direct id if it's a real entry;
        alias-index lookup otherwise. Returns None if neither resolves."""
        if capability_id in self._aliases:
            return self._aliases[capability_id]
        if capability_id in self._capabilities:
            return capability_id
        return None

    def get_capability(self, capability_id):
        """Alias-transparent read. None if absent under any resolution."""
        canonical = self.resolve(capability_id)
        return None if canonical is None else self._capabilities.get(canonical)

    def get_provider(self, provider_id):
        return self._providers.get(provider_id)

    def list_by_category(self, category):
        """O(1) index lookup, never a scan (C9)."""
        return [self._capabilities[cid] for cid in self._by_category.get(category, ())]

    def list_by_facet(self, facet):
        return [self._capabilities[cid] for cid in self._by_facet.get(facet, ())]

    def bindings_for(self, capability_id):
        """All bindings for a capability id, alias-resolved."""
        canonical = self.resolve(capability_id)
        if canonical is None:
            return []
        provider_ids = self._bindings_by_capability.get(canonical, ())
        return [self._bindings[(canonical, pid)] for pid in provider_ids]

    def relationships(self):
        return list(self._relationships)


def _build_category_index(capabilities):
    index = {}
    for cid, record in capabilities.items():
        index.setdefault(record.category, set()).add(cid)
    return index


def _build_facet_index(capabilities):
    index = {}
    for cid, record in capabilities.items():
        for facet in record.facets:
            index.setdefault(facet, set()).add(cid)
    return index


def _build_binding_indexes(bindings):
    by_cap, by_prov = {}, {}
    for (cap_id, prov_id) in bindings:
        by_cap.setdefault(cap_id, set()).add(prov_id)
        by_prov.setdefault(prov_id, set()).add(cap_id)
    return by_cap, by_prov


class RegistrySnapshot(_ReadSurface):
    """Immutable historical view as of one registry-global version
    (PRT/01 §4: published versions never change retroactively)."""

    def __init__(self, version, capabilities, providers, bindings, aliases, relationships):
        self.version = version
        self._capabilities = MappingProxyType(dict(capabilities))
        self._providers = MappingProxyType(dict(providers))
        self._bindings = MappingProxyType(dict(bindings))
        self._aliases = MappingProxyType(dict(aliases))
        self._relationships = tuple(relationships)
        self._by_category = MappingProxyType(
            {k: frozenset(v) for k, v in _build_category_index(self._capabilities).items()})
        self._by_facet = MappingProxyType(
            {k: frozenset(v) for k, v in _build_facet_index(self._capabilities).items()})
        by_cap, by_prov = _build_binding_indexes(self._bindings)
        self._bindings_by_capability = MappingProxyType({k: frozenset(v) for k, v in by_cap.items()})
        self._bindings_by_provider = MappingProxyType({k: frozenset(v) for k, v in by_prov.items()})


def _check_forward(old_state, new_state, error_cls, subject):
    if new_state not in _ORDER:
        raise error_cls("registry.unknown_lifecycle:" + subject + ":" + str(new_state))
    if _ORDER[new_state] <= _ORDER[old_state]:
        raise error_cls("registry.backward_or_same_transition:" + subject +
                        ":" + old_state + "->" + new_state)


class Registry(_ReadSurface):
    """Live, mutable-through-apply-only registry. PRT-R1: sole writer is
    this class's own apply(); every other subsystem reads only."""

    def __init__(self):
        self._version = 0
        self._capabilities = {}
        self._providers = {}
        self._bindings = {}      # (capability_id, provider_id) -> BindingRecord
        self._aliases = {}       # alias id -> canonical capability id
        self._relationships = []
        self._by_category = {}
        self._by_facet = {}
        self._bindings_by_capability = {}
        self._bindings_by_provider = {}
        self._history = [self._snapshot()]  # index 0 = empty version-0 state

    @property
    def current_version(self):
        return self._version

    def at_version(self, n):
        """Immutable view of registry content as of version n, forever
        (PRT/01 §4). Raises IndexError for a version that never existed —
        including negatives, which list indexing would otherwise silently
        resolve to a recent version and corrupt a replay coordinate."""
        if not isinstance(n, int) or n < 0 or n > self._version:
            raise IndexError("registry.no_such_version:" + str(n))
        return self._history[n]

    def _snapshot(self):
        return RegistrySnapshot(self._version, self._capabilities, self._providers,
                                self._bindings, self._aliases, self._relationships)

    # -- the one mutation entry point (PRT-R2) ------------------------------

    def apply(self, mutation):
        """Admit or refuse `mutation` (a dict with a "kind" key). Validates
        fully against a candidate next state, then commits atomically —
        never partially (PRT-A6 spirit). Returns the new registry-global
        version on success; raises a RegistryRefusal subclass on refusal,
        leaving version and content bit-for-bit untouched (PRT-R10)."""
        working = self._validate(mutation)  # raises a RegistryRefusal; no self.* touched

        # every check passed against the candidate state: commit atomically
        self._capabilities = working.capabilities
        self._providers = working.providers
        self._bindings = working.bindings
        self._aliases = working.aliases
        self._relationships = working.relationships
        self._by_category = _build_category_index(self._capabilities)
        self._by_facet = _build_facet_index(self._capabilities)
        self._bindings_by_capability, self._bindings_by_provider = \
            _build_binding_indexes(self._bindings)
        self._version += 1
        self._history.append(self._snapshot())
        return self._version

    def _validate(self, mutation):
        """Build a candidate next state and run `mutation`'s handler against
        it, WITHOUT committing (shared by apply() and dry_run()). Raises the
        same RegistryRefusal apply() would; returns the validated working
        copy on success. No side effect on `self` either way."""
        if not isinstance(mutation, dict) or "kind" not in mutation:
            raise UnknownMutationError("registry.malformed_mutation")
        kind = mutation["kind"]
        handler = _HANDLERS.get(kind)
        if handler is None:
            raise UnknownMutationError("registry.unknown_mutation_kind:" + str(kind))
        working = _Working(
            capabilities=dict(self._capabilities),
            providers=dict(self._providers),
            bindings=dict(self._bindings),
            aliases=dict(self._aliases),
            relationships=list(self._relationships),
        )
        handler(working, mutation)
        return working

    def dry_run(self, mutation):
        """PRT/02 §3 stage 8 (consistency validation) + stage 9's
        persist-before-commit need a validate-without-committing step that
        apply()'s validate+commit-in-one-call shape doesn't offer on its own.
        Raises on refusal, returns None on success; `self` is untouched
        either way — same guarantee apply() gives on a refusal."""
        self._validate(mutation)


class _Working:
    """Mutable candidate-next-state scratch pad for one apply() call."""

    __slots__ = ("capabilities", "providers", "bindings", "aliases", "relationships")

    def __init__(self, capabilities, providers, bindings, aliases, relationships):
        self.capabilities = capabilities
        self.providers = providers
        self.bindings = bindings
        self.aliases = aliases
        self.relationships = relationships

    def resolve(self, capability_id):
        if capability_id in self.aliases:
            return self.aliases[capability_id]
        if capability_id in self.capabilities:
            return capability_id
        return None


# -- per-mutation-kind handlers ----------------------------------------------

def _handle_add_capability(working, mutation):
    record = mutation["record"]
    if record.id in working.capabilities:
        existing = working.capabilities[record.id]
        if existing.lifecycle == "retired":
            raise TombstoneReuseError("registry.tombstone_reuse:" + record.id)
        raise DuplicateIdError("registry.duplicate_id:" + record.id)
    if record.id in working.aliases:
        raise AliasResolutionError("registry.id_already_an_alias:" + record.id)
    if not record.verification_expectations:  # PRT-I4/PRT-R9, re-checked at apply
        raise MetadataIncompleteError("registry.missing_verification_expectation:" + record.id)
    for alias in record.aliases:
        if alias in working.capabilities:
            raise AliasResolutionError("registry.alias_collides_with_capability:" + alias)
        if alias in working.aliases:
            raise AliasResolutionError("registry.alias_already_targeted:" + alias)

    working.capabilities[record.id] = record
    for alias in record.aliases:
        working.aliases[alias] = record.id


def _handle_update_capability(working, mutation):
    record = mutation["record"]
    existing = working.capabilities.get(record.id)
    if existing is None:
        raise NotFoundError("registry.capability_not_found:" + record.id)
    if existing.lifecycle == "retired":
        raise TombstoneReuseError("registry.retired_capability_immutable:" + record.id)
    if record.lifecycle != existing.lifecycle:
        raise LifecycleTransitionError(
            "registry.use_lifecycle_transition_mutation:" + record.id)
    # ponytail: ordinary content update keeps identity-adjacent fields (category,
    # aliases) fixed — changing them is a rename/recategorization, not a
    # compatible clarification (CP/01 §6 evolution boundary); those go through
    # a new capability id instead, same as CP/01 already requires.
    if record.category != existing.category:
        raise AliasResolutionError("registry.category_change_needs_new_id:" + record.id)
    if record.aliases != existing.aliases:
        raise AliasResolutionError("registry.alias_change_not_supported_via_update:" + record.id)
    if not record.verification_expectations:
        raise MetadataIncompleteError("registry.missing_verification_expectation:" + record.id)
    working.capabilities[record.id] = record


def _handle_add_provider(working, mutation):
    record = mutation["record"]
    if record.id in working.providers:
        existing = working.providers[record.id]
        if existing.lifecycle == "retired":
            raise TombstoneReuseError("registry.tombstone_reuse:" + record.id)
        raise DuplicateIdError("registry.duplicate_id:" + record.id)
    working.providers[record.id] = record


def _constraints_compatible(capability_constraints, provider_constraints):
    """Simplest correct predicate: shared keys must agree; no key can
    silently disagree. Never rejects a key present on only one side.
    # ponytail: equality-on-overlap, not a general constraint solver.
    # Upgrade path: replace with a real compatibility predicate (ranges,
    # semver, platform sets) if/when a phase needs richer constraints."""
    for key, value in capability_constraints.items():
        if key in provider_constraints and provider_constraints[key] != value:
            return False
    return True


def _handle_add_binding(working, mutation):
    record = mutation["record"]
    canonical = working.resolve(record.capability_id)
    if canonical is None:
        raise BindingConsistencyError("registry.binding_unknown_capability:" + record.capability_id)
    capability = working.capabilities[canonical]
    if capability.lifecycle not in ("active", "deprecated"):
        raise BindingConsistencyError(
            "registry.binding_target_not_matchable:" + canonical + ":" + capability.lifecycle)
    if record.provider_id not in working.providers:
        raise BindingConsistencyError("registry.binding_unregistered_provider:" + record.provider_id)
    provider = working.providers[record.provider_id]
    if not _constraints_compatible(capability.constraints, provider.declared_constraints):
        raise BindingConsistencyError(
            "registry.binding_constraint_conflict:" + canonical + ":" + record.provider_id)

    working.bindings[(canonical, record.provider_id)] = replace(record, capability_id=canonical)


def _handle_remove_binding(working, mutation):
    canonical = working.resolve(mutation["capability_id"])
    key = (canonical, mutation["provider_id"])
    if canonical is None or key not in working.bindings:
        raise NotFoundError("registry.binding_not_found:" +
                            str(mutation["capability_id"]) + "," + str(mutation["provider_id"]))
    del working.bindings[key]


def _handle_add_relationship(working, mutation):
    record = mutation["record"]
    if record.kind not in RELATIONSHIP_KINDS:  # PRT-R7, defense in depth past records.py
        raise UnknownMutationError("registry.unknown_relationship_kind:" + str(record.kind))
    if working.resolve(record.src) is None:
        raise RelationshipEndpointError("registry.dangling_relationship_endpoint:" + record.src)
    if working.resolve(record.dst) is None:
        raise RelationshipEndpointError("registry.dangling_relationship_endpoint:" + record.dst)
    working.relationships.append(record)


def _handle_lifecycle_transition(working, mutation):
    entity = mutation["entity"]
    entity_id = mutation["id"]
    to_state = mutation["to_state"]
    if entity == "capability":
        existing = working.capabilities.get(entity_id)
        if existing is None:
            raise NotFoundError("registry.capability_not_found:" + entity_id)
        _check_forward(existing.lifecycle, to_state, LifecycleTransitionError, entity_id)
        if to_state == "retired" and any(
                target == entity_id for target in working.aliases.values()):
            # PRT/01 §5: canonical target must stay active-or-deprecated;
            # alias cleanup (repoint or drop) must land in the same or an
            # earlier mutation, never after this one (KNOWN SEAM, PRT/02).
            raise AliasTargetRetirementError(
                "registry.alias_still_targets_retiring_capability:" + entity_id)
        working.capabilities[entity_id] = replace(existing, lifecycle=to_state)
    elif entity == "provider":
        existing = working.providers.get(entity_id)
        if existing is None:
            raise NotFoundError("registry.provider_not_found:" + entity_id)
        _check_forward(existing.lifecycle, to_state, LifecycleTransitionError, entity_id)
        working.providers[entity_id] = replace(existing, lifecycle=to_state)
        if to_state == "retired":
            # PRT-A11: retiring a provider removes its bindings in the SAME
            # mutation, atomically — never a separate, later cleanup step.
            for cap_id in list(working.bindings):
                if cap_id[1] == entity_id:
                    del working.bindings[cap_id]
    else:
        raise UnknownMutationError("registry.unknown_entity:" + str(entity))


def _handle_admit_bundle(working, mutation):
    """PRT/02 §3 stage 9 / PRT-A6/PRT-A10: one candidacy's ENTIRE proposed
    bundle (capabilities + provider + bindings + relationships) applied to
    ONE working state, so success mints exactly one version and failure
    anywhere leaves zero trace. Pure composition of the existing per-kind
    handlers, in the order a declaration's own parts depend on each other
    (capabilities and provider before bindings that reference them,
    relationships last) — no new consistency logic, extension only."""
    for record in mutation.get("capabilities", ()):
        _handle_add_capability(working, {"kind": "add_capability", "record": record})
    _handle_add_provider(working, {"kind": "add_provider", "record": mutation["provider"]})
    for record in mutation.get("bindings", ()):
        _handle_add_binding(working, {"kind": "add_binding", "record": record})
    for record in mutation.get("relationships", ()):
        _handle_add_relationship(working, {"kind": "add_relationship", "record": record})


_HANDLERS = {
    "add_capability": _handle_add_capability,
    "update_capability": _handle_update_capability,
    "add_provider": _handle_add_provider,
    "add_binding": _handle_add_binding,
    "remove_binding": _handle_remove_binding,
    "add_relationship": _handle_add_relationship,
    "lifecycle_transition": _handle_lifecycle_transition,
    "admit_bundle": _handle_admit_bundle,
}


if __name__ == "__main__":
    from .records import build_capability, build_provider, build_binding, build_relationship

    reg = Registry()
    assert reg.current_version == 0

    cap = build_capability("cap.a", "does a", "nlp", facets=("text",),
                           verification_expectations=("output non-empty",))
    v1 = reg.apply({"kind": "add_capability", "record": cap})
    assert v1 == 1 and reg.current_version == 1
    assert reg.get_capability("cap.a").id == "cap.a"

    # version 0 snapshot is still the empty registry, forever (PRT-R4)
    assert reg.at_version(0).get_capability("cap.a") is None
    assert reg.at_version(1).get_capability("cap.a").id == "cap.a"

    # duplicate id refused, version/content untouched (PRT-R10)
    try:
        reg.apply({"kind": "add_capability", "record": cap})
        raise SystemExit("duplicate capability id accepted")
    except DuplicateIdError:
        pass
    assert reg.current_version == 1

    prov = build_provider("prov.x", "1.0.0")
    v2 = reg.apply({"kind": "add_provider", "record": prov})
    assert v2 == 2

    # binding to a proposed (not yet active) capability refused
    binding = build_binding("cap.a", "prov.x")
    try:
        reg.apply({"kind": "add_binding", "record": binding})
        raise SystemExit("binding to proposed capability accepted")
    except BindingConsistencyError:
        pass
    assert reg.current_version == 2  # untouched

    v3 = reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                    "id": "cap.a", "to_state": "active"})
    assert v3 == 3

    v4 = reg.apply({"kind": "add_binding", "record": binding})
    assert v4 == 4
    assert [b.provider_id for b in reg.bindings_for("cap.a")] == ["prov.x"]

    # backward lifecycle transition refused, both directions
    try:
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.a", "to_state": "proposed"})
        raise SystemExit("backward transition accepted")
    except LifecycleTransitionError:
        pass

    # relationship: dangling endpoint refused
    edge_ok = build_relationship("dependency", "cap.a", "cap.a")
    v5 = reg.apply({"kind": "add_relationship", "record": edge_ok})
    assert v5 == 5
    edge_bad = build_relationship("dependency", "cap.a", "cap.missing")
    try:
        reg.apply({"kind": "add_relationship", "record": edge_bad})
        raise SystemExit("dangling relationship accepted")
    except RelationshipEndpointError:
        pass

    # retiring a provider removes its bindings in the SAME mutation (PRT-A11)
    assert reg.bindings_for("cap.a") != []
    v6 = reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                    "id": "prov.x", "to_state": "active"})
    v7 = reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                    "id": "prov.x", "to_state": "deprecated"})
    v8 = reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                    "id": "prov.x", "to_state": "retired"})
    assert reg.bindings_for("cap.a") == []
    assert reg.at_version(v8 - 1).bindings_for("cap.a") != []  # historical version unaffected

    # tombstone reuse: permanent, distinct type from recoverable duplicate
    try:
        reg.apply({"kind": "add_provider", "record": prov})
        raise SystemExit("tombstone id reuse accepted")
    except TombstoneReuseError:
        pass

    # alias resolution: register a capability, then one that aliases an old id
    old = build_capability("cap.old", "old name", "nlp",
                           verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": old})
    reg.apply({"kind": "lifecycle_transition", "entity": "capability",
              "id": "cap.old", "to_state": "active"})
    renamed = build_capability("cap.new", "new name", "nlp", aliases=("cap.old.alias",),
                               verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": renamed})
    assert reg.resolve("cap.old.alias") == "cap.new"
    assert reg.get_capability("cap.old.alias").id == "cap.new"

    # KNOWN SEAM (PRT/02): retiring a capability with a live alias targeting
    # it is refused -- alias cleanup must land in the same/earlier mutation
    reg.apply({"kind": "lifecycle_transition", "entity": "capability",
              "id": "cap.new", "to_state": "active"})
    try:
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.new", "to_state": "deprecated"})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.new", "to_state": "retired"})
        raise SystemExit("capability retired despite live alias target")
    except AliasTargetRetirementError:
        pass

    # dry_run: validates without committing (PRT/02 stage 8 / persist-before-commit)
    reg9 = Registry()
    good_cap = build_capability("cap.dry", "d", "nlp", verification_expectations=("x",))
    v_before = reg9.current_version
    reg9.dry_run({"kind": "add_capability", "record": good_cap})
    assert reg9.current_version == v_before  # no side effect on success
    assert reg9.get_capability("cap.dry") is None
    try:
        reg9.dry_run({"kind": "lifecycle_transition", "entity": "capability",
                      "id": "cap.missing", "to_state": "active"})
        raise SystemExit("dry_run of bad mutation accepted")
    except NotFoundError:
        pass
    assert reg9.current_version == v_before  # still no side effect on refusal

    # admit_bundle: one atomic composite mutation, one version (PRT-A6/A10)
    bundle_cap = build_capability("cap.bundle", "d", "nlp", lifecycle="active",
                                  verification_expectations=("x",))
    bundle_prov = build_provider("prov.bundle", "1.0")
    bundle_binding = build_binding("cap.bundle", "prov.bundle")
    mutation = {"kind": "admit_bundle", "capabilities": (bundle_cap,),
                "provider": bundle_prov, "bindings": (bundle_binding,),
                "relationships": ()}
    v_bundle = reg9.apply(mutation)
    assert reg9.get_capability("cap.bundle").id == "cap.bundle"
    assert reg9.get_provider("prov.bundle").id == "prov.bundle"
    assert [b.provider_id for b in reg9.bindings_for("cap.bundle")] == ["prov.bundle"]
    assert v_bundle == v_before + 1  # exactly one version for the whole bundle

    # admit_bundle failure anywhere -> zero registry change (all-or-nothing)
    bad_binding = build_binding("cap.bundle", "prov.nonexistent")
    v_before_bad = reg9.current_version
    try:
        reg9.apply({"kind": "admit_bundle", "capabilities": (),
                   "provider": build_provider("prov.bundle2", "1.0"),
                   "bindings": (bad_binding,), "relationships": ()})
        raise SystemExit("partially-invalid bundle accepted")
    except BindingConsistencyError:
        pass
    assert reg9.current_version == v_before_bad
    assert reg9.get_provider("prov.bundle2") is None  # provider add rolled back too

    print("registry selftest ok")
