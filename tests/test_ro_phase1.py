"""RO Phase 1 suite — RO/01-reasoning-capability-model.md + RO/03 §3
(descriptor row). Covers record validation (closed sets, 8 characteristics,
C0-C4 bands, 3 relationship kinds), lifecycle forward-only + legal forward
jumps, id-reuse tombstone permanence, dependency-cycle rejection, descriptor
row claim validation, versioning (monotonic, at_version snapshot semantics,
negative/never-existed refusal), determinism (identical mutation sequence ->
identical hashes/snapshots across independently built spaces), and
update_capability's category-freeze rule.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ro.records import (
    CATEGORIES,
    CHARACTERISTIC_BANDS,
    COMPLEXITY_RUNGS,
    RELATIONSHIP_KINDS,
    CapabilityRecord,
    DescriptorRow,
    RelationshipRecord,
    build_capability,
    build_descriptor_row,
    build_relationship,
    canonical,
    content_hash,
)
from ro.descriptor_space import (
    CategoryFrozenError,
    ClaimedCapabilityRetirementError,
    DependencyCycleError,
    DescriptorClaimError,
    DescriptorSpace,
    DuplicateIdError,
    LifecycleTransitionError,
    NotFoundError,
    PermanentRefusal,
    RecoverableRefusal,
    RelationshipEndpointError,
    TombstoneReuseError,
    UnknownMutationError,
)

_CHARS = {
    "inference_depth": "moderate", "context_sensitivity": "medium",
    "determinism_tolerance": "medium", "knowledge_dependency": "low",
    "creativity_requirement": "low", "reasoning_complexity": "C1",
    "verification_difficulty": "low", "expected_output_structure": "bounded",
}


def _cap(id, category="INTERPRETIVE", lifecycle="proposed", characteristics=None):
    return build_capability(id, category, characteristics or _CHARS, lifecycle=lifecycle)


def _active_space_with(*ids):
    """A DescriptorSpace with each given capability id added and forced active."""
    space = DescriptorSpace()
    for cid in ids:
        space.apply({"kind": "add_capability", "record": _cap(cid)})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": cid, "to_state": "active"})
    return space


def _row(provider_id, claims, **overrides):
    kwargs = dict(
        context_capacity_class="medium", cost_class="low", latency_class="fast",
        determinism_class="low_variance", deployment_locality="local",
        privacy_domain="internal",
    )
    kwargs.update(overrides)
    return build_descriptor_row(provider_id, claims, **kwargs)


class RecordValidationCase(unittest.TestCase):
    def test_five_categories_closed_set(self):
        self.assertEqual(set(CATEGORIES), {
            "INTERPRETIVE", "ANALYTIC", "GENERATIVE", "DELIBERATIVE", "INFERENTIAL",
        })
        for cat in CATEGORIES:
            build_capability("ro.cap." + cat.lower(), cat, _CHARS)
        with self.assertRaises(ValueError):
            build_capability("ro.cap.bad", "MADEUP", _CHARS)

    def test_exactly_eight_characteristics_required(self):
        self.assertEqual(len(CHARACTERISTIC_BANDS), 8)
        incomplete = dict(_CHARS)
        del incomplete["inference_depth"]
        with self.assertRaises(ValueError):
            build_capability("ro.cap.incomplete", "INTERPRETIVE", incomplete)
        extra = dict(_CHARS)
        extra["nonexistent"] = "low"
        with self.assertRaises(ValueError):
            build_capability("ro.cap.extra", "INTERPRETIVE", extra)

    def test_characteristic_bands_are_closed(self):
        bad = dict(_CHARS)
        bad["context_sensitivity"] = "extreme"
        with self.assertRaises(ValueError):
            build_capability("ro.cap.badband", "INTERPRETIVE", bad)

    def test_reasoning_complexity_band_is_c0_c4(self):
        self.assertEqual(CHARACTERISTIC_BANDS["reasoning_complexity"], COMPLEXITY_RUNGS)
        self.assertEqual(COMPLEXITY_RUNGS, ("C0", "C1", "C2", "C3", "C4"))
        for rung in COMPLEXITY_RUNGS:
            chars = dict(_CHARS)
            chars["reasoning_complexity"] = rung
            build_capability("ro.cap.rung." + rung, "INTERPRETIVE", chars)
        bad = dict(_CHARS)
        bad["reasoning_complexity"] = "C5"
        with self.assertRaises(ValueError):
            build_capability("ro.cap.badrung", "INTERPRETIVE", bad)

    def test_exactly_three_relationship_kinds(self):
        self.assertEqual(set(RELATIONSHIP_KINDS), {"composition", "specialization", "dependency"})
        for kind in RELATIONSHIP_KINDS:
            build_relationship(kind, "a", "b")
        with self.assertRaises(ValueError):
            build_relationship("alternative", "a", "b")
        with self.assertRaises(ValueError):
            build_relationship("conflict", "a", "b")

    def test_facets_stored_never_validated(self):
        cap = build_capability("ro.cap.facets", "INTERPRETIVE", _CHARS,
                                facets=("anything", "goes", "here"))
        self.assertEqual(cap.facets, ("anything", "goes", "here"))

    def test_frozen_records_reject_mutation(self):
        cap = _cap("ro.cap.frozen")
        with self.assertRaises(AttributeError):
            cap.category = "ANALYTIC"
        with self.assertRaises(TypeError):
            cap.characteristics["inference_depth"] = "deep"

    def test_descriptor_row_claims_at_least_one_capability(self):
        with self.assertRaises(ValueError):
            build_descriptor_row(
                "ro.provider.empty", {}, context_capacity_class="medium",
                cost_class="low", latency_class="fast", determinism_class="low_variance",
                deployment_locality="local", privacy_domain="internal",
            )

    def test_descriptor_row_rungs_restricted_to_c0_c4(self):
        with self.assertRaises(ValueError):
            _row("ro.provider.badrung", {"ro.cap.x": ("C9",)})
        row = _row("ro.provider.ok", {"ro.cap.x": ("C1", "C0", "C1")})
        self.assertEqual(row.capabilities_claimed["ro.cap.x"], ("C0", "C1"))

    def test_descriptor_row_closed_class_fields(self):
        with self.assertRaises(ValueError):
            _row("ro.provider.bad", {"ro.cap.x": ("C0",)}, cost_class="astronomical")
        with self.assertRaises(ValueError):
            _row("ro.provider.bad2", {"ro.cap.x": ("C0",)}, deployment_locality="orbital")

    def test_deployment_locality_is_local_or_remote(self):
        from ro.records import DEPLOYMENT_LOCALITY_CLASSES
        self.assertEqual(DEPLOYMENT_LOCALITY_CLASSES, ("local", "remote"))

    def test_canonical_content_hash_deterministic(self):
        cap1 = _cap("ro.cap.hash")
        cap2 = _cap("ro.cap.hash")
        self.assertEqual(canonical(cap1), canonical(cap2))
        self.assertEqual(content_hash(cap1), content_hash(cap2))
        row1 = _row("ro.provider.hash", {"ro.cap.x": ("C1",)})
        row2 = _row("ro.provider.hash", {"ro.cap.x": ("C1",)})
        self.assertEqual(content_hash(row1), content_hash(row2))


class LifecycleCase(unittest.TestCase):
    def test_forward_only_transition_enforced(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.lc")})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.lc", "to_state": "active"})
        with self.assertRaises(LifecycleTransitionError):
            space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.lc", "to_state": "proposed"})
        with self.assertRaises(LifecycleTransitionError):
            space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.lc", "to_state": "active"})  # sideways/same refused

    def test_forward_jump_is_legal(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.jump")})
        # proposed -> retired directly, skipping active/deprecated
        v = space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.jump", "to_state": "retired"})
        self.assertEqual(space.get_capability("ro.cap.jump").lifecycle, "retired")

    def test_unknown_lifecycle_state_refused(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.unk")})
        with self.assertRaises(LifecycleTransitionError):
            space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.unk", "to_state": "banished"})

    def test_transition_of_unknown_capability_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(NotFoundError):
            space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.missing", "to_state": "active"})


class TombstoneCase(unittest.TestCase):
    def test_id_reuse_after_retirement_is_permanent_refusal(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.tomb")
        space.apply({"kind": "add_capability", "record": cap})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.tomb", "to_state": "retired"})
        with self.assertRaises(TombstoneReuseError):
            space.apply({"kind": "add_capability", "record": cap})
        # and it is specifically a PermanentRefusal, not a RecoverableRefusal
        try:
            space.apply({"kind": "add_capability", "record": cap})
        except TombstoneReuseError as e:
            self.assertIsInstance(e, PermanentRefusal)
            self.assertNotIsInstance(e, RecoverableRefusal)

    def test_duplicate_live_id_is_recoverable(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.dup")
        space.apply({"kind": "add_capability", "record": cap})
        with self.assertRaises(DuplicateIdError):
            space.apply({"kind": "add_capability", "record": cap})
        try:
            space.apply({"kind": "add_capability", "record": cap})
        except DuplicateIdError as e:
            self.assertIsInstance(e, RecoverableRefusal)

    def test_retired_capability_immutable_via_update(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.immut")
        space.apply({"kind": "add_capability", "record": cap})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.immut", "to_state": "retired"})
        with self.assertRaises(TombstoneReuseError):
            space.apply({"kind": "update_capability", "record": cap})


class UpdateCapabilityCase(unittest.TestCase):
    def test_update_freezes_category(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.frz", category="INTERPRETIVE")
        space.apply({"kind": "add_capability", "record": cap})
        changed = _cap("ro.cap.frz", category="ANALYTIC")
        with self.assertRaises(CategoryFrozenError):
            space.apply({"kind": "update_capability", "record": changed})

    def test_update_allows_content_only_change(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.content")
        space.apply({"kind": "add_capability", "record": cap})
        new_chars = dict(_CHARS)
        new_chars["creativity_requirement"] = "high"
        updated = _cap("ro.cap.content", characteristics=new_chars)
        space.apply({"kind": "update_capability", "record": updated})
        self.assertEqual(
            space.get_capability("ro.cap.content").characteristics["creativity_requirement"],
            "high")

    def test_update_rejects_lifecycle_change(self):
        space = DescriptorSpace()
        cap = _cap("ro.cap.lcupd")
        space.apply({"kind": "add_capability", "record": cap})
        changed = _cap("ro.cap.lcupd", lifecycle="active")
        with self.assertRaises(LifecycleTransitionError):
            space.apply({"kind": "update_capability", "record": changed})

    def test_update_of_unknown_capability_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(NotFoundError):
            space.apply({"kind": "update_capability", "record": _cap("ro.cap.ghost")})


class RelationshipCase(unittest.TestCase):
    def test_dangling_endpoint_refused(self):
        space = _active_space_with("ro.cap.a")
        edge = build_relationship("dependency", "ro.cap.a", "ro.cap.missing")
        with self.assertRaises(RelationshipEndpointError):
            space.apply({"kind": "add_relationship", "record": edge})

    def test_dependency_cycle_rejected(self):
        space = _active_space_with("ro.cap.a", "ro.cap.b", "ro.cap.c")
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("dependency", "ro.cap.a", "ro.cap.b")})
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("dependency", "ro.cap.b", "ro.cap.c")})
        with self.assertRaises(DependencyCycleError):
            space.apply({"kind": "add_relationship",
                         "record": build_relationship("dependency", "ro.cap.c", "ro.cap.a")})

    def test_self_dependency_is_a_cycle(self):
        space = _active_space_with("ro.cap.self")
        with self.assertRaises(DependencyCycleError):
            space.apply({"kind": "add_relationship",
                         "record": build_relationship("dependency", "ro.cap.self", "ro.cap.self")})

    def test_non_dependency_kinds_not_cycle_checked(self):
        space = _active_space_with("ro.cap.a", "ro.cap.b")
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("specialization", "ro.cap.a", "ro.cap.b")})
        # reverse specialization edge is fine -- only dependency is acyclic
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("specialization", "ro.cap.b", "ro.cap.a")})

    def test_remove_relationship_exact_match(self):
        space = _active_space_with("ro.cap.a", "ro.cap.b")
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("composition", "ro.cap.a", "ro.cap.b")})
        space.apply({"kind": "remove_relationship", "relationship_kind": "composition",
                     "src": "ro.cap.a", "dst": "ro.cap.b"})
        self.assertEqual(space.relationships(), [])
        with self.assertRaises(NotFoundError):
            space.apply({"kind": "remove_relationship", "relationship_kind": "composition",
                         "src": "ro.cap.a", "dst": "ro.cap.b"})


class DescriptorRowCase(unittest.TestCase):
    def test_claiming_unknown_capability_refused(self):
        space = DescriptorSpace()
        row = _row("ro.provider.x", {"ro.cap.nope": ("C1",)})
        with self.assertRaises(DescriptorClaimError):
            space.apply({"kind": "add_descriptor_row", "record": row})

    def test_claiming_retired_capability_refused(self):
        space = _active_space_with("ro.cap.a")
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.a", "to_state": "retired"})
        row = _row("ro.provider.x", {"ro.cap.a": ("C1",)})
        with self.assertRaises(DescriptorClaimError):
            space.apply({"kind": "add_descriptor_row", "record": row})

    def test_claiming_proposed_capability_refused(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.proposed")})
        row = _row("ro.provider.x", {"ro.cap.proposed": ("C1",)})
        with self.assertRaises(DescriptorClaimError):
            space.apply({"kind": "add_descriptor_row", "record": row})

    def test_claiming_active_and_deprecated_capabilities_accepted(self):
        space = _active_space_with("ro.cap.a")
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.b")})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.b", "to_state": "active"})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.b", "to_state": "deprecated"})
        row = _row("ro.provider.x", {"ro.cap.a": ("C1",), "ro.cap.b": ("C0",)})
        space.apply({"kind": "add_descriptor_row", "record": row})
        self.assertIsNotNone(space.get_descriptor_row("ro.provider.x"))

    def test_duplicate_provider_id_refused(self):
        space = _active_space_with("ro.cap.a")
        row = _row("ro.provider.dup", {"ro.cap.a": ("C1",)})
        space.apply({"kind": "add_descriptor_row", "record": row})
        with self.assertRaises(DuplicateIdError):
            space.apply({"kind": "add_descriptor_row", "record": row})

    def test_remove_then_readd_is_not_a_tombstone(self):
        space = _active_space_with("ro.cap.a")
        row = _row("ro.provider.churn", {"ro.cap.a": ("C1",)})
        space.apply({"kind": "add_descriptor_row", "record": row})
        space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.churn"})
        # re-adding under the same provider id must NOT raise TombstoneReuseError
        space.apply({"kind": "add_descriptor_row", "record": row})
        self.assertIsNotNone(space.get_descriptor_row("ro.provider.churn"))

    def test_update_descriptor_row_revalidates_claims(self):
        space = _active_space_with("ro.cap.a")
        row = _row("ro.provider.x", {"ro.cap.a": ("C1",)})
        space.apply({"kind": "add_descriptor_row", "record": row})
        bad_update = _row("ro.provider.x", {"ro.cap.nonexistent": ("C1",)})
        with self.assertRaises(DescriptorClaimError):
            space.apply({"kind": "update_descriptor_row", "record": bad_update})

    def test_remove_of_unknown_row_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(NotFoundError):
            space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.ghost"})

    def test_retirement_refused_while_descriptor_rows_claim_capability(self):
        # RO/03 §3: claims resolve to active-or-deprecated only. Retirement
        # with live claims would create a state add_descriptor_row itself
        # refuses — the space must never reach it by mutation order.
        space = _active_space_with("ro.cap.a")
        row = _row("ro.provider.x", {"ro.cap.a": ("C1",)})
        space.apply({"kind": "add_descriptor_row", "record": row})
        version_before = space.current_version
        with self.assertRaises(ClaimedCapabilityRetirementError):
            space.apply({"kind": "transition_capability_lifecycle",
                         "id": "ro.cap.a", "to_state": "retired"})
        self.assertEqual(space.current_version, version_before)
        self.assertEqual(space.get_capability("ro.cap.a").lifecycle, "active")
        # removing the claimant unblocks retirement
        space.apply({"kind": "remove_descriptor_row", "provider_id": "ro.provider.x"})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.a", "to_state": "retired"})
        self.assertEqual(space.get_capability("ro.cap.a").lifecycle, "retired")


class VersioningCase(unittest.TestCase):
    def test_monotonic_version_per_mutation(self):
        space = DescriptorSpace()
        self.assertEqual(space.current_version, 0)
        v1 = space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        v2 = space.apply({"kind": "add_capability", "record": _cap("ro.cap.b")})
        self.assertEqual((v1, v2), (1, 2))
        self.assertEqual(space.current_version, 2)

    def test_refused_mutation_leaves_version_untouched(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        before = space.current_version
        with self.assertRaises(DuplicateIdError):
            space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        self.assertEqual(space.current_version, before)

    def test_at_version_snapshot_immutability_and_equality(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        snap_v1 = space.at_version(1)
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.a", "to_state": "active"})
        # historical snapshot is unaffected by the later mutation
        self.assertEqual(snap_v1.get_capability("ro.cap.a").lifecycle, "proposed")
        self.assertEqual(space.get_capability("ro.cap.a").lifecycle, "active")
        self.assertEqual(space.at_version(1).get_capability("ro.cap.a").lifecycle, "proposed")

    def test_version_zero_is_the_empty_space_forever(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        self.assertIsNone(space.at_version(0).get_capability("ro.cap.a"))

    def test_negative_version_refused(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        with self.assertRaises(IndexError):
            space.at_version(-1)

    def test_never_existed_version_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(IndexError):
            space.at_version(1)


class DeterminismCase(unittest.TestCase):
    def _build(self):
        space = DescriptorSpace()
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.a")})
        space.apply({"kind": "add_capability", "record": _cap("ro.cap.b", category="ANALYTIC")})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.a", "to_state": "active"})
        space.apply({"kind": "transition_capability_lifecycle",
                     "id": "ro.cap.b", "to_state": "active"})
        space.apply({"kind": "add_relationship",
                     "record": build_relationship("dependency", "ro.cap.a", "ro.cap.b")})
        row = _row("ro.provider.x", {"ro.cap.a": ("C1", "C0")})
        space.apply({"kind": "add_descriptor_row", "record": row})
        return space

    def test_same_mutation_sequence_yields_identical_hashes(self):
        s1 = self._build()
        s2 = self._build()
        self.assertEqual(s1.current_version, s2.current_version)
        for cid in ("ro.cap.a", "ro.cap.b"):
            self.assertEqual(
                content_hash(s1.get_capability(cid)), content_hash(s2.get_capability(cid)))
        self.assertEqual(
            content_hash(s1.get_descriptor_row("ro.provider.x")),
            content_hash(s2.get_descriptor_row("ro.provider.x")))

    def test_same_mutation_sequence_yields_identical_snapshots_at_every_version(self):
        s1 = self._build()
        s2 = self._build()
        for v in range(s1.current_version + 1):
            snap1, snap2 = s1.at_version(v), s2.at_version(v)
            caps1 = {c.id: content_hash(c) for c in snap1.all_capabilities()}
            caps2 = {c.id: content_hash(c) for c in snap2.all_capabilities()}
            self.assertEqual(caps1, caps2)
            rows1 = {r.provider_id: content_hash(r) for r in snap1.all_descriptor_rows()}
            rows2 = {r.provider_id: content_hash(r) for r in snap2.all_descriptor_rows()}
            self.assertEqual(rows1, rows2)


class MalformedMutationCase(unittest.TestCase):
    def test_unknown_mutation_kind_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(UnknownMutationError):
            space.apply({"kind": "teleport"})

    def test_missing_kind_key_refused(self):
        space = DescriptorSpace()
        with self.assertRaises(UnknownMutationError):
            space.apply({})

    def test_dry_run_has_no_side_effect_on_success_or_refusal(self):
        space = DescriptorSpace()
        before = space.current_version
        space.dry_run({"kind": "add_capability", "record": _cap("ro.cap.dry")})
        self.assertEqual(space.current_version, before)
        self.assertIsNone(space.get_capability("ro.cap.dry"))
        with self.assertRaises(UnknownMutationError):
            space.dry_run({"kind": "nope"})
        self.assertEqual(space.current_version, before)


if __name__ == "__main__":
    unittest.main()
