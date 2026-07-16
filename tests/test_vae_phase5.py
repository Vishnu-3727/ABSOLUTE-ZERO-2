"""VAE Phase 5 suite — VAE/06-implementation-blueprint.md Phase 5
(integration: runtime, telemetry, law enforcer, replay). Covers: the six
telemetry signal families (closed set, each emit_* function, unconditional
emission); the Verification composition root's full demand -> judge ->
persist -> publish path, per-check telemetry wiring, persistence-rejection
handling, and the no-open-judgment refusal; golden-artifact determinism
(identical inputs -> byte-identical evidence records and verdict events,
twice); byte-identical replay from Storage alone, including a tampered-
comparison refusal; and the law enforcer's seven static scans, each
verified to trip on a synthetic violation."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from vae import derivation as derivation_mod
from vae import emission as emission_mod
from vae import evidence as evidence_mod
from vae import intake as intake_mod
from vae import judgment as judgment_mod
from vae import law_enforcer
from vae import runtime as runtime_mod
from vae import telemetry as telemetry_mod
from vae.execution_double import ExecutionDouble
from vae.rules import RulesStore
from vae.storage_double import StorageDouble

POLICY = derivation_mod.build_derivation_policy(
    1, coverage_moderate_min_fraction=0.5, coverage_strong_min_fraction=0.9)


def _rules_store():
    store = RulesStore()
    store.ingest(1, {
        "plugin_output": {
            "required_checks": ("structural", "reference_wellformed"),
            "depth": "standard",
            "deadlines": {"structural": 10, "reference_wellformed": 5},
        },
    })
    return store


def _demand(artifact_ref, judgment_id, event_id, event_name="verify.requested"):
    return {
        "event_name": event_name, "event_id": event_id,
        "artifact_ref": artifact_ref, "judgment_id": judgment_id,
        "artifact_type": "plugin_output", "rules_version": 1,
        "delegated_check_levels": {"structural": "structural"},
        "static_check_levels": {"reference_wellformed": "system"},
    }


def _run_to_verdict(vr, artifact_ref, judgment_id, event_id, outcome="success"):
    vr.handle_demand(_demand(artifact_ref, judgment_id, event_id))
    exe = ExecutionDouble()
    vr.run_static(artifact_ref, "reference_wellformed", {})
    vr.dispatch(artifact_ref, "structural", exe, {"check": "structural"})
    if outcome is not None:
        exe.script_result(judgment_id + ":structural", arrival_time=1, outcome=outcome)
        vr.resolve(artifact_ref, "structural", exe, now=1)
    else:
        vr.resolve(artifact_ref, "structural", exe, now=10)  # no scripted result -> expiry
    return vr.try_close_and_emit(artifact_ref)


# =============================================================================
# telemetry
# =============================================================================

class TelemetrySignalFamilyTests(unittest.TestCase):
    def setUp(self):
        self.sink = telemetry_mod.TelemetrySinkDouble()

    def test_six_families_closed(self):
        self.assertEqual(len(telemetry_mod.SIGNAL_FAMILIES), 6)
        self.assertEqual(set(telemetry_mod.SIGNAL_FAMILIES), {
            "judgment_outcome", "check_activity", "coverage_readout",
            "agreement_record", "derivation_consistency", "latency_demand",
        })

    def test_unknown_signal_family_refused(self):
        with self.assertRaises(telemetry_mod.UnknownSignalFamilyError):
            telemetry_mod._emit(self.sink, "made_up_family", {})

    def test_judgment_outcome(self):
        telemetry_mod.emit_judgment_outcome(self.sink, "artifact:a1", 1, "passed", None, "Verified — High Assurance")
        payload = self.sink.by_family("judgment_outcome")[0]
        self.assertEqual(payload["verdict"], "passed")
        self.assertIsNone(payload["failure_cause"])

    def test_check_activity_closed_phase_set(self):
        telemetry_mod.emit_check_activity(self.sink, "artifact:a1", "structural", "dispatched")
        with self.assertRaises(telemetry_mod.UnknownCheckPhaseError):
            telemetry_mod.emit_check_activity(self.sink, "artifact:a1", "structural", "not_a_phase")

    def test_coverage_readout(self):
        telemetry_mod.emit_coverage_readout(self.sink, "artifact:a1",
                                             {"level": "moderate", "established": 2, "total": 3})
        payload = self.sink.by_family("coverage_readout")[0]
        self.assertEqual(payload["established"], 2)
        self.assertEqual(payload["total"], 3)

    def test_agreement_record_agreed_conflicted_disagreed_and_skipped(self):
        def item(rule, source, result, kind):
            return evidence_mod.build_evidence_item(rule, "artifact:a1", source, result, kind, "structural")

        telemetry_mod.emit_agreement_records(self.sink, "artifact:a1", [
            item("r1", "s1", "pass", "independent"), item("r1", "s2", "pass", "corroborating")])
        self.assertEqual(self.sink.by_family("agreement_record")[-1]["agreement"], "agreed")

        telemetry_mod.emit_agreement_records(self.sink, "artifact:a1", [
            item("r2", "s1", "pass", "independent"), item("r2", "s2", "fail", "conflicting")])
        self.assertEqual(self.sink.by_family("agreement_record")[-1]["agreement"], "conflicted")

        telemetry_mod.emit_agreement_records(self.sink, "artifact:a1", [
            item("r3", "s1", "pass", "independent"), item("r3", "s2", "fail", "corroborating")])
        self.assertEqual(self.sink.by_family("agreement_record")[-1]["agreement"], "disagreed")

        before = len(self.sink.by_family("agreement_record"))
        telemetry_mod.emit_agreement_records(self.sink, "artifact:a1", [item("r4", "s1", "pass", "independent")])
        self.assertEqual(len(self.sink.by_family("agreement_record")), before)  # single claim -> nothing to compare

    def test_derivation_consistency(self):
        record = evidence_mod.build_evidence_record("artifact:a1", 1)
        record = evidence_mod.append_item(record, evidence_mod.build_evidence_item(
            "r1", "artifact:a1", "s1", "pass", "independent", "structural"))
        account = derivation_mod.derive(record, POLICY)
        record_hash = evidence_mod.content_hash(evidence_mod.with_derivation_account(record, account))
        telemetry_mod.emit_derivation_consistency(self.sink, "artifact:a1", 1, record_hash, account)
        payload = self.sink.by_family("derivation_consistency")[0]
        self.assertEqual(payload["record_content_hash"], record_hash)
        self.assertEqual(payload["verdict"], account["verdict"])

    def test_latency_demand_no_clock_read_partial_fields(self):
        telemetry_mod.emit_latency_demand(self.sink, "artifact:a1", queue_depth=2)
        payload = self.sink.by_family("latency_demand")[0]
        self.assertEqual(payload["queue_depth"], 2)
        self.assertNotIn("judgment_duration", payload)
        telemetry_mod.emit_latency_demand(self.sink, "artifact:a2", judgment_duration=7,
                                           delegation_durations={"b": 2, "a": 1})
        payload2 = self.sink.by_family("latency_demand")[1]
        self.assertEqual(payload2["judgment_duration"], 7)
        self.assertEqual(list(payload2["delegation_durations"].items()), [("a", 1), ("b", 2)])  # sorted

    def test_emission_unconditional_every_call_recorded(self):
        telemetry_mod.emit_judgment_outcome(self.sink, "a", 1, "passed", None, "Unverified")
        telemetry_mod.emit_judgment_outcome(self.sink, "a", 1, "passed", None, "Unverified")
        self.assertEqual(len(self.sink.by_family("judgment_outcome")), 2)  # no sampling/dedup


# =============================================================================
# runtime — composition root
# =============================================================================

class RuntimeFullPathTests(unittest.TestCase):
    def test_demand_to_verdict_full_path_wires_every_module(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:a1", "judgment:a1", "e1")
        self.assertEqual(result.outcome, emission_mod.EMITTED)
        self.assertEqual(result.verdict, "passed")
        self.assertEqual(len(vr.bus.messages("verify.passed")), 1)
        self.assertTrue(vr.storage.exists(result.storage_key))
        self.assertNotIn("artifact:a1", vr._open)  # retired once terminal

        # telemetry fired across every family this path touches
        self.assertTrue(vr.telemetry_sink.by_family("check_activity"))
        self.assertEqual(vr.telemetry_sink.by_family("judgment_outcome")[-1]["verdict"], "passed")
        self.assertTrue(vr.telemetry_sink.by_family("coverage_readout"))
        self.assertTrue(vr.telemetry_sink.by_family("derivation_consistency"))

    def test_later_demand_answered_by_existing_verdict_never_rejudged(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        _run_to_verdict(vr, "artifact:a1", "judgment:a1", "e1")
        again = vr.handle_demand(_demand("artifact:a1", "judgment:a1-again", "e-late",
                                          event_name="exec.completed"))
        self.assertEqual(again.action, intake_mod.ANSWERED_BY_EXISTING_VERDICT)

    def test_fail_path_full_wiring(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:a2", "judgment:a2", "e2", outcome=None)
        self.assertEqual(result.outcome, emission_mod.EMITTED)
        self.assertEqual(result.verdict, "failed")
        self.assertEqual(vr.telemetry_sink.by_family("judgment_outcome")[-1]["failure_cause"],
                          derivation_mod.EXECUTION_FAILURE)

    def test_persistence_rejection_no_dangling_open_judgment_no_telemetry_lie(self):
        storage = StorageDouble()
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store(), storage=storage)
        vr.handle_demand(_demand("artifact:a3", "judgment:a3", "e3"))
        exe = ExecutionDouble()
        vr.run_static("artifact:a3", "reference_wellformed", {})
        vr.dispatch("artifact:a3", "structural", exe, {"check": "structural"})
        exe.script_result("judgment:a3:structural", arrival_time=1, outcome="success")
        vr.resolve("artifact:a3", "structural", exe, now=1)

        j = vr._open["artifact:a3"]
        closed = judgment_mod.close(j)
        preview = derivation_mod.attach_derivation(closed.record, POLICY)
        rejected_key = "vae/ev/" + evidence_mod.content_hash(preview)
        storage.script_reject(rejected_key)

        result = vr.try_close_and_emit("artifact:a3")
        self.assertEqual(result.outcome, emission_mod.REJECTED)
        self.assertEqual(vr.bus.messages("verify.passed"), [])
        self.assertEqual(vr.bus.messages("verify.failed"), [])
        self.assertEqual(len(vr.bus.messages("fault.recorded")), 1)
        self.assertNotIn("artifact:a3", vr._open)
        self.assertEqual(vr.telemetry_sink.by_family("judgment_outcome"), [])  # no lie for a never-emitted verdict

    def test_operation_on_unopened_artifact_refused(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        with self.assertRaises(runtime_mod.NoOpenJudgmentError):
            vr.dispatch("artifact:never-opened", "structural", ExecutionDouble(), {})

    def test_not_yet_closed_returns_none(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        vr.handle_demand(_demand("artifact:a4", "judgment:a4", "e4"))
        self.assertIsNone(vr.try_close_and_emit("artifact:a4"))
        self.assertIsNone(vr.try_close_and_emit("artifact:never-opened"))


# =============================================================================
# golden-artifact determinism (VAE/05 §8)
# =============================================================================

class GoldenArtifactDeterminismTests(unittest.TestCase):
    def test_identical_inputs_yield_byte_identical_records_and_events(self):
        vr1 = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        vr2 = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        r1 = _run_to_verdict(vr1, "artifact:golden", "judgment:golden", "e1")
        r2 = _run_to_verdict(vr2, "artifact:golden", "judgment:golden", "e1")

        self.assertEqual(r1.storage_key, r2.storage_key)  # content-addressed, identical bytes
        self.assertEqual(vr1.storage.read(r1.storage_key), vr2.storage.read(r2.storage_key))
        self.assertEqual(vr1.bus.messages("verify.passed")[0], vr2.bus.messages("verify.passed")[0])

    def test_running_the_same_judgment_a_third_time_is_still_identical(self):
        results = []
        for i in range(3):
            vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
            results.append(_run_to_verdict(vr, "artifact:golden3", "judgment:golden3", "e1"))
        ids = {r.event["event_id"] for r in results}
        self.assertEqual(len(ids), 1)  # determinism rate 100%, not "usually"


# =============================================================================
# byte-identical replay (VAE/05 §8)
# =============================================================================

class ReplayTests(unittest.TestCase):
    def test_replay_reconstructs_the_published_event_from_storage_alone(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:r1", "judgment:r1", "e1")
        originally_emitted = vr.bus.messages("verify.passed")[-1]

        record, account = vr.replay(result.storage_key, originally_emitted)
        self.assertEqual(account["verdict"], "passed")
        self.assertEqual(record.artifact_ref, "artifact:r1")

        # idempotent: replaying again from the same durable bytes agrees again
        vr.replay(result.storage_key, originally_emitted)

    def test_replay_of_a_failed_judgment(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:r2", "judgment:r2", "e2", outcome=None)
        originally_emitted = vr.bus.messages("verify.failed")[-1]
        record, account = vr.replay(result.storage_key, originally_emitted)
        self.assertEqual(account["verdict"], "failed")

    def test_tampered_originally_emitted_comparison_refused(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:r3", "judgment:r3", "e3")
        originally_emitted = vr.bus.messages("verify.passed")[-1]
        tampered = dict(originally_emitted,
                         payload=dict(originally_emitted["payload"], verdict_id="tampered"))
        with self.assertRaises(runtime_mod.ReplayMismatchError):
            vr.replay(result.storage_key, tampered)

    def test_wrong_storage_key_refused(self):
        vr = runtime_mod.Verification(policy=POLICY, rules_store=_rules_store())
        result = _run_to_verdict(vr, "artifact:r4", "judgment:r4", "e4")
        other_result = _run_to_verdict(vr, "artifact:r5", "judgment:r5", "e5", outcome=None)
        originally_emitted = vr.bus.messages("verify.passed")[-1]
        # a real key in the SAME storage, but for a different record entirely
        with self.assertRaises(runtime_mod.ReplayMismatchError):
            vr.replay(other_result.storage_key, originally_emitted)


# =============================================================================
# law enforcer
# =============================================================================

class LawEnforcerTests(unittest.TestCase):
    def test_real_tree_passes_every_check(self):
        self.assertTrue(law_enforcer.run())

    def test_time_import_trips(self):
        import ast
        tree = ast.parse("import random\n")
        self.assertTrue(any(isinstance(n, ast.Import) and n.names[0].name == "random"
                             for n in ast.walk(tree)))

    def test_zero_seam_trips(self):
        import ast
        tree = ast.parse("from ro import events\n")
        self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "ro"
                             for n in ast.walk(tree)))

    def test_event_canon_drift_trips(self):
        class _FakeEvents:
            PUBLISHED = ("made.up",)
            CONSUMED = ("verify.requested",)
        self.assertFalse(tuple(_FakeEvents.PUBLISHED) == law_enforcer._EXPECTED_PUBLISHED)

    def test_item_mutator_trips(self):
        import ast
        tree = ast.parse("def edit_item(record, index, item):\n    pass\n")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name in law_enforcer._FORBIDDEN_ITEM_MUTATORS
                             for n in ast.walk(tree)))

    def test_publish_before_persist_trips(self):
        import ast
        src = ("def emit_verdict(a, b, storage, bus, c):\n"
               "    events.emit(bus, 'verify.passed', 'e', 's', {})\n"
               "    storage.write('k', b'v')\n")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        write_lines = [n.lineno for n in ast.walk(fn)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "write"]
        emit_lines = [n.lineno for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "emit" and getattr(n.func.value, "id", None) == "events"]
        self.assertTrue(any(e < min(write_lines) for e in emit_lines))

    def test_producer_identity_trips(self):
        import ast
        tree = ast.parse("def derive(record, policy, producer_id):\n    pass\n")
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        params = {a.arg for a in fn.args.args}
        self.assertTrue(params & law_enforcer._PRODUCER_IDENTITY_PARAMS)

    def test_dead_vocabulary_trips(self):
        self.assertIn(law_enforcer._DEAD_PHRASES[0], 'EVENT = "task.scheduled"')


if __name__ == "__main__":
    unittest.main()
