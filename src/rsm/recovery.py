"""Startup/restart replay fold (RSM/03-internal-design.md §1 "Restart /
recovery"; RSM/05-implementation-spec.md M5). Rebuilds `store`/`journal`
state for a request from persisted Storage documents (journal index and/or
checkpoint, via `persistence`) by re-feeding the original events through
the same `ingest` pipeline used live — this IS the fold (RSM-I3/RSM-I12:
replay = fold(reducer_version, journal order), no separate reconstruction
code path that could drift from `ingest`'s own pipeline).

Journal stores event ids only, never payloads (RSM/05 §3: "journal-index
document (ordered event-id + seq + reducer-version tuples)") — recovery
cannot replay from the journal index alone. It requires a caller-supplied
*event source*: `event_id -> event envelope`, either a plain mapping (a
dict) or a zero-one-arg callable. Real Communication/Storage don't exist
yet (RSM/05 §6, "Storage's own swap-in is a later follow-up") — until they
do, callers (tests; later, real orchestration) supply a dict or a small
callable backed by whatever event-archival mechanism Storage/Communication
eventually provide. Recovery's own fold logic does not change when that
swap happens — only what fills `event_source` does, same shape as
`bus_double`'s and `persistence`'s Storage-double seams.

Reads-closed-until-done (RSM/03 §1 step 4: "only after all identified
non-terminal requests are re-folded does the read surface reopen") is
implemented as `RecoveryGate` — a lazy, caller-checked flag (RSM/05 M5:
"lazy mechanism OK, e.g. a flag the query path or recovery holder
checks"). `query.py` itself is deliberately not modified: gating reads is
a call-site concern, not a `query` responsibility, so this stays additive
rather than threading a gate parameter through every existing query
function.
"""
from .store import Store
from .journal import Journal
from .ingest import Ingest
from . import persistence


class ReplayMismatch(Exception):
    """RSM-I12: replay produced a record that differs from the live/
    persisted one it is being verified against. Halts loudly, per spec —
    deviation is corruption, not a warning a caller silently absorbs."""


class RecoveringError(Exception):
    """Raised by `RecoveryGate.guard()` while `recovering` is still True —
    the "recovering" read refusal (RSM/03 §1: "a query during recovery gets
    'recovering', never a stale or partially-rebuilt answer")."""


class RecoveryGate:
    """Process-scope "recovering" flag (RSM/03 §1 step 4). Starts True —
    a fresh RSM process/test scenario is recovering until something calls
    `open()`. `guard()` is the refusal a read call site invokes before
    delegating to `query`; `query`'s own functions are untouched."""

    def __init__(self):
        self.recovering = True

    def guard(self):
        if self.recovering:
            raise RecoveringError("rsm.recovering")

    def open(self):
        self.recovering = False


def _lookup(event_source, event_id):
    if hasattr(event_source, "__getitem__"):
        return event_source[event_id]
    return event_source(event_id)


def replay_journal(event_ids, event_source, seed_store=None, seed_journal=None):
    """Fold one request from an ordered sequence of applied event ids,
    resolving each id's full envelope via `event_source` (RSM/05 §3 "what
    ingest consumes" contract, reused unchanged for replay — the fold IS
    `ingest.process`, called here instead of live). `seed_store`/
    `seed_journal` let a checkpoint-bounded resume (`replay_from_
    checkpoint`, below) start from a pre-populated pair instead of folding
    from event 1 every time (RSM/03 §11's bounded-replay intent) — default
    is a fresh `Store()`/`Journal()`, i.e. a full replay. Returns
    `(store, journal, record)` for whichever request_id the folded events
    belong to (a single request's own event-id sequence is the caller's
    contract, same shape as one request's own journal). Every event id
    must resolve via `event_source` or `KeyError` propagates — an
    unresolvable id is a caller/Storage-contract bug, not a recoverable
    RSM condition."""
    store = seed_store if seed_store is not None else Store()
    journal = seed_journal if seed_journal is not None else Journal()
    ing = Ingest(store, journal)
    request_id = None
    for event_id in event_ids:
        event = _lookup(event_source, event_id)
        request_id = event["request_id"]
        ing.process(event)
    record = store.get(request_id) if request_id is not None else None
    return store, journal, record


def replay_from_journal_index(storage, request_id, event_source):
    """Rebuild a request purely from its persisted journal-index document
    (RSM/05 §3 "journal-index document") plus a caller-supplied event
    source — the no-checkpoint path (RSM/03 §1 bullet 2's other branch: "a
    full replay of that request's event subsequence from the persisted log"
    when no checkpoint exists for it)."""
    idx = persistence.read_journal_index(storage, request_id)
    event_ids = [entry[0] for entry in idx["entries"]]
    return replay_journal(event_ids, event_source)


def replay_from_checkpoint(storage, request_id, tail_event_ids, event_source, seq=None):
    """Bounded recovery (RSM/03 §11): seed from the latest (or a given
    `seq`) checkpoint document instead of event 1, then fold only
    `tail_event_ids` — the events applied *after* the checkpoint's own
    journal prefix (RSM/03 §11: "recovery ... only needs to replay from the
    last checkpoint forward, not from event 1"). The checkpoint's own
    prefix is trusted as already-correct (it was itself produced by a live
    fold, RSM-I3); `verify_byte_identical` below is what catches drift if
    that trust is ever wrong. Seeds `store` as ACTIVE (`store.seed`) — the
    scenario this exists for is resuming a non-terminal request after a
    crash (RSM/03 §1 "identify non-terminal requests as of the crash")."""
    doc = persistence.read_checkpoint(storage, request_id, seq=seq)
    seeded_record = persistence.record_from_checkpoint(doc)
    store = Store()
    store.seed(request_id, seeded_record)
    journal = Journal()
    for event_id, entry_seq, reducer_version in doc["journal_prefix"]:
        journal.append(request_id, event_id, reducer_version)
    return replay_journal(tail_event_ids, event_source, seed_store=store, seed_journal=journal)


def verify_byte_identical(replayed_record, reference_record):
    """RSM-I12: replay must reproduce the reference record exactly.
    Records are frozen dataclasses (record.py) — `==` is already a
    structural, field-by-field comparison (dataclass-generated), so
    "byte-identical" is literal Python equality here, not a serialization
    round-trip. Raises `ReplayMismatch` (halts loudly) rather than
    returning False — deviation is corruption, not a branch a caller is
    expected to handle silently."""
    if replayed_record != reference_record:
        raise ReplayMismatch(
            "recovery.mismatch:" + str(getattr(replayed_record, "request_id", "?")))
    return True


if __name__ == "__main__":
    from .ingest import make_event, APPLIED

    def _clock_factory(start=0):
        box = [start]
        return (lambda: box[0]), box

    # -- full replay from a persisted journal index -------------------------
    from ums.storage_double import StorageDouble

    storage = StorageDouble()
    store, journal = Store(), Journal()
    ing = Ingest(store, journal)
    clock, _ = _clock_factory(1000)

    events = [
        make_event("e0", "request.received", "r1", 1, {"declared_type": "a", "origin": "fe"}),
        make_event("e1", "task.scheduled", "r1", 1, {"task_id": "t1", "budget_granted": 10}),
        make_event("e2", "task.started", "r1", 1, {"task_id": "t1"}),
        make_event("e3", "request.completed", "r1", 1, {}),
    ]
    event_source = {e["event_id"]: e for e in events}
    for e in events:
        assert ing.process(e) == APPLIED

    persistence.persist_terminal(storage, journal, store, "r1", clock)
    live_record = store.get("r1")

    replay_store, replayed_journal, replayed_record = replay_from_journal_index(
        storage, "r1", event_source)
    assert verify_byte_identical(replayed_record, live_record) is True
    assert replayed_journal.entries("r1") == journal.entries("r1")

    # replay also matches the persisted terminal snapshot
    terminal_snapshot = persistence.read_terminal_snapshot(storage, "r1")
    assert verify_byte_identical(replayed_record, terminal_snapshot) is True

    # a genuine mismatch halts loudly, not silently
    tampered = replayed_record.evolve(budget={"granted": 999})
    try:
        verify_byte_identical(tampered, live_record)
        raise SystemExit("mismatch not detected")
    except ReplayMismatch:
        pass

    # -- bounded replay from a checkpoint ------------------------------------
    store2, journal2 = Store(), Journal()
    ing2 = Ingest(store2, journal2)
    events2 = [
        make_event("c0", "request.received", "r2", 1, {"declared_type": "a", "origin": "fe"}),
        make_event("c1", "task.scheduled", "r2", 1, {"task_id": "t1", "budget_granted": 5}),
        make_event("c2", "task.started", "r2", 1, {"task_id": "t1"}),
        make_event("c3", "cost.recorded", "r2", 1, {"amount": 2}),
    ]
    source2 = {e["event_id"]: e for e in events2}
    checkpoint_doc = None
    for e in events2[:2]:
        ing2.process(e)
        checkpoint_doc = persistence.maybe_checkpoint(storage, journal2, store2, "r2",
                                                        checkpoint_n=2)
    assert checkpoint_doc is not None and checkpoint_doc["seq"] == 1
    for e in events2[2:]:
        ing2.process(e)
    live_record2 = store2.get("r2")

    tail_ids = [e["event_id"] for e in events2[2:]]  # events after the checkpoint's prefix
    _, _, replayed2 = replay_from_checkpoint(storage, "r2", tail_ids, source2)
    assert verify_byte_identical(replayed2, live_record2) is True

    # -- reads-closed-until-done ---------------------------------------------
    gate = RecoveryGate()
    assert gate.recovering is True
    try:
        gate.guard()
        raise SystemExit("guard allowed a read mid-recovery")
    except RecoveringError:
        pass
    gate.open()
    gate.guard()  # no longer raises
    assert gate.recovering is False

    print("recovery selftest ok")
