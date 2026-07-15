"""In-memory Storage TEST DOUBLE — VAE's own copy (`ro/storage_double.py`,
`ums`/`prt`/`cm` equivalents). NOT the real Storage component: a blob store
standing in for VAE's single-writer durable path (evidence records, verdict
content — VAE-I11). VAE ships its own copy rather than importing another
component's (zero-seam rule, VAE/06 "Global laws" table).

Beyond the plain commit-or-raise shape of the sibling doubles, this one can
script a `storage.rejected` OUTCOME (not a transport exception) on a
per-key basis: VAE/04 §5.2's persistence-rejection path (VAE-O6) is an
ordinary Storage answer — "your write was refused" — not a connectivity
failure, and Phase 4's choreography (no verdict published, `fault.recorded`
emitted instead) needs to react to that answer, not catch an exception."""


class StorageDouble:
    def __init__(self):
        self._blobs = {}
        self._reject_once = set()  # keys whose next write() outcome is "rejected"

    def script_reject(self, key):
        """Script the NEXT write() to `key` to return "rejected" instead of
        committing (VAE-O6 path). One-shot: consumed by the next write."""
        self._reject_once.add(key)

    def write(self, key, data):
        """Returns "committed" or "rejected" (VAE/04 §7.2's
        storage.committed/storage.rejected outcomes) — never raises for a
        scripted rejection, since rejection is an ordinary Storage answer,
        not a communication failure."""
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

    assert store.write("vae/ev/a1", b"v1") == "committed"
    assert store.read("vae/ev/a1") == b"v1"
    assert store.exists("vae/ev/a1")
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

    # scripted rejection (VAE-O6): outcome, not an exception; data not stored
    store.script_reject("vae/ev/a2")
    assert store.write("vae/ev/a2", b"v2") == "rejected"
    assert not store.exists("vae/ev/a2")

    # one-shot: the next write to the same key commits normally
    assert store.write("vae/ev/a2", b"v2b") == "committed"
    assert store.read("vae/ev/a2") == b"v2b"

    print("storage_double selftest ok")
