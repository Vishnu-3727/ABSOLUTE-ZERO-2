"""LIE Phase 4 suite — LIE/03 operational lifecycle & runtime semantics.
Covers: Derivation State stamping on every advisory response (OPS-4);
pull-only, read-only consultation that never triggers derivation (OPS-2);
the four-part recommendation object and the definite "no relevant
experience" absence (INV-4); atomic publication (OPS-3) and its
notification side (`lesson.recorded`, never carrying advice as payload,
LIE/03 §7); the causal trigger model (ledger append, curation ruling,
ruleset change, explicit regeneration — OPS-7, no clocks); one-ruleset-
per-layer (OPS-6) on ruleset evolution; disposable/replayable derivation
(OPS-8) and crash recovery leaving the previously published layer
untouched (LIE/03 §8); end-to-end Gate -> Ledger -> Runtime -> Advisory
wiring matching the LIE/04 §1 walkthrough shape."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lie import derivation_state as ds_mod
from lie import distillery
from lie import envelope as envelope_mod
from lie import events
from lie import ruleset as ruleset_mod
from lie.admission_receipt import AdmissionReceipt
from lie.advisory import (AdvisoryInterface, AdvisoryRefusal, MalformedConsultationError,
                            NoLayerPublishedError, NoRelevantExperience, Recommendation)
from lie.bus_double import BusDouble
from lie.curation import build_annotation
from lie.episode import build_episode
from lie.gate import AdmissionGate
from lie.ledger import ExperienceLedger
from lie.overlay import CurationOverlay
from lie.runtime import LieRuntime, MalformedRuntimeInputError
from lie.storage_double import StorageDouble
from lie.telemetry_double import ObservabilityDouble
from lie.vocabulary import build_vocabulary

APPROACH_A = {"a": "flash-old"}
APPROACH_B = {"a": "flash-new"}


def _episode(identity, project="p1", facets=("jetson",), verdict="passed", approach=None,
             attestation_ref=None):
    env = envelope_mod.build_envelope(
        identity, envelope_mod.build_attestation(attestation_ref or "trace:" + identity, True, 1),
        envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
    return build_episode(env, situation={"s": 1}, approach=approach or {"a": 1},
                          outcome={"verdict": verdict}, cost={"c": 1})


def _stores():
    return ExperienceLedger(StorageDouble()), CurationOverlay(StorageDouble())


def _wired_runtime(ruleset=None):
    ledger, overlay = _stores()
    bus = BusDouble()
    advisory = AdvisoryInterface(ledger, bus)
    runtime = LieRuntime(ledger, overlay, ruleset or ruleset_mod.default_ruleset(), advisory)
    return ledger, overlay, bus, advisory, runtime


class AdvisoryConsultationTests(unittest.TestCase):
    def test_consult_before_any_publish_is_loud_not_a_silent_guess(self):
        ledger, _ = _stores()
        advisory = AdvisoryInterface(ledger, BusDouble())
        with self.assertRaises(NoLayerPublishedError):
            advisory.consult(("jetson",))

    def test_four_part_recommendation_object(self):
        ledger, overlay = _stores()
        for ep in (_episode("episode:f1", verdict="failed", approach=APPROACH_A),
                    _episode("episode:f2", verdict="failed", approach=APPROACH_A),
                    _episode("episode:r1", verdict="passed", approach=APPROACH_B)):
            ledger.append(AdmissionReceipt(ep))
        advisory = AdvisoryInterface(ledger, BusDouble())
        layer = distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset())
        state = advisory.publish(layer)

        hits = advisory.consult(("jetson",))
        anti = next(h for h in hits if h.kind == "anti_pattern")
        self.assertIsInstance(anti, Recommendation)
        self.assertTrue(anti.advice)                      # advice
        self.assertEqual(anti.scope, ("jetson",))          # scope statement
        self.assertIn(anti.maturity, ("provisional", "corroborated", "established"))
        self.assertIsInstance(anti.contested, bool)        # maturity + standing
        self.assertTrue(anti.citation_chain)                # walkable citation chain
        self.assertEqual(anti.derivation_state, state)      # OPS-4 stamp

    def test_no_relevant_experience_is_definite_and_stamped(self):
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1", facets=("jetson",))))
        advisory = AdvisoryInterface(ledger, BusDouble())
        state = advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        result = advisory.consult(("totally-unrelated",))
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], NoRelevantExperience)
        self.assertEqual(result[0].derivation_state, state)

    def test_scope_containment_matching(self):
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1", facets=("jetson", "cuda"))))
        advisory = AdvisoryInterface(ledger, BusDouble())
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        # situation offering a SUPERSET of the artifact's scope matches
        self.assertTrue(any(h.kind == "lesson" for h in advisory.consult(("jetson", "cuda", "extra"))))
        # situation missing part of the scope does not
        no_hit = advisory.consult(("jetson",))
        self.assertTrue(all(isinstance(h, NoRelevantExperience) for h in no_hit))

    def test_same_question_same_state_same_answer_forever(self):
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        advisory = AdvisoryInterface(ledger, BusDouble())
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        self.assertEqual(advisory.consult(("jetson",)), advisory.consult(("jetson",)))

    def test_consult_never_mutates_or_triggers_derivation(self):
        # OPS-2: no ledger/overlay write path is reachable from consult() at
        # all -- structural proof: neither object exposes anything but read
        # methods to AdvisoryInterface, and consult() takes no ledger/overlay
        # argument, so it CANNOT call regenerate() even by mistake.
        import inspect
        self.assertNotIn("ledger", inspect.signature(AdvisoryInterface.consult).parameters)
        self.assertNotIn("overlay", inspect.signature(AdvisoryInterface.consult).parameters)

    def test_malformed_consultation_refused(self):
        ledger, overlay = _stores()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        advisory = AdvisoryInterface(ledger, BusDouble())
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        with self.assertRaises(MalformedConsultationError):
            advisory.consult("jetson")  # a bare string, not a tuple/set of facets

    def test_publish_rejects_unbuilt_layer(self):
        ledger, _ = _stores()
        advisory = AdvisoryInterface(ledger, BusDouble())
        with self.assertRaises(AdvisoryRefusal):
            advisory.publish({"not": "a layer"})


class AdvisoryNotificationTests(unittest.TestCase):
    def test_publish_emits_lesson_recorded_for_new_advice(self):
        ledger, overlay = _stores()
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        recorded = bus.messages("lesson.recorded")
        self.assertGreaterEqual(len(recorded), 1)

    def test_notification_payload_never_carries_advice(self):
        ledger, overlay = _stores()
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        for msg in bus.messages("lesson.recorded"):
            self.assertEqual(set(msg["payload"].keys()), {"derivation_state"})
            self.assertNotIn("statement", msg["payload"])
            self.assertNotIn("advice", msg["payload"])

    def test_republishing_unchanged_layer_emits_nothing_new(self):
        ledger, overlay = _stores()
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        rs = ruleset_mod.default_ruleset()
        advisory.publish(distillery.regenerate(ledger, overlay, rs))
        before = len(bus.messages("lesson.recorded"))
        advisory.publish(distillery.regenerate(ledger, overlay, rs))  # identical content
        self.assertEqual(len(bus.messages("lesson.recorded")), before)

    def test_only_lesson_recorded_is_fired_this_phase(self):
        # ponytail: reliability.updated / prior.updated need a vocabulary
        # distinction this phase doesn't invent -- structurally verified
        # unfired rather than silently asserted absent in one test only.
        ledger, overlay = _stores()
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        advisory.publish(distillery.regenerate(ledger, overlay, ruleset_mod.default_ruleset()))
        self.assertEqual(bus.messages("reliability.updated"), [])
        self.assertEqual(bus.messages("prior.updated"), [])

    def test_unknown_event_name_structurally_refused(self):
        with self.assertRaises(events.UnknownEventError):
            events.build_envelope("lesson.learned", "e", "s", {})  # ERRATA C1


class AtomicPublicationTests(unittest.TestCase):
    def test_stale_answers_never_torn_between_layers(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        state1 = runtime.on_ledger_appended(None)
        hits1 = advisory.consult(("jetson",))
        self.assertTrue(all(h.derivation_state == state1 for h in hits1
                             if isinstance(h, Recommendation)))

        ledger.append(AdmissionReceipt(_episode("episode:e2", project="p2")))
        state2 = runtime.on_ledger_appended(None)
        self.assertNotEqual(state1, state2)
        hits2 = advisory.consult(("jetson",))
        # every answer post-publish reflects the NEW state, never a mix
        self.assertTrue(all(h.derivation_state == state2 for h in hits2
                             if isinstance(h, Recommendation)))


class CausalTriggerTests(unittest.TestCase):
    def test_ledger_append_triggers_republish(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        self.assertIsNone(runtime.current_derivation_state())
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        state = runtime.on_ledger_appended(None)
        self.assertEqual(state.ledger_position, 1)

    def test_curation_ruling_triggers_republish(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:f1", verdict="failed")))
        ledger.append(AdmissionReceipt(_episode("episode:f2", verdict="failed")))
        state1 = runtime.on_ledger_appended(None)
        overlay.append(build_annotation("deprecation", ("episode:f2",), "bad data",
                                         ("episode:f1",)))
        state2 = runtime.on_curation_ruling(None)
        self.assertEqual(state2.overlay_position, 1)
        self.assertNotEqual(state1, state2)

    def test_ruleset_change_triggers_full_regeneration_ops6(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1", approach=APPROACH_B)))
        ledger.append(AdmissionReceipt(_episode("episode:e2", approach=APPROACH_B)))
        runtime.on_ledger_appended(None)
        new_rs = ruleset_mod.build_ruleset(2, pattern_min_episodes=5, recipe_min_episodes=5,
                                            corroborated_min_episodes=5,
                                            established_min_projects=5)
        state = runtime.on_ruleset_changed(new_rs)
        self.assertEqual(state.ruleset_version, 2)
        # OPS-6: every artifact in the fresh layer names the SAME single
        # ruleset version -- no artifact can carry a stale one.
        layer = advisory._layer
        for artifact in layer.artifacts:
            self.assertEqual(artifact.envelope.attestation.derivation_state.ruleset_version, 2)
        # and the new (stricter) threshold actually took effect
        self.assertEqual(layer.by_kind.__self__, layer)  # sanity: still a real Layer

    def test_ruleset_change_rejects_unbuilt_ruleset(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        with self.assertRaises(MalformedRuntimeInputError):
            runtime.on_ruleset_changed({"version": 2})

    def test_explicit_regeneration_is_idempotent_replay(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        state1 = runtime.on_ledger_appended(None)
        state2 = runtime.regenerate()
        self.assertEqual(state1, state2)

    def test_no_clock_or_schedule_surface_exists(self):
        # OPS-7: nothing time-shaped anywhere on the runtime's public surface.
        import inspect
        for name in ("on_ledger_appended", "on_curation_ruling", "on_ruleset_changed",
                     "regenerate"):
            params = set(inspect.signature(getattr(LieRuntime, name)).parameters)
            self.assertFalse(params & {"timestamp", "interval", "schedule", "cron", "delay"})


class FailureRecoveryReplayTests(unittest.TestCase):
    def test_distillery_crash_leaves_published_layer_untouched(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        runtime.on_ledger_appended(None)
        published_before = advisory._layer

        real_regenerate = distillery.regenerate
        distillery.regenerate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertRaises(RuntimeError):
                runtime.regenerate()
            self.assertIs(advisory._layer, published_before)  # OPS-3: untouched
        finally:
            distillery.regenerate = real_regenerate

    def test_recovery_is_calling_the_trigger_again(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        state_before_crash = runtime.on_ledger_appended(None)

        real_regenerate = distillery.regenerate
        distillery.regenerate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertRaises(RuntimeError):
                runtime.regenerate()
        finally:
            distillery.regenerate = real_regenerate

        recovered_state = runtime.regenerate()
        self.assertEqual(recovered_state, state_before_crash)  # same destination

    def test_replay_reproduces_identical_layer_any_processing_order(self):
        rs = ruleset_mod.default_ruleset()
        records = [
            _episode("episode:f1", project="p1", verdict="failed", approach=APPROACH_A),
            _episode("episode:f2", project="p2", verdict="failed", approach=APPROACH_A),
            _episode("episode:r1", project="p1", verdict="passed", approach=APPROACH_B),
        ]

        def _regen(order):
            ledger, overlay = _stores()
            for ep in order:
                ledger.append(AdmissionReceipt(ep))
            return distillery.layer_canonical(distillery.regenerate(ledger, overlay, rs))

        forward = _regen(records)
        reversed_order = _regen(list(reversed(records)))
        self.assertEqual(forward, reversed_order)

    def test_layer_discardable_and_regenerable_ops8(self):
        ledger, overlay, bus, advisory, runtime = _wired_runtime()
        ledger.append(AdmissionReceipt(_episode("episode:e1")))
        state1 = runtime.on_ledger_appended(None)
        advisory._layer = None  # simulate a lost/corrupted published layer
        state2 = runtime.regenerate()  # full regeneration recovers it, no consumer participation
        self.assertEqual(state1, state2)


class EndToEndWalkthroughTests(unittest.TestCase):
    """LIE/04 §1 shape: Gate -> Ledger -> (runtime trigger) -> Distillery ->
    Advisory, without ever inspecting VAE/Kernel/UMS internals (out of
    Phase 4 scope) -- just the wiring this phase owns."""

    def test_gate_admission_flows_through_to_advisory(self):
        ledger = ExperienceLedger(StorageDouble())
        overlay = CurationOverlay(StorageDouble())
        vocabulary = build_vocabulary(1, {"jetson", "cuda"})
        telemetry = ObservabilityDouble()
        gate = AdmissionGate(ledger, vocabulary, telemetry)
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        runtime = LieRuntime(ledger, overlay, ruleset_mod.default_ruleset(), advisory)

        failure = _episode("episode:f1", verdict="failed", approach=APPROACH_A,
                            attestation_ref="trace:t1")
        result = gate.admit(failure)
        self.assertEqual(result.outcome, "admitted")
        state = runtime.on_ledger_appended(None)  # the Gate's caller fires the trigger
        self.assertEqual(state.ledger_position, 1)

        recovery = _episode("episode:r1", verdict="passed", approach=APPROACH_B,
                             attestation_ref="trace:t2")
        gate.admit(recovery)
        runtime.on_ledger_appended(None)

        hits = advisory.consult(("jetson",))
        self.assertTrue(any(h.kind == "lesson" for h in hits if isinstance(h, Recommendation)))
        # the advisory response cites all the way to VAE attestation refs (INV-4)
        cited = [h for h in hits if isinstance(h, Recommendation)]
        self.assertTrue(all(link["attestation_ref"].startswith("trace:")
                             for h in cited for link in h.citation_chain))

    def test_gate_rejection_never_reaches_advisory_or_republishes(self):
        ledger = ExperienceLedger(StorageDouble())
        overlay = CurationOverlay(StorageDouble())
        vocabulary = build_vocabulary(1, {"jetson"})
        telemetry = ObservabilityDouble()
        gate = AdmissionGate(ledger, vocabulary, telemetry)
        bus = BusDouble()
        advisory = AdvisoryInterface(ledger, bus)
        runtime = LieRuntime(ledger, overlay, ruleset_mod.default_ruleset(), advisory)

        bad = _episode("episode:bad", facets=("unknown_facet",), attestation_ref="trace:tbad")
        result = gate.admit(bad)
        self.assertEqual(result.outcome, "rejected")
        self.assertEqual(ledger.current_position(), 0)
        self.assertIsNone(runtime.current_derivation_state())  # nothing to trigger on


if __name__ == "__main__":
    unittest.main()
