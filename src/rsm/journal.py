"""Per-request applied-event journal (RSM/03-internal-design.md §3 step 6,
RSM-I5). Ordered index: event id, applied sequence number, reducer version
active when applied — never a copy of the event payload (ADR-RSM-3, that's
Storage's job at persistence time). Journal order IS applied order; this
module never reorders and never re-merges by topic.

Doubles as `dedup`'s source of truth (RSM/05-implementation-spec.md M2:
"per-request applied-id set (journal doubles as the source of truth)") —
`has()` is what `dedup.is_duplicate` calls, so there is exactly one place
an applied-event-id lives, not two structures that could drift apart.

Checkpoint hooks are M4 scope (persisted prefix + block snapshot every N
events, RSM/03 §11) — `checkpoint()` here is an honest stub.
"""


class Journal:
    def __init__(self):
        self._entries = {}  # request_id -> [(event_id, seq, reducer_version), ...]
        self._ids = {}      # request_id -> {event_id, ...} for O(1) membership

    def has(self, request_id, event_id):
        return event_id in self._ids.get(request_id, ())

    def append(self, request_id, event_id, reducer_version):
        """Append-only, applied order (RSM-I5). Caller (`ingest`) must only
        call this for an event that just successfully applied — never for a
        dropped, faulted, or unregistered-family event (RSM/03 §3: "journal
        holds only applied events")."""
        entries = self._entries.setdefault(request_id, [])
        ids = self._ids.setdefault(request_id, set())
        if event_id in ids:
            raise ValueError("journal.duplicate_append:" + event_id)
        seq = len(entries)
        entries.append((event_id, seq, reducer_version))
        ids.add(event_id)
        return seq

    def entries(self, request_id):
        """Ordered tuple of (event_id, seq, reducer_version) — journal order
        == applied order == replay order (RSM-I5)."""
        return tuple(self._entries.get(request_id, ()))

    def checkpoint(self, request_id):
        """# ponytail: M4 stub. Real checkpointing (persisted journal
        prefix + block-state snapshot, every N applied events, N from
        `config_view`) lands with `persistence`/`config_view` in M4
        (RSM/03 §11, RSM/05 M4). Returns None — honest, not a fake result.
        """
        return None


if __name__ == "__main__":
    j = Journal()
    assert j.has("r1", "e1") is False
    seq0 = j.append("r1", "e1", 1)
    assert seq0 == 0 and j.has("r1", "e1") is True
    seq1 = j.append("r1", "e2", 1)
    assert seq1 == 1
    assert j.entries("r1") == (("e1", 0, 1), ("e2", 1, 1))
    assert j.entries("r2") == ()  # untouched request id, empty not KeyError

    try:
        j.append("r1", "e1", 1)
        raise SystemExit("duplicate append allowed")
    except ValueError:
        pass

    assert j.checkpoint("r1") is None  # M4 stub

    print("journal selftest ok")
