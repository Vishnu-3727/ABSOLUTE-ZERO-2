"""Reducer registry: one pure reducer per contributing event family
(RSM/02-architectural-blueprint.md §4 ownership matrix; RSM/03-internal-
design.md §4 reducer discipline). Contract: `(record, event) -> record'`.
Pure — no I/O, no clock, no randomness, no cross-record access; a reducer
touches only the one `record` and one `event` it was handed and returns a
new snapshot via `record.evolve()` (never mutates in place, RSM-I9).

Schema layer (ADR-RSM-4, RSM-I16): a reducer may read only fields its
family's Communication-owned schema publishes for the event's declared
`schema_version`. Real Communication schemas don't exist yet (M2 predates
Communication), so `SCHEMAS` below is an explicit versioned fixture per
ADR-RSM-4's "reducers bind to explicit, versioned schema fixtures from day
one" — not a guess at a publisher's internals. A `schema_version` RSM
doesn't recognize for that family, or a payload missing a required field,
is `ReducerFault` — caught by `ingest`, never a silent absorption.

request.received (birth) has no prior record to fold into, so it is not a
`(record, event) -> record'` reducer like the rest of the registry — it is
`birth_reducer(event) -> identity_fields`, kept out of REGISTRY and
special-cased by `ingest`'s CREATE-row branch, exactly as `transitions.py`
already special-cases ABSENT+birth as its own row action.
"""

BIRTH_FAMILY = "request.received"

SCHEMA_MISMATCH = "reducer.schema_mismatch"
MALFORMED = "reducer.malformed"


class ReducerFault(Exception):
    """A reducer's schema check failed (RSM/03 §4 step 5: 'schema invalid
    -> fault.recorded'). `ingest` catches this — it is the fault path, not
    an unexpected error. Never journaled (RSM/03 §3)."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


# -- schema fixtures (ponytail: explicit per-family fixture, ADR-RSM-4 —
# upgrade path is swapping this dict for Communication's real registry once
# Communication exists; reducer bodies below don't change, only this table
# does) -----------------------------------------------------------------
SCHEMAS = {
    BIRTH_FAMILY: {1: ("declared_type", "origin")},
    "intent.classified": {1: ("classification_ref",)},
    "plan.created": {1: ("plan_id", "revision")},
    "plan.revised": {1: ("plan_id", "revision")},
    "plan.validated": {1: ("verdict_ref",)},
    "plan.rejected": {1: ("verdict_ref", "reason")},
    "task.scheduled": {1: ("task_id", "budget_granted")},
    "task.started": {1: ("task_id",)},
    "task.preempted": {1: ("task_id",)},
    "task.completed": {1: ("task_id",)},
    "task.failed": {1: ("task_id", "reason")},
    "exec.started": {1: ("exec_id", "task_id")},
    "exec.completed": {1: ("exec_id", "outcome_ref")},
    "exec.timeout": {1: ("exec_id",)},
    "exec.failed": {1: ("exec_id", "reason")},
    "context.assembled": {1: ("step", "context_package_id")},
    "verify.requested": {1: ("gate",)},
    "verify.passed": {1: ("gate", "verdict_ref")},
    "verify.failed": {1: ("gate", "verdict_ref")},
    "storage.committed": {1: ("commit_ref",)},
    "storage.rejected": {1: ("reason",)},
    "cost.recorded": {1: ("amount",)},
    "fault.recorded": {1: ("reason",)},
    "request.completed": {1: ()},
    "request.failed": {1: ("reason",)},
    "request.rejected": {1: ("reason",)},
    "request.cancelled": {1: ()},
}


def _validate(family, event):
    """Schema-bind + required-field check (ADR-RSM-4). Returns payload dict
    on success, raises ReducerFault otherwise. The one place every reducer
    below routes its schema discipline through."""
    version = event.get("schema_version")
    schema = SCHEMAS.get(family, {}).get(version)
    if schema is None:
        raise ReducerFault(SCHEMA_MISMATCH + ":" + family + ":" + str(version))
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ReducerFault(MALFORMED + ":" + family + ":no_payload")
    missing = [f for f in schema if f not in payload]
    if missing:
        raise ReducerFault(MALFORMED + ":" + family + ":" + ",".join(missing))
    return payload


def _failure_entry(family, event, ref, record):
    return {
        "source_event_id": event.get("event_id"),
        "family": family,
        "ref": ref,
        "seq": len(record.failure),
    }


def _task_state(work, task_id, state):
    work = dict(work)
    tasks = dict(work.get("tasks", {}))
    entry = dict(tasks.get(task_id, {}))
    entry["state"] = state
    tasks[task_id] = entry
    work["tasks"] = tasks
    return work


def _exec_state(work, exec_id, **fields):
    work = dict(work)
    execs = dict(work.get("execs", {}))
    entry = dict(execs.get(exec_id, {}))
    entry.update(fields)
    execs[exec_id] = entry
    work["execs"] = execs
    return work


# -- birth (special-cased by ingest, not in REGISTRY) ------------------------
def birth_reducer(event):
    """request.received: no prior record — produces Identity-block fields
    for `store.create` (RSM-I10 sole creation trigger)."""
    payload = _validate(BIRTH_FAMILY, event)
    return {"declared_type": payload["declared_type"], "origin": payload["origin"]}


# -- Plan block (Capability Planning; Verification) --------------------------
def reduce_intent_classified(record, event):
    payload = _validate("intent.classified", event)
    plan = dict(record.plan)
    plan["classification_ref"] = payload["classification_ref"]
    return record.evolve(plan=plan)


def reduce_plan_created(record, event):
    payload = _validate("plan.created", event)
    plan = dict(record.plan)
    plan["plan_id"] = payload["plan_id"]
    plan["revision"] = payload["revision"]
    return record.evolve(plan=plan)


def reduce_plan_revised(record, event):
    payload = _validate("plan.revised", event)
    plan = dict(record.plan)
    plan["plan_id"] = payload["plan_id"]
    plan["revision"] = payload["revision"]
    return record.evolve(plan=plan)


def reduce_plan_validated(record, event):
    payload = _validate("plan.validated", event)
    plan = dict(record.plan)
    plan["status"] = "validated"
    plan["verdict_ref"] = payload["verdict_ref"]
    return record.evolve(plan=plan)


def reduce_plan_rejected(record, event):
    # dual block: Plan (status) + Failure (RSM/03 §6 lists plan.rejected as
    # a Failure-feeding family alongside its Plan-block role, Phase2 §4).
    payload = _validate("plan.rejected", event)
    plan = dict(record.plan)
    plan["status"] = "rejected"
    plan["verdict_ref"] = payload["verdict_ref"]
    entry = _failure_entry("plan.rejected", event, None, record)
    return record.evolve(plan=plan, failure=record.failure + (entry,))


# -- Work block + Budget (Scheduling) -----------------------------------
def reduce_task_scheduled(record, event):
    # dual block: Work (task state) + Budget (granted amount, Phase3 §7 —
    # granted is read from task.scheduled/task.started budget fields).
    payload = _validate("task.scheduled", event)
    work = _task_state(record.work, payload["task_id"], "scheduled")
    budget = dict(record.budget)
    budget["granted"] = budget.get("granted", 0) + payload["budget_granted"]
    return record.evolve(work=work, budget=budget)


def reduce_task_started(record, event):
    payload = _validate("task.started", event)
    work = _task_state(record.work, payload["task_id"], "started")
    return record.evolve(work=work)


def reduce_task_preempted(record, event):
    payload = _validate("task.preempted", event)
    work = _task_state(record.work, payload["task_id"], "preempted")
    return record.evolve(work=work)


def reduce_task_completed(record, event):
    payload = _validate("task.completed", event)
    work = _task_state(record.work, payload["task_id"], "completed")
    return record.evolve(work=work)


def reduce_task_failed(record, event):
    payload = _validate("task.failed", event)
    work = _task_state(record.work, payload["task_id"], "failed")
    entry = _failure_entry("task.failed", event, payload["task_id"], record)
    return record.evolve(work=work, failure=record.failure + (entry,))


# -- Work block (Execution) --------------------------------------------------
def reduce_exec_started(record, event):
    payload = _validate("exec.started", event)
    work = _exec_state(record.work, payload["exec_id"], state="started",
                        task_id=payload["task_id"])
    return record.evolve(work=work)


def reduce_exec_completed(record, event):
    payload = _validate("exec.completed", event)
    work = _exec_state(record.work, payload["exec_id"], state="completed",
                        outcome_ref=payload["outcome_ref"])
    return record.evolve(work=work)


def reduce_exec_timeout(record, event):
    payload = _validate("exec.timeout", event)
    work = _exec_state(record.work, payload["exec_id"], state="timeout")
    entry = _failure_entry("exec.timeout", event, payload["exec_id"], record)
    return record.evolve(work=work, failure=record.failure + (entry,))


def reduce_exec_failed(record, event):
    payload = _validate("exec.failed", event)
    work = _exec_state(record.work, payload["exec_id"], state="failed")
    entry = _failure_entry("exec.failed", event, payload["exec_id"], record)
    return record.evolve(work=work, failure=record.failure + (entry,))


# -- Context block (Context Management) --------------------------------------
def reduce_context_assembled(record, event):
    payload = _validate("context.assembled", event)
    context = dict(record.context)
    context[payload["step"]] = payload["context_package_id"]
    return record.evolve(context=context)


# -- Verification block (Verification) ---------------------------------------
def reduce_verify_requested(record, event):
    payload = _validate("verify.requested", event)
    verification = dict(record.verification)
    verification[payload["gate"]] = {"state": "requested"}
    return record.evolve(verification=verification)


def reduce_verify_passed(record, event):
    payload = _validate("verify.passed", event)
    verification = dict(record.verification)
    verification[payload["gate"]] = {"state": "passed", "verdict_ref": payload["verdict_ref"]}
    return record.evolve(verification=verification)


def reduce_verify_failed(record, event):
    payload = _validate("verify.failed", event)
    verification = dict(record.verification)
    verification[payload["gate"]] = {"state": "failed", "verdict_ref": payload["verdict_ref"]}
    entry = _failure_entry("verify.failed", event, payload["gate"], record)
    return record.evolve(verification=verification, failure=record.failure + (entry,))


# -- Work/Failure block (Storage commit outcomes) -----------------------
def reduce_storage_committed(record, event):
    payload = _validate("storage.committed", event)
    work = dict(record.work)
    work["commit_ref"] = payload["commit_ref"]
    return record.evolve(work=work)


def reduce_storage_rejected(record, event):
    # RSM/03 §6 names storage.rejected explicitly in the Failure-family
    # list; Phase2 §4's "reflect ... into Work/Failure as applicable"
    # resolved as: both.
    payload = _validate("storage.rejected", event)
    work = dict(record.work)
    work["commit_ref"] = None
    entry = _failure_entry("storage.rejected", event, None, record)
    return record.evolve(work=work, failure=record.failure + (entry,))


# -- Budget block (Observability) --------------------------------------------
def reduce_cost_recorded(record, event):
    # Late-tolerant (RSM/03 §3, §7): this reducer is reachable from
    # terminal/persisted/retained states too, not only active — same pure
    # (record, event) -> record' contract regardless of state.
    payload = _validate("cost.recorded", event)
    budget = dict(record.budget)
    budget["consumed"] = budget.get("consumed", 0) + payload["amount"]
    return record.evolve(budget=budget)


# -- Failure block (any publisher, via fault.recorded as a payload) ---------
def reduce_fault_recorded(record, event):
    payload = _validate("fault.recorded", event)
    entry = _failure_entry("fault.recorded", event, payload.get("reason"), record)
    return record.evolve(failure=record.failure + (entry,))


# -- Lifecycle block (Kernel terminal family) --------------------------------
def reduce_request_completed(record, event):
    _validate("request.completed", event)
    return record.evolve(lifecycle={"state": "completed"})


def reduce_request_rejected(record, event):
    payload = _validate("request.rejected", event)
    return record.evolve(lifecycle={"state": "rejected", "reason": payload["reason"]})


def reduce_request_cancelled(record, event):
    _validate("request.cancelled", event)
    return record.evolve(lifecycle={"state": "cancelled"})


def reduce_request_failed(record, event):
    # dual block: Lifecycle (terminal outcome) + Failure (RSM/03 §6 /
    # Phase2 §4 both list request.failed as a Failure-feeding family).
    payload = _validate("request.failed", event)
    entry = _failure_entry("request.failed", event, None, record)
    return record.evolve(
        lifecycle={"state": "failed", "reason": payload["reason"]},
        failure=record.failure + (entry,),
    )


REGISTRY = {
    "intent.classified": reduce_intent_classified,
    "plan.created": reduce_plan_created,
    "plan.revised": reduce_plan_revised,
    "plan.validated": reduce_plan_validated,
    "plan.rejected": reduce_plan_rejected,
    "task.scheduled": reduce_task_scheduled,
    "task.started": reduce_task_started,
    "task.preempted": reduce_task_preempted,
    "task.completed": reduce_task_completed,
    "task.failed": reduce_task_failed,
    "exec.started": reduce_exec_started,
    "exec.completed": reduce_exec_completed,
    "exec.timeout": reduce_exec_timeout,
    "exec.failed": reduce_exec_failed,
    "context.assembled": reduce_context_assembled,
    "verify.requested": reduce_verify_requested,
    "verify.passed": reduce_verify_passed,
    "verify.failed": reduce_verify_failed,
    "storage.committed": reduce_storage_committed,
    "storage.rejected": reduce_storage_rejected,
    "cost.recorded": reduce_cost_recorded,
    "fault.recorded": reduce_fault_recorded,
    "request.completed": reduce_request_completed,
    "request.failed": reduce_request_failed,
    "request.rejected": reduce_request_rejected,
    "request.cancelled": reduce_request_cancelled,
}


if __name__ == "__main__":
    from . import record as record_mod
    from . import transitions

    # registry completeness: every non-birth registered family has exactly
    # one reducer (RSM/03 §4 "one family, one reducer").
    expected = transitions.REGISTERED_FAMILIES - {BIRTH_FAMILY}
    assert set(REGISTRY) == expected, set(REGISTRY) ^ expected

    # purity/determinism: same (record, event) in -> same record' out, every
    # time; the other in-scope record is untouched (cross-record isolation).
    rec = record_mod.birth("r1", {"declared_type": "a", "origin": "fe"})
    other = record_mod.birth("r2", {"declared_type": "b", "origin": "fe"})
    ev = {"event_id": "e1", "family": "task.scheduled", "request_id": "r1",
          "schema_version": 1, "payload": {"task_id": "t1", "budget_granted": 10}}
    out1 = REGISTRY["task.scheduled"](rec, ev)
    out2 = REGISTRY["task.scheduled"](rec, ev)
    assert out1 == out2
    assert out1.work == {"tasks": {"t1": {"state": "scheduled"}}}
    assert out1.budget == {"granted": 10}
    assert rec.work == {} and rec.budget == {}  # original untouched
    assert other.work == {} and other.budget == {}  # cross-record isolation

    # schema mismatch -> ReducerFault, not a crash, not a silent pass
    bad_version = dict(ev, schema_version=2)
    try:
        REGISTRY["task.scheduled"](rec, bad_version)
        raise SystemExit("schema mismatch accepted")
    except ReducerFault as f:
        assert f.reason.startswith(SCHEMA_MISMATCH)

    # malformed (missing required field) -> ReducerFault
    missing_field = {"event_id": "e2", "family": "task.scheduled", "request_id": "r1",
                      "schema_version": 1, "payload": {"task_id": "t1"}}
    try:
        REGISTRY["task.scheduled"](rec, missing_field)
        raise SystemExit("malformed event accepted")
    except ReducerFault as f:
        assert f.reason.startswith(MALFORMED)

    # dual-block reducer: failure + primary block in one version bump
    fail_ev = {"event_id": "e3", "family": "task.failed", "request_id": "r1",
               "schema_version": 1, "payload": {"task_id": "t1", "reason": "boom"}}
    failed = REGISTRY["task.failed"](out1, fail_ev)
    assert failed.work["tasks"]["t1"]["state"] == "failed"
    assert len(failed.failure) == 1 and failed.failure[0]["family"] == "task.failed"

    # birth is special-cased, not in REGISTRY
    assert BIRTH_FAMILY not in REGISTRY
    birth_ev = {"event_id": "e0", "family": BIRTH_FAMILY, "request_id": "r3",
                "schema_version": 1, "payload": {"declared_type": "x", "origin": "fe"}}
    assert birth_reducer(birth_ev) == {"declared_type": "x", "origin": "fe"}

    print("reducers selftest ok")
