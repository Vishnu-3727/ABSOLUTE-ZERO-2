"""Workbench OS session — the gateway's handle on the REAL operating
system, and the ONLY layer the UI gateway talks to.

The OS itself is composed in src/system.py (C3); this module adds only
gateway concerns: one lock (the gateway serializes commands, matching the
kernel's single-loop law), wall-clock observation times, the event ring
buffer, and UI-shaped read surfaces. Faithfulness rules (Workbench
charter):
  * Every value served to the UI originates from a real OS object.
  * Stand-ins are LABELED in the data (`provenance` fields) — the UI must
    render the label, never hide it.
  * The gateway subscribes to the bus as an ordinary durable consumer
    ("workbench") — the same door every component uses.
"""
import os
import sys
import threading
import time

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
sys.path.insert(0, SRC)

from system import System  # noqa: E402


class OsSession:
    """One booted OS instance behind the gateway."""

    def __init__(self, vault_dir):
        self._lock = threading.Lock()
        self.started_at = time.time()  # gateway wall-clock; the OS stays clockless
        self.system = System(vault_dir)
        self.system.subscribe_observer("workbench")
        self.events = []      # ring buffer of drained bus events
        self._listeners = []  # callables fed each new event batch
        self._seq = 0

    # -- compatibility properties (UI + main.py read these) ------------------

    @property
    def store(self):
        return self.system.store

    @property
    def bus(self):
        return self.system.bus

    @property
    def kernel(self):
        return self.system.kernel

    @property
    def engine(self):
        return self.system.engine

    @property
    def topics(self):
        return self.system.topics

    @property
    def requests(self):
        return self.system.requests

    # -- event plumbing -------------------------------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _pump(self):
        batch = []
        observed_at = time.time()  # arrival time — an observation, not OS state
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

    # -- commands ---------------------------------------------------------------

    def submit_request(self, intent, goals):
        with self._lock:
            record = self.system.submit(intent, goals)
            record["events"] = self._pump()
            return self.describe_request(record["request_id"])

    # -- read surfaces (everything derived from real objects) --------------------

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
        completed = sum(1 for r in described
                        if r and r["kernel_state"] == "completed")
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
        self.system.close()


# Store.keys raises on missing dirs; tiny probe helper kept here so the
# session never guesses at Storage internals.
def _exists_ns(store, namespace):
    try:
        return bool(store.keys(namespace))
    except Exception:
        return False


from storage import Store  # noqa: E402
Store.exists_ns = lambda self, namespace: _exists_ns(self, namespace)
