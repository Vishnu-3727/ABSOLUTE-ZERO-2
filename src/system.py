"""ABSOLUTE-ZERO V2 — the OS composition root (C3 System Integration).

One place where the operating system is ASSEMBLED: substrate first
(Storage, Communication), then the Kernel, then every component that is
actually wired into the request pipeline. Until this module existed the
only composition living anywhere was the workbench gateway's — the UI
adapter was the de facto operating system, and nothing in src/ ever
imported the components it shipped. Tests composed each component against
its own doubles; the whole was never built.

Charter (mirrors each component's own runtime.py):
  * Pure composition — no new rules. Every law lives in the component
    that owns it; this module only sequences the calls the ARCHITECTURE
    request-lifecycle diagram already fixes.
  * Injected ports only — Storage namespaces and the Bus are handed to
    components through the same doors their phase tests use.
  * Labeled stand-ins — where a seam's real provider is an unbuilt phase
    (CP discovery 2-4, PRT binding), the stand-in is named in the record's
    `provenance` and the consumer must surface it, never hide it.
    Improvising an unbuilt phase is refused, not faked (repo law).
"""
import sys

from communication import Bus
from communication.schema import default_registry
from cp import build_artifact, build_spec
from cp import events as cp_events
from execution import Engine
from kernel import envelope
from kernel.coordinator import Coordinator
from kernel.default_config import snapshot
from storage import Store
from ws import ACTIVE, WorkflowRun, compile_workflow

PY = sys.executable

# PRT-binding stand-in (labeled): deterministic no-op commands per
# capability until PRT binding is wired. Kept here, not in the gateway —
# the seam belongs to the OS, the label travels with it.
CAPABILITY_COMMANDS = {
    "cap.analyze": "print('analysis complete')",
    "cap.plan": "print('plan derived')",
    "cap.build": "print('build ok')",
    "cap.test": "print('tests green')",
    "cap.report": "print('report written')",
}


def default_binder(unit):
    code = CAPABILITY_COMMANDS.get(unit["capability_id"], "print('noop')")
    return {"command": [PY, "-c", code], "timeout_seconds": 30}


class System:
    """One booted operating system. Single-threaded by kernel law; callers
    that need concurrency serialize outside (the gateway holds one lock)."""

    def __init__(self, vault_dir, binder=None):
        self.store = Store(vault_dir)
        self.bus = Bus(storage=self.store.namespace("communication"))
        self.topics = sorted(default_registry())
        self.kernel = Coordinator(self.bus, snapshot())
        self.engine = Engine(storage=self.store.namespace("execution"),
                             bus=self.bus)
        self.binder = binder or default_binder
        self.requests = {}  # rid -> record of real object refs

    # -- helpers -------------------------------------------------------------

    def _env(self, eid, name, rid, payload):
        return envelope.make(eid, name, rid, 0, None, payload)

    def subscribe_observer(self, consumer):
        """Register a durable consumer on every known topic (the door the
        workbench and any future Observability use — no internal reach)."""
        for topic in self.topics:
            self.bus.subscribe(topic, consumer, durable=True)

    # -- the pipeline (ARCHITECTURE 'Request lifecycle', wired parts) --------

    def submit(self, intent, goals):
        rid = "REQ-%04d" % (len(self.requests) + 1)
        record = {"request_id": rid, "intent": intent, "goals": list(goals),
                  "provenance": {
                      "discovery": "fixture — CP phases 2-4 pending",
                      "verification": "auto-pass — VAE not wired",
                      "binding": "stand-in commands — PRT binding pending"}}
        self.requests[rid] = record

        # 1. Kernel admission + routing (real ledger, real gates)
        self.kernel.handle(self._env(rid + ":e1", "request.received", rid,
                                     {"declared_type": "type.alpha"}))

        # 2. CP Phase-1 plan artifact; discovery is the labeled fixture:
        #    one node per goal, chained.
        goals = [g for g in goals if g.strip()] or ["analyze"]
        nodes, edges, prev = {}, [], None
        for index, goal in enumerate(goals):
            nid = "n%d-%s" % (index, goal[:12])
            cap = "cap." + goal.split()[0].lower()
            nodes[nid] = {"capability_id": cap if cap in CAPABILITY_COMMANDS
                          else "cap.analyze",
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
                          bus=self.bus, binder=self.binder,
                          engine=self.engine)
        record["workflow"] = workflow
        record["run"] = run
        run.activate()
        while run.status == ACTIVE:
            step = run.dispatch_next()
            if step is None:
                break
            uid, result = step
            self._verdict(rid, uid, result, run)

        # 4. Kernel completion through its real gates
        self.kernel.handle(self._env(rid + ":e3", "verify.passed", rid, {}))
        self.kernel.handle(self._env(rid + ":e4", "task.completed", rid, {}))
        return record

    # -- seams later phases replace ------------------------------------------

    def _verdict(self, rid, uid, result, run):
        """Verification seam. Auto-pass, LABELED — replaced when VAE wires
        in. Published as the canonical event so the kernel gate is really
        enforced even while the verdict itself is a stand-in."""
        if result["state"] != "completed":
            return
        self.bus.publish("verify.passed", self._env(
            "%s:v:%s" % (rid, uid), "verify.passed", rid,
            {"unit_id": uid, "provenance": "auto-pass (VAE pending)"}))
        run.on_verdict(uid, True)

    def close(self):
        self.store.close()
