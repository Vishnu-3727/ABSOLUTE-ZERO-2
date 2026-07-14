"""THE Descriptor Space — RO/00 §10 + RO/01 (capability model) + RO/03 §3
(descriptor rows). RO's own versioned space, disjoint from PRT's registry
(RO-I9) — zero imports from src/prt anywhere in this package.

Mirrors prt/registry.py's discipline exactly: a single `apply(mutation)`
admission entry point, clone-validate-commit (nothing on `self` changes
until every check on a candidate working state has passed), one monotonic
global version per successful mutation, immutable per-version snapshots via
`at_version(n)`, and a two-tier refusal taxonomy (RecoverableRefusal vs.
PermanentRefusal — id/tombstone reuse is the only permanent case, exactly
as PRT-R10/tombstone discipline).

Held state: capabilities (id -> CapabilityRecord), relationships (a list of
RelationshipRecord), descriptor_rows (provider_id -> DescriptorRow).
Capability ids are permanent (RO-C3): once retired, an id is a tombstone,
never reused. Descriptor rows carry no such permanence — RO/01 §8 says a
disappearing provider's rows are simply removed, and a returning provider
re-adds under the same id with zero architectural weight, so re-adding
after removal is ordinary, not a tombstone violation.

# ponytail: history is one full snapshot per mutation (RegistrySnapshot
# pattern from prt/registry.py) — same simplest-correct tradeoff as there;
# same upgrade path (delta+replay) if space size ever makes this a real
# memory problem.
"""
from dataclasses import replace
from types import MappingProxyType

from .records import (
    CATEGORIES, COMPLEXITY_RUNGS, LIFECYCLE_STATES, RELATIONSHIP_KINDS,
)

_ORDER = {state: i for i, state in enumerate(LIFECYCLE_STATES)}


# -- refusal taxonomy (mirrors prt/registry.py) --

class DescriptorSpaceRefusal(Exception):
    """Base for every admission-time refusal apply() can raise."""


class RecoverableRefusal(DescriptorSpaceRefusal):
    """Resubmission (a corrected mutation) can succeed."""


class PermanentRefusal(DescriptorSpaceRefusal):
    """No resubmission under the same id ever succeeds (tombstone reuse)."""


class DuplicateIdError(RecoverableRefusal):
    """Two live entries would share an id."""


class TombstoneReuseError(PermanentRefusal):
    """Capability id was already retired; retired ids are never reused (RO-C3)."""


class LifecycleTransitionError(RecoverableRefusal):
    """Backward, sideways, or unknown-state lifecycle transition."""


class CategoryFrozenError(RecoverableRefusal):
    """RO-C3: a meaning change (category) produces a new id, never an
    in-place edit; update_capability may change content, never category."""


class RelationshipEndpointError(RecoverableRefusal):
    """A relationship edge references a capability id that doesn't resolve."""


class DependencyCycleError(RecoverableRefusal):
    """RO-C10: dependency relations are acyclic; this edge would close a cycle."""


class DescriptorClaimError(RecoverableRefusal):
    """A descriptor row claims a capability id that doesn't exist, or isn't
    active-or-deprecated (RO/03 §3 cross-reference)."""


class ClaimedCapabilityRetirementError(RecoverableRefusal):
    """A capability cannot retire while descriptor rows still claim it —
    otherwise the space would hold rows claiming a retired capability, a
    state its own admission rule (RO/03 §3: claims resolve to
    active-or-deprecated only) refuses to create. Remove or update the
    claiming rows first. Mirror image of PRT's binding-removal-at-retirement
    discipline (PRT-A11)."""


class NotFoundError(RecoverableRefusal):
    """Mutation targets a capability/relationship/descriptor row that doesn't exist."""


class UnknownMutationError(RecoverableRefusal):
    """Mutation shape/kind apply() does not recognize."""


# -- shared read surface (DescriptorSpace and its frozen snapshots both use it) --

class _ReadSurface:
    def get_capability(self, capability_id):
        return self._capabilities.get(capability_id)

    def all_capabilities(self):
        return list(self._capabilities.values())

    def relationships(self):
        return list(self._relationships)

    def get_descriptor_row(self, provider_id):
        return self._descriptor_rows.get(provider_id)

    def all_descriptor_rows(self):
        return list(self._descriptor_rows.values())


class DescriptorSpaceSnapshot(_ReadSurface):
    """Immutable historical view as of one global version. Published
    versions never change retroactively (mirrors PRT/01 §4)."""

    def __init__(self, version, capabilities, relationships, descriptor_rows):
        self.version = version
        self._capabilities = MappingProxyType(dict(capabilities))
        self._relationships = tuple(relationships)
        self._descriptor_rows = MappingProxyType(dict(descriptor_rows))


def _check_forward(old_state, new_state, subject):
    if new_state not in _ORDER:
        raise LifecycleTransitionError("descriptor_space.unknown_lifecycle:" +
                                        subject + ":" + str(new_state))
    if _ORDER[new_state] <= _ORDER[old_state]:
        raise LifecycleTransitionError(
            "descriptor_space.backward_or_same_transition:" + subject +
            ":" + old_state + "->" + new_state)


def _has_cycle(dependency_edges):
    """dependency_edges: iterable of (src, dst). DFS cycle detection over
    the directed graph they form. O(V+E); fine at this space's scale."""
    graph = {}
    for src, dst in dependency_edges:
        graph.setdefault(src, []).append(dst)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}

    def visit(node):
        color[node] = GRAY
        for nxt in graph.get(node, ()):
            state = color.get(nxt, WHITE)
            if state == GRAY:
                return True
            if state == WHITE and visit(nxt):
                return True
        color[node] = BLACK
        return False

    for node in list(graph):
        if color.get(node, WHITE) == WHITE:
            if visit(node):
                return True
    return False


class DescriptorSpace(_ReadSurface):
    """Live, mutable-through-apply-only space. Sole writer is this class's
    own apply() (mirrors PRT-R1/R2 discipline for RO's own authority)."""

    def __init__(self):
        self._version = 0
        self._capabilities = {}
        self._relationships = []
        self._descriptor_rows = {}
        self._history = [self._snapshot()]

    @property
    def current_version(self):
        return self._version

    def at_version(self, n):
        """Immutable view as of version n, forever. Raises IndexError for a
        version that never existed — including negatives, which list
        indexing would otherwise silently alias to a recent version and
        corrupt a replay coordinate (the PRT at_version lesson)."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > self._version:
            raise IndexError("descriptor_space.no_such_version:" + str(n))
        return self._history[n]

    def _snapshot(self):
        return DescriptorSpaceSnapshot(
            self._version, self._capabilities, self._relationships, self._descriptor_rows)

    # -- the one mutation entry point --

    def apply(self, mutation):
        """Admit or refuse `mutation` (a dict with a "kind" key). Validates
        fully against a candidate next state, then commits atomically.
        Returns the new global version on success; raises a
        DescriptorSpaceRefusal subclass on refusal, leaving version and
        content bit-for-bit untouched."""
        working = self._validate(mutation)

        self._capabilities = working.capabilities
        self._relationships = working.relationships
        self._descriptor_rows = working.descriptor_rows
        self._version += 1
        self._history.append(self._snapshot())
        return self._version

    def _validate(self, mutation):
        if not isinstance(mutation, dict) or "kind" not in mutation:
            raise UnknownMutationError("descriptor_space.malformed_mutation")
        kind = mutation["kind"]
        handler = _HANDLERS.get(kind)
        if handler is None:
            raise UnknownMutationError("descriptor_space.unknown_mutation_kind:" + str(kind))
        working = _Working(
            capabilities=dict(self._capabilities),
            relationships=list(self._relationships),
            descriptor_rows=dict(self._descriptor_rows),
        )
        handler(working, mutation)
        return working

    def dry_run(self, mutation):
        """Validate-without-commit. Raises on refusal, returns None on
        success; `self` is untouched either way."""
        self._validate(mutation)


class _Working:
    __slots__ = ("capabilities", "relationships", "descriptor_rows")

    def __init__(self, capabilities, relationships, descriptor_rows):
        self.capabilities = capabilities
        self.relationships = relationships
        self.descriptor_rows = descriptor_rows


# -- per-mutation-kind handlers --

def _handle_add_capability(working, mutation):
    record = mutation["record"]
    existing = working.capabilities.get(record.id)
    if existing is not None:
        if existing.lifecycle == "retired":
            raise TombstoneReuseError("descriptor_space.tombstone_reuse:" + record.id)
        raise DuplicateIdError("descriptor_space.duplicate_id:" + record.id)
    working.capabilities[record.id] = record


def _handle_update_capability(working, mutation):
    """Content-only update; id is permanent, category is frozen (a meaning
    change is a new id, RO-C3), lifecycle changes go through
    transition_capability_lifecycle only."""
    record = mutation["record"]
    existing = working.capabilities.get(record.id)
    if existing is None:
        raise NotFoundError("descriptor_space.capability_not_found:" + record.id)
    if existing.lifecycle == "retired":
        raise TombstoneReuseError("descriptor_space.retired_capability_immutable:" + record.id)
    if record.category != existing.category:
        raise CategoryFrozenError("descriptor_space.category_change_needs_new_id:" + record.id)
    if record.lifecycle != existing.lifecycle:
        raise LifecycleTransitionError(
            "descriptor_space.use_lifecycle_transition_mutation:" + record.id)
    working.capabilities[record.id] = record


def _handle_transition_capability_lifecycle(working, mutation):
    entity_id = mutation["id"]
    to_state = mutation["to_state"]
    existing = working.capabilities.get(entity_id)
    if existing is None:
        raise NotFoundError("descriptor_space.capability_not_found:" + entity_id)
    _check_forward(existing.lifecycle, to_state, entity_id)
    if to_state == "retired":
        claimants = sorted(
            provider_id for provider_id, row in working.descriptor_rows.items()
            if entity_id in row.capabilities_claimed)
        if claimants:
            raise ClaimedCapabilityRetirementError(
                "descriptor_space.retirement_while_claimed:" + entity_id +
                ":claimants=" + ",".join(claimants))
    working.capabilities[entity_id] = replace(existing, lifecycle=to_state)


def _handle_add_relationship(working, mutation):
    record = mutation["record"]
    if record.kind not in RELATIONSHIP_KINDS:  # RO-C8, defense in depth past records.py
        raise UnknownMutationError("descriptor_space.unknown_relationship_kind:" + str(record.kind))
    if record.src not in working.capabilities:
        raise RelationshipEndpointError("descriptor_space.dangling_relationship_endpoint:" + record.src)
    if record.dst not in working.capabilities:
        raise RelationshipEndpointError("descriptor_space.dangling_relationship_endpoint:" + record.dst)
    triple = (record.kind, record.src, record.dst)
    if any((r.kind, r.src, r.dst) == triple for r in working.relationships):
        raise DuplicateIdError("descriptor_space.duplicate_relationship:" + str(triple))

    if record.kind == "dependency":  # RO-C10: dependency relations are acyclic
        edges = [(r.src, r.dst) for r in working.relationships if r.kind == "dependency"]
        edges.append((record.src, record.dst))
        if _has_cycle(edges):
            raise DependencyCycleError(
                "descriptor_space.dependency_cycle:" + record.src + "->" + record.dst)

    working.relationships.append(record)


def _handle_remove_relationship(working, mutation):
    triple = (mutation["relationship_kind"], mutation["src"], mutation["dst"])
    for i, r in enumerate(working.relationships):
        if (r.kind, r.src, r.dst) == triple:
            del working.relationships[i]
            return
    raise NotFoundError("descriptor_space.relationship_not_found:" + str(triple))


def _validate_claims(working, descriptor_row):
    for cap_id in descriptor_row.capabilities_claimed:
        capability = working.capabilities.get(cap_id)
        if capability is None:
            raise DescriptorClaimError("descriptor_space.claim_unknown_capability:" + cap_id)
        if capability.lifecycle not in ("active", "deprecated"):
            raise DescriptorClaimError(
                "descriptor_space.claim_capability_not_matchable:" + cap_id +
                ":" + capability.lifecycle)
        # rungs are already restricted to COMPLEXITY_RUNGS at record
        # construction (records.build_descriptor_row); re-asserted here as
        # defense in depth, mirroring registry.py's relationship-kind check.
        for rung in descriptor_row.capabilities_claimed[cap_id]:
            if rung not in COMPLEXITY_RUNGS:
                raise DescriptorClaimError("descriptor_space.claim_unknown_rung:" + str(rung))


def _handle_add_descriptor_row(working, mutation):
    record = mutation["record"]
    if record.provider_id in working.descriptor_rows:
        raise DuplicateIdError("descriptor_space.duplicate_id:" + record.provider_id)
    _validate_claims(working, record)
    working.descriptor_rows[record.provider_id] = record


def _handle_update_descriptor_row(working, mutation):
    record = mutation["record"]
    if record.provider_id not in working.descriptor_rows:
        raise NotFoundError("descriptor_space.descriptor_row_not_found:" + record.provider_id)
    _validate_claims(working, record)
    working.descriptor_rows[record.provider_id] = record


def _handle_remove_descriptor_row(working, mutation):
    provider_id = mutation["provider_id"]
    if provider_id not in working.descriptor_rows:
        raise NotFoundError("descriptor_space.descriptor_row_not_found:" + provider_id)
    del working.descriptor_rows[provider_id]


_HANDLERS = {
    "add_capability": _handle_add_capability,
    "update_capability": _handle_update_capability,
    "transition_capability_lifecycle": _handle_transition_capability_lifecycle,
    "add_relationship": _handle_add_relationship,
    "remove_relationship": _handle_remove_relationship,
    "add_descriptor_row": _handle_add_descriptor_row,
    "update_descriptor_row": _handle_update_descriptor_row,
    "remove_descriptor_row": _handle_remove_descriptor_row,
}


if __name__ == "__main__":
    from .records import build_capability, build_descriptor_row, build_relationship

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "low",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }

    space = DescriptorSpace()
    assert space.current_version == 0

    cap_a = build_capability("ro.cap.a", "INTERPRETIVE", _CHARS)
    v1 = space.apply({"kind": "add_capability", "record": cap_a})
    assert v1 == 1 and space.current_version == 1
    assert space.get_capability("ro.cap.a").id == "ro.cap.a"

    # version 0 snapshot is still empty, forever
    assert space.at_version(0).get_capability("ro.cap.a") is None
    assert space.at_version(1).get_capability("ro.cap.a").id == "ro.cap.a"

    # duplicate id refused, version/content untouched
    try:
        space.apply({"kind": "add_capability", "record": cap_a})
        raise SystemExit("duplicate capability id accepted")
    except DuplicateIdError:
        pass
    assert space.current_version == 1

    # negative / never-existed version refused
    try:
        space.at_version(-1)
        raise SystemExit("negative version accepted")
    except IndexError:
        pass
    try:
        space.at_version(99)
        raise SystemExit("never-existed version accepted")
    except IndexError:
        pass

    v2 = space.apply({"kind": "transition_capability_lifecycle",
                       "id": "ro.cap.a", "to_state": "active"})
    assert v2 == 2

    # backward transition refused
    try:
        space.apply({"kind": "transition_capability_lifecycle",
                      "id": "ro.cap.a", "to_state": "proposed"})
        raise SystemExit("backward transition accepted")
    except LifecycleTransitionError:
        pass

    # forward jump legal (proposed already past; active -> retired skips deprecated)
    cap_b = build_capability("ro.cap.b", "ANALYTIC", _CHARS)
    space.apply({"kind": "add_capability", "record": cap_b})
    v_jump = space.apply({"kind": "transition_capability_lifecycle",
                           "id": "ro.cap.b", "to_state": "retired"})
    assert space.get_capability("ro.cap.b").lifecycle == "retired"

    # tombstone reuse: permanent, distinct type from recoverable duplicate
    try:
        space.apply({"kind": "add_capability", "record": cap_b})
        raise SystemExit("tombstone id reuse accepted")
    except TombstoneReuseError:
        pass

    # update_capability freezes category
    changed_category = build_capability("ro.cap.a", "ANALYTIC", _CHARS)
    try:
        space.apply({"kind": "update_capability", "record": changed_category})
        raise SystemExit("category change via update accepted")
    except CategoryFrozenError:
        pass
    # content-only update (same category, same lifecycle) accepted
    new_chars = dict(_CHARS)
    new_chars["creativity_requirement"] = "medium"
    content_update = build_capability("ro.cap.a", "INTERPRETIVE", new_chars, lifecycle="active")
    v_upd = space.apply({"kind": "update_capability", "record": content_update})
    assert space.get_capability("ro.cap.a").characteristics["creativity_requirement"] == "medium"

    # relationship: dangling endpoint refused
    bad_edge = build_relationship("dependency", "ro.cap.a", "ro.cap.missing")
    try:
        space.apply({"kind": "add_relationship", "record": bad_edge})
        raise SystemExit("dangling relationship accepted")
    except RelationshipEndpointError:
        pass

    cap_c = build_capability("ro.cap.c", "DELIBERATIVE", _CHARS)
    space.apply({"kind": "add_capability", "record": cap_c})
    edge_ac = build_relationship("dependency", "ro.cap.a", "ro.cap.c")
    space.apply({"kind": "add_relationship", "record": edge_ac})

    # dependency cycle refused (RO-C10)
    edge_ca = build_relationship("dependency", "ro.cap.c", "ro.cap.a")
    try:
        space.apply({"kind": "add_relationship", "record": edge_ca})
        raise SystemExit("dependency cycle accepted")
    except DependencyCycleError:
        pass

    # non-dependency relationship kinds are not cycle-checked
    edge_spec = build_relationship("specialization", "ro.cap.c", "ro.cap.a")
    space.apply({"kind": "add_relationship", "record": edge_spec})

    # remove_relationship: exact triple match required
    v_before_remove = space.current_version
    space.apply({"kind": "remove_relationship", "relationship_kind": "specialization",
                 "src": "ro.cap.c", "dst": "ro.cap.a"})
    assert space.current_version == v_before_remove + 1
    try:
        space.apply({"kind": "remove_relationship", "relationship_kind": "specialization",
                     "src": "ro.cap.c", "dst": "ro.cap.a"})
        raise SystemExit("removing already-removed relationship accepted")
    except NotFoundError:
        pass

    # descriptor row: claiming unknown capability refused
    row_bad = build_descriptor_row(
        "ro.provider.x", {"ro.cap.missing": ("C1",)}, context_capacity_class="medium",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    try:
        space.apply({"kind": "add_descriptor_row", "record": row_bad})
        raise SystemExit("descriptor row claiming unknown capability accepted")
    except DescriptorClaimError:
        pass

    # descriptor row: claiming a retired capability refused
    row_retired = build_descriptor_row(
        "ro.provider.y", {"ro.cap.b": ("C1",)}, context_capacity_class="medium",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    try:
        space.apply({"kind": "add_descriptor_row", "record": row_retired})
        raise SystemExit("descriptor row claiming retired capability accepted")
    except DescriptorClaimError:
        pass

    # descriptor row: claiming an active capability accepted
    row_ok = build_descriptor_row(
        "ro.provider.z", {"ro.cap.a": ("C1", "C0")}, context_capacity_class="medium",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    v_row = space.apply({"kind": "add_descriptor_row", "record": row_ok})
    assert space.get_descriptor_row("ro.provider.z").provider_id == "ro.provider.z"

    # update + remove descriptor row
    row_updated = build_descriptor_row(
        "ro.provider.z", {"ro.cap.a": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    space.apply({"kind": "update_descriptor_row", "record": row_updated})
    assert space.get_descriptor_row("ro.provider.z").context_capacity_class == "large"
    space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.z"})
    assert space.get_descriptor_row("ro.provider.z") is None
    try:
        space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.z"})
        raise SystemExit("removing already-removed descriptor row accepted")
    except NotFoundError:
        pass

    # re-adding a descriptor row after removal is NOT a tombstone violation
    space.apply({"kind": "add_descriptor_row", "record": row_ok})
    assert space.get_descriptor_row("ro.provider.z") is not None

    # retirement refused while a descriptor row still claims the capability
    try:
        space.apply({"kind": "transition_capability_lifecycle",
                      "id": "ro.cap.a", "to_state": "retired"})
        raise SystemExit("retirement while claimed accepted")
    except ClaimedCapabilityRetirementError:
        pass
    space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.z"})
    space.apply({"kind": "transition_capability_lifecycle",
                 "id": "ro.cap.a", "to_state": "retired"})
    assert space.get_capability("ro.cap.a").lifecycle == "retired"

    # determinism: two independently built spaces, same mutation sequence
    # -> identical content hashes at every version
    from .records import content_hash

    def _build_reference_space():
        s = DescriptorSpace()
        s.apply({"kind": "add_capability", "record": cap_a})
        s.apply({"kind": "transition_capability_lifecycle",
                 "id": "ro.cap.a", "to_state": "active"})
        return s

    s1 = _build_reference_space()
    s2 = _build_reference_space()
    assert s1.current_version == s2.current_version
    assert content_hash(s1.get_capability("ro.cap.a")) == content_hash(s2.get_capability("ro.cap.a"))

    # unknown mutation kind refused
    try:
        space.apply({"kind": "teleport_capability"})
        raise SystemExit("unknown mutation kind accepted")
    except UnknownMutationError:
        pass

    # dry_run: validates without committing, no side effect either way
    v_before_dry = space.current_version
    cap_dry = build_capability("ro.cap.dry", "GENERATIVE", _CHARS)
    space.dry_run({"kind": "add_capability", "record": cap_dry})
    assert space.current_version == v_before_dry
    assert space.get_capability("ro.cap.dry") is None

    print("descriptor_space selftest ok")
