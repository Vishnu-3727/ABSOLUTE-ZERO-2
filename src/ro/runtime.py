"""ReasoningOrchestrator — RO/05 (this doc's whole point: the composition
root wiring RO/00-04's frozen machinery to its integration surface).
Mirrors prt/runtime.py's shape: every collaborator is either injected or
constructed explicitly in `__init__` (no hidden/ambient state), bus/storage
are injected PORTS, and this module adds NO governance logic of its own —
every rule already lives in Phases 1-4; this file only sequences calls and
derives/emits/persists around them (RO-S1: behavior not derivable from
RO/00-05 does not exist).

`mirror_to_rsm` is Fable R5's fold-in: rsm_mirror.py was scoped out because
RO/05 §3's ruling is that the four canonical `reasoning.*` events (§2) ARE
the RSM mirror transport — RSM sits downstream on the bus, consuming the
exact same publish every other consumer sees. There is no second write.
This method is the one clearly-named seam marking that fact (RO-S4:
telemetry-only, one-way, zero RSM import, zero query surface — it never
reads anything back, only publishes)."""
from . import events
from . import execution_replay
from . import experience_feed
from . import invocation
from . import persistence
from .bus_double import BusDouble
from .decision_gate import content_hash as decision_content_hash
from .decision_gate import decide
from .descriptor_space import DescriptorSpace
from .outcome import content_hash as outcome_content_hash
from .priors import PriorsStore
from .schemas import SchemaRegistry
from .storage_double import StorageDouble
from .verification_handoff import build_handoff


class RuntimeRefusal(Exception):
    """Base for orchestrator-level refusals."""


class ReplayMismatchError(RuntimeRefusal):
    """RO-S3/G4: a governance-side replay reproduced records or events that
    do not byte-match what was originally emitted/sealed. Always loud."""


class ReasoningOrchestrator:
    """One governance loop, injected collaborators, zero hidden state."""

    def __init__(self, *, descriptor_space=None, schema_registry=None, priors_store=None,
                 bus=None, storage=None, engine_boundary=None, policy_view=None,
                 execution_policy=None):
        self.descriptor_space = descriptor_space if descriptor_space is not None else DescriptorSpace()
        self.schema_registry = schema_registry if schema_registry is not None else SchemaRegistry()
        self.priors_store = priors_store if priors_store is not None else PriorsStore()
        self.bus = bus if bus is not None else BusDouble()
        self.storage = storage if storage is not None else StorageDouble()
        self.engine_boundary = engine_boundary
        self.policy_view = policy_view
        self.execution_policy = execution_policy
        self.context_signals = []  # RO/05 §2: context.assembled facts, stored, never fetched

    # -- mirror seam (RO/05 §3, Fable R5) ------------------------------

    def mirror_to_rsm(self, event_name, event_id, subject_id, payload):
        events.emit(self.bus, event_name, event_id, subject_id, payload)

    # -- event dispatch (RO/05 §2 CONSUME set, exhaustively) ------------

    def handle_event(self, event_name, payload):
        """Dispatch one CONSUMED event. Refuses non-canon events loudly via
        events.check_consumed (RO-S2) before touching the payload."""
        events.check_consumed(event_name)
        if event_name == "context.assembled":
            self.context_signals.append(dict(payload or {}))
        elif event_name == "prior.updated":
            self.priors_store.ingest(payload)
        return event_name

    # -- govern: decide + emit reasoning.decided + mirror + persist ----

    def govern(self, sealed_inputs):
        decision = decide(sealed_inputs)
        dhash = decision_content_hash(decision)
        subject_id = decision.approved_capability_id or ""
        self.mirror_to_rsm(
            "reasoning.decided", events.decided_event_id(decision, dhash), subject_id,
            events.decided_payload(decision, dhash))
        persistence.persist_decision_record(decision, self.storage)
        return decision

    # -- execute: run_attempts + derive/emit events + mirror + persist -

    def execute(self, decision_record, request, resolution, *, boundary=None,
                execution_policy=None, request_form="prompt_text",
                latency_constraint="standard", cancellation_signals=()):
        eb = boundary if boundary is not None else self.engine_boundary
        policy = execution_policy if execution_policy is not None else self.execution_policy

        records = invocation.run_attempts(
            request, resolution, eb, policy, request_form=request_form,
            latency_constraint=latency_constraint, cancellation_signals=cancellation_signals)

        for record in records:
            self._emit_derived(record)
            persistence.persist_sealed_outcome(record, self.storage)

        final = records[-1]
        handoff = build_handoff(final, request) if final.recovery_kind == "RETURNED" else None
        batch = experience_feed.build_experience_batch((decision_record,), records)
        return records, handoff, batch

    def _emit_derived(self, record):
        """R1: one `reasoning.invoked` per sealed attempt record (the
        crossing began), then exactly one terminal event — `reasoning.
        completed` for RETURNED, `reasoning.failed` for everything else
        (FAILED/EXPIRED/CANCELLED, including F6-initiation records and the
        extra terminal F3 exhaustion record — both are ordinary records,
        so both are ordinary reasoning.failed events)."""
        rhash = outcome_content_hash(record)
        self.mirror_to_rsm(
            "reasoning.invoked", events.invoked_event_id(rhash), record.provider_id,
            events.invoked_payload(record, rhash))
        if record.recovery_kind == "RETURNED":
            self.mirror_to_rsm(
                "reasoning.completed", events.sealed_event_id(rhash), record.provider_id,
                events.completed_payload(record, rhash))
        else:
            self.mirror_to_rsm(
                "reasoning.failed", events.sealed_event_id(rhash), record.provider_id,
                events.failed_payload(record, rhash))

    # -- replay: governance-side, zero live reads (RO-S3/G4) ------------

    def replay(self, decision_record_hash, outcome_record_hashes, originally_emitted,
               execution_policy=None):
        """Reload the decision record + every sealed outcome record from
        Storage by content hash ALONE (`self.storage`; never a live
        collaborator), re-verify the attempt sequence via
        execution_replay.replay_attempts, re-derive every event a fresh
        `govern`+`execute` pass would have emitted, and assert the result
        is byte-identical to `originally_emitted` — a dict keyed by topic
        name (`"reasoning.decided"`/`"reasoning.invoked"`/`"reasoning.
        completed"`/`"reasoning.failed"`) to that topic's captured message
        list, e.g. built straight from `BusDouble.messages(topic)` per
        topic. Grouping by topic (rather than one globally-interleaved
        list) matches RO/05 §2's own Ordering rule — "seal order within one
        request only," a promise made per event name, never across event
        names. Raises ReplayMismatchError loud on any divergence — this is
        the determinism-rate-100% gate (RO/05 §10 testing philosophy)."""
        policy = execution_policy if execution_policy is not None else self.execution_policy

        decision = persistence.load_decision_record(decision_record_hash, self.storage)
        records = tuple(
            persistence.load_sealed_outcome(h, self.storage) for h in outcome_record_hashes)
        if records:
            execution_replay.replay_attempts(records, policy)

        derived = {"reasoning.decided": [self._decided_message(decision)],
                   "reasoning.invoked": [], "reasoning.completed": [], "reasoning.failed": []}
        for record in records:
            invoked, terminal_topic, terminal = self._derived_messages(record)
            derived["reasoning.invoked"].append(invoked)
            derived[terminal_topic].append(terminal)

        expected = {topic: list(originally_emitted.get(topic, [])) for topic in derived}
        if derived != expected:
            raise ReplayMismatchError("runtime.replay_event_mismatch")

        return decision, records

    def _decided_message(self, decision):
        dhash = decision_content_hash(decision)
        subject_id = decision.approved_capability_id or ""
        return {
            "event_name": "reasoning.decided", "event_id": events.decided_event_id(decision, dhash),
            "subject_id": subject_id, "payload": events.decided_payload(decision, dhash),
        }

    def _derived_messages(self, record):
        rhash = outcome_content_hash(record)
        invoked = {
            "event_name": "reasoning.invoked", "event_id": events.invoked_event_id(rhash),
            "subject_id": record.provider_id, "payload": events.invoked_payload(record, rhash),
        }
        if record.recovery_kind == "RETURNED":
            terminal_topic, terminal = "reasoning.completed", {
                "event_name": "reasoning.completed", "event_id": events.sealed_event_id(rhash),
                "subject_id": record.provider_id, "payload": events.completed_payload(record, rhash),
            }
        else:
            terminal_topic, terminal = "reasoning.failed", {
                "event_name": "reasoning.failed", "event_id": events.sealed_event_id(rhash),
                "subject_id": record.provider_id, "payload": events.failed_payload(record, rhash),
            }
        return invoked, terminal_topic, terminal


if __name__ == "__main__":
    from types import MappingProxyType

    from .budget import allocate_budget
    from .decision_gate import DecisionRecord
    from .demand import build_demand, build_ladder_evidence, build_sealed_inputs
    from .engine_boundary import ScriptedEngineDouble
    from .execution_policy import build_execution_policy_view
    from .policy_view import build_policy_view
    from .records import build_capability, build_descriptor_row
    from .request import prepare

    _CHARS = {
        "inference_depth": "moderate", "context_sensitivity": "medium",
        "determinism_tolerance": "medium", "knowledge_dependency": "low",
        "creativity_requirement": "low", "reasoning_complexity": "C1",
        "verification_difficulty": "low", "expected_output_structure": "bounded",
    }
    cap = build_capability("ro.cap.summarize", "INTERPRETIVE", _CHARS, lifecycle="active")
    scope = {"description": "summarize the report", "granularity": "single_demand"}
    demand = build_demand(
        "ro.demand.1", "ro.cap.summarize", "C1", scope,
        underdetermined={"claim": True, "justification": "no recorded answer"},
        generalization_required={"claim": True, "justification": "synthesis needed"},
    )
    ladder = tuple(build_ladder_evidence(r, "exhausted", "tried and failed")
                    for r in ("D1", "D2", "D3", "D4", "D5"))
    policy = build_policy_view(True, ("INTERPRETIVE",), ("C0", "C1", "C2"), 1)
    sealed = build_sealed_inputs(
        demand, "rqm.hash.abc", ladder, "wf.ref.1", cap,
        priors_version=1, policy=policy, budget_available=True,
    )

    row = build_descriptor_row(
        "ro.provider.x", {"ro.cap.summarize": ("C1",)}, context_capacity_class="large",
        cost_class="low", latency_class="fast", determinism_class="low_variance",
        deployment_locality="local", privacy_domain="internal",
    )
    exec_policy = build_execution_policy_view(policy_version=1, attempt_ceiling=3,
                                               retryable_classes={"F1"})
    boundary = ScriptedEngineDouble([
        {"kind": "returned", "output": b'{"summary": "ok"}', "consumed": 100, "timing": {}},
    ])

    rt = ReasoningOrchestrator(engine_boundary=boundary, execution_policy=exec_policy)

    # unknown consumed event refused loud
    try:
        rt.handle_event("plan.created", {})
        raise SystemExit("unknown consumed event accepted")
    except ValueError:
        pass

    rt.handle_event("context.assembled", {"rqm_ref": "abc"})
    assert rt.context_signals == [{"rqm_ref": "abc"}]

    rt.handle_event("prior.updated", {
        "priors_version": 1, "provider_priors": {}, "routing_priors": {},
        "demand_shape_priors": {}, "policy_proposals": (),
    })
    assert rt.priors_store.current().priors_version == 1

    decision = rt.govern(sealed)
    assert decision.outcome == "REASONING_APPROVED"
    assert len(rt.bus.messages("reasoning.decided")) == 1

    registry = SchemaRegistry()
    registry.register("ro.schema.summary", 1, ("summary",))
    req, res = prepare(
        decision, rqm={"core": ({"id": "c1", "content": "alpha", "provenance": "doc:1"},), "supporting": ()},
        capability_record=cap, descriptor_rows=[row], descriptor_space_version=0,
        policy_view=policy, priors_version=1, schema_registry=registry,
        schema_id="ro.schema.summary", schema_version=1, budget_ceiling=10_000,
        budget_source_policy_version=1, verification_expectations={"must_cite": True},
    )

    records, handoff, batch = rt.execute(decision, req, res)
    assert len(records) == 1 and records[0].recovery_kind == "RETURNED"
    assert handoff is not None and handoff.output == {"summary": "ok"}
    assert len(batch.outcome_refs) == 1
    assert len(rt.bus.messages("reasoning.invoked")) == 1
    assert len(rt.bus.messages("reasoning.completed")) == 1

    # full replay from storage alone
    dhash = decision_content_hash(decision)
    outcome_hashes = [outcome_content_hash(r) for r in records]
    all_emitted = {
        "reasoning.decided": rt.bus.messages("reasoning.decided"),
        "reasoning.invoked": rt.bus.messages("reasoning.invoked"),
        "reasoning.completed": rt.bus.messages("reasoning.completed"),
        "reasoning.failed": rt.bus.messages("reasoning.failed"),
    }
    replayed_decision, replayed_records = rt.replay(dhash, outcome_hashes, all_emitted, exec_policy)
    assert replayed_decision.outcome == decision.outcome
    assert [outcome_content_hash(r) for r in replayed_records] == outcome_hashes

    # tampered originally_emitted -> replay refuses loud
    tampered = {k: list(v) for k, v in all_emitted.items()}
    tampered["reasoning.decided"] = [dict(tampered["reasoning.decided"][0])]
    tampered["reasoning.decided"][0]["payload"] = dict(
        tampered["reasoning.decided"][0]["payload"], outcome="TAMPERED")
    try:
        rt.replay(dhash, outcome_hashes, tampered, exec_policy)
        raise SystemExit("tampered replay comparison accepted")
    except ReplayMismatchError:
        pass

    print("runtime selftest ok")
