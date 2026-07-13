"""In-memory Storage TEST DOUBLE (kernel bus.py pattern).

NOT the real Storage component — a stand-in until Storage exists. Two
duties Phase 1 needs, per COMPONENTS/memory.md Dependencies ("persists
index files and reads repository bytes on Repository Memory's behalf"):

- blob store for index persistence: write(key)/read(key)/exists(key);
  in-memory by default, optionally dir-backed for restart-style tests.
- read_bytes(path): repository file-byte reads — filesystem pass-through
  here; the real Storage will own this seam.

Failure injection mirrors Bus.fail_publishes. bytes_read_calls lets tests
assert the token law (unchanged content is never re-read).
"""
import os


class StorageDouble:
    def __init__(self, dir_path=None):
        self._blobs = {}
        self.dir_path = dir_path
        self.fail_writes = False
        self.fail_reads = False
        self.bytes_read_calls = 0

    # -- index blob store ------------------------------------------------
    def _key_path(self, key):
        # ponytail: flat filename mangling, fine for a test double
        return os.path.join(self.dir_path, key.replace("/", "_"))

    def write(self, key, data):
        if self.fail_writes:
            raise ConnectionError("storage.unavailable")
        if not isinstance(data, bytes):
            raise TypeError("storage.write_wants_bytes")
        if self.dir_path is not None:
            with open(self._key_path(key), "wb") as handle:
                handle.write(data)
        else:
            self._blobs[key] = data

    def read(self, key):
        if self.fail_reads:
            raise ConnectionError("storage.unavailable")
        if self.dir_path is not None:
            path = self._key_path(key)
            if not os.path.exists(path):
                raise KeyError(key)
            with open(path, "rb") as handle:
                return handle.read()
        if key not in self._blobs:
            raise KeyError(key)
        return self._blobs[key]

    def exists(self, key):
        if self.dir_path is not None:
            return os.path.exists(self._key_path(key))
        return key in self._blobs

    # -- repository byte reads --------------------------------------------
    def read_bytes(self, path):
        """Repo file bytes on UMS's behalf (memory.md Dependencies)."""
        if self.fail_reads:
            raise ConnectionError("storage.unavailable")
        self.bytes_read_calls += 1
        with open(path, "rb") as handle:
            return handle.read()


if __name__ == "__main__":
    import tempfile

    store = StorageDouble()
    store.write("k", b"v1")
    assert store.read("k") == b"v1" and store.exists("k")
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

    with tempfile.TemporaryDirectory() as tmp:
        disk = StorageDouble(dir_path=tmp)
        disk.write("ums/index/r1", b"blob")
        # "restart": a fresh double over the same directory sees the blob
        disk2 = StorageDouble(dir_path=tmp)
        assert disk2.read("ums/index/r1") == b"blob"
        assert disk2.exists("ums/index/r1")

        src = os.path.join(tmp, "f.txt")
        with open(src, "wb") as handle:
            handle.write(b"repo bytes")
        assert disk.read_bytes(src) == b"repo bytes"
        assert disk.bytes_read_calls == 1
    print("storage_double selftest ok")
