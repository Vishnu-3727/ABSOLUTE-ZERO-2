"""Behavioral spec suite for the Kernel — KERNEL/10-test-spec.md.

Every test method name carries its spec ID. The spec defines 34 stable IDs
(IT 7, DT 3, RT 4, CR 3, FI 4, EO 3, CT 3, CF 3, BT 4); all are implemented
here. Structural tests (IT-7, BT-1, BT-4) audit the kernel source with
ast/regex instead of running scenarios.
"""
import ast
import copy
import dataclasses
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kernel import Bus, Coordinator, snapshot
from kernel import router
from kernel.config_view import ConfigView

KERNEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "kernel")

OUT_TOPICS = (
    "request.admitted", "request.rejected", "request.completed",
    "request.failed", "request.cancelled", "gate.enforced",
    "fault.recorded", "routing.directive",
)


def env(event_id, name, rid, payload=None, ts=0):
    return {"event_id": event_id, "event_name": name, "request_id": rid,
            "timestamp": ts, "payload": payload if payload is not None else {}}


def received(event_id, rid, declared_type="type.alpha", ts=0):
    return env(event_id, "request.received", rid, {"declared_type": declared_type}, ts)


def ledger_canon(coord):
    """Canonical bytes of the full Ledger (byte-identical comparison)."""
    entries = {}
    for rid in coord.ledger.request_ids():
        data = dataclasses.asdict(coord.ledger.get(rid))
        entries[rid] = data
    return json.dumps(entries, sort_keys=True).encode()


def log_canon(coord):
    return json.dumps(coord.log, sort_keys=True).encode()


def kernel_sources():
    for name in sorted(os.listdir(KERNEL_DIR)):
        if name.endswith(".py"):
            path = os.path.join(KERNEL_DIR, name)
            with open(path, encoding="utf-8") as handle:
                yield name, handle.read()


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.coord = Coordinator(self.bus, snapshot())
        self._eid = 0

    def send(self, name, rid, payload=None, event_id=None, ts=0):
        if event_id is None:
            self._eid += 1
            event_id = "e%d" % self._eid
        e = env(event_id, name, rid, payload, ts)
        self.coord.handle(e)
        return e

    def drive(self, rid, state, declared_type="type.alpha"):
        """Drive a fresh request to a resting state via events."""
        self.coord.handle(received("%s-adm" % rid, rid, declared_type))
        if state == "scheduled":
            return
        self.send("plan.created", rid)
        if state == "executing":
            return
        if state == "verifying":
            self.send("task.completed", rid)  # no verdict -> blocked into verifying
            return
        if state == "completed":
            self.send("verify.passed", rid)
            self.send("task.completed", rid)
            return
        raise AssertionError("state not reachable at rest between events: " + state)

    def state(self, rid):
        entry = self.coord.ledger.get(rid)
        return None if entry is None else entry.lifecycle_state

    def emitted(self, topic):
        return self.bus.messages(topic)


# ---------------------------------------------------------------------------
# 1. Invariant tests
# ---------------------------------------------------------------------------
class InvariantTests(KernelCase):
    def test_IT_1_duplicate_never_mutates(self):
        self.drive("r1", "executing")
        event = self.send("verify.passed", "r1")
        before = copy.deepcopy(dataclasses.asdict(self.coord.ledger.get("r1")))
        faults_before = len(self.emitted("fault.recorded"))
        self.coord.handle(event)  # exact same envelope redelivered
        after = dataclasses.asdict(self.coord.ledger.get("r1"))
        self.assertEqual(before, after)  # no state mutation
        self.assertEqual(self.coord.log[-1].get("verdict"), "duplicate")
        self.assertEqual(len(self.emitted("fault.recorded")), faults_before)  # no fault

    def test_IT_2_missing_verdict_blocks_completion(self):
        self.drive("r1", "executing")
        self.send("task.completed", "r1")
        self.assertEqual(self.state("r1"), "verifying")
        gate = self.emitted("gate.enforced")[-1]
        self.assertEqual(gate["payload"]["decision"], "block")
        self.assertEqual(gate["payload"]["gate"], "completion")

    def test_IT_3_failed_verdict_never_completes(self):
        self.drive("r1", "executing")
        self.send("verify.failed", "r1")
        self.send("task.completed", "r1")
        self.assertEqual(self.state("r1"), "verifying")
        self.assertEqual(self.emitted("request.completed"), [])

    def test_IT_4_unknown_request_verdict_is_fault_no_entry(self):
        self.send("verify.passed", "ghost")
        self.assertIsNone(self.coord.ledger.get("ghost"))
        faults = self.emitted("fault.recorded")
        self.assertEqual(len(faults), 1)
        self.assertIn("request.unknown", faults[0]["payload"]["reason"])

    def test_IT_5_unknown_or_ambiguous_type_rejected_never_routed(self):
        data = snapshot()
        data["routing_table"]["type.multi"] = ["planning", "scheduling"]
        coord = Coordinator(self.bus, data)
        coord.handle(received("a1", "u1", "type.unknown"))
        coord.handle(received("a2", "u2", "type.multi"))
        self.assertEqual(coord.ledger.get("u1").lifecycle_state, "failed")
        self.assertEqual(coord.ledger.get("u2").lifecycle_state, "failed")
        self.assertEqual(self.emitted("routing.directive"), [])
        reasons = [m["payload"]["reason"] for m in self.emitted("request.rejected")]
        self.assertEqual(reasons, ["routing.unknown_type", "routing.ambiguous_type"])

    def test_IT_6_unmatched_state_event_pair_faults_state_unchanged(self):
        self.drive("r1", "scheduled")
        self.send("task.completed", "r1")  # not legal from scheduled
        self.assertEqual(self.state("r1"), "scheduled")
        faults = self.emitted("fault.recorded")
        self.assertEqual(len(faults), 1)
        self.assertIn("transition.unmatched:scheduled|task.completed",
                      faults[0]["payload"]["reason"])

    def test_IT_7_coordinator_sole_ledger_mutator(self):
        mutation = re.compile(
            r"\._(?:create|evict)\(|"
            r"\.(?:lifecycle_state|transition_sequence|replan_count|"
            r"last_applied_event_id|routing_target|cancellation_flag)\s*=[^=]|"
            r"\.recorded_verdicts\[")
        for name, source in kernel_sources():
            if name in ("coordinator.py", "ledger.py"):
                continue
            body = source.split('if __name__ ==', 1)[0]  # selftests exempt
            self.assertIsNone(mutation.search(body),
                              "%s mutates the Ledger; only coordinator may (I1)" % name)


# ---------------------------------------------------------------------------
# 2. Determinism tests
# ---------------------------------------------------------------------------
SCENARIO = (
    [received("s1", "d1")]
    + [env("s%d" % i, name, "d1", {}) for i, name in enumerate(
        ("plan.created", "verify.passed", "task.completed"), start=2)]
    + [received("s10", "d2", "type.beta"),
       env("s11", "task.failed", "d2", {"reason": "timeout"}),
       env("s12", "request.cancelled", "d2", {})]
)


class DeterminismTests(KernelCase):
    def test_DT_1_same_events_same_config_byte_identical_logs(self):
        runs = []
        for _ in range(2):
            coord = Coordinator(Bus(), snapshot())
            for event in copy.deepcopy(SCENARIO):
                coord.handle(event)
            runs.append(log_canon(coord))
        self.assertEqual(runs[0], runs[1])

    def test_DT_2_no_timestamp_participates_in_guards(self):
        logs = []
        for stamp in (0, 999999):
            coord = Coordinator(Bus(), snapshot(), clock=lambda s=stamp: s)
            for event in copy.deepcopy(SCENARIO):
                event["timestamp"] = stamp
                coord.handle(event)
            logs.append(log_canon(coord))
        self.assertEqual(logs[0], logs[1])  # decisions immune to time (I10)

    def test_DT_3_routing_is_static_forever(self):
        cfg = ConfigView(snapshot())
        results = {router.route("type.alpha", cfg) for _ in range(1000)}
        self.assertEqual(results, {("planning", "")})


# ---------------------------------------------------------------------------
# 3. Replay tests
# ---------------------------------------------------------------------------
class ReplayTests(KernelCase):
    def full_log(self):
        for event in copy.deepcopy(SCENARIO):
            self.coord.handle(event)
        return list(self.coord.log)

    def test_RT_1_replay_rebuilds_byte_identical_ledger(self):
        records = self.full_log()
        fresh = Coordinator(Bus(), snapshot())
        self.assertTrue(fresh.recover(records))
        self.assertEqual(ledger_canon(fresh), ledger_canon(self.coord))
        self.assertEqual(log_canon(fresh), log_canon(self.coord))

    def test_RT_2_altered_record_detected_halt_fault(self):
        records = copy.deepcopy(self.full_log())
        records[1]["next_state"] = "completed"  # tamper
        bus = Bus()
        fresh = Coordinator(bus, snapshot())
        self.assertFalse(fresh.recover(records))
        self.assertTrue(fresh.halted)
        faults = bus.messages("fault.recorded")
        self.assertTrue(faults and "replay.deviation" in faults[-1]["payload"]["reason"])

    def test_RT_3_replay_uses_logged_config_version_not_current(self):
        self.drive("r1", "executing")
        new = snapshot(version=2)
        new["fault_policy"]["max_replans"] = 0
        self.send("config.changed", None, {"snapshot": new})
        self.send("task.failed", "r1", {"reason": "timeout"})  # pinned v1 permits replan
        records = list(self.coord.log)
        fresh = Coordinator(Bus(), snapshot())
        self.assertTrue(fresh.recover(records))
        self.assertEqual(fresh._config.version, 2)  # current config is v2
        entry = fresh.ledger.get("r1")
        self.assertEqual(entry.config_version, 1)   # decisions replayed under v1
        self.assertEqual(entry.lifecycle_state, "scheduled")
        self.assertEqual([rec["config_version"] for rec in records
                          if rec["request_id"] == "r1"], [1, 1, 1, 1])

    def test_RT_4_dedup_noop_records_replay_as_noops(self):
        self.drive("r1", "executing")
        event = self.send("verify.passed", "r1")
        self.coord.handle(event)  # duplicate -> no-op record in log
        records = list(self.coord.log)
        fresh = Coordinator(Bus(), snapshot())
        self.assertTrue(fresh.recover(records))
        self.assertEqual(ledger_canon(fresh), ledger_canon(self.coord))
        noops = [rec for rec in fresh.log if rec.get("verdict") == "duplicate"]
        self.assertEqual(len(noops), 1)


# ---------------------------------------------------------------------------
# 4. Crash recovery tests
# ---------------------------------------------------------------------------
class CrashRecoveryTests(KernelCase):
    def test_CR_1_logged_but_unpublished_directive_reemitted(self):
        self.drive("r1", "scheduled")
        records = list(self.coord.log)
        directive_record = next(rec for rec in records
                                if "routing.directive" in rec["emitted_events"])
        published = {(rec["request_id"], rec["sequence"]) for rec in records
                     if rec is not directive_record}
        bus = Bus()
        fresh = Coordinator(bus, snapshot())
        self.assertTrue(fresh.recover(records, published=published))
        directives = bus.messages("routing.directive")
        self.assertEqual(len(directives), 1)
        self.assertEqual(directives[0]["payload"]["target"], "planning")
        self.assertEqual(directives[0]["payload"]["request_id"], "r1")

    def test_CR_2_recovery_rejoins_exact_state(self):
        # 'created' resolves within a single event processing, so a crash
        # there leaves no record: at-least-once redelivery of
        # request.received rebuilds it — asserted last.
        for state in ("initialized", "scheduled", "executing", "verifying"):
            coord = Coordinator(Bus(), snapshot())
            coord.handle(received("c1", "r1"))
            coord.handle(env("c2", "plan.created", "r1", {}))
            coord.handle(env("c3", "task.completed", "r1", {}))
            prefix = []
            for rec in coord.log:
                prefix.append(rec)
                if rec["next_state"] == state:
                    break
            fresh = Coordinator(Bus(), snapshot())
            self.assertTrue(fresh.recover(prefix))
            self.assertEqual(fresh.ledger.get("r1").lifecycle_state, state)
        fresh = Coordinator(Bus(), snapshot())
        self.assertTrue(fresh.recover([]))  # crash in 'created': nothing logged
        self.assertIsNone(fresh.ledger.get("r1"))
        fresh.handle(received("c1", "r1"))  # redelivery (at-least-once)
        self.assertEqual(fresh.ledger.get("r1").lifecycle_state, "scheduled")

    def test_CR_3_crash_during_recovery_is_idempotent(self):
        for event in copy.deepcopy(SCENARIO):
            self.coord.handle(event)
        records = list(self.coord.log)
        fresh = Coordinator(Bus(), snapshot())
        self.assertTrue(fresh.recover(records[:3]))  # first recovery crashes midway
        self.assertTrue(fresh.recover(records))      # second recovery from scratch
        self.assertEqual(ledger_canon(fresh), ledger_canon(self.coord))
        self.assertEqual(log_canon(fresh), log_canon(self.coord))


# ---------------------------------------------------------------------------
# 5. Fault injection tests
# ---------------------------------------------------------------------------
class FaultInjectionTests(KernelCase):
    def test_FI_1_communication_unavailable_halts_without_loss(self):
        self.bus.fail_publishes = True
        self.coord.handle(received("f1", "r1"))  # must not raise
        self.assertTrue(self.coord.halted)
        self.assertTrue(self.coord.log)  # records retained: no event loss
        self.bus.fail_publishes = False
        self.coord.handle(received("f2", "r2"))
        self.assertEqual(self.state("r2"), "failed")  # halted: admissions refused
        reasons = [m["payload"]["reason"] for m in self.emitted("request.rejected")]
        self.assertEqual(reasons, ["admission.halted"])

    def test_FI_2_invalid_config_rejected_last_good_retained(self):
        bad = snapshot(version=2)
        del bad["routing_table"]
        self.send("config.changed", None, {"snapshot": bad})
        faults = self.emitted("fault.recorded")
        self.assertEqual(len(faults), 1)
        self.assertIn("config.invalid", faults[0]["payload"]["reason"])
        self.assertEqual(self.coord._config.version, 1)  # last-good retained
        self.drive("r1", "scheduled")  # still fully operational under v1
        self.assertEqual(self.state("r1"), "scheduled")

    def test_FI_3_exhaustion_refuses_admissions_protects_active(self):
        data = snapshot()
        data["fault_policy"]["max_active_requests"] = 1
        coord = Coordinator(self.bus, data)
        coord.handle(received("x1", "r1"))
        self.assertEqual(coord.ledger.get("r1").lifecycle_state, "scheduled")
        coord.handle(received("x2", "r2"))  # over threshold
        self.assertEqual(coord.ledger.get("r2").lifecycle_state, "failed")
        self.assertIn("admission.exhausted",
                      self.emitted("request.rejected")[0]["payload"]["reason"])
        coord.handle(env("x3", "plan.created", "r1", {}))  # active request untouched
        coord.handle(env("x4", "verify.passed", "r1", {}))
        coord.handle(env("x5", "task.completed", "r1", {}))
        self.assertEqual(coord.ledger.get("r1").lifecycle_state, "completed")

    def test_FI_4_poison_envelope_faults_and_loop_continues(self):
        poisons = ("not a mapping",
                   {"event_id": "p2"},                                  # missing fields
                   env("p3", "task.started", "r1", {}),                 # unknown name
                   env("", "request.received", "r1", {}))               # bad event id
        for poison in poisons:
            self.coord.handle(poison)
        self.assertEqual(len(self.emitted("fault.recorded")), len(poisons))
        self.assertFalse(self.coord.halted)
        self.drive("r1", "scheduled")  # loop continues
        self.assertEqual(self.state("r1"), "scheduled")


# ---------------------------------------------------------------------------
# 6. Event ordering tests
# ---------------------------------------------------------------------------
class EventOrderingTests(KernelCase):
    def test_EO_1_transitions_follow_arrival_order(self):
        self.drive("r1", "scheduled")
        for name in ("plan.created", "verify.passed", "task.completed"):
            self.send(name, "r1")
        events = [rec["event"] for rec in self.coord.log if rec["request_id"] == "r1"]
        self.assertEqual(events, ["request.received", "__routing__",
                                  "plan.created", "verify.passed", "task.completed"])

    def test_EO_2_interleaved_requests_match_isolated_runs(self):
        streams = {
            "a": [received("ea0", "a"), env("ea1", "plan.created", "a", {}),
                  env("ea2", "verify.passed", "a", {}), env("ea3", "task.completed", "a", {})],
            "b": [received("eb0", "b", "type.beta"), env("eb1", "plan.created", "b", {}),
                  env("eb2", "task.failed", "b", {}), env("eb3", "request.cancelled", "b", {})],
        }
        isolated = {}
        for rid, stream in streams.items():
            coord = Coordinator(Bus(), snapshot())
            for event in copy.deepcopy(stream):
                coord.handle(event)
            isolated[rid] = (coord.ledger.get(rid).lifecycle_state,
                             [rec for rec in coord.log if rec["request_id"] == rid])
        interleaved = [item for pair in zip(streams["a"], streams["b"]) for item in pair]
        coord = Coordinator(Bus(), snapshot())
        for event in copy.deepcopy(interleaved):
            coord.handle(event)
        for rid in ("a", "b"):
            self.assertEqual(coord.ledger.get(rid).lifecycle_state, isolated[rid][0])
            mine = [rec for rec in coord.log if rec["request_id"] == rid]
            self.assertEqual(json.dumps(mine, sort_keys=True),
                             json.dumps(isolated[rid][1], sort_keys=True))

    def test_EO_3_early_verdict_recorded_then_gate_permits(self):
        self.drive("r1", "executing")
        self.send("verify.passed", "r1")   # verdict before task.completed
        self.send("task.completed", "r1")
        self.assertEqual(self.state("r1"), "completed")
        gate = self.emitted("gate.enforced")[-1]
        self.assertEqual(gate["payload"], {"request_id": "r1", "gate": "completion",
                                           "decision": "permit"})


# ---------------------------------------------------------------------------
# 7. Cancellation tests
# ---------------------------------------------------------------------------
class CancellationTests(KernelCase):
    def test_CT_1_cancel_legal_from_every_non_terminal_state(self):
        # created/initialized resolve within one event processing and are
        # never at rest between events; their legality is table data.
        cfg = snapshot()
        for state in ("created", "initialized"):
            row = cfg["transitions"][state + "|request.cancelled"][0]
            self.assertEqual(row["next"], "cancelled")
        for state in ("scheduled", "executing", "verifying"):
            bus = Bus()
            coord = Coordinator(bus, snapshot())
            coord.handle(received("k1", "r1"))
            if state != "scheduled":
                coord.handle(env("k2", "plan.created", "r1", {}))
            if state == "verifying":
                coord.handle(env("k3", "task.completed", "r1", {}))
            self.assertEqual(coord.ledger.get("r1").lifecycle_state, state)
            coord.handle(env("k9", "request.cancelled", "r1", {}))
            entry = coord.ledger.get("r1")
            self.assertEqual(entry.lifecycle_state, "cancelled")
            self.assertTrue(entry.cancellation_flag)
            acks = bus.messages("request.cancelled")
            self.assertEqual(len(acks), 1)
            self.assertTrue(acks[0]["payload"]["ack"])
            # cleanup: eviction at the session boundary
            coord.handle(env("k10", "session.sleep", None, {}))
            self.assertIsNone(coord.ledger.get("r1"))
            self.assertEqual(coord.log[-1]["next_state"], "cleanup")

    def test_CT_2_cancel_on_terminal_request_is_noop(self):
        self.drive("r1", "completed")
        self.send("request.cancelled", "r1")
        self.assertEqual(self.state("r1"), "completed")
        self.assertEqual(self.emitted("request.cancelled"), [])  # no ack
        self.assertEqual(self.emitted("fault.recorded"), [])

    def test_CT_3_second_cancel_single_ack_dedup_noop(self):
        self.drive("r1", "scheduled")
        event = self.send("request.cancelled", "r1")
        self.coord.handle(event)  # redelivered cancel, same event id
        self.assertEqual(len(self.emitted("request.cancelled")), 1)  # single ack
        self.assertEqual(self.coord.log[-1].get("verdict"), "duplicate")
        self.assertEqual(self.state("r1"), "cancelled")


# ---------------------------------------------------------------------------
# 8. Configuration tests
# ---------------------------------------------------------------------------
class ConfigurationTests(KernelCase):
    def test_CF_1_in_flight_pinned_all_decisions_log_version(self):
        self.drive("r1", "executing")
        new = snapshot(version=2)
        new["fault_policy"]["max_replans"] = 0
        self.send("config.changed", None, {"snapshot": new})
        self.send("task.failed", "r1", {"reason": "timeout"})
        self.assertEqual(self.state("r1"), "scheduled")  # v1 policy: replan permitted
        self.drive("r2", "executing")
        self.send("task.failed", "r2", {"reason": "timeout"})
        self.assertEqual(self.state("r2"), "failed")     # v2 policy: zero replans
        for rec in self.coord.log:
            if rec["request_id"] == "r1":
                self.assertEqual(rec["config_version"], 1)
            elif rec["request_id"] == "r2":
                self.assertEqual(rec["config_version"], 2)

    def test_CF_2_policy_change_effective_without_recompile(self):
        self.coord.handle(received("g1", "r1", "type.gamma"))
        self.assertEqual(self.state("r1"), "failed")  # unknown under v1
        new = snapshot(version=2)
        new["routing_table"]["type.gamma"] = "scheduling"
        self.send("config.changed", None, {"snapshot": new})
        self.coord.handle(received("g2", "r2", "type.gamma"))
        self.assertEqual(self.state("r2"), "scheduled")
        self.assertEqual(self.emitted("routing.directive")[0]["payload"]["target"],
                         "scheduling")

    def test_CF_3_replan_exhaustion_fails_request(self):
        self.drive("r1", "executing")
        for _ in range(2):  # max_replans = 2 in default config
            self.send("task.failed", "r1", {"reason": "timeout"})
            self.assertEqual(self.state("r1"), "scheduled")
            self.send("plan.created", "r1")
        self.send("task.failed", "r1", {"reason": "timeout"})
        self.assertEqual(self.state("r1"), "failed")
        failed = self.emitted("request.failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["payload"]["request_id"], "r1")


# ---------------------------------------------------------------------------
# 9. Boundary tests
# ---------------------------------------------------------------------------
class BoundaryTests(KernelCase):
    FORBIDDEN_IMPORTS = {
        "os", "sys", "subprocess", "socket", "threading", "asyncio", "time",
        "datetime", "random", "urllib", "http", "pathlib", "io", "shutil",
        "multiprocessing", "concurrent", "ctypes", "signal", "sqlite3",
    }

    def test_BT_1_no_storage_spawn_retrieval_calls(self):
        for name, source in kernel_sources():
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0],
                                         self.FORBIDDEN_IMPORTS,
                                         "%s imports %s" % (name, alias.name))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    module = (node.module or "").split(".")[0]
                    self.assertNotIn(module, self.FORBIDDEN_IMPORTS,
                                     "%s imports from %s" % (name, node.module))
                elif isinstance(node, ast.Call):
                    func = node.func
                    self.assertFalse(isinstance(func, ast.Name) and func.id == "open",
                                     "%s calls open()" % name)

    def test_BT_2_every_emitted_event_passes_envelope_schema(self):
        for event in copy.deepcopy(SCENARIO):
            self.coord.handle(event)
        self.send("verify.passed", "ghost")  # a fault emission too
        checked = 0
        for topic in OUT_TOPICS:
            for message in self.emitted(topic):
                for field in ("event_id", "event_name", "request_id",
                              "timestamp", "config_version", "payload"):
                    self.assertIn(field, message, "%s missing %s" % (topic, field))
                self.assertEqual(message["event_name"], topic)
                checked += 1
        self.assertGreater(checked, 8)

    def test_BT_3_no_silent_work(self):
        inputs = copy.deepcopy(SCENARIO) + [
            env("b1", "verify.passed", "ghost", {}),         # unknown id fault
            env("b2", "task.started", "d1", {}),             # poison
            env("b3", "session.wake", None, {}),
            env("b4", "session.sleep", None, {}),
        ]
        for event in inputs:
            log_before = len(self.coord.log)
            out_before = sum(len(self.emitted(t)) for t in OUT_TOPICS)
            self.coord.handle(event)
            log_after = len(self.coord.log)
            out_after = sum(len(self.emitted(t)) for t in OUT_TOPICS)
            self.assertGreater(log_after + out_after, log_before + out_before,
                               "silent work on %s" % str(event)[:60])

    def test_BT_4_zero_domain_terms_in_contract_strings(self):
        banned = re.compile(
            r"\b(git|repos?|repositor(y|ies)|python|llm|gpt|claude|openai|"
            r"branch(es)?|merge[sd]?|commit(s|ted)?|pull|push)\b", re.IGNORECASE)
        for name, source in kernel_sources():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    match = banned.search(node.value)
                    self.assertIsNone(
                        match, "%s line %s: domain term %r in %r" % (
                            name, node.lineno, match and match.group(0),
                            node.value[:70]))


if __name__ == "__main__":
    unittest.main()
