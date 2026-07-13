"""Read-only query surface over `store`/`journal` snapshots (RSM/05-
implementation-spec.md M3; RSM/03-internal-design.md §5 execution history,
§7 budget tracking). Every function here reads already-materialized state —
never calls a reducer, never mutates `store` or `journal`, never touches the
bus (RSM-I9: reads never block reducers, never observe a torn record).
Because `record.evolve()` always builds a brand-new `RequestRecord`
(record.py) rather than mutating in place, a reference returned by any
function below stays frozen forever regardless of what `ingest` applies
afterward — there is no locking to do here, immutability is the mechanism.

D4a-mirror (RSM-I10): absent and evicted are different, honestly disclosed
answers, never conflated and never a resurrection attempt. `status()` is
the one place that distinction is made; every other read here is built on
top of it.
"""
from . import record as record_mod
from . import transitions

ABSENT = transitions.ABSENT
EVICTED = transitions.EVICTED
ACTIVE = transitions.ACTIVE

READABLE_BLOCKS = record_mod.BLOCK_NAMES


def status(store, request_id):
    """Materialization state: 'absent' | 'active' | 'terminal' |
    'persisted' | 'retained' | 'evicted' (RSM/03 §2)."""
    return store.state_of(request_id)


def snapshot(store, request_id):
    """Current RequestRecord for a live/retained id, or None for
    absent/evicted (RSM/05 §3, "record snapshot by request id"). Never
    reconstructs an evicted record inline (RSM/03 §2) — call `status()` to
    tell absent from evicted."""
    if status(store, request_id) in (ABSENT, EVICTED):
        return None
    return store.get(request_id)


def block(store, request_id, block_name):
    """One block's value without serializing the whole record (RSM/05 §3:
    "block sub-reads ... without serializing the whole record"). `budget`
    returns the derived view (see `budget()` below), not the raw stored
    sub-dict, so a block-read and a direct `budget()` call always agree."""
    if block_name not in READABLE_BLOCKS:
        raise ValueError("query.unknown_block:" + str(block_name))
    if block_name == "budget":
        return budget(store, request_id)
    rec = snapshot(store, request_id)
    return getattr(rec, block_name) if rec is not None else None


def budget(store, request_id):
    """granted / consumed / remaining (RSM/03 §7). `remaining` is derived
    here at read time, never stored on the record — a stored value would be
    a second place arithmetic could drift (RSM/03 §7's own reasoning).
    Over-consumption is reported, not clamped: RSM records, never reacts
    (§6) — a negative `remaining` is a legitimate, honest answer, not an
    error and not enforcement (enforcement authority stays with
    Scheduling, RSM/02 Budget-block semantics)."""
    rec = snapshot(store, request_id)
    if rec is None:
        return None
    granted = rec.budget.get("granted", 0)
    consumed = rec.budget.get("consumed", 0)
    return {"granted": granted, "consumed": consumed, "remaining": granted - consumed}


def failures(store, request_id):
    """Ordered failure entries plus `replan_count` (RSM/03 §6).

    # ponytail: `replan_count` should be "a count of plan.revised events
    # folded so far" (RSM/03 §6) via a read-time scan of the applied event
    # stream. `journal` only retains (event_id, seq, reducer_version) per
    # entry (journal.py) — no family — so a query-time scan can't tell a
    # plan.revised apply from any other. The one already-in-record proxy is
    # Plan block's `revision` field, which Capability Planning's schema
    # (ADR-RSM-4) defines as a 0-based counter starting at plan.created and
    # bumped once per plan.revised — so it equals the fold count under that
    # contract. Upgrade path: if that monotonic-+1 contract is ever not
    # guaranteed, add family to `journal` entries and count by replay
    # instead of trusting the payload-owned field.
    """
    rec = snapshot(store, request_id)
    if rec is None:
        return None
    return {"entries": rec.failure, "replan_count": rec.plan.get("revision", 0)}


def enumerate_active(store):
    """All request ids currently materialization-state 'active' (RSM/05 §3
    "active-request enumeration", bounded upstream by admission control per
    RSM/03 §10) — excludes terminal/persisted/retained/evicted."""
    return [rid for rid in store.request_ids() if store.state_of(rid) == ACTIVE]


def journal_read(journal, store, request_id):
    """Ordered applied event ids for any non-evicted record (RSM/05 §3:
    "journal read for a completed request, used by recovery and Learning's
    read path" — the underlying `journal.entries()` already holds every
    applied id regardless of state, RSM/03 §5 "Exact — journal replay", so
    this works for any non-evicted state, not only terminal-and-later).
    None for absent and evicted ids (D4a-mirror, same as `snapshot`)."""
    if status(store, request_id) in (ABSENT, EVICTED):
        return None
    return tuple(event_id for event_id, _, _ in journal.entries(request_id))


if __name__ == "__main__":
    from .store import Store
    from .journal import Journal
    from .ingest import Ingest, make_event, APPLIED

    store = Store()
    journal = Journal()
    ing = Ingest(store, journal)

    # absent: honest None/"absent" everywhere, no crash, no resurrection
    assert status(store, "ghost") == ABSENT
    assert snapshot(store, "ghost") is None
    assert block(store, "ghost", "budget") is None
    assert failures(store, "ghost") is None
    assert journal_read(journal, store, "ghost") is None

    assert ing.process(make_event("e0", "request.received", "r1", 1,
                                   {"declared_type": "a", "origin": "fe"})) == APPLIED
    assert status(store, "r1") == ACTIVE
    assert enumerate_active(store) == ["r1"]

    # zero-grant budget: no task.scheduled yet
    assert budget(store, "r1") == {"granted": 0, "consumed": 0, "remaining": 0}

    assert ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                   {"task_id": "t1", "budget_granted": 10})) == APPLIED
    assert budget(store, "r1") == {"granted": 10, "consumed": 0, "remaining": 10}
    assert block(store, "r1", "budget") == budget(store, "r1")

    # snapshot torn-read proof: a held reference never changes under later applies
    held = snapshot(store, "r1")
    assert held.work["tasks"]["t1"]["state"] == "scheduled"
    assert ing.process(make_event("e2", "task.started", "r1", 1, {"task_id": "t1"})) == APPLIED
    assert held.work["tasks"]["t1"]["state"] == "scheduled"  # old snapshot untouched (RSM-I9)
    assert snapshot(store, "r1").work["tasks"]["t1"]["state"] == "started"  # fresh read sees the fold

    # over-consumption: reported, not clamped
    assert ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 25})) == APPLIED
    assert budget(store, "r1") == {"granted": 10, "consumed": 25, "remaining": -15}

    # replan_count via plan.revised fold
    assert ing.process(make_event("e4", "plan.created", "r1", 1,
                                   {"plan_id": "p1", "revision": 0})) == APPLIED
    assert ing.process(make_event("e5", "plan.revised", "r1", 1,
                                   {"plan_id": "p1", "revision": 1})) == APPLIED
    assert failures(store, "r1")["replan_count"] == 1
    assert failures(store, "r1")["entries"] == ()

    assert ing.process(make_event("e6", "task.failed", "r1", 1,
                                   {"task_id": "t1", "reason": "boom"})) == APPLIED
    assert len(failures(store, "r1")["entries"]) == 1

    assert journal_read(journal, store, "r1") == ("e0", "e1", "e2", "e3", "e4", "e5", "e6")

    assert ing.process(make_event("e7", "request.completed", "r1", 1, {})) == APPLIED
    assert enumerate_active(store) == []  # terminal, no longer "active"
    assert status(store, "r1") == "terminal"

    # evicted: distinct, honest answer, never a crash, never a stale reconstruction
    store.mark_evicted("r1")
    assert status(store, "r1") == EVICTED
    assert snapshot(store, "r1") is None
    assert block(store, "r1", "identity") is None
    assert failures(store, "r1") is None
    assert journal_read(journal, store, "r1") is None
    assert status(store, "r1") != status(store, "ghost")  # evicted != absent, D4a-mirror

    try:
        block(store, "r1", "not_a_block")
        raise SystemExit("unknown block name accepted")
    except ValueError:
        pass

    print("query selftest ok")
