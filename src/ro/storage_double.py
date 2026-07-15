"""In-memory Storage TEST DOUBLE — RO's own copy (prt/storage_double.py,
ums/storage_double.py pattern). NOT the real Storage component: a blob
store standing in for RO-S3's durable-artifact coordinates (descriptor-
space versions, schemas, decision/outcome records, priors artifacts).
RO ships its own copy rather than importing another component's (zero-seam
rule, RO-S8 — see bus_double.py's docstring for the same reasoning)."""


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
    store.write("ro/x", b"v1")
    assert store.read("ro/x") == b"v1"
    assert store.exists("ro/x")
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
        store.read("ro/x")
        raise SystemExit("read should have raised")
    except ConnectionError:
        pass
    store.fail_reads = False

    print("storage_double selftest ok")
