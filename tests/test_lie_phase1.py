"""LIE Phase 1 suite — LIE/04 §6 implementation contract (foundation:
provenance envelope, Episode/Decision, facet vocabulary, curation
annotation, Experience Ledger, curation overlay, Derivation State, event
canon, Admission Gate, boundary contracts). Covers: envelope completeness
refusal; closed relation/annotation-kind sets; additive-only vocabulary
evolution; append-only Ledger/Overlay with no update/delete API; INV-1
(Gate-only ledger writes) and INV-2 (immutability) structural enforcement;
OPS-5 idempotent admission under redelivery; INV-7 round-trip
serialization determinism; INV-9 identifier-only `about` relations;
monotonic Ledger/overlay positions; envelope-completeness rejection at
construction time (rejection, not partial admit)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lie import curation
from lie import decision as decision_mod
from lie import derivation_state as derivation_state_mod
from lie import envelope as envelope_mod
from lie import episode as episode_mod
from lie import events
from lie import overlay as overlay_mod
from lie import vocabulary as vocabulary_mod
from lie.admission_receipt import AdmissionReceipt
from lie.bus_double import BusDouble
from lie.contracts import AdvisoryPort, CuratorPort, DistilleryPort
from lie.gate import ADMITTED, AdmissionGate, DEDUPED, REJECTED
from lie.ledger import DuplicateIdentityError, ExperienceLedger, LedgerAppendRejectedError, \
    UnauthorizedAppendError
from lie.storage_double import StorageDouble
from lie.telemetry_double import ObservabilityDouble


def _envelope(identity="episode:e1", attestation_ref="trace:t1", trace_closed=True,
              vocabulary_version=1, project="asunama", facets=("ros2",), relations=()):
    return envelope_mod.build_envelope(
        identity,
        envelope_mod.build_attestation(attestation_ref, trace_closed, vocabulary_version),
        envelope_mod.build_origin(project, "isaac-sim", "vishnu", "epoch-0"),
        facets, relations)


def _episode(**kwargs):
    return episode_mod.build_episode(
        _envelope(**kwargs), situation={"needed": "gps-denied nav"},
        approach={"steps": ["orb-slam"]}, outcome={"verdict": "passed"}, cost={"retries": 0})


def _decision(**kwargs):
    return decision_mod.build_decision(
        _envelope(**kwargs), question="which SLAM stack?", options=("orb-slam3", "vins-fusion"),
        chosen="orb-slam3", rationale="better monocular robustness",
        constraints={"gps": "denied"}, consequences_expected={"risk": "moderate"})


class VocabularyTests(unittest.TestCase):
    def test_build_seed_vocabulary(self):
        v = vocabulary_mod.build_vocabulary(1, {"ros2", "cuda"})
        self.assertEqual(v.version, 1)
        self.assertEqual(v.terms, frozenset({"ros2", "cuda"}))

    def test_evolve_is_additive_and_bumps_version(self):
        v1 = vocabulary_mod.build_vocabulary(1, {"ros2"})
        v2 = vocabulary_mod.evolve(v1, {"ros2", "jetson"})
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.terms, frozenset({"ros2", "jetson"}))
        self.assertEqual(v1.terms, frozenset({"ros2"}))  # original untouched

    def test_evolve_refuses_removal(self):
        v1 = vocabulary_mod.build_vocabulary(1, {"ros2", "cuda"})
        with self.assertRaises(vocabulary_mod.VocabularyNotAdditiveError):
            vocabulary_mod.evolve(v1, {"ros2"})

    def test_evolve_refuses_rename(self):
        v1 = vocabulary_mod.build_vocabulary(1, {"ros2"})
        with self.assertRaises(vocabulary_mod.VocabularyNotAdditiveError):
            vocabulary_mod.evolve(v1, {"ros_two"})

    def test_evolve_refuses_no_new_terms(self):
        v1 = vocabulary_mod.build_vocabulary(1, {"ros2"})
        with self.assertRaises(vocabulary_mod.VocabularyNoNewTermsError):
            vocabulary_mod.evolve(v1, {"ros2"})

    def test_no_edit_or_rename_api_exists(self):
        v1 = vocabulary_mod.build_vocabulary(1, {"ros2"})
        self.assertFalse(hasattr(v1, "remove_term"))
        self.assertFalse(hasattr(v1, "rename_term"))
        self.assertFalse(hasattr(vocabulary_mod, "remove_term"))

    def test_malformed_vocabulary_refused(self):
        with self.assertRaises(vocabulary_mod.MalformedVocabularyError):
            vocabulary_mod.build_vocabulary(0, {"a"})
        with self.assertRaises(vocabulary_mod.MalformedVocabularyError):
            vocabulary_mod.build_vocabulary(1, set())
        with self.assertRaises(vocabulary_mod.MalformedVocabularyError):
            vocabulary_mod.build_vocabulary(1, {""})


class EnvelopeCompletenessTests(unittest.TestCase):
    def test_complete_envelope_builds(self):
        env = _envelope()
        self.assertEqual(env.identity, "episode:e1")
        self.assertEqual(env.facets, ("ros2",))

    def test_frozen_no_field_reassignment(self):
        env = _envelope()
        with self.assertRaises(AttributeError):
            env.identity = "other"

    def test_missing_attestation_ref_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_attestation("", True, 1)

    def test_non_bool_trace_closed_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_attestation("t1", "yes", 1)

    def test_bad_vocabulary_version_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_attestation("t1", True, 0)

    def test_unidentifiable_origin_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_origin("", "env", None, "t0")

    def test_missing_occurred_at_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_origin("proj", "env", None, None)

    def test_empty_facets_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_envelope(
                "e1", envelope_mod.build_attestation("t1", True, 1),
                envelope_mod.build_origin("p", "e", None, "t0"), (), ())

    def test_unbuilt_relation_object_refused(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_envelope(
                "e1", envelope_mod.build_attestation("t1", True, 1),
                envelope_mod.build_origin("p", "e", None, "t0"), ("ros2",),
                ({"relation_type": "about", "target_id": "x"},))

    def test_an_incomplete_envelope_is_a_construction_time_rejection(self):
        # "An envelope that cannot be completed is a rejection, not a
        # partial admit" (LIE/04 §6) -- no half-built Envelope escapes
        # build_envelope() as a usable object.
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_envelope(
                "", envelope_mod.build_attestation("t1", True, 1),
                envelope_mod.build_origin("p", "e", None, "t0"), ("ros2",), ())


class RelationTests(unittest.TestCase):
    def test_closed_relation_set(self):
        self.assertEqual(envelope_mod.RELATION_TYPES, (
            "enacts", "recovers", "follows", "evidenced-by", "instead-of", "supersedes", "about"))

    def test_invented_relation_type_refused(self):
        with self.assertRaises(envelope_mod.UnknownRelationTypeError):
            envelope_mod.build_relation("mentions", "ums:x")

    def test_about_relation_carries_identifier_only(self):
        # INV-9: `about` -> UMS identifier, never copied content. Structural
        # proof: target_id is always a bare str, never a mapping/object.
        rel = envelope_mod.build_relation("about", "ums:repo/asunama")
        self.assertIsInstance(rel.target_id, str)
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_relation("about", {"content": "not an identifier"})

    def test_relation_target_must_be_nonempty_string(self):
        with self.assertRaises(envelope_mod.EnvelopeIncompleteError):
            envelope_mod.build_relation("about", "")


class EpisodeTests(unittest.TestCase):
    def test_build_episode(self):
        ep = _episode()
        self.assertEqual(ep.situation["needed"], "gps-denied nav")

    def test_frozen_top_level_and_content(self):
        ep = _episode()
        with self.assertRaises(AttributeError):
            ep.outcome = {}
        with self.assertRaises(TypeError):
            ep.outcome["verdict"] = "failed"

    def test_each_of_four_parts_required_nonempty(self):
        env = _envelope()
        base = {"situation": {"a": 1}, "approach": {"a": 1}, "outcome": {"a": 1}, "cost": {"a": 1}}
        for missing in ("situation", "approach", "outcome", "cost"):
            kwargs = dict(base)
            kwargs[missing] = {}
            with self.assertRaises(episode_mod.MalformedEpisodeError):
                episode_mod.build_episode(env, **kwargs)

    def test_envelope_must_be_built(self):
        with self.assertRaises(episode_mod.MalformedEpisodeError):
            episode_mod.build_episode({"not": "an envelope"}, situation={"a": 1},
                                       approach={"a": 1}, outcome={"a": 1}, cost={"a": 1})


class DecisionTests(unittest.TestCase):
    def test_build_decision(self):
        dec = _decision()
        self.assertEqual(dec.chosen, "orb-slam3")

    def test_frozen_top_level_and_content(self):
        dec = _decision()
        with self.assertRaises(AttributeError):
            dec.chosen = "vins-fusion"
        with self.assertRaises(TypeError):
            dec.constraints["gps"] = "available"

    def test_chosen_must_be_among_options(self):
        env = _envelope()
        with self.assertRaises(decision_mod.MalformedDecisionError):
            decision_mod.build_decision(env, "q", ("a", "b"), "c", "r", {}, {})

    def test_empty_constraints_and_consequences_are_legitimate(self):
        env = _envelope()
        dec = decision_mod.build_decision(env, "q", ("a",), "a", "r", {}, {})
        self.assertEqual(dec.constraints, {})
        self.assertEqual(dec.consequences_expected, {})


class SerializationRoundTripTests(unittest.TestCase):
    """INV-7: human-readable, deterministic round-trip serialization."""

    def test_envelope_round_trip_deterministic(self):
        env = _envelope(relations=(envelope_mod.build_relation("about", "ums:repo/x"),))
        d1 = envelope_mod.to_dict(env)
        d2 = envelope_mod.to_dict(env)
        self.assertEqual(d1, d2)
        restored = envelope_mod.from_dict(d1)
        self.assertEqual(restored, env)
        self.assertEqual(envelope_mod.canonical(env), envelope_mod.canonical(restored))

    def test_episode_round_trip_deterministic(self):
        ep = _episode()
        restored = episode_mod.from_dict(episode_mod.to_dict(ep))
        self.assertEqual(restored, ep)

    def test_decision_round_trip_deterministic(self):
        dec = _decision()
        restored = decision_mod.from_dict(decision_mod.to_dict(dec))
        self.assertEqual(restored, dec)

    def test_annotation_round_trip_deterministic(self):
        ann = curation.build_annotation("deprecation", ("episode:e1",), "stale", ("episode:e2",))
        restored = curation.from_dict(curation.to_dict(ann))
        self.assertEqual(restored, ann)

    def test_derivation_state_round_trip_deterministic(self):
        state = derivation_state_mod.build_derivation_state(3, 1, 1)
        restored = derivation_state_mod.from_dict(derivation_state_mod.to_dict(state))
        self.assertEqual(restored, state)

    def test_dicts_are_json_serializable_plain_data(self):
        import json
        ep = _episode()
        # human-readable per INV-7: no exotic types survive to_dict()
        json.dumps(episode_mod.to_dict(ep))


class CurationAnnotationTests(unittest.TestCase):
    def test_closed_kind_set(self):
        self.assertEqual(curation.ANNOTATION_KINDS,
                          ("deprecation", "supersession", "contradiction_resolution"))

    def test_invented_kind_refused(self):
        with self.assertRaises(curation.UnknownAnnotationKindError):
            curation.build_annotation("delete", ("episode:e1",), "r", ("episode:e2",))

    def test_reason_required(self):
        with self.assertRaises(curation.MalformedAnnotationError):
            curation.build_annotation("deprecation", ("episode:e1",), "", ("episode:e2",))

    def test_cited_evidence_required(self):
        with self.assertRaises(curation.MalformedAnnotationError):
            curation.build_annotation("deprecation", ("episode:e1",), "reason", ())

    def test_no_edit_or_remove_api_exists(self):
        ann = curation.build_annotation("deprecation", ("episode:e1",), "r", ("episode:e2",))
        self.assertFalse(hasattr(ann, "edit"))
        self.assertFalse(hasattr(ann, "remove"))


class LedgerInvariantTests(unittest.TestCase):
    def test_append_assigns_monotonic_position(self):
        ledger = ExperienceLedger(StorageDouble())
        e1 = ledger.append(AdmissionReceipt(_episode(identity="episode:e1")))
        e2 = ledger.append(AdmissionReceipt(_episode(identity="episode:e2", attestation_ref="trace:t2")))
        self.assertEqual(e1.position, 1)
        self.assertEqual(e2.position, 2)
        self.assertEqual(ledger.current_position(), 2)

    def test_read_serve_api(self):
        ledger = ExperienceLedger(StorageDouble())
        entry = ledger.append(AdmissionReceipt(_episode()))
        self.assertEqual(ledger.by_position(1), entry)
        self.assertIsNone(ledger.by_position(99))
        self.assertEqual(ledger.by_identity("episode:e1"), entry)
        self.assertEqual(ledger.all(), (entry,))

    def test_inv1_append_requires_a_real_admission_receipt(self):
        ledger = ExperienceLedger(StorageDouble())
        with self.assertRaises(UnauthorizedAppendError):
            ledger.append(_episode())  # bare record, not a receipt

    def test_inv2_no_update_delete_edit_api_exists(self):
        ledger = ExperienceLedger(StorageDouble())
        self.assertFalse(hasattr(ledger, "update"))
        self.assertFalse(hasattr(ledger, "delete"))
        self.assertFalse(hasattr(ledger, "edit"))
        self.assertFalse(hasattr(ledger, "remove"))

    def test_inv2_duplicate_identity_refused_never_reused(self):
        ledger = ExperienceLedger(StorageDouble())
        ledger.append(AdmissionReceipt(_episode(identity="episode:e1", attestation_ref="trace:t1")))
        with self.assertRaises(DuplicateIdentityError):
            ledger.append(AdmissionReceipt(_episode(identity="episode:e1", attestation_ref="trace:t9")))
        self.assertEqual(ledger.current_position(), 1)  # refused attempt leaves no trace

    def test_durable_append_then_position_storage_rejection_gets_no_position(self):
        storage = StorageDouble()
        storage.script_reject("lie/ledger/episode:e1")
        ledger = ExperienceLedger(storage)
        with self.assertRaises(LedgerAppendRejectedError):
            ledger.append(AdmissionReceipt(_episode()))
        self.assertEqual(ledger.current_position(), 0)
        self.assertIsNone(ledger.by_identity("episode:e1"))

    def test_writes_go_through_storage(self):
        storage = StorageDouble()
        ledger = ExperienceLedger(storage)
        ledger.append(AdmissionReceipt(_episode()))
        self.assertTrue(storage.exists("lie/ledger/episode:e1"))


class OverlayTests(unittest.TestCase):
    def test_append_assigns_monotonic_position(self):
        ov = overlay_mod.CurationOverlay(StorageDouble())
        ann1 = curation.build_annotation("deprecation", ("episode:e1",), "r1", ("episode:e2",))
        ann2 = curation.build_annotation("supersession", ("episode:e1",), "r2", ("episode:e3",))
        entry1 = ov.append(ann1)
        entry2 = ov.append(ann2)
        self.assertEqual(entry1.position, 1)
        self.assertEqual(entry2.position, 2)
        self.assertEqual(ov.current_position(), 2)

    def test_by_target_reads_without_mutating(self):
        ov = overlay_mod.CurationOverlay(StorageDouble())
        ann1 = curation.build_annotation("deprecation", ("episode:e1",), "r1", ("episode:e2",))
        ov.append(ann1)
        matches = ov.by_target("episode:e1")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].annotation, ann1)
        self.assertEqual(ov.by_target("episode:nope"), ())

    def test_no_update_delete_edit_api_exists(self):
        ov = overlay_mod.CurationOverlay(StorageDouble())
        self.assertFalse(hasattr(ov, "update"))
        self.assertFalse(hasattr(ov, "delete"))
        self.assertFalse(hasattr(ov, "edit"))
        self.assertFalse(hasattr(ov, "remove"))

    def test_storage_rejection_gets_no_position(self):
        storage = StorageDouble()
        storage.script_reject("lie/overlay/1")
        ov = overlay_mod.CurationOverlay(storage)
        ann = curation.build_annotation("deprecation", ("episode:e1",), "r", ("episode:e2",))
        with self.assertRaises(overlay_mod.OverlayAppendRejectedError):
            ov.append(ann)
        self.assertEqual(ov.current_position(), 0)


class DerivationStateTests(unittest.TestCase):
    def test_build_and_value_equality(self):
        s1 = derivation_state_mod.build_derivation_state(3, 1, 1)
        s2 = derivation_state_mod.build_derivation_state(3, 1, 1)
        self.assertEqual(s1, s2)

    def test_frozen(self):
        s = derivation_state_mod.build_derivation_state(0, 0, 1)
        with self.assertRaises(AttributeError):
            s.ledger_position = 1

    def test_negative_components_refused(self):
        with self.assertRaises(derivation_state_mod.MalformedDerivationStateError):
            derivation_state_mod.build_derivation_state(-1, 0, 1)


class EventCanonTests(unittest.TestCase):
    def test_closed_sets_match_canon(self):
        self.assertEqual(events.PUBLISHED, ("lesson.recorded", "reliability.updated", "prior.updated"))
        self.assertEqual(events.CONSUMED, ("trace.closed",))

    def test_lesson_learned_is_not_canon(self):
        # pre-ruled: LIE uses lesson.recorded, never lesson.learned.
        self.assertNotIn("lesson.learned", events.PUBLISHED)
        self.assertNotIn("lesson.learned", events.CONSUMED)
        with self.assertRaises(events.UnknownEventError):
            events.emit(BusDouble(), "lesson.learned", "e1", "s", {})

    def test_invented_publish_name_refused(self):
        bus = BusDouble()
        with self.assertRaises(events.UnknownEventError):
            events.emit(bus, "lesson.maybe", "e1", "s", {})
        self.assertEqual(bus.messages("lesson.maybe"), [])

    def test_invented_consume_name_refused(self):
        with self.assertRaises(events.UnknownEventError):
            events.check_consumed("lesson.maybe")

    def test_published_name_not_a_consumed_name(self):
        with self.assertRaises(events.UnknownEventError):
            events.check_consumed("lesson.recorded")

    def test_consumed_name_not_a_published_name(self):
        with self.assertRaises(events.UnknownEventError):
            events.emit(BusDouble(), "trace.closed", "e1", "s", {})

    def test_payload_never_carries_advice_only_reference_shaped(self):
        bus = BusDouble()
        env = events.emit(bus, "lesson.recorded", "e1", "episode:e1", {"derivation_state_ref": "3:1:1"})
        self.assertEqual(env["payload"], {"derivation_state_ref": "3:1:1"})
        with self.assertRaises(events.EventRefusal):
            events.build_envelope("lesson.recorded", "e1", "s", ["not", "a", "mapping"])


class AdmissionGateInvariantTests(unittest.TestCase):
    def _gate(self, storage=None, terms=("ros2", "cuda")):
        storage = storage or StorageDouble()
        ledger = ExperienceLedger(storage)
        vocab = vocabulary_mod.build_vocabulary(1, set(terms))
        telemetry = ObservabilityDouble()
        return AdmissionGate(ledger, vocab, telemetry), ledger, telemetry

    def test_ordinary_admission(self):
        gate, ledger, _ = self._gate()
        result = gate.admit(_episode())
        self.assertEqual(result.outcome, ADMITTED)
        self.assertEqual(result.ledger_position, 1)
        self.assertEqual(ledger.current_position(), 1)

    def test_ops5_idempotent_redelivery_same_attestation_dedupes(self):
        gate, ledger, _ = self._gate()
        first = gate.admit(_episode(identity="episode:e1", attestation_ref="trace:t1"))
        second = gate.admit(_episode(identity="episode:e1-retry", attestation_ref="trace:t1"))
        self.assertEqual(first.outcome, ADMITTED)
        self.assertEqual(second.outcome, DEDUPED)
        self.assertEqual(second.ledger_position, first.ledger_position)
        self.assertEqual(ledger.current_position(), 1)  # one attested unit -> one record, ever

    def test_ops5_redelivery_survives_many_repeats(self):
        gate, ledger, _ = self._gate()
        gate.admit(_episode(attestation_ref="trace:t1"))
        for _ in range(5):
            result = gate.admit(_episode(attestation_ref="trace:t1"))
            self.assertEqual(result.outcome, DEDUPED)
        self.assertEqual(ledger.current_position(), 1)

    def test_provenance_rejection_missing_attestation_ref(self):
        gate, ledger, telemetry = self._gate()
        # missing attestation_ref is itself an incomplete envelope --
        # build_attestation() already refuses it at construction time, so
        # exercise Gate's own defense-in-depth check directly via a
        # hand-built envelope bypassing that factory.
        env = envelope_mod.build_envelope(
            "episode:bad", envelope_mod.Attestation(attestation_ref="", trace_closed=True,
                                                      vocabulary_version=1),
            envelope_mod.build_origin("p", "e", None, "t0"), ("ros2",), ())
        ep = episode_mod.build_episode(env, situation={"a": 1}, approach={"a": 1},
                                        outcome={"a": 1}, cost={"a": 1})
        r = gate.admit(ep)
        self.assertEqual(r.outcome, REJECTED)
        self.assertEqual(r.reason, "missing_attestation_ref")
        self.assertEqual(ledger.current_position(), 0)
        self.assertEqual(telemetry.by_kind("admission_rejected")[0]["reason"], "missing_attestation_ref")

    def test_provenance_rejection_trace_not_closed(self):
        gate, ledger, telemetry = self._gate()
        result = gate.admit(_episode(attestation_ref="trace:t2", trace_closed=False))
        self.assertEqual(result.outcome, REJECTED)
        self.assertEqual(result.reason, "trace_not_closed")
        self.assertEqual(ledger.current_position(), 0)  # R1: rejection never touches the ledger
        self.assertEqual(telemetry.by_kind("admission_rejected")[0]["reason"], "trace_not_closed")

    def test_vocabulary_normalization_rejects_unknown_facet(self):
        gate, ledger, _ = self._gate(terms=("ros2",))
        result = gate.admit(_episode(attestation_ref="trace:t3", facets=("ros2", "quantum_flux")))
        self.assertEqual(result.outcome, REJECTED)
        self.assertEqual(result.reason, "unknown_facet:quantum_flux")
        self.assertEqual(ledger.current_position(), 0)

    def test_vocabulary_version_ahead_of_current_rejected(self):
        gate, ledger, _ = self._gate()
        result = gate.admit(_episode(attestation_ref="trace:t4", vocabulary_version=99))
        self.assertEqual(result.outcome, REJECTED)
        self.assertEqual(result.reason, "vocabulary_version_ahead_of_current")

    def test_rejection_recorded_to_telemetry_never_ledger(self):
        gate, ledger, telemetry = self._gate()
        gate.admit(_episode(attestation_ref="trace:t5", trace_closed=False))
        self.assertEqual(len(telemetry.by_kind("admission_rejected")), 1)
        self.assertEqual(ledger.current_position(), 0)

    def test_durable_append_then_acknowledge_storage_rejection(self):
        storage = StorageDouble()
        storage.script_reject("lie/ledger/episode:e1")
        gate, ledger, telemetry = self._gate(storage=storage)
        result = gate.admit(_episode())
        self.assertEqual(result.outcome, REJECTED)
        self.assertEqual(result.reason, "storage_rejected")
        self.assertEqual(ledger.current_position(), 0)
        self.assertEqual(telemetry.by_kind("admission_rejected")[0]["reason"], "storage_rejected")

    def test_rejected_attestation_can_be_resubmitted_and_admitted(self):
        gate, ledger, _ = self._gate()
        rejected = gate.admit(_episode(identity="episode:e1", attestation_ref="trace:t1",
                                        trace_closed=False))
        self.assertEqual(rejected.outcome, REJECTED)
        fixed = gate.admit(_episode(identity="episode:e1b", attestation_ref="trace:t1",
                                     trace_closed=True))
        self.assertEqual(fixed.outcome, ADMITTED)
        self.assertEqual(ledger.current_position(), 1)

    def test_unknown_record_kind_refused(self):
        gate, _, _ = self._gate()
        with self.assertRaises(Exception):
            gate.admit("not a record")

    def test_decisions_admit_through_the_same_gate(self):
        gate, ledger, _ = self._gate()
        result = gate.admit(_decision())
        self.assertEqual(result.outcome, ADMITTED)
        self.assertEqual(ledger.by_position(1).record.chosen, "orb-slam3")


class BoundaryContractTests(unittest.TestCase):
    """Phase 1 scope: these are seams only, no logic."""

    def test_distillery_port_seam_methods(self):
        self.assertTrue(set(vars(DistilleryPort)) >= {"absorb", "regenerate"})

    def test_advisory_port_seam_methods(self):
        self.assertTrue(set(vars(AdvisoryPort)) >= {"consult"})

    def test_curator_port_seam_methods(self):
        self.assertTrue(set(vars(CuratorPort)) >= {"rule"})


class BusDoubleTests(unittest.TestCase):
    def test_per_topic_fifo(self):
        bus = BusDouble()
        bus.publish("lesson.recorded", {"n": 1})
        bus.publish("lesson.recorded", {"n": 2})
        self.assertEqual(bus.messages("lesson.recorded"), [{"n": 1}, {"n": 2}])

    def test_inject_duplicate(self):
        bus = BusDouble()
        bus.publish("prior.updated", {"event_id": "e1"})
        bus.inject_duplicate("prior.updated")
        self.assertEqual(bus.messages("prior.updated"), [{"event_id": "e1"}, {"event_id": "e1"}])


class StorageDoubleTests(unittest.TestCase):
    def test_write_commits_by_default(self):
        store = StorageDouble()
        self.assertEqual(store.write("lie/ledger/e1", b"v1"), "committed")
        self.assertEqual(store.read("lie/ledger/e1"), b"v1")

    def test_scripted_rejection_is_an_outcome_not_an_exception(self):
        store = StorageDouble()
        store.script_reject("k")
        self.assertEqual(store.write("k", b"v"), "rejected")
        self.assertFalse(store.exists("k"))


class ObservabilityDoubleTests(unittest.TestCase):
    def test_record_and_by_kind(self):
        sink = ObservabilityDouble()
        sink.record("admission_rejected", {"reason": "x"})
        self.assertEqual(sink.by_kind("admission_rejected"), ({"reason": "x"},))
        self.assertEqual(sink.by_kind("nothing_here"), ())


if __name__ == "__main__":
    unittest.main()
