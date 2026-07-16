"""In-memory Storage TEST DOUBLE -- SGPE's own copy (`lie/storage_double.py`
and every sibling component's equivalent). NOT the real Storage component:
a blob store standing in for SGPE's single-writer durable path (SGPE/01 §8
"all durable writes go through Storage," Law 3). SGPE ships its own copy
rather than importing another component's (zero-seam rule beats DRY, the
same discipline every sibling's own storage_double.py docstring states).

Same commit-or-reject shape as `lie/storage_double.py`: `write()` returns
"committed" or "rejected" as an ordinary Storage ANSWER, never an
exception."""


class StorageDouble:
    def __init__(self):
        self._blobs = {}
        self._reject_once = set()  # keys whose next write() outcome is "rejected"

    def script_reject(self, key):
        """Script the NEXT write() to `key` to return "rejected" instead of
        committing. One-shot: consumed by the next write."""
        self._reject_once.add(key)

    def write(self, key, data):
        if not isinstance(data, bytes):
            raise TypeError("storage.write_wants_bytes")
        if key in self._reject_once:
            self._reject_once.discard(key)
            return "rejected"
        self._blobs[key] = data
        return "committed"

    def read(self, key):
        if key not in self._blobs:
            raise KeyError(key)
        return self._blobs[key]

    def exists(self, key):
        return key in self._blobs


if __name__ == "__main__":
    store = StorageDouble()

    assert store.write("sgpe/catalog/1", b"v1") == "committed"
    assert store.read("sgpe/catalog/1") == b"v1"
    assert store.exists("sgpe/catalog/1")
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

    store.script_reject("sgpe/catalog/2")
    assert store.write("sgpe/catalog/2", b"v2") == "rejected"
    assert not store.exists("sgpe/catalog/2")
    assert store.write("sgpe/catalog/2", b"v2b") == "committed"  # one-shot: next write commits
    assert store.read("sgpe/catalog/2") == b"v2b"

    print("storage_double selftest ok")
