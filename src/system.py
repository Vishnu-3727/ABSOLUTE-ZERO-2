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
from sgpe import compiler as sgpe_compiler
from sgpe import condition as sgpe_condition
from sgpe import document as sgpe_document
from sgpe import rule as sgpe_rule
from sgpe import vocabulary as sgpe_vocabulary
from sgpe.evaluator import build_question
from sgpe.ledger import GrantLedger
from sgpe.runtime import GovernanceRuntime
from sgpe.store import PolicyStore
from storage import Store
from vae.derivation import build_derivation_policy
from vae.rules import RulesStore
from vae.runtime import Verification
from vae.static_checks import StaticCheckRegistry
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


# -- SGPE bootstrap canon (SGPE/05 §3): vocabulary v1 + system defaults →
#    first compile → first activation. The constitution below is the
#    system-default deny-by-default document the canon requires — policy
#    CONTENT authored here at the composition root, no policy LOGIC.

SGPE_OPERATIONS = (
    "execution.run", "token-budget.run",
    "persistence.store", "resource-limit.store",
    "plugin.bind",
    "model.invoke", "token-budget.invoke",
    "resource-limit.dispatch", "retry-limit.dispatch",
    "context-limit.assemble",
    "resource-limit.verify", "approval.waive",
)


def _sgpe_rule(rule_id, domain, operation, selector, effect, value=None,
               condition=None, final=False):
    return sgpe_rule.build_rule(
        rule_id, sgpe_rule.build_target(domain, operation, selector),
        sgpe_rule.build_effect(effect, value),
        condition=condition, final=final)


def default_constitution():
    """System-default constitution: execution and persistence allowed
    under budget ceilings, plugin binding needs approval, waivers denied
    outright. Every declared operation answered (totality)."""
    over_budget = sgpe_condition.build_comparison("usage.tokens", "gte", 1000)
    return (
        _sgpe_rule("r-exec", "execution", "run", "*", "ALLOW"),
        _sgpe_rule("r-exec-budget", "token-budget", "run", "*", "LIMIT", 5000),
        _sgpe_rule("r-persist", "persistence", "store", "*", "ALLOW"),
        _sgpe_rule("r-retention", "resource-limit", "store", "*", "LIMIT", 30),
        _sgpe_rule("r-plugin", "plugin", "bind", "*", "REQUIRE_APPROVAL"),
        _sgpe_rule("r-model", "model", "invoke", "*", "ALLOW"),
        _sgpe_rule("r-model-cap", "model", "invoke", "*", "DENY",
                   condition=over_budget),
        _sgpe_rule("r-model-budget", "token-budget", "invoke", "*", "LIMIT", 1000),
        _sgpe_rule("r-concurrency", "resource-limit", "dispatch", "*", "LIMIT", 4),
        _sgpe_rule("r-retries", "retry-limit", "dispatch", "*", "LIMIT", 3),
        _sgpe_rule("r-context", "context-limit", "assemble", "*", "LIMIT", 8000),
        _sgpe_rule("r-verify-budget", "resource-limit", "verify", "*", "LIMIT", 2),
        _sgpe_rule("r-no-waiver", "approval", "waive", "*", "DENY", final=True),
    )


# -- VAE wiring: the OS verifies workflow units for real -------------------

class VerdictBusAdapter:
    """Lifts VAE's reference-shaped envelope (event_name, event_id,
    subject_ref, payload — VAE/05 §2) into the kernel wire shape the
    `verify.*` topics carry (the matrix's consumer is the Kernel, so the
    wire speaks kernel envelope). The request_id is recovered from the
    artifact_ref the System itself minted ("unit:<rid>:<uid>") — this
    adapter belongs to the composition root precisely because only the
    composer knows that naming. No frozen VAE code is touched."""

    def __init__(self, bus):
        self._bus = bus

    def publish(self, topic, message):
        payload = dict(message.get("payload", {}))
        subject = message.get("subject_ref", "")
        payload["subject_ref"] = subject
        parts = subject.split(":")
        rid = parts[1] if len(parts) >= 3 and parts[0] == "unit" else subject
        self._bus.publish(topic, envelope.make(
            message["event_id"], message["event_name"], rid, 0, None,
            payload))


def _exec_completed_check(artifact_ref, metadata):
    """Static check: the execution result this unit produced really is a
    completed one. Reference-shaped: it inspects the result STATE the
    engine reported, never artifact content."""
    return {"outcome": "pass" if metadata.get("state") == "completed"
            else "fail", "detail": {"state": metadata.get("state")}}


def boot_verification(storage, bus):
    """VAE over the real substrate. Static checks only: the delegated-
    check path needs the Execution delegation adapter (unbuilt phase) —
    refused, not improvised; the demand below declares no delegated
    checks, so judgments close on static evidence alone."""
    registry = StaticCheckRegistry()
    registry.register("exec_completed", _exec_completed_check)
    rules = RulesStore()
    rules.ingest(1, {
        "workflow_unit": {
            "required_checks": ("exec_completed", "reference_wellformed"),
            "depth": "standard",
            "deadlines": {"exec_completed": 10, "reference_wellformed": 10},
        },
    })
    policy = build_derivation_policy(
        1, coverage_moderate_min_fraction=0.5,
        coverage_strong_min_fraction=0.9)
    return Verification(policy=policy, rules_store=rules,
                        bus=VerdictBusAdapter(bus), storage=storage,
                        static_registry=registry)


def boot_governance(storage, bus):
    """Build SGPE over real Storage. First boot runs the bootstrap canon;
    a rebooted vault already carries its authored world and is NOT
    re-authored (the catalog is append-only law, not a config file)."""
    store = PolicyStore(storage, bus=bus)
    if store.catalog_position() == 0:
        v1 = sgpe_vocabulary.default_v1()
        store.append_vocabulary(v1)
        store.append_vocabulary(sgpe_vocabulary.evolve(
            v1, operations=SGPE_OPERATIONS, fact_names=("usage.tokens",)))
        provenance = sgpe_document.build_provenance(
            "system", "epoch-0", "constitution")
        header = sgpe_document.build_header(
            "system", "constitution", ("execution",), provenance, 2, 1)
        store.append_document(
            sgpe_document.build_document(header, default_constitution()))
        result = sgpe_compiler.compile_snapshot(
            store, store.catalog_position(), bus=bus)
        if result.outcome != "compiled":
            raise RuntimeError("sgpe bootstrap failed: %r"
                               % (result.report.errors,))
        sgpe_compiler.activate(store, result, bus=bus)
    ledger = GrantLedger(storage, bus=bus)
    return GovernanceRuntime(store, ledger, bus=bus)


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
        self.governance = boot_governance(self.store.namespace("sgpe"),
                                          self.bus)
        self.verification = boot_verification(self.store.namespace("vae"),
                                              self.bus)
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

    def submit(self, intent, goals, principal="workbench", project="default"):
        rid = "REQ-%04d" % (len(self.requests) + 1)
        record = {"request_id": rid, "intent": intent, "goals": list(goals),
                  "provenance": {
                      "discovery": "fixture — CP phases 2-4 pending",
                      "verification": "VAE static checks — delegation "
                                      "adapter pending",
                      "binding": "stand-in commands — PRT binding pending"}}
        self.requests[rid] = record

        # 0. Governance admission (SGPE/04 §2.2): bind the frozen Effective
        #    Policy, then ask the one question that gates the pipeline —
        #    may this principal run work at all? DENY refuses the request
        #    before the kernel ever sees it; the decision is recorded
        #    either way (stamped, replayable forever).
        view = self.governance.admit(rid, principal, project)
        record["governance"] = {"ep_stamp": view.stamp()}
        decision = view.consult(build_question(
            "kernel", rid, principal, "execution", "run", "workflow", {}))
        record["governance"]["admission"] = {
            "effect": getattr(decision, "effect_kind", "ILL_POSED"),
            "question_hash": getattr(decision, "question_hash", None)}
        if getattr(decision, "effect_kind", "DENY") != "ALLOW":
            record["refused"] = "governance: %s" % \
                record["governance"]["admission"]["effect"]
            return record

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

        # 4. Kernel completion through its real gates — task.completed only
        #    claims what the verdicts above already established; a failed
        #    unit routes to task.failed and the kernel decides replan/fail.
        all_ok = (run.status == "completed"
                  and all(state == "succeeded"
                          for state in run.unit_state.values()))
        self.kernel.handle(self._env(
            rid + ":e4", "task.completed" if all_ok else "task.failed",
            rid, {}))
        return record

    # -- seams later phases replace ------------------------------------------

    def _verdict(self, rid, uid, result, run):
        """Verification for one dispatched unit — VAE for real (VAE/04 §5:
        demand -> judge -> persist -> publish). The demand declares static
        checks only; the delegated path awaits the Execution delegation
        adapter (unbuilt phase, refused not improvised). The verdict event
        VAE publishes is the one the workflow gate consumes — nothing here
        invents a pass."""
        if result["state"] != "completed":
            # WS law: a failed execution is already terminal (on_exec_result
            # marked it FAILED); there is no result for VAE to judge and
            # on_verdict would refuse (ws.verdict_without_execution).
            return None
        artifact_ref = "unit:%s:%s" % (rid, uid)
        self.verification.handle_demand({
            "event_name": "verify.requested",
            "event_id": "%s:vr:%s" % (rid, uid),
            "artifact_ref": artifact_ref,
            "judgment_id": "j:" + artifact_ref,
            "artifact_type": "workflow_unit", "rules_version": 1,
            "delegated_check_levels": {},
            "static_check_levels": {"exec_completed": "system",
                                    "reference_wellformed": "system"},
        })
        self.verification.run_static(artifact_ref, "exec_completed",
                                     {"state": result["state"]})
        self.verification.run_static(artifact_ref, "reference_wellformed", {})
        emission = self.verification.try_close_and_emit(artifact_ref)
        if emission is None or emission.outcome != "emitted":
            raise RuntimeError("verification did not emit for " + artifact_ref)
        passed = emission.verdict == "passed"
        run.on_verdict(uid, passed)
        # the kernel records each real verdict (its completion gate demands
        # a recorded verify.passed — I5: never a default permit)
        self.kernel.handle(self._env(
            "%s:kv:%s" % (rid, uid),
            "verify.passed" if passed else "verify.failed", rid,
            {"unit_id": uid, "evidence_record_ref":
             emission.evidence_record_ref}))
        return emission.verdict

    def close(self):
        self.store.close()
