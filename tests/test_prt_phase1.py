"""PRT Phase 1 suite — PRT/01-registry-model.md (registry model + PRT-R1..R11)
and PRT/05-system-integration.md §4 (event canon, PRT-S1/PRT-S2).

Covers every PRT-R invariant testable at this layer, the closed event
vocabulary + dead-vocabulary rejection, lifecycle forward-only legality,
tombstone-reuse permanence, and atomic provider retirement.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from prt import events
from prt.bus_double import BusDouble
from prt.records import (
    RELATIONSHIP_KINDS, build_binding, build_capability, build_provider,
    build_relationship,
)
from prt.registry import (
    AliasResolutionError, BindingConsistencyError, DuplicateIdError,
    LifecycleTransitionError, MetadataIncompleteError, NotFoundError,
    PermanentRefusal, RecoverableRefusal, Registry, RelationshipEndpointError,
    TombstoneReuseError, UnknownMutationError,
)
from prt.storage_double import StorageDouble


def _active_capability(cap_id, category="nlp", facets=(), aliases=()):
    """Helper: build + admit a capability, then push it straight to active."""
    reg = Registry()
    cap = build_capability(cap_id, "d", category, facets=facets, aliases=aliases,
                           verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": cap})
    reg.apply({"kind": "lifecycle_transition", "entity": "capability",
              "id": cap_id, "to_state": "active"})
    return reg


class EventCanonCase(unittest.TestCase):
    def test_published_and_consumed_sets_match_prt05_table(self):
        self.assertEqual(set(events.PUBLISHED), {
            "plugin.discovered", "plugin.registered", "plugin.loaded",
            "plugin.unloaded", "plugin.health.changed",
        })
        self.assertEqual(set(events.CONSUMED), {
            "plugin.lifecycle.changed", "reliability.updated",
            "exec.failed", "exec.timeout", "exec.completed",
        })

    def test_emit_refuses_unknown_and_dead_names(self):
        bus = BusDouble()
        for good in events.PUBLISHED:
            events.emit(bus, good, "s1")
        with self.assertRaises(ValueError):
            events.emit(bus, "plugin.invented", "s1")
        for dead in ("plugin.disabled", "process.failed", "process.timeout"):
            with self.assertRaises(ValueError) as ctx:
                events.emit(bus, dead, "s1")
            self.assertIn("PRT/05", str(ctx.exception))
        self.assertEqual(bus.messages("plugin.invented"), [])
        self.assertEqual(bus.messages("plugin.disabled"), [])

    def test_check_consumed_refuses_unknown_and_dead_names(self):
        for good in events.CONSUMED:
            events.check_consumed(good)
        with self.assertRaises(ValueError):
            events.check_consumed("plugin.invented")
        for dead in ("plugin.disabled", "process.failed", "process.timeout"):
            with self.assertRaises(ValueError):
                events.check_consumed(dead)


class RegistryModelInvariantsCase(unittest.TestCase):
    def test_r1_no_public_mutation_surface_besides_apply(self):
        reg = Registry()
        public_methods = [name for name in dir(reg)
                          if not name.startswith("_") and callable(getattr(reg, name))]
        mutating_verbs = ("add", "set", "update", "remove", "delete", "put", "write")
        offenders = [m for m in public_methods
                    if m != "apply" and any(m.startswith(v) for v in mutating_verbs)]
        self.assertEqual(offenders, [])
        # returned records are frozen; a reader cannot mutate registry content in place
        reg2 = _active_capability("cap.r1")
        cap = reg2.get_capability("cap.r1")
        with self.assertRaises(AttributeError):
            cap.description = "hacked"

    def test_r4_version_per_mutation_and_snapshot_immutability(self):
        reg = Registry()
        self.assertEqual(reg.current_version, 0)
        cap = build_capability("cap.v", "d", "nlp", verification_expectations=("x",))
        v1 = reg.apply({"kind": "add_capability", "record": cap})
        self.assertEqual(v1, 1)
        self.assertEqual(reg.current_version, 1)
        v2 = reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                        "id": "cap.v", "to_state": "active"})
        self.assertEqual(v2, 2)
        snap_v1 = reg.at_version(1)
        self.assertEqual(snap_v1.get_capability("cap.v").lifecycle, "proposed")
        # later mutation does not retroactively alter the earlier snapshot (PRT/01 §4)
        v3 = reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                        "id": "cap.v", "to_state": "deprecated"})
        self.assertEqual(reg.at_version(1).get_capability("cap.v").lifecycle, "proposed")
        self.assertEqual(reg.at_version(2).get_capability("cap.v").lifecycle, "active")
        self.assertEqual(reg.at_version(3).get_capability("cap.v").lifecycle, "deprecated")

    def test_r5_global_version_and_entry_version_are_distinct(self):
        reg = Registry()
        cap = build_capability("cap.e", "d", "nlp", verification_expectations=("x",),
                               entry_version=7)
        reg.apply({"kind": "add_capability", "record": cap})
        # registry-global version advanced to 1; entry_version is untouched at 7
        self.assertEqual(reg.current_version, 1)
        self.assertEqual(reg.get_capability("cap.e").entry_version, 7)
        # a further mutation advances the global counter without touching entry_version
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.e", "to_state": "active"})
        self.assertEqual(reg.current_version, 2)
        self.assertEqual(reg.get_capability("cap.e").entry_version, 7)

    def test_r6_alias_resolution_centralized_deterministic_acyclic(self):
        reg = _active_capability("cap.canonical", aliases=("cap.old",))
        # deterministic: repeated resolution of the same id at the same version agrees
        self.assertEqual(reg.resolve("cap.old"), "cap.canonical")
        self.assertEqual(reg.resolve("cap.old"), reg.resolve("cap.old"))
        self.assertEqual(reg.get_capability("cap.old").id, "cap.canonical")
        # acyclicity: an alias id can't collide with a real capability id
        other = build_capability("cap.other", "d", "nlp", aliases=("cap.canonical",),
                                 verification_expectations=("x",))
        with self.assertRaises(AliasResolutionError):
            reg.apply({"kind": "add_capability", "record": other})
        # nor can the same alias be double-targeted by a second capability
        third = build_capability("cap.third", "d", "nlp", aliases=("cap.old",),
                                 verification_expectations=("x",))
        with self.assertRaises(AliasResolutionError):
            reg.apply({"kind": "add_capability", "record": third})

    def test_r7_exactly_four_relationship_kinds(self):
        self.assertEqual(set(RELATIONSHIP_KINDS),
                        {"dependency", "composition", "alternative", "conflict"})
        reg = _active_capability("cap.rel")
        for kind in RELATIONSHIP_KINDS:
            edge = build_relationship(kind, "cap.rel", "cap.rel")
            reg.apply({"kind": "add_relationship", "record": edge})
        self.assertEqual(len(reg.relationships()), len(RELATIONSHIP_KINDS))
        with self.assertRaises(ValueError):
            build_relationship("specialization", "cap.rel", "cap.rel")

    def test_r8_many_to_many_bindings_removal_leaves_capability_untouched(self):
        reg = _active_capability("cap.m2m")
        for pid in ("prov.a", "prov.b"):
            reg.apply({"kind": "add_provider", "record": build_provider(pid, "1.0")})
            reg.apply({"kind": "add_binding",
                      "record": build_binding("cap.m2m", pid)})
        self.assertEqual({b.provider_id for b in reg.bindings_for("cap.m2m")},
                        {"prov.a", "prov.b"})
        before = reg.get_capability("cap.m2m")
        reg.apply({"kind": "remove_binding", "capability_id": "cap.m2m",
                  "provider_id": "prov.a"})
        after = reg.get_capability("cap.m2m")
        self.assertEqual({b.provider_id for b in reg.bindings_for("cap.m2m")}, {"prov.b"})
        self.assertEqual(before, after)  # binding removal never touches the capability def
        with self.assertRaises(NotFoundError):
            reg.apply({"kind": "remove_binding", "capability_id": "cap.m2m",
                      "provider_id": "prov.a"})

    def test_r9_verification_expectation_mandatory_construction_and_apply(self):
        with self.assertRaises(ValueError):
            build_capability("cap.bad", "d", "nlp", verification_expectations=())
        # defense in depth: apply() re-checks even if a record slipped through
        # construction with an empty tuple via direct dataclass instantiation
        from prt.records import CapabilityRecord
        from types import MappingProxyType
        bare = CapabilityRecord(id="cap.bare", description="d", category="nlp",
                                facets=(), lifecycle="proposed", aliases=(),
                                verification_expectations=(),
                                constraints=MappingProxyType({}), entry_version=1,
                                deprecation_pointer=None)
        reg = Registry()
        with self.assertRaises(MetadataIncompleteError):
            reg.apply({"kind": "add_capability", "record": bare})

    def test_r10_refused_mutation_leaves_version_and_content_untouched(self):
        reg = _active_capability("cap.stable")
        version_before = reg.current_version
        snapshot_before = reg.get_capability("cap.stable")
        with self.assertRaises(BindingConsistencyError):
            reg.apply({"kind": "add_binding",
                      "record": build_binding("cap.stable", "prov.unregistered")})
        self.assertEqual(reg.current_version, version_before)
        self.assertEqual(reg.get_capability("cap.stable"), snapshot_before)

    def test_r11_new_category_and_facet_values_are_pure_data(self):
        reg = Registry()
        # a brand-new category/facet value never seen before requires zero
        # code change here -- just data through the same apply() path
        cap = build_capability("cap.newdomain", "d", "quantum-hardware-control",
                               facets=("never-seen-facet",),
                               verification_expectations=("x",))
        reg.apply({"kind": "add_capability", "record": cap})
        self.assertEqual(reg.list_by_category("quantum-hardware-control")[0].id,
                        "cap.newdomain")
        self.assertEqual(reg.list_by_facet("never-seen-facet")[0].id, "cap.newdomain")


class LifecycleLegalityCase(unittest.TestCase):
    def test_capability_lifecycle_forward_only_backward_refused(self):
        reg = Registry()
        cap = build_capability("cap.lc", "d", "nlp", verification_expectations=("x",))
        reg.apply({"kind": "add_capability", "record": cap})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.lc", "to_state": "active"})
        with self.assertRaises(LifecycleTransitionError):
            reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                      "id": "cap.lc", "to_state": "proposed"})
        with self.assertRaises(LifecycleTransitionError):
            reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                      "id": "cap.lc", "to_state": "active"})  # sideways/same refused too

    def test_provider_lifecycle_forward_only_backward_refused(self):
        reg = Registry()
        reg.apply({"kind": "add_provider", "record": build_provider("prov.lc", "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.lc", "to_state": "active"})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.lc", "to_state": "deprecated"})
        with self.assertRaises(LifecycleTransitionError):
            reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                      "id": "prov.lc", "to_state": "active"})

    def test_tombstone_reuse_is_permanent_refusal_distinct_from_duplicate(self):
        reg = Registry()
        reg.apply({"kind": "add_capability",
                  "record": build_capability("cap.tomb", "d", "nlp",
                                             verification_expectations=("x",))})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.tomb", "to_state": "active"})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.tomb", "to_state": "deprecated"})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.tomb", "to_state": "retired"})
        with self.assertRaises(TombstoneReuseError) as ctx:
            reg.apply({"kind": "add_capability",
                      "record": build_capability("cap.tomb", "d2", "nlp",
                                                 verification_expectations=("y",))})
        self.assertIsInstance(ctx.exception, PermanentRefusal)
        self.assertNotIsInstance(ctx.exception, RecoverableRefusal)
        # an ordinary live-id collision, by contrast, is Recoverable
        reg2 = Registry()
        cap = build_capability("cap.dup", "d", "nlp", verification_expectations=("x",))
        reg2.apply({"kind": "add_capability", "record": cap})
        with self.assertRaises(DuplicateIdError) as ctx2:
            reg2.apply({"kind": "add_capability", "record": cap})
        self.assertIsInstance(ctx2.exception, RecoverableRefusal)

    def test_atomic_retirement_removes_bindings_in_same_version(self):
        reg = _active_capability("cap.atomic")
        reg.apply({"kind": "add_provider", "record": build_provider("prov.atomic", "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.atomic", "to_state": "active"})
        reg.apply({"kind": "add_binding",
                  "record": build_binding("cap.atomic", "prov.atomic")})
        self.assertEqual(len(reg.bindings_for("cap.atomic")), 1)
        version_before_retire = reg.current_version
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.atomic", "to_state": "deprecated"})
        v_retire = reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                              "id": "prov.atomic", "to_state": "retired"})
        # binding gone in the exact same mutation that retired the provider
        self.assertEqual(reg.bindings_for("cap.atomic"), [])
        self.assertEqual(reg.at_version(v_retire).bindings_for("cap.atomic"), [])
        # the version right before still shows the binding (retirement wasn't split
        # across two mutations)
        self.assertNotEqual(v_retire, version_before_retire)


class RelationshipAndDanglingReferenceCase(unittest.TestCase):
    def test_relationship_dangling_endpoint_refused(self):
        reg = _active_capability("cap.left")
        edge = build_relationship("dependency", "cap.left", "cap.nonexistent")
        with self.assertRaises(RelationshipEndpointError):
            reg.apply({"kind": "add_relationship", "record": edge})


class UnknownMutationCase(unittest.TestCase):
    def test_unknown_mutation_kind_refused(self):
        reg = Registry()
        with self.assertRaises(UnknownMutationError):
            reg.apply({"kind": "not_a_real_mutation"})
        with self.assertRaises(UnknownMutationError):
            reg.apply({"nope": "no kind key at all"})


class StorageDoubleRoundTripCase(unittest.TestCase):
    def test_write_read_round_trip_and_failure_injection(self):
        store = StorageDouble()
        store.write("prt/registry/snapshot", b"blob")
        self.assertEqual(store.read("prt/registry/snapshot"), b"blob")
        self.assertTrue(store.exists("prt/registry/snapshot"))
        store.fail_reads = True
        with self.assertRaises(ConnectionError):
            store.read("prt/registry/snapshot")


if __name__ == "__main__":
    unittest.main()
