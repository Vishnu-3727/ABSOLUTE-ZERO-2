"""LIE Phase 2 suite — LIE/01 engineering knowledge model (derived
artifact record MODELS only, no derivation logic). Covers: the six
intelligence-layer record kinds (Lesson, Pattern, AntiPattern, Recipe,
ProjectDossier, DomainKnowledgePack); derivation-flavored attestation
(LIE/01 §3) required on derived records and refused on experience records;
INV-4 at construction time (no `evidenced-by` citation → no record);
maturity placeholder pinned until the ladder's owning phase; ordered recipe
steps; relationship statements citing shared facets (never bare scalars);
knowledge-class tagging derived from record type (LIE/01 §2); Architecture
Records as facet-scoped Decisions (LIE/01 §4.2); INV-7 round-trip
determinism for every new type; Phase 1 invariants unweakened."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lie import curation
from lie import decision as decision_mod
from lie import derived
from lie import envelope as envelope_mod
from lie import episode as episode_mod
from lie.derivation_state import build_derivation_state


def _experience_env(identity="episode:e1", facets=("ros2",), relations=()):
    return envelope_mod.build_envelope(
        identity,
        envelope_mod.build_attestation("trace:t1", True, 1),
        envelope_mod.build_origin("asunama", "isaac-sim", "vishnu", "epoch-0"),
        facets, relations)


def _derived_env(identity="lesson:l1", facets=("ros2",), relations=None,
                 derivation_state=(3, 1, 1)):
    if relations is None:
        relations = (envelope_mod.build_relation("evidenced-by", "episode:e1"),)
    return envelope_mod.build_envelope(
        identity,
        envelope_mod.build_derivation_attestation(build_derivation_state(*derivation_state)),
        envelope_mod.build_origin("asunama", "isaac-sim", "vishnu", "epoch-0"),
        facets, relations)


def _episode(env=None):
    return episode_mod.build_episode(
        env or _experience_env(), situation={"needed": "nav"}, approach={"steps": ["slam"]},
        outcome={"verdict": "passed"}, cost={"retries": 0})


def _decision(env=None):
    return decision_mod.build_decision(
        env or _experience_env("decision:d1"), question="which stack?", options=("a", "b"),
        chosen="a", rationale="better", constraints={}, consequences_expected={})


class DerivationAttestationTests(unittest.TestCase):
    def test_build_derivation_attestation(self):
        att = envelope_mod.build_derivation_attestation(build_derivation_state(3, 1, 1))
        self.assertEqual(att.derivation_state.ledger_position, 3)

    def test_unbuilt_derivation_state_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_derivation_attestation({"ledger_position": 3})

    def test_derived_envelope_builds_and_is_frozen(self):
        env = _derived_env()
        self.assertEqual(env.attestation.derivation_state.ruleset_version, 1)
        with self.assertRaises(AttributeError):
            env.attestation = None

    def test_derived_envelope_round_trips_deterministically(self):
        env = _derived_env()
        d1 = envelope_mod.to_dict(env)
        d2 = envelope_mod.to_dict(env)
        self.assertEqual(d1, d2)
        restored = envelope_mod.from_dict(d1)
        self.assertEqual(restored, env)
        self.assertEqual(envelope_mod.canonical(env), envelope_mod.canonical(restored))

    def test_experience_envelope_dicts_unchanged_from_phase_1(self):
        env = _experience_env()
        d = envelope_mod.to_dict(env)
        self.assertIn("attestation_ref", d["attestation"])
        self.assertNotIn("derivation_state", d["attestation"])
        self.assertEqual(envelope_mod.from_dict(d), env)


class AttestationFlavorSeparationTests(unittest.TestCase):
    """Experience records demand VAE attestation; derived records demand
    derivation attestation. Neither flavor crosses the layer boundary."""

    def test_episode_refuses_derivation_attestation(self):
        with self.assertRaises(episode_mod.MalformedEpisodeError):
            episode_mod.build_episode(_derived_env("episode:x"), situation={"a": 1},
                                       approach={"a": 1}, outcome={"a": 1}, cost={"a": 1})

    def test_decision_refuses_derivation_attestation(self):
        with self.assertRaises(decision_mod.MalformedDecisionError):
            decision_mod.build_decision(_derived_env("decision:x"), "q", ("a",), "a", "r", {}, {})

    def test_derived_record_refuses_experience_attestation(self):
        env = _experience_env("lesson:x", relations=(
            envelope_mod.build_relation("evidenced-by", "episode:e1"),))
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_lesson(env, "statement")

    def test_phase_1_experience_construction_still_works(self):
        self.assertEqual(_episode().outcome["verdict"], "passed")
        self.assertEqual(_decision().chosen, "a")


class EvidenceCitationTests(unittest.TestCase):
    """INV-4's mechanism: a derived record without at least one
    `evidenced-by` relation is never built."""

    def test_every_kind_refuses_construction_without_citation(self):
        env = _derived_env(relations=())
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_lesson(env, "s")
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_pattern(env, {"a": 1})
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_anti_pattern(env, {"a": 1}, "c")
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_recipe(env, ("step",))
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_project_dossier(env, "p", (), (), (), ())
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_domain_knowledge_pack(env, ("lesson:l1",))

    def test_non_evidence_relations_do_not_satisfy_the_citation_rule(self):
        env = _derived_env(relations=(envelope_mod.build_relation("about", "ums:x"),))
        with self.assertRaises(derived.MissingEvidenceCitationError):
            derived.build_lesson(env, "s")

    def test_one_citation_suffices(self):
        lesson = derived.build_lesson(_derived_env(), "s")
        self.assertEqual(lesson.envelope.relations[0].relation_type, "evidenced-by")


class LessonTests(unittest.TestCase):
    def test_build_and_frozen(self):
        lesson = derived.build_lesson(_derived_env(), "monocular SLAM drifts indoors")
        self.assertEqual(lesson.statement, "monocular SLAM drifts indoors")
        with self.assertRaises(AttributeError):
            lesson.statement = "other"

    def test_empty_statement_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_lesson(_derived_env(), "")

    def test_scope_is_the_envelope_facets(self):
        lesson = derived.build_lesson(_derived_env(facets=("ros2", "cuda")), "s")
        self.assertEqual(lesson.envelope.facets, ("ros2", "cuda"))


class PatternAndAntiPatternTests(unittest.TestCase):
    def test_pattern_build_and_frozen_content(self):
        pattern = derived.build_pattern(_derived_env("pattern:p1"), {"approach": "orb-slam3"})
        with self.assertRaises(AttributeError):
            pattern.approach = {}
        with self.assertRaises(TypeError):
            pattern.approach["approach"] = "x"

    def test_pattern_empty_approach_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_pattern(_derived_env("pattern:p2"), {})

    def test_anti_pattern_carries_observed_consequence(self):
        anti = derived.build_anti_pattern(_derived_env("anti:a1"), {"a": "raw GPS indoors"},
                                           "position diverges")
        self.assertEqual(anti.consequence, "position diverges")

    def test_anti_pattern_empty_consequence_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_anti_pattern(_derived_env("anti:a2"), {"a": 1}, "")

    def test_anti_pattern_instead_of_relation_is_optional_and_allowed(self):
        with_alt = derived.build_anti_pattern(
            _derived_env("anti:a3", relations=(
                envelope_mod.build_relation("evidenced-by", "episode:e1"),
                envelope_mod.build_relation("instead-of", "pattern:p1"))),
            {"a": 1}, "c")
        self.assertTrue(any(r.relation_type == "instead-of" for r in with_alt.envelope.relations))
        without_alt = derived.build_anti_pattern(_derived_env("anti:a4"), {"a": 1}, "c")
        self.assertFalse(any(r.relation_type == "instead-of"
                              for r in without_alt.envelope.relations))


class RecipeTests(unittest.TestCase):
    def test_steps_ordered_and_preserved(self):
        recipe = derived.build_recipe(_derived_env("recipe:r1"),
                                       ("flash jetson", "install ros2", "build ws"))
        self.assertEqual(recipe.steps, ("flash jetson", "install ros2", "build ws"))

    def test_step_order_survives_round_trip_never_sorted(self):
        steps = ("z step", "a step", "m step")  # deliberately unsorted
        recipe = derived.build_recipe(_derived_env("recipe:r2"), steps)
        restored = derived.from_dict(derived.to_dict(recipe))
        self.assertEqual(restored.steps, steps)

    def test_empty_steps_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_recipe(_derived_env("recipe:r3"), ())

    def test_empty_step_string_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_recipe(_derived_env("recipe:r4"), ("ok", ""))

    def test_facet_scope_always_present(self):
        # build_envelope already refuses empty facets, so every recipe has
        # a non-empty scope by construction; assert the chain holds.
        recipe = derived.build_recipe(_derived_env("recipe:r5", facets=("jetson",)), ("s",))
        self.assertEqual(recipe.envelope.facets, ("jetson",))


class ProjectDossierTests(unittest.TestCase):
    def test_build_dossier(self):
        rel = derived.build_project_relationship("other-drone", ("ros2", "cuda"))
        dossier = derived.build_project_dossier(
            _derived_env("dossier:d1"), "asunama", ("decision:d1",), ("episode:e1",),
            ("lesson:l1",), (rel,))
        self.assertEqual(dossier.project, "asunama")
        self.assertEqual(dossier.relationships[0].other_project, "other-drone")

    def test_empty_ref_lists_are_legitimate(self):
        dossier = derived.build_project_dossier(_derived_env("dossier:d2"), "young-project",
                                                 (), (), (), ())
        self.assertEqual(dossier.decision_refs, ())
        self.assertEqual(dossier.relationships, ())

    def test_relationship_must_cite_shared_facets_never_bare_scalar(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_project_relationship("other", ())

    def test_unbuilt_relationship_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_project_dossier(_derived_env("dossier:d3"), "p", (), (), (),
                                           ({"other_project": "x"},))

    def test_empty_project_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_project_dossier(_derived_env("dossier:d4"), "", (), (), (), ())


class DomainKnowledgePackTests(unittest.TestCase):
    def test_declared_scope_is_the_envelope_facets(self):
        pack = derived.build_domain_knowledge_pack(
            _derived_env("pack:ros2", facets=("ros2",)), ("lesson:l1", "pattern:p1"))
        self.assertEqual(pack.envelope.facets, ("ros2",))
        self.assertEqual(pack.member_refs, ("lesson:l1", "pattern:p1"))

    def test_empty_membership_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_domain_knowledge_pack(_derived_env("pack:x"), ())

    def test_membership_is_identifier_strings_only(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.build_domain_knowledge_pack(_derived_env("pack:y"),
                                                 ({"artifact": "content"},))


class MaturityPlaceholderTests(unittest.TestCase):
    def test_every_kind_pinned_to_provisional(self):
        for artifact in self._all_kinds():
            self.assertEqual(artifact.maturity, derived.MATURITY_PROVISIONAL)

    def test_builders_take_no_maturity_argument(self):
        with self.assertRaises(TypeError):
            derived.build_lesson(_derived_env(), "s", maturity="established")

    def test_from_dict_refuses_non_placeholder_maturity(self):
        d = derived.to_dict(derived.build_lesson(_derived_env(), "s"))
        d["maturity"] = "established"
        with self.assertRaises(derived.MaturityNotAvailableError):
            derived.from_dict(d)

    @staticmethod
    def _all_kinds():
        return (
            derived.build_lesson(_derived_env("lesson:l1"), "s"),
            derived.build_pattern(_derived_env("pattern:p1"), {"a": 1}),
            derived.build_anti_pattern(_derived_env("anti:a1"), {"a": 1}, "c"),
            derived.build_recipe(_derived_env("recipe:r1"), ("s",)),
            derived.build_project_dossier(_derived_env("dossier:d1"), "p", (), (), (), ()),
            derived.build_domain_knowledge_pack(_derived_env("pack:p1"), ("lesson:l1",)),
        )


class KnowledgeClassTests(unittest.TestCase):
    def test_experience_class(self):
        self.assertEqual(derived.knowledge_class(_episode()), derived.EXPERIENCE)
        self.assertEqual(derived.knowledge_class(_decision()), derived.EXPERIENCE)

    def test_intelligence_class(self):
        for artifact in MaturityPlaceholderTests._all_kinds():
            self.assertEqual(derived.knowledge_class(artifact), derived.INTELLIGENCE)

    def test_curation_class(self):
        ann = curation.build_annotation("deprecation", ("episode:e1",), "r", ("episode:e2",))
        self.assertEqual(derived.knowledge_class(ann), derived.CURATION)

    def test_non_record_refused(self):
        with self.assertRaises(derived.UnknownKnowledgeRecordError):
            derived.knowledge_class({"kind": "episode"})

    def test_closed_class_set(self):
        self.assertEqual(derived.KNOWLEDGE_CLASSES, ("experience", "intelligence", "curation"))


class ArchitectureRecordTests(unittest.TestCase):
    """LIE/01 §4.2: Architecture Records are Decisions with architectural
    scope — a facet, not a subclass."""

    def test_decision_with_architecture_facet_is_architecture_record(self):
        env = _experience_env("decision:d1", facets=("ros2", decision_mod.ARCHITECTURE_FACET))
        dec = decision_mod.build_decision(env, "q", ("a",), "a", "r", {}, {})
        self.assertTrue(decision_mod.is_architecture_record(dec))

    def test_ordinary_decision_is_not(self):
        self.assertFalse(decision_mod.is_architecture_record(_decision()))

    def test_no_subclass_exists(self):
        self.assertFalse(hasattr(decision_mod, "ArchitectureRecord"))
        self.assertFalse(hasattr(derived, "ArchitectureRecord"))


class DerivedSerializationRoundTripTests(unittest.TestCase):
    """INV-7 for every new type: human-readable, deterministic,
    round-trippable plain data."""

    def _all_kinds(self):
        rel = derived.build_project_relationship("other", ("ros2",))
        return (
            derived.build_lesson(_derived_env("lesson:l1"), "s"),
            derived.build_pattern(_derived_env("pattern:p1"), {"a": 1}),
            derived.build_anti_pattern(
                _derived_env("anti:a1", relations=(
                    envelope_mod.build_relation("evidenced-by", "episode:e1"),
                    envelope_mod.build_relation("instead-of", "pattern:p1"))),
                {"a": 1}, "c"),
            derived.build_recipe(_derived_env("recipe:r1"), ("s1", "s2")),
            derived.build_project_dossier(_derived_env("dossier:d1"), "p",
                                           ("decision:d1",), ("episode:e1",), ("lesson:l1",),
                                           (rel,)),
            derived.build_domain_knowledge_pack(_derived_env("pack:p1"), ("lesson:l1",)),
        )

    def test_round_trip_every_kind(self):
        for artifact in self._all_kinds():
            d = derived.to_dict(artifact)
            self.assertEqual(derived.from_dict(d), artifact)
            self.assertEqual(derived.to_dict(derived.from_dict(d)), d)

    def test_to_dict_deterministic(self):
        for artifact in self._all_kinds():
            self.assertEqual(derived.to_dict(artifact), derived.to_dict(artifact))

    def test_dicts_are_plain_json_data(self):
        for artifact in self._all_kinds():
            json.dumps(derived.to_dict(artifact))  # raises on any exotic type

    def test_kind_tags_match_closed_set(self):
        kinds = tuple(derived.to_dict(a)["kind"] for a in self._all_kinds())
        self.assertEqual(kinds, derived.DERIVED_KINDS)

    def test_from_dict_unknown_kind_refused(self):
        with self.assertRaises(derived.MalformedDerivedRecordError):
            derived.from_dict({"kind": "wisdom", "maturity": "provisional"})


if __name__ == "__main__":
    unittest.main()
