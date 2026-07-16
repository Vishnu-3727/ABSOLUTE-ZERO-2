"""LIE Phase 5 suite — architecture freeze validation (LIE/04). Covers:
the Curator subsystem (rulings lifecycle, vocabulary ownership, ruleset
version governance, Contested queue processing — LIE/04 §6 Curator
contract); responsibility-separation enforcement across all five
subsystem boundaries ("no component grades its own homework", LIE/00 §8);
the two Phase 3 precision calls re-verified against the frozen docs
(contested vs instead-of at approach granularity, LIE/02 §7 + LIE/04 §1;
contradiction_resolution target_ids = ruled-AGAINST side, LIE/02 §8);
Gate vocabulary adoption (normalization onto the CURRENT vocabulary, R2);
end-to-end integration Gate -> Ledger -> Distillery -> Advisory ->
Curator and back around the loop; replay/regeneration/migration
equivalence (LIE/03 §8: "all the same operation"); and a final
invariant sweep over INV-1..10 and OPS-1..8 enforcement points."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lie import derived
from lie import distillery
from lie import envelope as envelope_mod
from lie import ruleset as ruleset_mod
from lie.admission_receipt import AdmissionReceipt
from lie.advisory import AdvisoryInterface, NoRelevantExperience, Recommendation
from lie.bus_double import BusDouble
from lie.contracts import CuratorPort
from lie.curation import build_annotation
from lie.curator import (Curator, MalformedCuratorInputError,
                          RulesetVersionNotAdvancingError)
from lie.episode import build_episode
from lie.gate import ADMITTED, AdmissionGate, GateRefusal, REJECTED
from lie.ledger import ExperienceLedger, UnauthorizedAppendError
from lie.overlay import CurationOverlay
from lie.runtime import LieRuntime
from lie.storage_double import StorageDouble
from lie.telemetry_double import ObservabilityDouble
from lie.vocabulary import VocabularyNotAdditiveError, build_vocabulary

APPROACH_A = {"a": "flash-old"}
APPROACH_B = {"a": "flash-new"}


def _episode(identity, project="p1", facets=("jetson",), verdict="passed", approach=None,
             attestation_ref=None, vocabulary_version=1):
    env = envelope_mod.build_envelope(
        identity,
        envelope_mod.build_attestation(attestation_ref or "trace:" + identity, True,
                                        vocabulary_version),
        envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
    return build_episode(env, situation={"s": 1}, approach=approach or {"a": 1},
                          outcome={"verdict": verdict}, cost={"c": 1})


def _stores():
    return ExperienceLedger(StorageDouble()), CurationOverlay(StorageDouble())


def _contested_stores():
    """Same signature, SAME approach, opposite valence at threshold."""
    ledger, overlay = _stores()
    for i, verdict in enumerate(("passed", "passed", "failed", "failed")):
        ledger.append(AdmissionReceipt(_episode(
            "episode:c" + str(i), project="p" + str(i % 2), facets=("cuda",),
            verdict=verdict, approach=APPROACH_A)))
    return ledger, overlay


class CuratorRulingTests(unittest.TestCase):
    def _curator(self):
        overlay = CurationOverlay(StorageDouble())
        return Curator(overlay, build_vocabulary(1, {"jetson", "cuda"}),
                        ruleset_mod.default_ruleset()), overlay

    def test_rule_appends_and_returns_citable_position(self):
        curator, overlay = self._curator()
        pos = curator.rule(build_annotation("deprecation", ("episode:e1",), "bad sensor",
                                              ("episode:e2",)))
        self.assertEqual(pos, 1)
        self.assertEqual(overlay.by_position(1).annotation.kind, "deprecation")

    def test_overlay_position_advances_monotonically(self):
        curator, overlay = self._curator()
        positions = [curator.rule(build_annotation("deprecation", ("episode:e" + str(i),),
                                                     "r", ("episode:x",)))
                      for i in range(3)]
        self.assertEqual(positions, [1, 2, 3])

    def test_unbuilt_ruling_refused(self):
        curator, _ = self._curator()
        with self.assertRaises(MalformedCuratorInputError):
            curator.rule({"kind": "deprecation"})

    def test_implements_curator_port(self):
        # the seam contracts.py fixed in Phase 1: rule(annotation) -> int
        self.assertTrue(callable(getattr(Curator, "rule")))
        self.assertIn("rule", vars(CuratorPort))

    def test_curator_construction_validated(self):
        with self.assertRaises(MalformedCuratorInputError):
            Curator("not overlay", build_vocabulary(1, {"a"}), ruleset_mod.default_ruleset())
        with self.assertRaises(MalformedCuratorInputError):
            Curator(CurationOverlay(StorageDouble()), {"v": 1}, ruleset_mod.default_ruleset())
        with self.assertRaises(MalformedCuratorInputError):
            Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"a"}), {"v": 1})


class CuratorVocabularyTests(unittest.TestCase):
    def test_additive_evolution_advances_version_and_keeps_history(self):
        v1 = build_vocabulary(1, {"jetson"})
        curator = Curator(CurationOverlay(StorageDouble()), v1, ruleset_mod.default_ruleset())
        v2 = curator.evolve_vocabulary({"jetson", "cuda"})
        self.assertEqual(v2.version, 2)
        self.assertIs(curator.current_vocabulary(), v2)
        self.assertIs(curator.vocabulary_version(1), v1)  # never deleted

    def test_removal_or_rename_refused_and_state_unchanged(self):
        curator = Curator(CurationOverlay(StorageDouble()),
                           build_vocabulary(1, {"jetson", "cuda"}),
                           ruleset_mod.default_ruleset())
        with self.assertRaises(VocabularyNotAdditiveError):
            curator.evolve_vocabulary({"jetson"})
        self.assertEqual(curator.current_vocabulary().version, 1)


class CuratorRulesetGovernanceTests(unittest.TestCase):
    def test_adoption_is_monotonic_and_history_retained(self):
        rs1 = ruleset_mod.default_ruleset()
        curator = Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"a"}), rs1)
        rs2 = ruleset_mod.default_ruleset(version=2)
        curator.adopt_ruleset(rs2)
        self.assertIs(curator.current_ruleset(), rs2)
        self.assertIs(curator.ruleset_version(1), rs1)  # reconstructible forever
        for bad in (1, 2):
            with self.assertRaises(RulesetVersionNotAdvancingError):
                curator.adopt_ruleset(ruleset_mod.default_ruleset(version=bad))

    def test_historical_layer_reconstructible_from_retained_version(self):
        # LIE/03 §6: "any historical layer state remains reconstructible
        # from its Derivation State triple" -- the retained old ruleset is
        # the third leg of that triple.
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        rs1 = ruleset_mod.default_ruleset()
        curator = Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"jetson"}), rs1)
        historical = distillery.layer_canonical(distillery.regenerate(ledger, overlay, rs1))
        curator.adopt_ruleset(ruleset_mod.default_ruleset(version=2))
        reconstructed = distillery.layer_canonical(
            distillery.regenerate(ledger, overlay, curator.ruleset_version(1)))
        self.assertEqual(historical, reconstructed)


class ContestedQueueTests(unittest.TestCase):
    def test_queue_lists_flagged_pairs_from_published_layer(self):
        ledger, overlay = _contested_stores()
        rs = ruleset_mod.default_ruleset()
        curator = Curator(overlay, build_vocabulary(1, {"cuda"}), rs)
        layer = distillery.regenerate(ledger, overlay, rs)
        queue = curator.contested_queue(layer)
        self.assertEqual(len(queue), 2)  # both sides of the pair
        self.assertTrue(all(a.contested for a in queue))

    def test_processing_the_queue_empties_it(self):
        ledger, overlay = _contested_stores()
        rs = ruleset_mod.default_ruleset()
        curator = Curator(overlay, build_vocabulary(1, {"cuda"}), rs)
        layer = distillery.regenerate(ledger, overlay, rs)
        anti_id = next(a.envelope.identity for a in curator.contested_queue(layer)
                        if isinstance(a, derived.AntiPattern))
        curator.rule(build_annotation("contradiction_resolution", (anti_id,),
                                        "failures traced to bad sensor batch",
                                        ("episode:c0", "episode:c1")))
        fresh = distillery.regenerate(ledger, overlay, rs)
        self.assertEqual(curator.contested_queue(fresh), ())

    def test_queue_is_computed_never_stored(self):
        curator = Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"a"}),
                           ruleset_mod.default_ruleset())
        self.assertFalse(any("queue" in n for n in vars(curator)))
        with self.assertRaises(MalformedCuratorInputError):
            curator.contested_queue("not a layer")


class PrecisionCallTests(unittest.TestCase):
    """The two Phase 3 precision calls, re-verified against the frozen
    docs — no behavior change, verification only."""

    def test_call_1_contested_is_same_approach_only(self):
        # LIE/02 §7 / LIE/04 §1: same signature + SAME approach + opposite
        # valence = Contested. Same signature + DIFFERENT approach +
        # opposite valence = the failure/recovery shape -> instead-of link,
        # never contested. Both shapes in one layer:
        ledger, overlay = _stores()
        for ep in (
            _episode("episode:f1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", verdict="passed", approach=APPROACH_B),  # different approach
        ):
            ledger.append(AdmissionReceipt(ep))
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        anti = next(a for a in layer.by_kind(derived.AntiPattern))
        self.assertFalse(anti.contested)  # different approach: NOT a conflict
        self.assertTrue(any(r.relation_type == "instead-of"
                             for r in anti.envelope.relations))  # compiled, not authored

        contested_ledger, contested_overlay = _contested_stores()  # SAME approach
        contested_layer = distillery.regenerate(contested_ledger, contested_overlay,
                                                  ruleset_mod.default_ruleset())
        c_anti = next(a for a in contested_layer.by_kind(derived.AntiPattern))
        self.assertTrue(c_anti.contested)  # same approach: conflict, both flagged
        self.assertFalse(any(r.relation_type == "instead-of"
                              for r in c_anti.envelope.relations))  # no side taken

    def test_call_2_resolution_targets_name_the_ruled_against_side(self):
        # LIE/02 §8 "derivation follows the ruling": target_ids name the
        # side fresh derivation DROPS; the untargeted side survives,
        # un-contested. Verified in both directions.
        rs = ruleset_mod.default_ruleset()
        for loser_kind, survivor_kind in ((derived.AntiPattern, derived.Pattern),
                                            (derived.Pattern, derived.AntiPattern)):
            ledger, overlay = _contested_stores()
            layer = distillery.regenerate(ledger, overlay, rs)
            loser_id = next(a.envelope.identity for a in layer.artifacts
                             if isinstance(a, loser_kind) and a.contested)
            overlay.append(build_annotation("contradiction_resolution", (loser_id,),
                                              "ruled against", ("episode:c0",)))
            fresh = distillery.regenerate(ledger, overlay, rs)
            self.assertIsNone(fresh.by_identity(loser_id))          # dropped
            survivor = next(a for a in fresh.artifacts if isinstance(a, survivor_kind))
            self.assertFalse(survivor.contested)                     # un-contested


class GateVocabularyAdoptionTests(unittest.TestCase):
    def test_gate_admits_new_facets_after_adoption(self):
        ledger = ExperienceLedger(StorageDouble())
        curator = Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"jetson"}),
                           ruleset_mod.default_ruleset())
        gate = AdmissionGate(ledger, curator.current_vocabulary(), ObservabilityDouble())

        before = gate.admit(_episode("episode:new", facets=("ros2",),
                                       attestation_ref="trace:t1"))
        self.assertEqual(before.outcome, REJECTED)
        self.assertTrue(before.reason.startswith("unknown_facet"))

        gate.adopt_vocabulary(curator.evolve_vocabulary({"jetson", "ros2"}))
        after = gate.admit(_episode("episode:new2", facets=("ros2",),
                                      attestation_ref="trace:t2", vocabulary_version=2))
        self.assertEqual(after.outcome, ADMITTED)

    def test_adoption_is_forward_only(self):
        gate = AdmissionGate(ExperienceLedger(StorageDouble()),
                              build_vocabulary(2, {"jetson"}), ObservabilityDouble())
        for bad in (build_vocabulary(1, {"jetson"}), build_vocabulary(2, {"jetson"})):
            with self.assertRaises(GateRefusal):
                gate.adopt_vocabulary(bad)
        with self.assertRaises(GateRefusal):
            gate.adopt_vocabulary({"version": 3})


class ResponsibilitySeparationTests(unittest.TestCase):
    """LIE/00 §8.6 "no component grades its own homework" + LIE/04 §2
    leak checks, enforced structurally: forbidden surfaces do not exist."""

    def test_curator_cannot_admit_compile_or_advise(self):
        curator = Curator(CurationOverlay(StorageDouble()), build_vocabulary(1, {"a"}),
                           ruleset_mod.default_ruleset())
        for forbidden in ("admit", "append", "regenerate", "absorb", "consult"):
            self.assertFalse(hasattr(curator, forbidden))

    def test_gate_cannot_derive_or_rule(self):
        gate = AdmissionGate(ExperienceLedger(StorageDouble()),
                              build_vocabulary(1, {"a"}), ObservabilityDouble())
        for forbidden in ("regenerate", "absorb", "consult", "rule", "publish"):
            self.assertFalse(hasattr(gate, forbidden))

    def test_ledger_is_passive_append_and_serve_only(self):
        ledger = ExperienceLedger(StorageDouble())
        for forbidden in ("update", "delete", "edit", "remove", "regenerate", "consult",
                           "rule", "admit"):
            self.assertFalse(hasattr(ledger, forbidden))

    def test_advisory_cannot_write_admit_or_rule(self):
        advisory = AdvisoryInterface(ExperienceLedger(StorageDouble()), BusDouble())
        for forbidden in ("admit", "append", "rule", "regenerate", "absorb"):
            self.assertFalse(hasattr(advisory, forbidden))

    def test_only_the_gate_writes_experience(self):
        # INV-1 single door: a direct ledger append without the Gate's
        # AdmissionReceipt is structurally refused.
        ledger = ExperienceLedger(StorageDouble())
        with self.assertRaises(UnauthorizedAppendError):
            ledger.append(_episode("episode:e1"))

    def test_overlay_is_append_only(self):
        overlay = CurationOverlay(StorageDouble())
        for forbidden in ("update", "delete", "edit", "remove"):
            self.assertFalse(hasattr(overlay, forbidden))


class IntegrationTests(unittest.TestCase):
    """End-to-end across all five subsystems, LIE/04 §1 walkthrough shape,
    then around the loop again with governance acts."""

    def _system(self):
        ledger = ExperienceLedger(StorageDouble())
        overlay = CurationOverlay(StorageDouble())
        curator = Curator(overlay, build_vocabulary(1, {"jetson", "cuda"}),
                           ruleset_mod.default_ruleset())
        gate = AdmissionGate(ledger, curator.current_vocabulary(), ObservabilityDouble())
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        runtime = LieRuntime(ledger, overlay, curator.current_ruleset(), advisory)
        return ledger, overlay, curator, gate, bus, advisory, runtime

    def test_full_loop_admission_to_advice_to_ruling_to_fresh_advice(self):
        ledger, overlay, curator, gate, bus, advisory, runtime = self._system()

        # verified failure + recovery admitted through the single door
        for identity, verdict, approach in (("episode:f1", "failed", APPROACH_A),
                                              ("episode:f2", "failed", APPROACH_A),
                                              ("episode:r1", "passed", APPROACH_B)):
            result = gate.admit(_episode(identity, verdict=verdict, approach=approach))
            self.assertEqual(result.outcome, ADMITTED)
            runtime.on_ledger_appended(None)

        # advisory serves the compiled anti-pattern with instead-of, cited to VAE
        hits = advisory.consult(("jetson",))
        anti = next(h for h in hits if h.kind == "anti_pattern")
        self.assertTrue(all(link["attestation_ref"].startswith("trace:")
                             for link in anti.citation_chain))
        self.assertTrue(bus.messages("lesson.recorded"))  # notifications fired

        # Curator deprecates one failure; fresh advice reweighs
        curator.rule(build_annotation("deprecation", ("episode:f2",), "bad sensor",
                                        ("episode:f1",)))
        state = runtime.on_curation_ruling(None)
        self.assertEqual(state.overlay_position, 1)
        fresh = advisory.consult(("jetson",))
        self.assertFalse(any(h.kind == "anti_pattern" for h in fresh
                              if isinstance(h, Recommendation)))  # recurrence lost

        # Curator adopts a new ruleset; OPS-6 via full regeneration
        state2 = runtime.on_ruleset_changed(
            curator.adopt_ruleset(ruleset_mod.default_ruleset(version=2)))
        self.assertEqual(state2.ruleset_version, 2)

        # ledger history untouched by all governance (INV-2)
        self.assertIsNotNone(ledger.by_identity("episode:f2"))

    def test_contested_loop_through_curator_queue(self):
        ledger, overlay, curator, gate, bus, advisory, runtime = self._system()
        for i, verdict in enumerate(("passed", "passed", "failed", "failed")):
            gate.admit(_episode("episode:c" + str(i), project="p" + str(i % 2),
                                  facets=("cuda",), verdict=verdict, approach=APPROACH_A))
            runtime.on_ledger_appended(None)

        # both sides served while contested (LIE/04 §1: "advice would
        # meanwhile present both sides")
        hits = advisory.consult(("cuda",))
        contested_hits = [h for h in hits if isinstance(h, Recommendation) and h.contested]
        self.assertEqual({h.kind for h in contested_hits}, {"pattern", "anti_pattern"})

        # deliberate ruling via the queue; fresh layer keeps one side only
        queue = curator.contested_queue(advisory._layer)
        anti_id = next(a.envelope.identity for a in queue
                        if isinstance(a, derived.AntiPattern))
        curator.rule(build_annotation("contradiction_resolution", (anti_id,),
                                        "failures env-specific", ("episode:c0",)))
        runtime.on_curation_ruling(None)
        after = advisory.consult(("cuda",))
        self.assertFalse(any(h.kind == "anti_pattern" for h in after
                              if isinstance(h, Recommendation)))
        self.assertFalse(any(h.contested for h in after if isinstance(h, Recommendation)))

    def test_vocabulary_evolution_reaches_the_gate(self):
        ledger, overlay, curator, gate, bus, advisory, runtime = self._system()
        self.assertEqual(gate.admit(_episode("episode:x", facets=("ros2",))).outcome,
                          REJECTED)
        gate.adopt_vocabulary(curator.evolve_vocabulary({"jetson", "cuda", "ros2"}))
        result = gate.admit(_episode("episode:y", facets=("ros2",),
                                       vocabulary_version=2))
        self.assertEqual(result.outcome, ADMITTED)
        runtime.on_ledger_appended(None)
        self.assertTrue(advisory.consult(("ros2",)))


class ReplayRegenerationTests(unittest.TestCase):
    def test_migration_clone_plus_regeneration_reproduces_layer(self):
        # LIE/03 §8: migration = clone the records, regenerate -- identical
        # layer at the same Derivation State.
        rs = ruleset_mod.default_ruleset()
        records = [
            _episode("episode:f1", project="p1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", project="p2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", project="p1", verdict="passed", approach=APPROACH_B),
        ]
        original_ledger, original_overlay = _stores()
        for ep in records:
            original_ledger.append(AdmissionReceipt(ep))
        original_overlay.append(build_annotation("deprecation", ("episode:f2",), "r",
                                                    ("episode:f1",)))
        original = distillery.regenerate(original_ledger, original_overlay, rs)

        clone_ledger, clone_overlay = _stores()  # "new installation"
        for ep in records:
            clone_ledger.append(AdmissionReceipt(ep))
        clone_overlay.append(build_annotation("deprecation", ("episode:f2",), "r",
                                                ("episode:f1",)))
        clone = distillery.regenerate(clone_ledger, clone_overlay, rs)

        self.assertEqual(original.derivation_state, clone.derivation_state)
        self.assertEqual(distillery.layer_canonical(original),
                          distillery.layer_canonical(clone))

    def test_forensic_reconstruction_prior_derivation_state(self):
        # "what did the system believe when it advised this?" -- replay at
        # the earlier overlay position by rebuilding the earlier inputs.
        rs = ruleset_mod.default_ruleset()
        ledger, overlay = _contested_stores()
        before_ruling = distillery.layer_canonical(distillery.regenerate(ledger, overlay, rs))
        layer = distillery.regenerate(ledger, overlay, rs)
        anti_id = next(a.envelope.identity for a in layer.artifacts
                        if isinstance(a, derived.AntiPattern))
        overlay.append(build_annotation("contradiction_resolution", (anti_id,), "resolved",
                                          ("episode:c0",)))
        # reconstruct the pre-ruling state on fresh stores
        ledger2, overlay2 = _contested_stores()
        reconstructed = distillery.layer_canonical(
            distillery.regenerate(ledger2, overlay2, rs))
        self.assertEqual(before_ruling, reconstructed)

    def test_equivalence_oracle_repeated_regeneration_byte_identical(self):
        # LIE/04 §6: "ship the comparison as a first-class check" --
        # layer_canonical IS that check; two compilations of one
        # Derivation State are byte-identical.
        rs = ruleset_mod.default_ruleset()
        ledger, overlay = _contested_stores()
        a = distillery.layer_canonical(distillery.regenerate(ledger, overlay, rs))
        b = distillery.layer_canonical(distillery.regenerate(ledger, overlay, rs))
        self.assertEqual(a, b)


class FinalInvariantSweepTests(unittest.TestCase):
    """One enforcement-point check per invariant not already pinned by a
    dedicated test above or in phases 1-4."""

    def test_inv6_nothing_model_shaped_in_stored_artifacts(self):
        rs = ruleset_mod.default_ruleset()
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        layer = distillery.regenerate(ledger, overlay, rs)
        import json
        for artifact in layer.artifacts:
            payload = json.dumps(derived.to_dict(artifact))
            for word in ("embedding", "weights", "logits", "model_id"):
                self.assertNotIn(word, payload)

    def test_inv7_all_stored_forms_are_plain_readable_data(self):
        import json
        from lie.episode import to_dict as episode_to_dict
        from lie.curation import to_dict as annotation_to_dict
        ep = _episode("episode:e1")
        ann = build_annotation("deprecation", ("episode:e1",), "r", ("episode:e2",))
        rs = ruleset_mod.default_ruleset()
        for d in (episode_to_dict(ep), annotation_to_dict(ann), ruleset_mod.to_dict(rs)):
            json.dumps(d)  # raises if anything non-plain leaked in

    def test_inv9_derived_envelopes_carry_identifiers_not_repo_content(self):
        # relations carry target identifiers only -- structurally, a
        # Relation has no content field at all.
        rel = envelope_mod.build_relation("about", "ums:artifact:123")
        self.assertEqual(set(rel.__dataclass_fields__), {"relation_type", "target_id"})

    def test_inv10_absorption_cost_is_signature_local_in_output(self):
        # adding an episode at one signature leaves artifacts at OTHER
        # signatures content-identical (the output-side observable of
        # bounded incremental cost). The Derivation State stamp advances
        # by canon (every artifact carries the layer's stamp), so compare
        # content with the stamp excluded.
        def _content(artifact):
            d = derived.to_dict(artifact)
            d["envelope"] = dict(d["envelope"])
            d["envelope"].pop("attestation")     # the DerivationState stamp
            d["envelope"]["origin"] = dict(d["envelope"]["origin"])
            d["envelope"]["origin"].pop("occurred_at")  # derived@L..:O..:R.. stamp
            return d

        rs = ruleset_mod.default_ruleset()
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:a1", facets=("cuda",))))
        before = {a.envelope.identity: _content(a)
                   for a in distillery.regenerate(ledger, overlay, rs).artifacts
                   if a.envelope.facets == ("cuda",)}
        ledger.append(AdmissionReceipt(_episode("episode:b1", facets=("jetson",))))
        after_layer = distillery.regenerate(ledger, overlay, rs)
        for identity, snapshot in before.items():
            artifact = after_layer.by_identity(identity)
            if not isinstance(artifact, (derived.ProjectDossier, derived.DomainKnowledgePack)):
                self.assertEqual(_content(artifact), snapshot)

    def test_ops1_no_lie_surface_blocks_execution(self):
        # nothing in the whole public surface takes a wait/timeout/callback
        import inspect
        for cls in (AdmissionGate, ExperienceLedger, AdvisoryInterface, LieRuntime, Curator):
            for name, member in inspect.getmembers(cls, inspect.isfunction):
                if name.startswith("_"):
                    continue
                params = set(inspect.signature(member).parameters)
                self.assertFalse(params & {"timeout", "callback", "wait", "block"},
                                  cls.__name__ + "." + name)


if __name__ == "__main__":
    unittest.main()
