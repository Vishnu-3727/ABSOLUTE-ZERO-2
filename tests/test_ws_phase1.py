"""WS phase 1 — compiler + dispatcher (WS/01-02, ERRATA C15).

Compiler: determinism (WS-W5), coverage (WS-W2/W3), fidelity (WS-W4),
acyclicity (WS-W1), immutability (WS-W10), late binding (WS-W11).
Runtime: readiness semantics, canonical-order dispatch through the REAL
Execution engine, per-unit verified success, branch selection, failure
propagation (WS-E9), cancellation, journal + replay + restart over REAL
Storage, C15 events schema-validated on the REAL bus.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ws import (ACTIVE, COMPLETED, FAILED, NOT_EXECUTED, STALLED,  # noqa: E402
                SUCCEEDED, SchedulerRefusal, WorkflowRejected, WorkflowRun,
                compile_workflow)

PY = sys.executable


def graph(**overrides):
    base = {"plan_artifact_id": "plan-9", "plan_version": 2,
            "nodes": [
                {"node_id": "read", "capability_id": "cap.read",
                 "priority_band": "CRITICAL"},
                {"node_id": "build", "capability_id": "cap.build",
                 "priority_band": "REQUIRED"},
                {"node_id": "lint", "capability_id": "cap.lint",
                 "priority_band": "OPTIONAL"},
                {"node_id": "ship", "capability_id": "cap.ship",
                 "priority_band": "REQUIRED"},
            ],
            "requires_edges": [["read", "build"], ["read", "lint"],
                               ["build", "ship"], ["lint", "ship"]]}
    base.update(overrides)
    return base


def ok_binder(unit):
    return {"command": [PY, "-c", "print('%s')" % unit["capability_id"]],
            "timeout_seconds": 30}


class TestCompiler(unittest.TestCase):
    def test_deterministic_byte_stable(self):
        a = compile_workflow(graph(), 1)
        b = compile_workflow(json.loads(json.dumps(graph())), 1)
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.canonical_order, b.canonical_order)
        self.assertNotEqual(compile_workflow(graph(), 2).workflow_id, a.workflow_id)

    def test_coverage_and_fidelity(self):
        wf = compile_workflow(graph(), 1)
        self.assertEqual(len(wf.units), 4)   # WS-W2/W3: 1:1, none dropped/invented
        self.assertEqual(len(wf.edges), 4)   # WS-W4: verbatim
        self.assertEqual(len(wf.levels), 3)  # read | build+lint | ship
        self.assertEqual(len(wf.levels[1]), 2)

    def test_fail_closed_gates(self):
        with self.assertRaises(WorkflowRejected):  # WS-W1 cycle
            compile_workflow(graph(requires_edges=[["read", "build"],
                                                   ["build", "read"]]), 1)
        with self.assertRaises(WorkflowRejected):  # unknown edge endpoint
            compile_workflow(graph(requires_edges=[["read", "ghost"]]), 1)
        with self.assertRaises(WorkflowRejected):  # WS-W11 provider id
            bad = graph()
            bad["nodes"][0]["provider_id"] = "plugin.x"
            compile_workflow(bad, 1)
        with self.assertRaises(WorkflowRejected):  # bad band
            bad = graph()
            bad["nodes"][0]["priority_band"] = "URGENT"
            compile_workflow(bad, 1)

    def test_artifact_immutable_and_runtime_state_free(self):
        wf = compile_workflow(graph(), 1)
        first = wf.canonical_order[0]
        with self.assertRaises(TypeError):
            wf.units[first]["priority_band"] = "DEFERRED"
        for unit in wf.units.values():  # WS-W12
            for key in unit:
                self.assertNotIn(key, ("state", "attempts", "result"))


class TestRuntime(unittest.TestCase):
    def _drive_to_completion(self, run):
        while run.status == ACTIVE:
            step = run.dispatch_next()
            if step is None:
                break
            uid, result = step
            if result["state"] == "completed":
                run.on_verdict(uid, True)

    def test_canonical_order_dispatch_and_completion(self):
        from execution import Engine

        run = WorkflowRun(compile_workflow(graph(), 1),
                          binder=ok_binder, engine=Engine()).activate()
        dispatched = []
        while run.status == ACTIVE:
            step = run.dispatch_next()
            if step is None:
                break
            uid, result = step
            dispatched.append(run.workflow.units[uid]["node_id"])
            run.on_verdict(uid, True)
        self.assertEqual(run.status, COMPLETED)
        self.assertEqual(dispatched[0], "read")          # root first
        self.assertEqual(dispatched[-1], "ship")         # join last
        self.assertEqual(set(dispatched[1:3]), {"build", "lint"})

    def test_verified_success_required(self):
        from execution import Engine

        run = WorkflowRun(compile_workflow(graph(), 1),
                          binder=ok_binder, engine=Engine()).activate()
        uid, result = run.dispatch_next()
        self.assertEqual(result["state"], "completed")
        self.assertEqual(run.ready(), [])  # exec ok alone unblocks nothing (WS-E3)
        run.on_verdict(uid, False)         # verify.failed => FAILED
        self.assertEqual(run.unit_state[uid], FAILED)
        self.assertEqual(run.status, STALLED)  # CRITICAL failed (WS-E9, §10b)
        self.assertEqual(run.ready(), [])      # downstream permanently unready

    def test_optional_failure_does_not_block_completion(self):
        from execution import Engine

        def binder(unit):
            code = ("raise SystemExit(1)" if unit["capability_id"] == "cap.lint"
                    else "print('ok')")
            return {"command": [PY, "-c", code], "timeout_seconds": 30}

        wf = compile_workflow(graph(requires_edges=[["read", "build"],
                                                    ["read", "lint"]],
                                    nodes=graph()["nodes"][:3]), 1)
        run = WorkflowRun(wf, binder=binder, engine=Engine()).activate()
        self._drive_to_completion(run)
        lint = [uid for uid, u in wf.units.items() if u["node_id"] == "lint"][0]
        self.assertEqual(run.unit_state[lint], FAILED)
        self.assertEqual(run.status, COMPLETED)  # WS/02 §10b

    def test_branch_selection_default_and_not_executed(self):
        from execution import Engine

        nodes = [{"node_id": "a", "capability_id": "cap.a",
                  "priority_band": "REQUIRED", "group_id": "g", "rank": 2},
                 {"node_id": "b", "capability_id": "cap.b",
                  "priority_band": "REQUIRED", "group_id": "g", "rank": 1}]
        wf = compile_workflow(graph(nodes=nodes, requires_edges=[]), 1)
        run = WorkflowRun(wf, binder=ok_binder, engine=Engine()).activate()
        chosen = run.selected["g"]
        self.assertEqual(wf.units[chosen]["node_id"], "b")  # rank 1 = highest
        losers = [uid for uid in wf.groups["g"] if uid != chosen]
        self.assertEqual(run.unit_state[losers[0]], NOT_EXECUTED)  # WS-E4
        with self.assertRaises(SchedulerRefusal):  # C2: selection is once
            run.select_branch("g", losers[0])
        self._drive_to_completion(run)
        self.assertEqual(run.status, COMPLETED)

    def test_cancellation_and_fail_closed(self):
        run = WorkflowRun(compile_workflow(graph(), 1)).activate()
        with self.assertRaises(SchedulerRefusal):
            run.dispatch_next()  # no binder/engine: refuse, never guess
        run.cancel()
        self.assertEqual(run.ready(), [])
        with self.assertRaises(SchedulerRefusal):
            run.cancel()
        with self.assertRaises(SchedulerRefusal):
            run.activate()


class TestJournalReplayRestart(unittest.TestCase):
    def test_replay_reconstructs_and_restart_continues(self):
        from execution import Engine
        from storage import Store

        wf = compile_workflow(graph(), 1)
        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "vault")
            with Store(vault) as store:
                run = WorkflowRun(wf, storage=store.namespace("ws"),
                                  binder=ok_binder, engine=Engine()).activate()
                uid, _ = run.dispatch_next()   # run "read" only, then "crash"
                run.on_verdict(uid, True)
                live_states = dict(run.unit_state)
            with Store(vault) as store2:       # restart
                rebuilt = WorkflowRun.replay(wf, store2.namespace("ws"))
                self.assertEqual(rebuilt.unit_state, live_states)
                self.assertEqual(rebuilt.status, ACTIVE)
                self.assertEqual(rebuilt.ready(), run.ready())
                # resume with fresh collaborators, run to completion
                rebuilt.storage = store2.namespace("ws")
                rebuilt.binder = ok_binder
                rebuilt.engine = Engine()
                while rebuilt.status == ACTIVE:
                    step = rebuilt.dispatch_next()
                    if step is None:
                        break
                    uid, result = step
                    rebuilt.on_verdict(uid, result["state"] == "completed")
                self.assertEqual(rebuilt.status, COMPLETED)


class TestCommunicationIntegration(unittest.TestCase):
    def test_c15_events_flow_and_validate(self):
        from communication import Bus
        from execution import Engine

        bus = Bus()
        topics = ("workflow.created", "task.scheduled", "task.started",
                  "verify.requested", "task.completed", "task.failed")
        for topic in topics:
            bus.subscribe(topic, "probe")
        run = WorkflowRun(compile_workflow(graph(), 1), bus=bus,
                          binder=ok_binder, engine=Engine()).activate()
        while run.status == ACTIVE:
            step = run.dispatch_next()
            if step is None:
                break
            uid, result = step
            run.on_verdict(uid, True)
        self.assertEqual(len(bus.drain("workflow.created", "probe")), 1)
        self.assertEqual(len(bus.drain("task.scheduled", "probe")), 4)
        self.assertEqual(len(bus.drain("task.started", "probe")), 4)
        self.assertEqual(len(bus.drain("verify.requested", "probe")), 4)
        self.assertEqual(len(bus.drain("task.completed", "probe")), 4)
        self.assertEqual(bus.drain("task.failed", "probe"), [])

    def test_dead_draft_name_banned(self):
        from communication import Bus, SchemaViolation

        with self.assertRaises(SchemaViolation):  # ERRATA C15 §1
            Bus().publish("task.dispatched",
                          {"event_id": "e1", "event_name": "task.dispatched",
                           "request_id": None, "timestamp": 0, "payload": {}})


if __name__ == "__main__":
    unittest.main()
