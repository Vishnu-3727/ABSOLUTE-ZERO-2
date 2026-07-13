"""Duplicate elimination (blueprint Phase 3): identity is the candidate
`id`; a content hash (json.dumps of the `content` field, canonical style)
decides whether a repeated id is a true duplicate or a contradiction.

Same id, same content -> exact duplicate, the repeat is dropped and the
first occurrence's position is kept (stable ordering preserved, CM-I2).
Same id, different content -> a contradiction: UMS/RSM/reference sources
disagree about the same thing. CM-I never blends conflicting content, so
both survive, each tagged `contradiction: True` for the caller/validator to
see rather than being silently resolved here.

dedup(dedup(x)) == dedup(x): a second pass sees the same ids with the same
content hashes it already decided on, so nothing new changes.
"""
import hashlib
import json


def _content_hash(candidate):
    return hashlib.sha256(
        json.dumps(candidate.get("content"), sort_keys=True, separators=(",", ":"),
                   default=str).encode()
    ).hexdigest()


def dedup(candidates):
    """Return a new list: exact duplicates removed, contradictions flagged,
    original relative order preserved."""
    id_hashes = {}
    for c in candidates:
        id_hashes.setdefault(c["id"], set()).add(_content_hash(c))
    contradicted_ids = {cid for cid, hashes in id_hashes.items() if len(hashes) > 1}

    seen = set()  # (id, content_hash) pairs already emitted
    result = []
    for c in candidates:
        key = (c["id"], _content_hash(c))
        if key in seen:
            continue  # exact duplicate of an already-kept item, drop the repeat
        seen.add(key)
        if c["id"] in contradicted_ids:
            c = dict(c, contradiction=True)
        result.append(c)
    return result


if __name__ == "__main__":
    a = {"id": "x1", "section": "files", "content": {"full": "A"}, "score": 1,
         "stale": False, "provenance": {}}
    a_dup = dict(a)  # identical content, same id -> exact duplicate
    b = {"id": "x2", "section": "files", "content": {"full": "B"}, "score": 1,
         "stale": False, "provenance": {}}
    a_conflict = {"id": "x1", "section": "files", "content": {"full": "A-DIFFERENT"},
                  "score": 1, "stale": False, "provenance": {}}

    out = dedup([a, a_dup, b])
    assert [c["id"] for c in out] == ["x1", "x2"]  # exact dup dropped
    assert "contradiction" not in out[0]

    # contradiction: same id, different content -> both kept, flagged
    out2 = dedup([a, a_conflict, b])
    assert [c["id"] for c in out2] == ["x1", "x1", "x2"]
    assert out2[0]["contradiction"] is True
    assert out2[1]["contradiction"] is True
    assert out2[0]["content"] != out2[1]["content"]  # never blended

    # idempotence: dedup(dedup(x)) == dedup(x)
    assert dedup(dedup([a, a_dup, b])) == dedup([a, a_dup, b])
    assert dedup(dedup([a, a_conflict, b])) == dedup([a, a_conflict, b])

    # stable ordering preserved after removal (original relative order)
    c1 = {"id": "z", "section": "files", "content": {"full": "1"}, "score": 1,
          "stale": False, "provenance": {}}
    c2 = {"id": "a", "section": "files", "content": {"full": "2"}, "score": 1,
          "stale": False, "provenance": {}}
    out3 = dedup([c1, c2])
    assert [c["id"] for c in out3] == ["z", "a"]  # not re-sorted here

    # empty input
    assert dedup([]) == []

    print("dedup selftest ok")
