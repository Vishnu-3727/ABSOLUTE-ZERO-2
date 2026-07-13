"""Single-threaded ingest pipeline (RSM/03-internal-design.md §4): dedup ->
request-id extraction -> record lookup -> transition-table row -> reducer
apply -> journal append -> telemetry-stub. This is the sole caller of
`reducers` and the sole mutator of `store` (RSM-I2 — enforced structurally:
no other module in `src/rsm/` constructs or calls a reducer, or writes to
`store`'s maps directly).

Interpretation note on pipeline ordering: RSM/03 §4's diagram lists "dedup
check (event id)" as step 1, before "request-id extraction" (step 2). But
RSM/05-implementation-spec.md's module table ties `dedup` to "a request's
journal" — which requires request_id already extracted. This module
extracts request_id first (structurally required to consult that request's
journal), then dedups. This changes nothing observable: a missing/invalid
request_id and an already-applied event id are mutually exclusive failure
modes on different events, so which check runs first never changes an
outcome, only which fault reason is reported for a doubly-bad event.

Interpretation note on "malformed": `transitions.lookup`'s `malformed`
parameter exists for the M1 table-exhaustiveness tests, which pass it in
directly. The real pipeline can't know malformed-ness until step 5 (a
reducer's own schema check, RSM/03 §4) — so `ingest` calls `lookup` with
`malformed` never set, and instead catches `reducers.ReducerFault` raised
by the reducer/birth_reducer call itself, treating it as the fault outcome.
"""
from . import reducers
from .transitions import lookup, CREATE, APPLY_TERMINAL, FAULT, UNREGISTERED

APPLIED = "applied"
DROPPED = "dropped"
FAULTED = "faulted"
UNREGISTERED_OUT = "unregistered"


def make_event(event_id, family, request_id, schema_version, payload):
    """Minimal event envelope (RSM/05-implementation-spec.md §3, "what
    ingest consumes"): event id (dedup key), family/topic (reducer
    selector), request id, schema version (reducer binding, ADR-RSM-4),
    payload (the Communication-owned fields a reducer may read). Plain
    dict — kernel `envelope.py` style precedent, not imported from here."""
    return {
        "event_id": event_id,
        "family": family,
        "request_id": request_id,
        "schema_version": schema_version,
        "payload": dict(payload),
    }


class Ingest:
    """Coordinates one `store` + one `journal` through the pipeline above.
    `process()` completes one event fully (all seven steps) before the
    caller may hand it the next — no interleaving (RSM/03 §9)."""

    def __init__(self, store, journal):
        self.store = store
        self.journal = journal
        # RSM's own health counters (RSM/03 §8) — "counted" seam for M2;
        # real bus-facing telemetry (`fault.recorded`, `state.updated`) is
        # M5.
        self.counters = {"applied": 0, "dedup_drop": 0, "fault": 0, "unregistered": 0}

    def _telemetry(self, kind, **fields):
        # ponytail: M5 stub. Real emission (`state.updated`/`state.evicted`/
        # `fault.recorded` to Observability, RSM/03 §8) lands with the
        # `telemetry` module. This is the counted, honest no-op seam
        # RSM/05-implementation-spec.md M2 calls for — counters above are
        # already real; only the bus publish is deferred.
        return None

    def process(self, event):
        request_id = event.get("request_id")
        event_id = event.get("event_id")
        family = event.get("family")
        if not request_id or not event_id or not family:
            self.counters["fault"] += 1
            self._telemetry("fault", reason="envelope_malformed")
            return FAULTED

        if self.journal.has(request_id, event_id):
            self.counters["dedup_drop"] += 1
            self._telemetry("dedup_drop", request_id=request_id, event_id=event_id)
            return DROPPED

        state = self.store.state_of(request_id)
        row = lookup(state, family)

        if row.action == UNREGISTERED:
            self.counters["unregistered"] += 1
            self._telemetry("unregistered", family=family)
            return UNREGISTERED_OUT

        if row.action == FAULT:
            self.counters["fault"] += 1
            self._telemetry("fault", request_id=request_id, family=family)
            return FAULTED

        try:
            if row.action == CREATE:
                identity_fields = reducers.birth_reducer(event)
                self.store.create(request_id, identity_fields)
            else:
                reducer = reducers.REGISTRY[family]
                current = self.store.get(request_id)
                new_record = reducer(current, event)
                if row.action == APPLY_TERMINAL:
                    self.store.apply_terminal(request_id, new_record)
                else:
                    self.store.apply(request_id, new_record)
        except reducers.ReducerFault as exc:
            self.counters["fault"] += 1
            self._telemetry("fault", request_id=request_id, family=family, reason=exc.reason)
            return FAULTED

        self.journal.append(request_id, event_id, reducer_version=1)
        self.counters["applied"] += 1
        self._telemetry("state.updated", request_id=request_id, family=family)
        return APPLIED


if __name__ == "__main__":
    from .store import Store
    from .journal import Journal

    store = Store()
    journal = Journal()
    ing = Ingest(store, journal)

    birth = make_event("e0", "request.received", "r1", 1,
                        {"declared_type": "type.alpha", "origin": "frontend"})
    assert ing.process(birth) == APPLIED
    assert store.get("r1").identity["declared_type"] == "type.alpha"
    assert journal.entries("r1") == (("e0", 0, 1),)

    sched = make_event("e1", "task.scheduled", "r1", 1,
                        {"task_id": "t1", "budget_granted": 5})
    assert ing.process(sched) == APPLIED
    assert store.get("r1").work["tasks"]["t1"]["state"] == "scheduled"
    assert store.get("r1").budget["granted"] == 5

    # duplicate delivery: silently dropped, journal/record unchanged
    before = store.get("r1")
    assert ing.process(sched) == DROPPED
    assert store.get("r1") is before
    assert journal.entries("r1") == (("e0", 0, 1), ("e1", 1, 1))

    # unregistered family: counted, not faulted, not journaled
    stray = make_event("e2", "memory.indexed", "r1", 1, {})
    assert ing.process(stray) == UNREGISTERED_OUT
    assert ing.counters["unregistered"] == 1
    assert journal.has("r1", "e2") is False

    # malformed registered event: faulted, not journaled
    bad = make_event("e3", "task.started", "r1", 1, {})  # missing task_id
    assert ing.process(bad) == FAULTED
    assert journal.has("r1", "e3") is False

    # unknown request id: faulted, no auto-create
    ghost = make_event("e4", "task.started", "ghost", 1, {"task_id": "t1"})
    assert ing.process(ghost) == FAULTED
    assert store.get("ghost") is None

    # terminal path
    term = make_event("e5", "request.completed", "r1", 1, {})
    assert ing.process(term) == APPLIED
    assert store.state_of("r1") == "terminal"
    assert store.get("r1").lifecycle == {"state": "completed"}

    # late-tolerant cost.recorded after terminal
    cost = make_event("e6", "cost.recorded", "r1", 1, {"amount": 3})
    assert ing.process(cost) == APPLIED
    assert store.get("r1").budget["consumed"] == 3

    # non-tolerant family after terminal: fault
    late = make_event("e7", "task.started", "r1", 1, {"task_id": "t1"})
    assert ing.process(late) == FAULTED

    print("ingest selftest ok — counters:", ing.counters)
