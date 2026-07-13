"""Event-id exactly-once application (RSM-I4: delivery at-least-once in,
application exactly-once). A thin query over the request's own journal —
RSM/05-implementation-spec.md M2 decides the journal is dedup's source of
truth, so this module holds no parallel id set of its own; two structures
that could drift is exactly the failure mode a single source of truth
avoids.
"""


def is_duplicate(journal, request_id, event_id):
    """True if `event_id` already applied for `request_id` — caller
    (`ingest`) silently drops on True: no reducer call, no journal append,
    no telemetry beyond a dedup counter (RSM/03 §3)."""
    return journal.has(request_id, event_id)


if __name__ == "__main__":
    from .journal import Journal

    j = Journal()
    assert is_duplicate(j, "r1", "e1") is False
    j.append("r1", "e1", 1)
    assert is_duplicate(j, "r1", "e1") is True
    assert is_duplicate(j, "r1", "e2") is False  # different event id, not a dup
    assert is_duplicate(j, "r2", "e1") is False  # different request, own journal

    print("dedup selftest ok")
