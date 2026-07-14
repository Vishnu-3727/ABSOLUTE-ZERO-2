"""PRT Phase 2 suite — PRT/02-discovery-admission.md (PRT-A1..A12).

Covers: discovery never mutates the registry (PRT-A1); every source class
traverses the identical pipeline with no fast path (PRT-A2); pipeline stage
order + stage-specific rejection recorded (PRT-A12) for every PRT/02 §9
failure class; all-or-nothing one-version-per-candidacy (PRT-A6/A10);
deterministic admission + deterministic discovery serialization (PRT-A9);
persist-before-commit and its one non-terminal (retryable) failure (§9);
retirement enactment via plugin.lifecycle.changed (PRT-A4) with atomic
binding removal and untouched historical snapshots (PRT-A11); the
alias-retirement gate (KNOWN SEAM); replay stability; full-suite regression.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from prt import events
from prt.admission import (
    CapabilityReferenceError, CompatibilityConflictError,
    ConstraintIncoherenceError, SemanticHijackError, admit,
)
from prt.bus_double import BusDouble
from prt.candidacy import Candidacy, CandidacyError
from prt.declarations import SOURCE_CLASSES, build_declaration
from prt.discovery import FixtureSource, discover
from prt.records import (
    CapabilityRecord, build_binding, build_capability, build_provider,
    build_relationship,
)
from prt.registry import (
    AliasTargetRetirementError, BindingConsistencyError, MetadataIncompleteError,
    Registry, RelationshipEndpointError, TombstoneReuseError,
)
from prt.retirement import enact_lifecycle_event
from prt.storage_double import StorageDouble


def _new_env():
    return Registry(), BusDouble(), StorageDouble()


def _active_capability_declaration(provider_id, cap_id, **kwargs):
    cap = build_capability(cap_id, "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    prov = build_provider(provider_id, "1.0")
    binding = build_binding(cap_id, provider_id)
    return build_declaration(prov, capabilities=(cap,), bindings=(binding,), **kwargs)


class DiscoveryNeverMutatesCase(unittest.TestCase):
    def test_a1_discovery_never_touches_a_registry(self):
        # discover()'s signature has no registry parameter at all -- there is
        # structurally nothing for it to mutate, not merely a convention.
        import inspect
        params = inspect.signature(discover).parameters
        self.assertNotIn("registry", params)

        bus = BusDouble()
        decl = build_declaration(build_provider("prov.disc.x", "1.0"))
        source = FixtureSource([decl])
        ordered = discover([source], bus)
        self.assertEqual(len(ordered), 1)
        # only a plugin.discovered event was published -- no registry exists
        # in this test at all, and none is needed to exercise discover().
        self.assertEqual(len(bus.messages("plugin.discovered")), 1)
        self.assertEqual(bus.messages("plugin.registered"), [])


class SourceClassNoFastPathCase(unittest.TestCase):
    def test_a2_every_source_class_traverses_identical_pipeline(self):
        self.assertEqual(set(SOURCE_CLASSES),
                         {"built-in", "local", "enterprise", "remote"})
        # same malformed declaration (dangling capability reference), one per
        # source class -- every one of them must fail at the SAME stage, no
        # source class getting a shortcut past stage 2.
        for source_class in SOURCE_CLASSES:
            reg, bus, store = _new_env()
            decl = build_declaration(
                build_provider("prov.sc." + source_class, "1.0"),
                bindings=(build_binding("cap.missing", "prov.sc." + source_class),),
                source_class=source_class)
            candidacy = admit(reg, decl, bus, store)
            self.assertEqual(candidacy.state, "REJECTED")
            self.assertEqual(candidacy.failing_stage, "capability")
            self.assertIsInstance(candidacy.refusal, CapabilityReferenceError)


class StageOrderAndFailureClassCase(unittest.TestCase):
    """One test per PRT/02 §9 failure-class row."""

    def test_metadata_incompleteness_recoverable(self):
        reg, bus, store = _new_env()
        from types import MappingProxyType
        bare = CapabilityRecord(id="cap.meta", description="d", category="nlp",
                                facets=(), lifecycle="active", aliases=(),
                                verification_expectations=(),
                                constraints=MappingProxyType({}), entry_version=1,
                                deprecation_pointer=None)
        decl = build_declaration(build_provider("prov.meta", "1.0"), capabilities=(bare,))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "metadata")
        self.assertIsInstance(candidacy.refusal, MetadataIncompleteError)

    def test_constraint_inconsistency_recoverable(self):
        reg, bus, store = _new_env()
        prov = build_provider("prov.constr", "1.0", declared_constraints={"platform": "linux"})
        cap = build_capability("cap.constr", "d", "nlp", lifecycle="active",
                               verification_expectations=("x",))
        binding = build_binding("cap.constr", "prov.constr", terms={"platform": "windows"})
        decl = build_declaration(prov, capabilities=(cap,), bindings=(binding,))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "constraint")
        self.assertIsInstance(candidacy.refusal, ConstraintIncoherenceError)

    def test_relationship_dangling_reference_recoverable(self):
        reg, bus, store = _new_env()
        prov = build_provider("prov.rel", "1.0")
        edge = build_relationship("dependency", "cap.rel.a", "cap.rel.missing")
        decl = build_declaration(prov, relationships=(edge,))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "relationship")
        self.assertIsInstance(candidacy.refusal, RelationshipEndpointError)

    def test_binding_invalidity_recoverable(self):
        # target capability exists but is not matchable (still "proposed")
        reg, bus, store = _new_env()
        reg.apply({"kind": "add_capability", "record": build_capability(
            "cap.bind.a", "d", "nlp", verification_expectations=("x",))})  # proposed, not active
        decl = build_declaration(build_provider("prov.bind", "1.0"),
                                 bindings=(build_binding("cap.bind.a", "prov.bind"),))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "binding")
        self.assertIsInstance(candidacy.refusal, BindingConsistencyError)

    def test_compatibility_conflict_recoverable(self):
        # alias collision with an existing live capability id (C10)
        reg, bus, store = _new_env()
        reg.apply({"kind": "add_capability", "record": build_capability(
            "cap.compat.taken", "d", "nlp", verification_expectations=("x",))})
        colliding = build_capability("cap.compat.new", "d", "nlp",
                                     aliases=("cap.compat.taken",),
                                     verification_expectations=("x",))
        decl = build_declaration(build_provider("prov.compat", "1.0"),
                                 capabilities=(colliding,))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "compatibility")
        self.assertIsInstance(candidacy.refusal, CompatibilityConflictError)

    def test_tombstone_id_reuse_permanent(self):
        reg, bus, store = _new_env()
        reg.apply({"kind": "add_provider", "record": build_provider("prov.tomb", "1.0")})
        for to_state in ("active", "deprecated", "retired"):
            reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                      "id": "prov.tomb", "to_state": to_state})
        decl = build_declaration(build_provider("prov.tomb", "2.0"))
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "identity")
        self.assertIsInstance(candidacy.refusal, TombstoneReuseError)
        from prt.registry import PermanentRefusal, RecoverableRefusal
        self.assertIsInstance(candidacy.refusal, PermanentRefusal)
        self.assertNotIsInstance(candidacy.refusal, RecoverableRefusal)

    def test_semantic_hijack_permanent(self):
        reg, bus, store = _new_env()
        reg.apply({"kind": "add_provider", "record": build_provider("prov.hijack", "1.0")})
        decl = build_declaration(build_provider("prov.hijack", "2.0"))  # same id, different content
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(candidacy.failing_stage, "identity")
        self.assertIsInstance(candidacy.refusal, SemanticHijackError)
        from prt.registry import PermanentRefusal
        self.assertIsInstance(candidacy.refusal, PermanentRefusal)

    def test_later_stages_never_attempted_after_earlier_failure(self):
        # a declaration with BOTH a stage-1 tombstone conflict AND a stage-7
        # style issue -- only stage 1's rejection is ever recorded.
        reg, bus, store = _new_env()
        reg.apply({"kind": "add_provider", "record": build_provider("prov.order", "1.0")})
        for to_state in ("active", "deprecated", "retired"):
            reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                      "id": "prov.order", "to_state": to_state})
        decl = build_declaration(
            build_provider("prov.order", "9.9"),
            bindings=(build_binding("cap.also.missing", "prov.order"),))  # would also fail stage 2
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.failing_stage, "identity")
        # audit trail has exactly one entry: the stage-1 rejection, nothing else
        self.assertEqual(len(candidacy.audit_trail), 1)
        self.assertEqual(candidacy.audit_trail[0][0], "identity")
        self.assertEqual(candidacy.audit_trail[0][1], "rejected")


class AllOrNothingCase(unittest.TestCase):
    def test_a6_a10_multipart_declaration_admits_atomically(self):
        reg, bus, store = _new_env()
        cap = build_capability("cap.aon.a", "d", "nlp", lifecycle="active",
                               verification_expectations=("x",))
        prov = build_provider("prov.aon.a", "1.0")
        binding = build_binding("cap.aon.a", "prov.aon.a")
        edge = build_relationship("dependency", "cap.aon.a", "cap.aon.a")
        decl = build_declaration(prov, capabilities=(cap,), bindings=(binding,),
                                 relationships=(edge,))
        v_before = reg.current_version
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "ADMITTED")
        self.assertEqual(reg.current_version, v_before + 1)  # exactly one version
        self.assertEqual(reg.get_capability("cap.aon.a").id, "cap.aon.a")
        self.assertEqual(reg.get_provider("prov.aon.a").id, "prov.aon.a")
        self.assertEqual(len(reg.bindings_for("cap.aon.a")), 1)
        self.assertEqual(len(reg.relationships()), 1)

    def test_any_stage_failure_leaves_zero_registry_change(self):
        reg, bus, store = _new_env()
        cap = build_capability("cap.aon.b", "d", "nlp", lifecycle="active",
                               verification_expectations=("x",))
        prov = build_provider("prov.aon.b", "1.0")
        # capability + provider are individually fine, but the binding
        # targets a provider id that doesn't exist -- whole bundle refused
        bad_binding = build_binding("cap.aon.b", "prov.nonexistent")
        decl = build_declaration(prov, capabilities=(cap,), bindings=(bad_binding,))
        v_before = reg.current_version
        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "REJECTED")
        self.assertEqual(reg.current_version, v_before)
        self.assertIsNone(reg.get_capability("cap.aon.b"))
        self.assertIsNone(reg.get_provider("prov.aon.b"))


class DeterminismCase(unittest.TestCase):
    def test_a9_same_declaration_same_prior_version_same_outcome(self):
        decl = _active_capability_declaration("prov.det.a", "cap.det.a")
        reg1, bus1, store1 = _new_env()
        reg2, bus2, store2 = _new_env()
        c1 = admit(reg1, decl, bus1, store1)
        c2 = admit(reg2, decl, bus2, store2)
        self.assertEqual(c1.state, c2.state, "ADMITTED")
        self.assertEqual(c1.minted_version, c2.minted_version)
        self.assertEqual(reg1.get_capability("cap.det.a"), reg2.get_capability("cap.det.a"))
        self.assertEqual(reg1.get_provider("prov.det.a"), reg2.get_provider("prov.det.a"))
        self.assertEqual(reg1.current_version, reg2.current_version)

    def test_a9_discovery_serialization_order_independent_of_source_order(self):
        decl_a = build_declaration(build_provider("prov.ord.a", "1.0"))
        decl_b = build_declaration(build_provider("prov.ord.b", "1.0"))
        decl_c = build_declaration(build_provider("prov.ord.c", "1.0"))
        bus1, bus2 = BusDouble(), BusDouble()
        order1 = discover([FixtureSource([decl_a]), FixtureSource([decl_b, decl_c])], bus1)
        order2 = discover([FixtureSource([decl_c, decl_b]), FixtureSource([decl_a])], bus2)
        self.assertEqual([d.content_hash for d in order1], [d.content_hash for d in order2])
        expected = sorted((decl_a, decl_b, decl_c), key=lambda d: d.content_hash)
        self.assertEqual([d.content_hash for d in order1], [d.content_hash for d in expected])


class PublicationPersistBeforeCommitCase(unittest.TestCase):
    def test_storage_refusal_no_version_candidacy_validated_retryable(self):
        reg = Registry()
        bus = BusDouble()
        store = StorageDouble()
        store.fail_writes = True
        decl = _active_capability_declaration("prov.pub.a", "cap.pub.a")

        candidacy = admit(reg, decl, bus, store)
        self.assertEqual(candidacy.state, "VALIDATED")
        self.assertEqual(reg.current_version, 0)
        self.assertEqual(bus.messages("plugin.registered"), [])

        # retry after storage heals: succeeds, exactly one version minted
        store.fail_writes = False
        retried = admit(reg, decl, bus, store)
        self.assertEqual(retried.state, "ADMITTED")
        self.assertEqual(reg.current_version, 1)
        self.assertEqual(len(bus.messages("plugin.registered")), 1)

    def test_candidacy_publication_failure_is_not_rejected(self):
        candidacy = Candidacy(_active_capability_declaration("prov.pub.b", "cap.pub.b"))
        candidacy.begin()
        candidacy.validate()
        candidacy.mark_publication_failed()
        self.assertEqual(candidacy.state, "VALIDATED")
        self.assertIsNone(candidacy.failing_stage)
        self.assertIsNone(candidacy.refusal)
        # still admittable afterward -- same object, no new candidacy needed
        candidacy.admit(5)
        self.assertEqual(candidacy.state, "ADMITTED")


class RetirementEnactmentCase(unittest.TestCase):
    def test_a4_enacts_lifecycle_changed_never_originates(self):
        reg = Registry()
        reg.apply({"kind": "add_provider", "record": build_provider("prov.enact.a", "1.0")})
        v1 = enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.enact.a",
                                         "to_state": "active"})
        self.assertEqual(reg.get_provider("prov.enact.a").lifecycle, "active")
        self.assertEqual(reg.current_version, v1)

    def test_a11_atomic_binding_removal_and_historical_snapshots_unaffected(self):
        reg = Registry()
        reg.apply({"kind": "add_capability", "record": build_capability(
            "cap.enact.a", "d", "nlp", lifecycle="active",
            verification_expectations=("x",))})
        reg.apply({"kind": "add_provider", "record": build_provider("prov.enact.b", "1.0")})
        enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.enact.b",
                                    "to_state": "active"})
        reg.apply({"kind": "add_binding",
                  "record": build_binding("cap.enact.a", "prov.enact.b")})
        v_bound = reg.current_version
        self.assertEqual(len(reg.bindings_for("cap.enact.a")), 1)

        enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.enact.b",
                                    "to_state": "deprecated"})
        v_retired = enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.enact.b",
                                                "to_state": "retired"})
        self.assertEqual(reg.bindings_for("cap.enact.a"), [])
        self.assertEqual(reg.at_version(v_retired).bindings_for("cap.enact.a"), [])
        # historical version before retirement still shows the binding
        self.assertEqual(len(reg.at_version(v_bound).bindings_for("cap.enact.a")), 1)


class AliasRetirementGateCase(unittest.TestCase):
    def test_capability_with_live_alias_refuses_retirement(self):
        reg = Registry()
        reg.apply({"kind": "add_capability", "record": build_capability(
            "cap.alias.old", "d", "nlp", verification_expectations=("x",))})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.alias.old", "to_state": "active"})
        reg.apply({"kind": "add_capability", "record": build_capability(
            "cap.alias.new", "d", "nlp", aliases=("cap.alias.old.alt",),
            verification_expectations=("x",))})
        reg.apply({"kind": "lifecycle_transition", "entity": "capability",
                  "id": "cap.alias.new", "to_state": "active"})
        enact_lifecycle_event(reg, {"entity": "capability", "id": "cap.alias.new",
                                    "to_state": "deprecated"})
        with self.assertRaises(AliasTargetRetirementError):
            enact_lifecycle_event(reg, {"entity": "capability", "id": "cap.alias.new",
                                        "to_state": "retired"})
        # capability is still deprecated, not retired -- refusal left it untouched
        self.assertEqual(reg.get_capability("cap.alias.new").lifecycle, "deprecated")


class ReplayStabilityCase(unittest.TestCase):
    def test_at_version_content_identical_before_and_after_later_admissions(self):
        reg, bus, store = _new_env()
        decl1 = _active_capability_declaration("prov.replay.a", "cap.replay.a")
        c1 = admit(reg, decl1, bus, store)
        v1 = c1.minted_version
        snapshot_v1_before = reg.at_version(v1).get_provider("prov.replay.a")

        decl2 = _active_capability_declaration("prov.replay.b", "cap.replay.b")
        admit(reg, decl2, bus, store)

        snapshot_v1_after = reg.at_version(v1).get_provider("prov.replay.a")
        self.assertEqual(snapshot_v1_before, snapshot_v1_after)
        self.assertIsNone(reg.at_version(v1).get_provider("prov.replay.b"))


class CandidacyTerminalStateCase(unittest.TestCase):
    def test_rejected_is_terminal_no_resume(self):
        candidacy = Candidacy(build_declaration(build_provider("prov.term.a", "1.0")))
        candidacy.begin()
        candidacy.reject("identity", ValueError("boom"))
        with self.assertRaises(CandidacyError):
            candidacy.validate()
        with self.assertRaises(CandidacyError):
            candidacy.record_pass("late")


class RegressionCase(unittest.TestCase):
    def test_phase1_event_canon_still_holds(self):
        self.assertEqual(set(events.PUBLISHED), {
            "plugin.discovered", "plugin.registered", "plugin.loaded",
            "plugin.unloaded", "plugin.health.changed",
        })


if __name__ == "__main__":
    unittest.main()
