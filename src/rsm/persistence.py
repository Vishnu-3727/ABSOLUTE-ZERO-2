"""Storage-double-backed persistence writes (RSM/03-internal-design.md §2
"terminal -> persisted", §11 checkpoints; RSM/05-implementation-spec.md M4,
§3 "What persistence hands Storage"). Three opaque document kinds, each
format-versioned (RSM/05 §3): journal-index, terminal-snapshot, checkpoint.

Storage double: this module's `storage` argument is duck-typed to
`src/ums/storage_double.py`'s `StorageDouble` — `write(key, bytes)` /
`read(key) -> bytes` / `exists(key) -> bool`, blob semantics only (RSM/05
§3: "mirrors ... storage_double.py's write/read/exists blob shape exactly").
Reused directly rather than re-implemented — real Storage doesn't exist yet,
and this double's contract is already proven by UMS.

This module performs writes; it never decides *when* to persist. The
milestone spec (RSM/05 M4) ties persistence to two triggers — once at
terminal, and every N applied events for checkpoints — but does not name
`ingest` as the trigger's caller, and wiring ingest into the write path is
explicitly deferred integration (RSM/05 §6 lists Storage's own swap-in as
a later follow-up, not this milestone). So the trigger points here are
functions a caller (this milestone's tests; later, real orchestration)
invokes explicitly: `persist_terminal` once, `maybe_checkpoint` after each
applied event.
"""
import json

from . import record as record_mod
from . import transitions

FORMAT_VERSION = 1


# -- storage key layout ----------------------------------------------------
def _journal_key(request_id):
    return "rsm/journal/" + request_id


def _terminal_key(request_id):
    return "rsm/terminal/" + request_id


def _checkpoint_key(request_id, seq):
    return "rsm/checkpoint/%s/%d" % (request_id, seq)


def _checkpoint_index_key(request_id):
    return "rsm/checkpoint_index/" + request_id


# -- record <-> plain-dict document (JSON needs lists, not tuples) ---------
def _record_to_dict(rec):
    return {
        "request_id": rec.request_id,
        "version": rec.version,
        "identity": rec.identity,
        "lifecycle": rec.lifecycle,
        "plan": rec.plan,
        "work": rec.work,
        "context": rec.context,
        "verification": rec.verification,
        "budget": rec.budget,
        "failure": list(rec.failure),
        "journal_meta": rec.journal_meta,
    }


def _dict_to_record(d):
    return record_mod.RequestRecord(
        request_id=d["request_id"],
        version=d["version"],
        identity=d["identity"],
        lifecycle=d["lifecycle"],
        plan=d["plan"],
        work=d["work"],
        context=d["context"],
        verification=d["verification"],
        budget=d["budget"],
        failure=tuple(d["failure"]),
        journal_meta=d["journal_meta"],
    )


# -- journal-index document -------------------------------------------------
def write_journal_index(storage, request_id, journal):
    """RSM-I8: journal index (ordered event-id + seq + reducer-version
    tuples), durable via Storage (RSM/05 §3). Called once at terminal
    (`persist_terminal`) and re-called on every late-tolerant apply after
    persisted (RSM/03 §3 "re-trigger a journal-index write") — see
    `reapply_journal_index` below."""
    entries = journal.entries(request_id)
    doc = {
        "format_version": FORMAT_VERSION,
        "request_id": request_id,
        "entries": [list(e) for e in entries],
    }
    storage.write(_journal_key(request_id), json.dumps(doc).encode("utf-8"))
    return doc


def read_journal_index(storage, request_id):
    return json.loads(storage.read(_journal_key(request_id)))


# -- terminal-snapshot document ---------------------------------------------
def write_terminal_snapshot(storage, request_id, record):
    """RSM-I8: the record's block state at the moment it reached `terminal`
    (RSM/03 §2). Written once — it is a snapshot of that moment, not a
    running mirror; a later late-tolerant apply updates the journal index
    (above) but never rewrites this document."""
    doc = {"format_version": FORMAT_VERSION, "record": _record_to_dict(record)}
    storage.write(_terminal_key(request_id), json.dumps(doc).encode("utf-8"))
    return doc


def read_terminal_snapshot(storage, request_id):
    doc = json.loads(storage.read(_terminal_key(request_id)))
    return _dict_to_record(doc["record"])


# -- checkpoint document ------------------------------------------------
def write_checkpoint(storage, journal, store, request_id):
    """Persisted journal prefix + block-state snapshot as of the current
    applied sequence number (RSM/03 §11). Additive to the journal, never a
    replacement (§11: "the full index is still the ground truth"). Keyed by
    (request_id, seq) so multiple checkpoints for one long-running request
    coexist; `_checkpoint_index_key` tracks the latest seq since
    `StorageDouble` is key/value only, no key listing."""
    entries = journal.entries(request_id)
    seq = entries[-1][1] if entries else -1
    rec = store.get(request_id)
    doc = {
        "format_version": FORMAT_VERSION,
        "request_id": request_id,
        "seq": seq,
        "journal_prefix": [list(e) for e in entries],
        "record": _record_to_dict(rec),
    }
    storage.write(_checkpoint_key(request_id, seq), json.dumps(doc).encode("utf-8"))
    storage.write(_checkpoint_index_key(request_id),
                  json.dumps({"latest_seq": seq}).encode("utf-8"))
    return doc


def read_checkpoint(storage, request_id, seq=None):
    """Latest checkpoint document by default, or a specific `seq`."""
    if seq is None:
        idx = json.loads(storage.read(_checkpoint_index_key(request_id)))
        seq = idx["latest_seq"]
    return json.loads(storage.read(_checkpoint_key(request_id, seq)))


def record_from_checkpoint(doc):
    """Reconstruct the `RequestRecord` a checkpoint document's `record`
    field encodes — public so callers (checkpoint-prefix-correctness tests,
    RSM/05 M4) never need the private dict<->record conversion helpers."""
    return _dict_to_record(doc["record"])


def maybe_checkpoint(storage, journal, store, request_id, checkpoint_n):
    """Every N applied events (`config_view.checkpoint_n`, RSM/03 §11).
    Caller invokes this once per applied event (e.g. after `ingest.process`
    returns APPLIED); a no-op unless the journal length just crossed a
    multiple of N. Returns the checkpoint doc if one was written, else
    None."""
    n = len(journal.entries(request_id))
    if n == 0 or checkpoint_n <= 0 or n % checkpoint_n != 0:
        return None
    return write_checkpoint(storage, journal, store, request_id)


# -- terminal -> persisted (M4) ---------------------------------------------
def persist_terminal(storage, journal, store, request_id, clock):
    """RSM/03 §2's terminal -> persisted step: write journal index +
    terminal snapshot durably via Storage, then move `store`'s own
    bookkeeping to `persisted` (`store.mark_persisted`). `clock` is the
    same injectable zero-arg time source `store.mark_persisted` and
    `store.evict_gate` use — no wall-clock reads here either.

    Precondition: `store.state_of(request_id) == transitions.TERMINAL`
    (raises otherwise — `store.mark_persisted` enforces this too, but
    checking here gives an accurate reason before any write happens)."""
    if store.state_of(request_id) != transitions.TERMINAL:
        raise ValueError("persistence.not_terminal:" + request_id)
    write_journal_index(storage, request_id, journal)
    write_terminal_snapshot(storage, request_id, store.get(request_id))
    store.mark_persisted(request_id, clock)


def reapply_journal_index(storage, journal, request_id):
    """A late-tolerant `cost.recorded` landing after `persisted` re-triggers
    a journal-index write (RSM/03 §3: "persisted is not
    read-only-yet-mutable-again ... late-tolerant families still apply and
    re-trigger a journal-index write"). The terminal snapshot is
    deliberately NOT rewritten here — see `write_terminal_snapshot`'s
    docstring."""
    return write_journal_index(storage, request_id, journal)


if __name__ == "__main__":
    from .store import Store
    from .journal import Journal
    from .ingest import Ingest, make_event, APPLIED
    from ums.storage_double import StorageDouble

    def _clock_factory(start=0):
        box = [start]
        return (lambda: box[0]), box

    storage = StorageDouble()
    store, journal = Store(), Journal()
    ing = Ingest(store, journal)
    clock, box = _clock_factory(1000)

    assert ing.process(make_event("e0", "request.received", "r1", 1,
                                   {"declared_type": "a", "origin": "fe"})) == APPLIED
    assert ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                   {"task_id": "t1", "budget_granted": 10})) == APPLIED
    assert ing.process(make_event("e2", "request.completed", "r1", 1, {})) == APPLIED
    assert store.state_of("r1") == "terminal"

    persist_terminal(storage, journal, store, "r1", clock)
    assert store.state_of("r1") == "persisted"
    assert storage.exists("rsm/journal/r1") and storage.exists("rsm/terminal/r1")

    idx = read_journal_index(storage, "r1")
    assert idx["entries"] == [["e0", 0, 1], ["e1", 1, 1], ["e2", 2, 1]]

    snap = read_terminal_snapshot(storage, "r1")
    assert snap.lifecycle == {"state": "completed"}
    assert snap.budget == {"granted": 10}

    # re-persisting an already-persisted id is refused (not TERMINAL anymore)
    try:
        persist_terminal(storage, journal, store, "r1", clock)
        raise SystemExit("re-persist allowed")
    except ValueError:
        pass

    # late-tolerant cost.recorded after persisted: applies, re-triggers journal write
    assert ing.process(make_event("e3", "cost.recorded", "r1", 1, {"amount": 4})) == APPLIED
    idx_before = read_journal_index(storage, "r1")
    assert len(idx_before["entries"]) == 3  # not yet re-persisted
    reapply_journal_index(storage, journal, "r1")
    idx_after = read_journal_index(storage, "r1")
    assert len(idx_after["entries"]) == 4 and idx_after["entries"][3][0] == "e3"
    # terminal snapshot untouched by the late re-trigger
    assert read_terminal_snapshot(storage, "r1").budget == {"granted": 10}

    # checkpoints every N applied events
    store2, journal2 = Store(), Journal()
    ing2 = Ingest(store2, journal2)
    ing2.process(make_event("c0", "request.received", "r2", 1,
                             {"declared_type": "a", "origin": "fe"}))
    checkpoints_written = []
    for i in range(1, 5):
        ing2.process(make_event("c%d" % i, "cost.recorded", "r2", 1, {"amount": 1}))
        doc = maybe_checkpoint(storage, journal2, store2, "r2", checkpoint_n=2)
        if doc is not None:
            checkpoints_written.append(doc["seq"])
    assert checkpoints_written == [1, 3]  # journal len 2 and 4 -> seq 1 and 3 (0-indexed)

    cp = read_checkpoint(storage, "r2")  # latest by default
    assert cp["seq"] == 3
    assert len(cp["journal_prefix"]) == 4
    assert cp["record"]["budget"] == {"consumed": 3}

    cp0 = read_checkpoint(storage, "r2", seq=1)
    assert cp0["seq"] == 1 and len(cp0["journal_prefix"]) == 2
    assert record_from_checkpoint(cp0).budget == {"consumed": 1}

    print("persistence selftest ok")
