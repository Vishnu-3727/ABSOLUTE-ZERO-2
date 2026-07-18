"""Workbench OS session — boots the REAL operating system in-process and
is the ONLY layer the UI gateway talks to.

Faithfulness rules (Workbench charter):
  * Every value served to the UI originates from a real OS object: the
    Kernel ledger, the Communication bus, the Storage vault, CP artifacts,
    WS workflows, Execution results. Nothing is invented here.
  * Where a component is not yet wired into the pipeline (CP discovery
    phases 2-4, VAE, PRT binding), the stand-in is LABELED in the data
    (`"provenance"` fields) — the UI must render that label, never hide it.
  * The gateway subscribes to the bus as an ordinary durable consumer
    ("workbench") and reads Storage through namespace handles — the same
    doors every component uses. No internal state is reached around them.
"""
import os
import sys
import threading
import time

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
sys.path.insert(0, SRC)

from communication import Bus  # noqa: E402
from communication.schema import default_registry  # noqa: E402
from cp import build_artifact, build_spec  # noqa: E402
from cp import events as cp_events  # noqa: E402
from execution import Engine  # noqa: E402
from kernel import envelope  # noqa: E402
from kernel.coordinator import Coordinator  # noqa: E402
from kernel.default_config import snapshot  # noqa: E402
from storage import Store  # noqa: E402
from ws import ACTIVE, WorkflowRun, compile_workflow  # noqa: E402

PY = sys.executable

# Demo capability handlers — the PRT-binding seam's stand-in, labeled.
_CAPABILITY_COMMANDS = {
    "cap.analyze": "print('analysis complete')",
    "cap.plan": "print('plan derived')",
    "cap.build": "print('build ok')",
    "cap.test": "print('tests green')",
    "cap.report": "print('report written')",
}


def _binder(unit):
    code = _CAPABILITY_COMMANDS.get(unit["capability_id"], "print('noop')")
    return {"command": [PY, "-c", code], "timeout_seconds": 30}


class OsSession:
    """One booted OS instance behind the gateway. Single-threaded OS,
    guarded by one lock — the gateway serializes commands, matching the
    kernel's own single-loop law."""

    def __init__(self, vault_dir):
        self._lock = threading.Lock()
        self.started_at = time.time()  # gateway wall-clock; the OS itself stays clockless
        self.store = Store(vault_dir)
        self.bus = Bus(storage=self.store.namespace("communication"))
        # the workbench is a plain durable consumer on every known topic
        self.topics = sorted(default_registry())
        for topic in self.topics:
            self.bus.subscribe(topic, "workbench", durable=True)
        self.kernel = Coordinator(self.bus, snapshot())
        self.engine = Engine(storage=self.store.namespace("execution"),
                             bus=self.bus)
        self.requests = {}   # rid -> request record (real object refs)
        self.events = []     # ring buffer of drained bus events
        self._listeners = []  # callables fed each new event batch
        self._seq = 0

    # -- event plumbing ----------------------------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _pump(self):
        batch = []
        observed_at = time.time()  # gateway arrival time — an observation, not OS state
        for topic in self.topics:
            for message in self.bus.drain(topic, "workbench"):
                self._seq += 1
                batch.append({"seq": self._seq, "topic": topic,
                              "observed_at": observed_at, "message": message})
        self.events.extend(batch)
        del self.events[:-5000]  # ring buffer
        for listener in list(self._listeners):
            listener(batch)
        return batch

    def _env(self, eid, name, rid, payload):
        return envelope.make(eid, name, rid, 0, None, payload)

    # -- the one command: run a request through the real pipeline -----------

    def submit_request(self, intent, goals):
        with self._lock:
            rid = "REQ-%04d" % (len(self.requests) + 1)
            record = {"request_id": rid, "intent": intent, "goals": goals,
                      "provenance": {
                          "discovery": "gateway fixture — CP phases 2-4 pending",
                          "verification": "auto-pass — VAE not wired (C3 pending)",
                          "binding": "gateway demo commands — PRT binding pending"}}
            self.requests[rid] = record

            # 1. Kernel admission + routing (real ledger, real gates)
            self.kernel.handle(self._env(rid + ":e1", "request.received", rid,
                                         {"declared_type": "type.alpha"}))

            # 2. CP Phase-1 artifact (real cp.build_artifact; discovery is
            #    the labeled fixture: one node per goal, chained)
            goals = [g for g in goals if g.strip()] or ["analyze"]
            nodes, edges, prev = {}, [], None
            for index, goal in enumerate(goals):
                nid = "n%d-%s" % (index, goal[:12])
                cap = "cap." + (goal.split()[0].lower())
                nodes[nid] = {"capability_id": cap
                              if cap in _CAPABILITY_COMMANDS else "cap.analyze",
                              "origin": "explicit",
                              "priority_band": "REQUIRED" if index else "CRITICAL",
                              "confidence": 0.9}
                if prev is not None:
                    edges.append(("requires", prev, nid))
                prev = nid
            spec = build_spec(rid, intent, goals, [], "rm-none", {}, {},
                              registry_version=1, priors_version=0,
                              config_version=1)
            plan = build_artifact(spec.determinism_tuple(), nodes, edges,
                                  confidence=0.9)
            record["plan"] = plan
            cp_events.emit(self.bus, "plan.created", rid + ":plan",
                           {"request_id": rid, "plan_id": plan.plan_id,
                            "hash": plan.content_hash,
                            "confidence": plan.confidence, "gap_count": 0,
                            "predecessor": None})
            self.kernel.handle(self._env(rid + ":e2", "plan.created", rid, {}))

            # 3. WS compile + dispatch through the real Execution engine
            workflow = compile_workflow(plan.to_sealed_graph(), 1)
            run = WorkflowRun(workflow, storage=self.store.namespace("ws"),
                              bus=self.bus, binder=_binder, engine=self.engine)
            record["workflow"] = workflow
            record["run"] = run
            run.activate()
            while run.status == ACTIVE:
                step = run.dispatch_next()
                if step is None:
                    break
                uid, result = step
                if result["state"] == "completed":
                    # labeled auto-verdict (VAE unwired); published as the
                    # canonical event so the kernel gate is really enforced
                    self.bus.publish("verify.passed", self._env(
                        "%s:v:%s" % (rid, uid), "verify.passed", rid,
                        {"unit_id": uid, "provenance": "auto-pass (VAE pending)"}))
                    run.on_verdict(uid, True)

            # 4. Kernel completion through its real gates
            self.kernel.handle(self._env(rid + ":e3", "verify.passed", rid, {}))
            self.kernel.handle(self._env(rid + ":e4", "task.completed", rid, {}))
            record["events"] = self._pump()
            return self.describe_request(rid)

    # -- read surfaces (everything derived from real objects) ---------------

    def describe_request(self, rid):
        record = self.requests.get(rid)
        if record is None:
            return None
        entry = self.kernel.ledger.get(rid)
        run = record.get("run")
        plan = record.get("plan")
        workflow = record.get("workflow")
        return {
            "request_id": rid, "intent": record["intent"],
            "goals": record["goals"], "provenance": record["provenance"],
            "kernel_state": entry.lifecycle_state if entry else "evicted",
            "plan": None if plan is None else {
                "plan_id": plan.plan_id, "version": plan.plan_version,
                "confidence": plan.confidence, "hash": plan.content_hash,
                "determinism": dict(plan.determinism),
                "nodes": {nid: dict(n) for nid, n in plan.nodes.items()},
                "edges": [list(e) for e in plan.edges]},
            "workflow": None if workflow is None else {
                "workflow_id": workflow.workflow_id,
                "hash": workflow.content_hash,
                "canonical_order": list(workflow.canonical_order),
                "levels": [list(level) for level in workflow.levels],
                "units": {uid: dict(u) for uid, u in workflow.units.items()},
                "edges": [list(e) for e in workflow.edges]},
            "run": None if run is None else {
                "status": run.status,
                "unit_state": dict(run.unit_state)},
        }

    def system_overview(self):
        described = [self.describe_request(rid) for rid in self.requests]
        completed = sum(1 for r in described if r and r["kernel_state"] == "completed")
        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "success_rate": (completed / len(described)) if described else None,
            "components": {
                "kernel": {"active_requests": self.kernel.ledger.active_count(),
                           "halted": self.kernel.halted,
                           "log_records": len(self.kernel.log)},
                "communication": {"topics": len(self.topics),
                                  "dead_letters": len(self.bus.dead_letters)},
                "storage": {"vault": self.store.dir},
                "execution": {"executions": len(self.engine._handles)},
            },
            "requests": described,
            "event_count": self._seq,
            "unwired": ["VAE (verification auto-pass)", "PRT binding",
                        "CP discovery phases 2-4", "LIE", "SGPE", "RSM live",
                        "UMS/CM context"],
        }

    def storage_namespaces(self):
        out = {}
        for namespace in ("communication", "execution", "ws"):
            keys = self.store.keys(namespace) if self.store.exists_ns(namespace) \
                else []
            out[namespace] = keys
        return out

    def replay_topic(self, topic):
        return self.bus.replay(topic)

    def close(self):
        self.store.close()


# Store.keys raises on missing dirs; tiny probe helper kept here so the
# session never guesses at Storage internals.
def _exists_ns(store, namespace):
    try:
        return bool(store.keys(namespace))
    except Exception:
        return False


Store.exists_ns = lambda self, namespace: _exists_ns(self, namespace)
