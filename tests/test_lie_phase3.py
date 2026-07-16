"""LIE Phase 3 suite — LIE/02 intelligence derivation (the Distillery).
Covers: ruleset as validated versioned data; Situation Signature;
evidence-set grouping/partitioning; all six derivation shapes; Maturity
Grades as a pure function of evidence + thresholds; Contested detection
with no automatic tie-break; contradiction_resolution rulings directing
fresh derivation; deprecation/supersession exclusion from fresh evidence
sets; automatic instead-of links; citation-chain walkability; Derivation
State stamping; determinism (byte-identical layers), order-insensitivity
(shuffled admission orders), and ruleset-version provenance changes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lie import derived
from lie import distillery
from lie import envelope as envelope_mod
from lie import ruleset as ruleset_mod
from lie.admission_receipt import AdmissionReceipt
from lie.curation import build_annotation
from lie.decision import build_decision
from lie.episode import build_episode
from lie.ledger import ExperienceLedger
from lie.overlay import CurationOverlay
from lie.storage_double import StorageDouble

APPROACH_A = {"a": "flash-old"}
APPROACH_B = {"a": "flash-new"}


def _episode(identity, project="p1", facets=("jetson",), verdict="passed",
             approach=None, outcome_extra=None):
    env = envelope_mod.build_envelope(
        identity, envelope_mod.build_attestation("trace:" + identity, True, 1),
        envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
    outcome = {"verdict": verdict}
    outcome.update(outcome_extra or {})
    return build_episode(env, situation={"s": 1}, approach=approach or {"a": 1},
                          outcome=outcome, cost={"c": 1})


def _decision(identity, project="p1", facets=("jetson",)):
    env = envelope_mod.build_envelope(
        identity, envelope_mod.build_attestation("trace:" + identity, True, 1),
        envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
    return build_decision(env, "q", ("a", "b"), "a", "r", {}, {})


def _stores(records=()):
    ledger = ExperienceLedger(StorageDouble())
    overlay = CurationOverlay(StorageDouble())
    for record in records:
        ledger.append(AdmissionReceipt(record))
    return ledger, overlay


def _hash(approach):
    return distillery._canonical_hash(approach)


class RulesetTests(unittest.TestCase):
    def test_default_ruleset_values_are_data(self):
        rs = ruleset_mod.default_ruleset()
        self.assertEqual(rs.version, 1)
        self.assertEqual(rs.pattern_min_episodes, 2)

    def test_thresholds_validated(self):
        for bad in (0, -1, True, "2"):
            with self.assertRaises(ruleset_mod.MalformedRulesetError):
                ruleset_mod.build_ruleset(1, pattern_min_episodes=bad, recipe_min_episodes=2,
                                           corroborated_min_episodes=2,
                                           established_min_projects=2)

    def test_pack_scopes_validated(self):
        with self.assertRaises(ruleset_mod.MalformedRulesetError):
            ruleset_mod.default_ruleset(pack_scopes={"ros2": ()})
        with self.assertRaises(ruleset_mod.MalformedRulesetError):
            ruleset_mod.default_ruleset(pack_scopes={"": ("ros2",)})

    def test_frozen_including_scopes(self):
        rs = ruleset_mod.default_ruleset(pack_scopes={"ros2": ("ros2",)})
        with self.assertRaises(AttributeError):
            rs.version = 2
        with self.assertRaises(TypeError):
            rs.pack_scopes["cuda"] = ("cuda",)

    def test_round_trip_deterministic(self):
        rs = ruleset_mod.build_ruleset(3, pattern_min_episodes=4, recipe_min_episodes=3,
                                        corroborated_min_episodes=5, established_min_projects=2,
                                        pack_scopes={"ros2": ("ros2", "jetson")})
        self.assertEqual(ruleset_mod.from_dict(ruleset_mod.to_dict(rs)), rs)
        self.assertEqual(ruleset_mod.to_dict(rs), ruleset_mod.to_dict(rs))


class SignatureTests(unittest.TestCase):
    def test_signature_is_sorted_unique_facets(self):
        ep = _episode("episode:e1", facets=("cuda", "jetson", "cuda"))
        self.assertEqual(distillery.signature_of(ep).facets, ("cuda", "jetson"))

    def test_signatures_comparable_value_objects(self):
        a = distillery.signature_of(_episode("episode:e1", facets=("jetson", "cuda")))
        b = distillery.signature_of(_episode("episode:e2", facets=("cuda", "jetson")))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_polarity_closed_two(self):
        self.assertEqual(distillery.polarity_of(_episode("episode:e1", verdict="passed")),
                          distillery.POSITIVE)
        self.assertEqual(distillery.polarity_of(_episode("episode:e2", verdict="failed")),
                          distillery.NEGATIVE)
        with self.assertRaises(distillery.UnknownVerdictError):
            distillery.polarity_of(_episode("episode:e3", verdict="maybe"))


class EvidenceSetTests(unittest.TestCase):
    def test_grouping_and_partitioning(self):
        eps = [
            _episode("episode:e1", facets=("jetson",), verdict="passed"),
            _episode("episode:e2", facets=("jetson",), verdict="failed"),
            _episode("episode:e3", facets=("cuda",), verdict="passed"),
        ]
        sets = distillery.evidence_sets(eps)
        jetson = sets[distillery.Signature(facets=("jetson",))]
        self.assertEqual([e.envelope.identity for e in jetson[distillery.POSITIVE]],
                          ["episode:e1"])
        self.assertEqual([e.envelope.identity for e in jetson[distillery.NEGATIVE]],
                          ["episode:e2"])

    def test_membership_sorted_by_identity_not_input_order(self):
        eps = [
            _episode("episode:z", verdict="passed"),
            _episode("episode:a", verdict="passed"),
        ]
        sets = distillery.evidence_sets(eps)
        members = sets[distillery.Signature(facets=("jetson",))][distillery.POSITIVE]
        self.assertEqual([e.envelope.identity for e in members], ["episode:a", "episode:z"])


class DerivationShapeTests(unittest.TestCase):
    def test_lesson_from_single_episode(self):
        ledger, overlay = _stores([_episode("episode:e1")])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        lesson = layer.by_identity("lesson:jetson:positive")
        self.assertIsNotNone(lesson)
        self.assertIn("1 episode(s)", lesson.statement)
        self.assertEqual(lesson.maturity, derived.MATURITY_PROVISIONAL)

    def test_pattern_requires_recurrence_threshold(self):
        below = _stores([_episode("episode:e1", approach=APPROACH_B)])
        layer_below = distillery.regenerate(*below, ruleset_mod.default_ruleset())
        self.assertEqual(layer_below.by_kind(derived.Pattern), ())

        at = _stores([_episode("episode:e1", approach=APPROACH_B),
                       _episode("episode:e2", approach=APPROACH_B)])
        layer_at = distillery.regenerate(*at, ruleset_mod.default_ruleset())
        patterns = layer_at.by_kind(derived.Pattern)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(dict(patterns[0].approach), APPROACH_B)

    def test_threshold_is_ruleset_data_not_compiler_constant(self):
        stores = _stores([_episode("episode:e1", approach=APPROACH_B),
                           _episode("episode:e2", approach=APPROACH_B)])
        strict = ruleset_mod.build_ruleset(1, pattern_min_episodes=3, recipe_min_episodes=3,
                                            corroborated_min_episodes=3,
                                            established_min_projects=3)
        layer = distillery.regenerate(*stores, strict)
        self.assertEqual(layer.by_kind(derived.Pattern), ())

    def test_anti_pattern_with_automatic_instead_of(self):
        ledger, overlay = _stores([
            _episode("episode:f1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", verdict="passed", approach=APPROACH_B),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        anti = layer.by_identity("anti_pattern:jetson:" + _hash(APPROACH_A))
        self.assertIsNotNone(anti)
        self.assertFalse(anti.contested)  # different approach -> instead-of, not conflict
        instead = [r for r in anti.envelope.relations if r.relation_type == "instead-of"]
        self.assertEqual(len(instead), 1)
        self.assertEqual(instead[0].target_id, "lesson:jetson:positive")

    def test_instead_of_prefers_a_compiled_pattern(self):
        ledger, overlay = _stores([
            _episode("episode:f1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", verdict="passed", approach=APPROACH_B),
            _episode("episode:r2", verdict="passed", approach=APPROACH_B),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        anti = layer.by_identity("anti_pattern:jetson:" + _hash(APPROACH_A))
        instead = [r for r in anti.envelope.relations if r.relation_type == "instead-of"]
        self.assertEqual(instead[0].target_id, "pattern:jetson:" + _hash(APPROACH_B))

    def test_no_instead_of_without_positive_evidence(self):
        ledger, overlay = _stores([
            _episode("episode:f1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", verdict="failed", approach=APPROACH_A),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        anti = layer.by_identity("anti_pattern:jetson:" + _hash(APPROACH_A))
        self.assertEqual([r for r in anti.envelope.relations
                           if r.relation_type == "instead-of"], [])

    def test_recipe_from_agreeing_step_threads(self):
        steps = {"steps": ["flash", "install", "build"]}
        ledger, overlay = _stores([
            _episode("episode:s1", facets=("ros2",), approach=steps),
            _episode("episode:s2", facets=("ros2",), approach=steps),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        recipes = layer.by_kind(derived.Recipe)
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0].steps, ("flash", "install", "build"))

    def test_disagreeing_step_threads_make_no_recipe(self):
        ledger, overlay = _stores([
            _episode("episode:s1", facets=("ros2",), approach={"steps": ["a", "b"]}),
            _episode("episode:s2", facets=("ros2",), approach={"steps": ["b", "a"]}),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertEqual(layer.by_kind(derived.Recipe), ())

    def test_dossier_compiled_per_project(self):
        ledger, overlay = _stores([
            _episode("episode:e1", project="p1", facets=("jetson",)),
            _decision("decision:d1", project="p1", facets=("jetson",)),
            _episode("episode:e2", project="p2", facets=("jetson", "cuda")),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        dossier = layer.by_identity("dossier:p1")
        self.assertEqual(dossier.episode_refs, ("episode:e1",))
        self.assertEqual(dossier.decision_refs, ("decision:d1",))
        self.assertEqual(dossier.lesson_refs, ("lesson:jetson:positive",))

    def test_dossier_relationships_cite_shared_facets(self):
        ledger, overlay = _stores([
            _episode("episode:e1", project="p1", facets=("jetson", "ros2")),
            _episode("episode:e2", project="p2", facets=("jetson", "cuda")),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        rel = layer.by_identity("dossier:p1").relationships[0]
        self.assertEqual(rel.other_project, "p2")
        self.assertEqual(rel.shared_facets, ("jetson",))  # never a bare scalar

    def test_pack_selects_from_layer_and_ledger_by_declared_scope(self):
        ledger, overlay = _stores([
            _episode("episode:b1", facets=("ros2",),
                      outcome_extra={"measurements": {"fps": 30}}),
            _episode("episode:o1", facets=("other",)),
        ])
        rs = ruleset_mod.default_ruleset(pack_scopes={"ros2-pack": ("ros2",)})
        layer = distillery.regenerate(ledger, overlay, rs)
        pack = layer.by_identity("pack:ros2-pack")
        self.assertIn("lesson:ros2:positive", pack.member_refs)
        self.assertIn("episode:b1", pack.member_refs)  # benchmark-bearing, in scope
        self.assertNotIn("lesson:other:positive", pack.member_refs)

    def test_pack_with_no_members_not_compiled(self):
        ledger, overlay = _stores([_episode("episode:e1", facets=("jetson",))])
        rs = ruleset_mod.default_ruleset(pack_scopes={"empty": ("nothing-here",)})
        layer = distillery.regenerate(ledger, overlay, rs)
        self.assertIsNone(layer.by_identity("pack:empty"))


class MaturityGradeTests(unittest.TestCase):
    def test_provisional_thin_evidence(self):
        ledger, overlay = _stores([_episode("episode:e1")])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertEqual(layer.by_identity("lesson:jetson:positive").maturity,
                          derived.MATURITY_PROVISIONAL)

    def test_corroborated_recurrence_within_one_project(self):
        ledger, overlay = _stores([_episode("episode:e1"), _episode("episode:e2")])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertEqual(layer.by_identity("lesson:jetson:positive").maturity,
                          derived.MATURITY_CORROBORATED)

    def test_established_spans_projects(self):
        ledger, overlay = _stores([
            _episode("episode:e1", project="p1"),
            _episode("episode:e2", project="p2"),
        ])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertEqual(layer.by_identity("lesson:jetson:positive").maturity,
                          derived.MATURITY_ESTABLISHED)

    def test_demotion_via_curation_exclusion(self):
        ledger, overlay = _stores([
            _episode("episode:e1", project="p1"),
            _episode("episode:e2", project="p2"),
        ])
        overlay.append(build_annotation("deprecation", ("episode:e2",), "bad data",
                                         ("episode:e1",)))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertEqual(layer.by_identity("lesson:jetson:positive").maturity,
                          derived.MATURITY_PROVISIONAL)


class ContestedTests(unittest.TestCase):
    def _conflicted_stores(self):
        return _stores([
            _episode("episode:c1", project="p1", facets=("cuda",), verdict="passed",
                      approach=APPROACH_A),
            _episode("episode:c2", project="p2", facets=("cuda",), verdict="passed",
                      approach=APPROACH_A),
            _episode("episode:c3", project="p1", facets=("cuda",), verdict="failed",
                      approach=APPROACH_A),
            _episode("episode:c4", project="p2", facets=("cuda",), verdict="failed",
                      approach=APPROACH_A),
        ])

    def test_same_signature_same_approach_opposite_valence_both_contested(self):
        ledger, overlay = self._conflicted_stores()
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        key = _hash(APPROACH_A)
        self.assertTrue(layer.by_identity("pattern:cuda:" + key).contested)
        self.assertTrue(layer.by_identity("anti_pattern:cuda:" + key).contested)

    def test_no_automatic_tie_break_both_sides_remain(self):
        # counts are asymmetric (3 positive vs 2 negative) -- count must NOT resolve
        ledger, overlay = self._conflicted_stores()
        ledger.append(AdmissionReceipt(_episode("episode:c5", project="p1", facets=("cuda",),
                                                  verdict="passed", approach=APPROACH_A)))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        key = _hash(APPROACH_A)
        self.assertTrue(layer.by_identity("pattern:cuda:" + key).contested)
        self.assertTrue(layer.by_identity("anti_pattern:cuda:" + key).contested)

    def test_contested_pair_gets_no_instead_of(self):
        ledger, overlay = self._conflicted_stores()
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        anti = layer.by_identity("anti_pattern:cuda:" + _hash(APPROACH_A))
        self.assertEqual([r for r in anti.envelope.relations
                           if r.relation_type == "instead-of"], [])

    def test_resolution_ruling_directs_fresh_derivation(self):
        ledger, overlay = self._conflicted_stores()
        key = _hash(APPROACH_A)
        overlay.append(build_annotation(
            "contradiction_resolution", ("anti_pattern:cuda:" + key,),
            "failures traced to a bad sensor batch", ("episode:c1", "episode:c2")))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertIsNone(layer.by_identity("anti_pattern:cuda:" + key))
        self.assertFalse(layer.by_identity("pattern:cuda:" + key).contested)

    def test_history_unchanged_ruling_only_affects_fresh_layers(self):
        ledger, overlay = self._conflicted_stores()
        key = _hash(APPROACH_A)
        before = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        overlay.append(build_annotation(
            "contradiction_resolution", ("anti_pattern:cuda:" + key,), "resolved",
            ("episode:c1",)))
        after = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertTrue(before.by_identity("anti_pattern:cuda:" + key).contested)
        self.assertIsNone(after.by_identity("anti_pattern:cuda:" + key))
        self.assertNotEqual(before.derivation_state, after.derivation_state)


class CurationWeightingTests(unittest.TestCase):
    def test_deprecated_records_excluded_from_fresh_sets(self):
        ledger, overlay = _stores([
            _episode("episode:f1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", verdict="failed", approach=APPROACH_A),
        ])
        overlay.append(build_annotation("deprecation", ("episode:f2",), "bad sensor",
                                         ("episode:f1",)))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertIsNone(layer.by_identity("anti_pattern:jetson:" + _hash(APPROACH_A)))

    def test_superseded_records_contribute_only_via_superseder(self):
        ledger, overlay = _stores([
            _episode("episode:old", verdict="passed", approach=APPROACH_A),
            _episode("episode:new", verdict="passed", approach=APPROACH_B),
        ])
        overlay.append(build_annotation("supersession", ("episode:old",),
                                         "re-attempted with better evidence",
                                         ("episode:new",)))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        lesson = layer.by_identity("lesson:jetson:positive")
        evidence = [r.target_id for r in lesson.envelope.relations
                     if r.relation_type == "evidenced-by"]
        self.assertEqual(evidence, ["episode:new"])  # superseder carries the weight

    def test_ledger_untouched_by_rulings(self):
        ledger, overlay = _stores([_episode("episode:e1")])
        overlay.append(build_annotation("deprecation", ("episode:e1",), "r",
                                         ("episode:e2",)))
        distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        self.assertIsNotNone(ledger.by_identity("episode:e1"))  # INV-2: never mutated


class CitationChainTests(unittest.TestCase):
    def test_chain_walks_artifact_to_attestation(self):
        ledger, overlay = _stores([_episode("episode:e1"), _episode("episode:e2")])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        lesson = layer.by_identity("lesson:jetson:positive")
        chain = distillery.citation_chain(lesson, ledger)
        self.assertEqual([l["evidence"] for l in chain], ["episode:e1", "episode:e2"])
        self.assertEqual(chain[0]["attestation_ref"], "trace:episode:e1")
        self.assertEqual(chain[0]["artifact"], "lesson:jetson:positive")

    def test_unresolvable_link_raises_loud(self):
        ledger, overlay = _stores([_episode("episode:e1")])
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        lesson = layer.by_identity("lesson:jetson:positive")
        empty_ledger = ExperienceLedger(StorageDouble())
        with self.assertRaises(distillery.UnwalkableChainError):
            distillery.citation_chain(lesson, empty_ledger)


class DerivationStateStampTests(unittest.TestCase):
    def test_layer_and_every_artifact_stamped(self):
        ledger, overlay = _stores([_episode("episode:e1")])
        overlay.append(build_annotation("deprecation", ("episode:x",), "r", ("episode:y",)))
        rs = ruleset_mod.default_ruleset(version=7)
        layer = distillery.regenerate(ledger, overlay, rs)
        self.assertEqual(layer.derivation_state.ledger_position, 1)
        self.assertEqual(layer.derivation_state.overlay_position, 1)
        self.assertEqual(layer.derivation_state.ruleset_version, 7)
        for artifact in layer.artifacts:
            self.assertEqual(artifact.envelope.attestation.derivation_state,
                              layer.derivation_state)


class DeterminismTests(unittest.TestCase):
    def _records(self):
        return [
            _episode("episode:f1", project="p1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", project="p2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", project="p1", verdict="passed", approach=APPROACH_B),
            _episode("episode:s1", project="p1", facets=("ros2",),
                      approach={"steps": ["a", "b"]}),
            _episode("episode:s2", project="p2", facets=("ros2",),
                      approach={"steps": ["a", "b"]}),
            _decision("decision:d1", project="p1"),
        ]

    def test_identical_inputs_byte_identical_layers(self):
        rs = ruleset_mod.default_ruleset(pack_scopes={"ros2": ("ros2",)})
        layer_a = distillery.regenerate(*_stores(self._records()), rs)
        layer_b = distillery.regenerate(*_stores(self._records()), rs)
        self.assertEqual(distillery.layer_canonical(layer_a),
                          distillery.layer_canonical(layer_b))

    def test_order_insensitivity_shuffled_admission_orders(self):
        rs = ruleset_mod.default_ruleset(pack_scopes={"ros2": ("ros2",)})
        records = self._records()
        reference = distillery.layer_canonical(distillery.regenerate(*_stores(records), rs))
        # deterministic "shuffles": reversed, and rotated by 2 (no randomness)
        for reordered in (list(reversed(records)), records[2:] + records[:2]):
            layer = distillery.regenerate(*_stores(reordered), rs)
            self.assertEqual(distillery.layer_canonical(layer), reference)

    def test_ruleset_version_changes_provenance_stamps(self):
        layer_v1 = distillery.regenerate(*_stores(self._records()),
                                          ruleset_mod.default_ruleset(version=1))
        layer_v2 = distillery.regenerate(*_stores(self._records()),
                                          ruleset_mod.default_ruleset(version=2))
        self.assertEqual(layer_v1.derivation_state.ruleset_version, 1)
        self.assertEqual(layer_v2.derivation_state.ruleset_version, 2)
        self.assertNotEqual(distillery.layer_canonical(layer_v1),
                             distillery.layer_canonical(layer_v2))

    def test_layer_round_trips_through_derived_from_dict(self):
        rs = ruleset_mod.default_ruleset()
        layer = distillery.regenerate(*_stores(self._records()), rs)
        for artifact in layer.artifacts:
            self.assertEqual(derived.from_dict(derived.to_dict(artifact)), artifact)

    def test_empty_ledger_compiles_empty_layer(self):
        layer = distillery.regenerate(*_stores(), ruleset_mod.default_ruleset())
        self.assertEqual(layer.artifacts, ())
        self.assertEqual(layer.derivation_state.ledger_position, 0)

    def test_unbuilt_ruleset_refused(self):
        ledger, overlay = _stores()
        with self.assertRaises(distillery.MalformedCompilerInputError):
            distillery.regenerate(ledger, overlay, {"version": 1})


if __name__ == "__main__":
    unittest.main()
