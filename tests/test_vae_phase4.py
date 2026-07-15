"""VAE Phase 4 suite — VAE/06-implementation-blueprint.md Phase 4
(choreography: persist-then-publish, loud absence, pending projection).
Covers: emission ordering (storage write observed before bus publish);
scripted storage rejection -> fault.recorded, zero verify.* events, record
absent; exactly-one-emission (a second attempt refused); VAE/03 §2.1
payload contract (all required fields present, failure_cause/reasons only
on verify.failed, no artifact content anywhere in a payload); deterministic
event ids (same closed body -> same id, twice); pending rebuild determinism
(build -> lose -> rebuild -> identical projection); terminal-not-reopened
after rebuild; crash-with-in-flight-delegation expires correctly post-
rebuild through delegation.py's existing machinery; an end-to-end
Phase 1-3 + emission integration wired by hand (no runtime, per Phase 4/5
scope split)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from vae import derivation as derivation_mod
from vae import emission as emission_mod
from vae import evidence
from vae import judgment as judgment_mod
from vae import pending as pending_mod
from vae.bus_double import BusDouble
from vae.execution_double import ExecutionDouble
from vae.intake import Intake
from vae.rules import RulesStore
from vae.static_checks import StaticCheckRegistry
from vae.storage_double import StorageDouble

POLICY = derivation_mod.build_derivation_policy(
    1, coverage_moderate_min_fraction=0.5, coverage_strong_min_fraction=0.9)


def _closed_pass_judgment(artifact_ref="artifact:a1", judgment_id="judgment:a1"):
    exe = ExecutionDouble()
    registry = StaticCheckRegistry()
    j = judgment_mod.open_judgment(
        judgment_id, artifact_ref, rules_version=1,
        delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
        static_checks_spec={"reference_wellformed": {"level": "system"}})
    j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
    j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
    exe.script_result(judgment_id + ":structural", arrival_time=1, outcome="success")
    j = judgment_mod.resolve_delegation(j, "structural", exe, now=1)
    return judgment_mod.close(j)


def _closed_fail_judgment(artifact_ref="artifact:a2", judgment_id="judgment:a2"):
    exe = ExecutionDouble()
    j = judgment_mod.open_judgment(
        judgment_id, artifact_ref, rules_version=1,
        delegated_checks={"structural": {"deadline": 5, "level": "structural"}},
        static_checks_spec={})
    j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
    j = judgment_mod.resolve_delegation(j, "structural", exe, now=5)  # no result -> expiry
    return judgment_mod.close(j)


# -- ordering: persist observed before publish (VAE-O5) ----------------------

class OrderingRecordingStorage(StorageDouble):
    def __init__(self, order_log):
        super().__init__()
        self._order_log = order_log

    def write(self, key, data):
        self._order_log.append("storage.write")
        return super().write(key, data)


class OrderingRecordingBus(BusDouble):
    def __init__(self, order_log):
        super().__init__()
        self._order_log = order_log

    def publish(self, topic, message):
        self._order_log.append("bus.publish:" + topic)
        return super().publish(topic, message)


class EmissionOrderingTests(unittest.TestCase):
    def test_storage_write_observed_before_bus_publish(self):
        order = []
        storage = OrderingRecordingStorage(order)
        bus = OrderingRecordingBus(order)
        intake = Intake()
        result = emission_mod.emit_verdict(_closed_pass_judgment(), POLICY, storage, bus, intake)
        self.assertEqual(result.outcome, emission_mod.EMITTED)
        self.assertEqual(order, ["storage.write", "bus.publish:verify.passed"])

    def test_rejection_never_publishes_before_the_write_attempt(self):
        order = []
        storage = OrderingRecordingStorage(order)
        bus = OrderingRecordingBus(order)
        intake = Intake()
        j = _closed_pass_judgment(artifact_ref="artifact:a9", judgment_id="judgment:a9")
        account_record = derivation_mod.attach_derivation(j.record, POLICY)
        key = "vae/ev/" + evidence.content_hash(account_record)
        storage.script_reject(key)
        result = emission_mod.emit_verdict(j, POLICY, storage, bus, intake)
        self.assertEqual(result.outcome, emission_mod.REJECTED)
        self.assertEqual(order, ["storage.write", "bus.publish:fault.recorded"])


# -- storage rejection: loud absence, never a recordless verdict (VAE-O6) ----

class PersistenceRejectionTests(unittest.TestCase):
    def test_rejected_write_yields_fault_recorded_and_zero_verdicts(self):
        storage, bus, intake = StorageDouble(), BusDouble(), Intake()
        j = _closed_pass_judgment(artifact_ref="artifact:a3", judgment_id="judgment:a3")
        account_record = derivation_mod.attach_derivation(j.record, POLICY)
        key = "vae/ev/" + evidence.content_hash(account_record)
        storage.script_reject(key)

        result = emission_mod.emit_verdict(j, POLICY, storage, bus, intake)

        self.assertEqual(result.outcome, emission_mod.REJECTED)
        self.assertFalse(storage.exists(key))
        self.assertEqual(bus.messages("verify.passed"), [])
        self.assertEqual(bus.messages("verify.failed"), [])
        self.assertEqual(len(bus.messages("fault.recorded")), 1)
        fault_payload = bus.messages("fault.recorded")[0]["payload"]
        self.assertEqual(fault_payload["reason"], "storage_rejected")
        self.assertEqual(fault_payload["artifact_id"], "artifact:a3")
        self.assertIsNone(intake.terminal_verdict("artifact:a3"))


# -- exactly-one-emission (VAE/04 §5.3) ---------------------------------------

class ExactlyOneEmissionTests(unittest.TestCase):
    def test_second_emission_attempt_is_refused(self):
        storage, bus, intake = StorageDouble(), BusDouble(), Intake()
        j = _closed_pass_judgment()
        first = emission_mod.emit_verdict(j, POLICY, storage, bus, intake)
        self.assertEqual(first.outcome, emission_mod.EMITTED)
        with self.assertRaises(emission_mod.AlreadyEmittedError):
            emission_mod.emit_verdict(j, POLICY, storage, bus, intake)
        # still exactly one verdict event published
        self.assertEqual(len(bus.messages("verify.passed")), 1)

    def test_emission_before_close_is_refused(self):
        exe = ExecutionDouble()
        j_open = judgment_mod.open_judgment(
            "judgment:a4", "artifact:a4", 1,
            delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
            static_checks_spec={})
        with self.assertRaises(emission_mod.JudgmentNotClosedError):
            emission_mod.emit_verdict(j_open, POLICY, StorageDouble(), BusDouble(), Intake())


# -- VAE/03 §2.1 payload contract ---------------------------------------------

class PayloadContractTests(unittest.TestCase):
    def test_verify_passed_payload_has_required_fields_and_no_failure_fields(self):
        storage, bus, intake = StorageDouble(), BusDouble(), Intake()
        emission_mod.emit_verdict(_closed_pass_judgment(), POLICY, storage, bus, intake)
        payload = bus.messages("verify.passed")[0]["payload"]
        for field in ("verdict_id", "artifact_id", "rules_version",
                      "evidence_record_ref", "assurance_level"):
            self.assertIn(field, payload)
        self.assertNotIn("failure_cause", payload)
        self.assertNotIn("reasons", payload)

    def test_verify_failed_payload_has_failure_cause_and_reasons(self):
        storage, bus, intake = StorageDouble(), BusDouble(), Intake()
        emission_mod.emit_verdict(_closed_fail_judgment(), POLICY, storage, bus, intake)
        payload = bus.messages("verify.failed")[0]["payload"]
        for field in ("verdict_id", "artifact_id", "rules_version",
                      "evidence_record_ref", "assurance_level", "failure_cause", "reasons"):
            self.assertIn(field, payload)
        self.assertEqual(payload["failure_cause"], derivation_mod.EXECUTION_FAILURE)
        self.assertTrue(payload["reasons"])

    def test_no_payload_ever_carries_artifact_content(self):
        # every payload field is a reference/id/string classification, never
        # a body — spot-check by type/shape rather than by name, since VAE
        # has no concept of "artifact content" objects to compare against.
        storage, bus, intake = StorageDouble(), BusDouble(), Intake()
        emission_mod.emit_verdict(_closed_pass_judgment(), POLICY, storage, bus, intake)
        payload = bus.messages("verify.passed")[0]["payload"]
        for value in payload.values():
            self.assertIsInstance(value, (str, int, float))


# -- deterministic event ids (VAE-I6, RO `<record_hash>:<suffix>` pattern) ---

class DeterministicEventIdTests(unittest.TestCase):
    def test_same_closed_body_yields_same_event_id_twice(self):
        storage1, bus1, intake1 = StorageDouble(), BusDouble(), Intake()
        storage2, bus2, intake2 = StorageDouble(), BusDouble(), Intake()
        r1 = emission_mod.emit_verdict(_closed_pass_judgment(), POLICY, storage1, bus1, intake1)
        r2 = emission_mod.emit_verdict(_closed_pass_judgment(), POLICY, storage2, bus2, intake2)
        self.assertEqual(r1.event["event_id"], r2.event["event_id"])
        self.assertEqual(r1.storage_key, r2.storage_key)


# -- pending rebuild -----------------------------------------------------------

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


def _demand(artifact_ref, judgment_id, event_id):
    return {
        "event_name": "verify.requested", "event_id": event_id,
        "artifact_ref": artifact_ref, "judgment_id": judgment_id,
        "artifact_type": "plugin_output", "rules_version": 1,
        "delegated_check_levels": {"structural": "structural"},
        "static_check_levels": {"reference_wellformed": "system"},
    }


class PendingRebuildTests(unittest.TestCase):
    def test_rebuild_determinism(self):
        rules_store = _rules_store()
        demands = [_demand("artifact:a1", "judgment:a1", "e1"),
                   _demand("artifact:a2", "judgment:a2", "e2")]
        proj1 = pending_mod.rebuild(demands, {}, rules_store)
        proj2 = pending_mod.rebuild(demands, {}, rules_store)
        self.assertEqual(proj1.judgments, proj2.judgments)

    def test_lost_projection_rebuilds_identically(self):
        rules_store = _rules_store()
        demands = [_demand("artifact:a1", "judgment:a1", "e1")]
        built = pending_mod.rebuild(demands, {}, rules_store)
        # simulate loss: discard `built` entirely (nothing carried over)
        del built
        rebuilt = pending_mod.rebuild(demands, {}, rules_store)
        self.assertIn("artifact:a1", rebuilt.judgments)
        self.assertEqual(rebuilt.judgments["artifact:a1"].rules_version, 1)

    def test_terminal_verdict_never_reopened(self):
        rules_store = _rules_store()
        record = evidence.build_evidence_record("artifact:a1", 1)
        record = evidence.append_item(record, evidence.build_evidence_item(
            "rule.structural", "artifact:a1", "check.structural", "pass",
            "independent", "structural"))
        persisted = derivation_mod.attach_derivation(record, POLICY)

        demands = [_demand("artifact:a1", "judgment:a1", "e1"),
                   _demand("artifact:a2", "judgment:a2", "e2")]
        proj = pending_mod.rebuild(demands, {"artifact:a1": persisted}, rules_store)

        self.assertNotIn("artifact:a1", proj.judgments)
        self.assertIn("artifact:a2", proj.judgments)
        self.assertIsNotNone(proj.intake.terminal_verdict("artifact:a1"))

    def test_crash_with_in_flight_delegation_expires_post_rebuild(self):
        rules_store = _rules_store()
        demand = _demand("artifact:a2", "judgment:a2", "e2")

        # "before crash": dispatch a delegation but never resolve it
        proj_before = pending_mod.rebuild([demand], {}, rules_store)
        exe_before = ExecutionDouble()
        j_before = judgment_mod.dispatch_delegation(
            proj_before.get("artifact:a2"), "structural", exe_before, {"check": "structural"})
        proj_before.update(j_before)
        self.assertEqual(j_before.delegations["structural"].state, "dispatched")

        # "crash": build a brand-new projection from the same durable inputs only
        proj_after = pending_mod.rebuild([demand], {}, rules_store)
        recovered = proj_after.get("artifact:a2")
        # dispatch state is NOT resurrected (VAE-O1: pending state itself is not durable)
        self.assertEqual(recovered.delegations["structural"].state, "required")
        # rules-assigned deadline is preserved across the crash
        self.assertEqual(recovered.delegations["structural"].deadline, 10)

        # existing machinery (delegation.py) carries it to expiry, no bespoke path
        registry = StaticCheckRegistry()
        recovered = judgment_mod.run_static_check(recovered, "reference_wellformed", registry, {})
        exe_after = ExecutionDouble()
        recovered = judgment_mod.dispatch_delegation(
            recovered, "structural", exe_after, {"check": "structural"})
        recovered = judgment_mod.resolve_delegation(recovered, "structural", exe_after, now=10)
        self.assertTrue(judgment_mod.is_closed(recovered))
        self.assertEqual(recovered.delegations["structural"].state, "expired")
        closed = judgment_mod.close(recovered)
        account = derivation_mod.derive(closed.record, POLICY)
        self.assertEqual(account["failure_cause"], derivation_mod.EXECUTION_FAILURE)


# -- Phase 1-3 + emission end-to-end, manually wired (no runtime) -------------

class EndToEndIntegrationTests(unittest.TestCase):
    def test_demand_to_verdict_full_path(self):
        rules_store = _rules_store()
        intake = Intake()
        storage = StorageDouble()
        bus = BusDouble()

        demand = _demand("artifact:e2e", "judgment:e2e", "e1")
        proj = pending_mod.rebuild([demand], {}, rules_store)
        # rebuild's own Intake is throwaway for this test; use the shared one
        # that emission will also check, mirroring real composition.
        intake_result = intake.receive("verify.requested", "e1", "artifact:e2e", "judgment:e2e")
        self.assertEqual(intake_result.action, "opened")

        j = proj.get("artifact:e2e")
        exe = ExecutionDouble()
        registry = StaticCheckRegistry()
        j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
        j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result("judgment:e2e:structural", arrival_time=1, outcome="success")
        j = judgment_mod.resolve_delegation(j, "structural", exe, now=1)
        self.assertTrue(judgment_mod.is_closed(j))
        j = judgment_mod.close(j)

        result = emission_mod.emit_verdict(j, POLICY, storage, bus, intake)
        self.assertEqual(result.outcome, emission_mod.EMITTED)
        self.assertEqual(result.verdict, "passed")
        self.assertEqual(len(bus.messages("verify.passed")), 1)
        self.assertTrue(storage.exists(result.storage_key))
        self.assertEqual(intake.terminal_verdict("artifact:e2e"), result.evidence_record_ref)

        # a subsequent demand for the same artifact is answered by the
        # existing verdict, never re-judged (VAE/04 §2.2, via the same intake)
        again = intake.receive("exec.completed", "e-late", "artifact:e2e", "judgment:e2e-again")
        self.assertEqual(again.action, "answered_by_existing_verdict")
        self.assertEqual(again.verdict_ref, result.evidence_record_ref)


if __name__ == "__main__":
    unittest.main()
