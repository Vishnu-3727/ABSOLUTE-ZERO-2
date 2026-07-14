"""In-memory Storage TEST DOUBLE — PRT's own copy (ums/storage_double.py
pattern). NOT the real Storage component: a blob store standing in for
"registry snapshot persist/load" (PRT/00 C6: persistence via Storage only,
PRT never writes disk itself).

Phase 1 needs exactly the round-trip: write(key, bytes) / read(key) /
exists(key), plus failure injection (`fail_writes`/`fail_reads`) so a
future caller can exercise PRT/02 §9's "publication failure = no version
minted" path — a mutation that tries to persist-before-commit and gets a
ConnectionError must leave the registry's version and content untouched.

# ponytail: registry.py in this phase does NOT wire apply() through this
# double — Phase 1 scope is the registry's own in-memory admission model
# (PRT/01 §9), and persistence-gated version minting is a Phase 2 concern
# (registration is where "publication" first becomes a durable-write
# question, PRT/02 §7). This module ships now with only its own round-trip
# selftest; wiring registry.apply() to persist-before-commit through it,
# and asserting no-version-mint-on-refusal end to end, is deferred to
# Phase 2's admission pipeline, which is the actual owner of "publication."
"""


class StorageDouble:
    def __init__(self):
        self._blobs = {}
        self.fail_writes = False
        self.fail_reads = False

    def write(self, key, data):
        if self.fail_writes:
            raise ConnectionError("storage.unavailable")
        if not isinstance(data, bytes):
            raise TypeError("storage.write_wants_bytes")
        self._blobs[key] = data

    def read(self, key):
        if self.fail_reads:
            raise ConnectionError("storage.unavailable")
        if key not in self._blobs:
            raise KeyError(key)
        return self._blobs[key]

    def exists(self, key):
        return key in self._blobs


if __name__ == "__main__":
    store = StorageDouble()
    store.write("prt/registry/snapshot", b"v1")
    assert store.read("prt/registry/snapshot") == b"v1"
    assert store.exists("prt/registry/snapshot")
    assert not store.exists("missing")
    try:
        store.read("missing")
        raise SystemExit("read of missing key succeeded")
    except KeyError:
        pass
    try:
        store.write("k", "not bytes")
        raise SystemExit("non-bytes write accepted")
    except TypeError:
        pass

    store.fail_writes = True
    try:
        store.write("k", b"x")
        raise SystemExit("write should have raised")
    except ConnectionError:
        pass
    store.fail_writes = False

    store.fail_reads = True
    try:
        store.read("prt/registry/snapshot")
        raise SystemExit("read should have raised")
    except ConnectionError:
        pass
    store.fail_reads = False

    print("storage_double selftest ok")
