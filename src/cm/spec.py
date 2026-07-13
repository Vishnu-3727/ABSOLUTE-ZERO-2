"""Assembly Spec intake — normalizes a caller's request into the canonical,
deterministic spec CM assembles against (blueprint Phase 1). The spec hash
is the cache key Phase 5's cache.py will key on; it must not depend on the
order a caller happened to list capabilities/references in, or on dict
insertion order (CM-I2, Law 6: identical spec -> byte-identical Request
Memory downstream).

Normalization: capabilities and references are unordered sets from the
caller's point of view, so they're deduped and sorted here; canonical()
(json.dumps sort_keys) then handles dict key order for free.
"""
import hashlib
import json


def build(request_id, objective, budget_tokens, capabilities=(), constraints=None, references=()):
    """Return a canonical, deterministic Assembly Spec (plain dict)."""
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("spec.bad_request_id")
    if not isinstance(budget_tokens, int) or isinstance(budget_tokens, bool) or budget_tokens < 0:
        raise ValueError("spec.bad_budget_tokens")
    return {
        "request_id": request_id,
        "objective": objective,
        "budget_tokens": budget_tokens,
        "capabilities": sorted(set(capabilities)),
        "constraints": dict(constraints or {}),
        "references": sorted(set(references)),
    }


def canonical(spec):
    """Canonical byte form (envelope.canonical style: sort_keys, compact)."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()


def spec_hash(spec):
    """Deterministic cache key (Phase 5 cache.py keys on this)."""
    return hashlib.sha256(canonical(spec)).hexdigest()


if __name__ == "__main__":
    s1 = build("r1", "fix bug", 500, capabilities=["read", "write"],
               constraints={"lang": "py"}, references=["b.md", "a.md"])
    # order of capabilities/references at the call site must not matter
    s2 = build("r1", "fix bug", 500, capabilities=["write", "read"],
               constraints={"lang": "py"}, references=["a.md", "b.md"])
    assert s1 == s2
    assert spec_hash(s1) == spec_hash(s2)
    assert canonical(s1) == canonical(s2)

    # dict key order at the call site must not matter either
    s3 = build("r1", "fix bug", 500, capabilities=["read", "write"],
               constraints={"lang": "py"}, references=["a.md", "b.md"])
    assert spec_hash(s1) == spec_hash(s3)

    # different content -> different hash
    s4 = build("r1", "fix bug", 501, capabilities=["read", "write"],
               constraints={"lang": "py"}, references=["a.md", "b.md"])
    assert spec_hash(s4) != spec_hash(s1)

    # dedup of duplicated references/capabilities
    s5 = build("r1", "x", 10, capabilities=["read", "read"], references=["a.md", "a.md"])
    assert s5["capabilities"] == ["read"]
    assert s5["references"] == ["a.md"]

    for bad_id in ("", None, 5):
        try:
            build(bad_id, "x", 10)
            raise SystemExit("bad request_id accepted")
        except ValueError:
            pass
    for bad_budget in (-1, "10", True):
        try:
            build("r1", "x", bad_budget)
            raise SystemExit("bad budget_tokens accepted")
        except ValueError:
            pass

    print("spec selftest ok")
