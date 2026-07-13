"""Ephemeral Request-Memory registry (blueprint Phase 5): the cache half of
`update flow`: `index.updated{paths}` -> cache scan for path overlap ->
invalidate -> on next demand, rebuild. This module is only the registry --
get/put/invalidate on a key -- and knows nothing about how an artifact was
assembled or how invalidation is decided (`freshness.py` owns both of
those); keeping caching independent from assembly means `cache.py` never
imports `assembler`.

Keyed by `(request_id, spec_hash)` -- deterministic (`spec.spec_hash` is
itself deterministic, CM-I2) so the same request replayed against the same
spec always lands the same cache slot. Never persisted (CM-I4): this is a
plain in-memory dict, gone when the process is gone, same ephemerality as
Request Memory itself.

Correctness over reuse: `get()` returns `None` the instant an entry is
invalidated -- there is no "serve slightly stale while rebuilding" path,
because CM-I5 forbids hiding staleness. `peek()` is the one exception,
used only by `freshness.py` to inspect (not serve) an artifact while
deciding whether it overlaps a change set, including artifacts already
invalidated (so a second overlapping `index.updated` is a safe no-op).
"""


def key(request_id, spec_h):
    """Deterministic cache key -- CM-I2: identical (request_id, spec_hash)
    always maps to the same slot."""
    return (request_id, spec_h)


class Cache:
    def __init__(self):
        self._entries = {}  # key -> {"artifact": RequestMemory, "invalidated": bool}

    def get(self, cache_key):
        """Return the cached artifact, or None if absent or invalidated
        (stale is never served, CM-I5)."""
        entry = self._entries.get(cache_key)
        if entry is None or entry["invalidated"]:
            return None
        return entry["artifact"]

    def put(self, cache_key, artifact):
        """Cache (or replace) an artifact for `cache_key`, fresh (not
        invalidated)."""
        self._entries[cache_key] = {"artifact": artifact, "invalidated": False}

    def invalidate(self, cache_key):
        """Mark an entry invalidated. Returns True the first time (state
        actually changed), False if already invalidated or absent --
        idempotent, so replaying the same `index.updated` twice is safe."""
        entry = self._entries.get(cache_key)
        if entry is None or entry["invalidated"]:
            return False
        entry["invalidated"] = True
        return True

    def peek(self, cache_key):
        """Return the cached artifact regardless of invalidation state, or
        None if absent. For freshness.py's overlap scan only -- never for
        serving a request."""
        entry = self._entries.get(cache_key)
        return entry["artifact"] if entry is not None else None

    def is_invalidated(self, cache_key):
        entry = self._entries.get(cache_key)
        return entry is not None and entry["invalidated"]

    def keys(self):
        """Snapshot of cached keys (stable list, safe to iterate while the
        caller mutates the cache)."""
        return list(self._entries)


if __name__ == "__main__":
    cache = Cache()
    k1 = key("r1", "hash-a")
    k2 = key("r1", "hash-b")

    # deterministic key
    assert key("r1", "hash-a") == k1

    # miss
    assert cache.get(k1) is None
    assert cache.peek(k1) is None

    cache.put(k1, "artifact-1")
    cache.put(k2, "artifact-2")
    assert cache.get(k1) == "artifact-1"
    assert cache.get(k2) == "artifact-2"
    assert cache.keys() == [k1, k2]

    # invalidate: served-then-gone, never stale
    assert cache.invalidate(k1) is True
    assert cache.get(k1) is None
    assert cache.is_invalidated(k1) is True
    assert cache.peek(k1) == "artifact-1"  # still inspectable, never served

    # unrelated entry untouched
    assert cache.get(k2) == "artifact-2"

    # idempotent invalidate
    assert cache.invalidate(k1) is False

    # invalidating an absent key is a safe no-op
    assert cache.invalidate(("ghost", "h")) is False

    # put after invalidate re-freshens
    cache.put(k1, "artifact-1-rebuilt")
    assert cache.get(k1) == "artifact-1-rebuilt"
    assert cache.is_invalidated(k1) is False

    print("cache selftest ok")
