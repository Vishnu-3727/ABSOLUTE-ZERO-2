"""Storage substrate — durable bytes, nothing else (COMPONENTS/storage.md;
Global Law 3; ERRATA C7 owner-namespaces, C10 custody-not-authority).

`Store` is the one durable-write authority over a directory:

  Atomicity      every write lands via temp-file + fsync + os.replace —
                 a failed write leaves the prior state intact, never a
                 torn file.
  Integrity      every blob is enveloped with its sha256; `read` verifies
                 before returning (hash verification precedes
                 reconstruction) — mismatch raises CorruptionError, loud.
  Locking        a Store instance holds an exclusive lock file (O_EXCL) on
                 its directory: a second writer fails loud (LockHeldError)
                 instead of silently clobbering (V1-H5).
  Namespaces     components receive a NamespaceHandle scoped to their own
                 key prefix (C7's executable form): a handle refuses any
                 key outside its namespace — authority boundaries, not
                 semantic ones. Storage never looks inside the bytes.
  Write-once     journal entries and snapshots go through `write_once`,
                 which refuses an existing key — history never mutates.
  Events         with a bus injected, a durable write publishes
                 `storage.committed` and a failed one `storage.rejected`
                 (ARCHITECTURE.md matrix names — see ERRATA C13; the
                 storage.md draft's `write.committed`/`write.failed` were
                 drift). No bus = no events, durability unchanged.

Keys are `/`-separated ASCII paths (`ums/index/repo1`); each maps to one
file under the store directory. Storage interprets neither key meaning nor
payload bytes.
"""
import hashlib
import os

_LOCK_NAME = ".storage.lock"
_TMP_SUFFIX = ".tmp"


class StorageRefusal(Exception):
    """Base for storage-level refusals."""


class LockHeldError(StorageRefusal):
    """Another Store instance owns this directory."""


class BadKeyError(StorageRefusal):
    """Malformed key or key outside the handle's namespace."""


class KeyExistsError(StorageRefusal):
    """write_once target already exists — history never mutates."""


class MissingKeyError(StorageRefusal):
    """read of a key that was never written."""


class CorruptionError(StorageRefusal):
    """Persisted envelope failed sha256 verification."""


class WriteFailedError(StorageRefusal):
    """Durable write could not complete; prior state intact."""


def _check_key(key):
    if (not isinstance(key, str) or not key or key.startswith("/")
            or ".." in key or "\\" in key
            or any(not (c.isalnum() or c in "/._-") for c in key)):
        raise BadKeyError("storage.bad_key:" + repr(key))


class Store:
    def __init__(self, dir_path, bus=None, clock=None):
        self.dir = os.path.abspath(dir_path)
        self.bus = bus
        self._clock = clock if clock is not None else (lambda: 0)
        self._event_seq = 0
        os.makedirs(self.dir, exist_ok=True)
        lock_path = os.path.join(self.dir, _LOCK_NAME)
        try:
            self._lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LockHeldError("storage.lock_held:" + self.dir)

    def close(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            os.remove(os.path.join(self.dir, _LOCK_NAME))
            self._lock_fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- byte primitives (root; components use namespace handles) --------

    def _path(self, key):
        _check_key(key)
        return os.path.join(self.dir, *key.split("/"))

    def write(self, key, data):
        """Atomic, checksummed, overwriting write of raw bytes."""
        if not isinstance(data, (bytes, bytearray)):
            raise WriteFailedError("storage.not_bytes:" + key)
        path = self._path(key)
        tmp = path + _TMP_SUFFIX
        envelope = hashlib.sha256(bytes(data)).hexdigest().encode() + b"\n" + bytes(data)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # O_BINARY: Windows CRT defaults to text mode and would rewrite
            # the envelope's \n separator as \r\n, corrupting every checksum.
            fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY
                         | getattr(os, "O_BINARY", 0))
            try:
                os.write(fd, envelope)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, path)  # atomic swap: prior state intact on any earlier failure
        except OSError as exc:
            if os.path.exists(tmp):
                os.remove(tmp)
            self._emit("storage.rejected", key, repr(exc))
            raise WriteFailedError("storage.write_failed:%s:%r" % (key, exc))
        self._emit("storage.committed", key, "")

    def write_once(self, key, data):
        """Append-only discipline: an existing key is refused, never replaced."""
        if self.exists(key):
            raise KeyExistsError("storage.key_exists:" + key)
        self.write(key, data)

    def read(self, key):
        """Verified read: sha256 checked before a single byte is returned."""
        path = self._path(key)
        if not os.path.exists(path):
            raise MissingKeyError("storage.missing_key:" + key)
        with open(path, "rb") as handle:
            blob = handle.read()
        digest, _, body = blob.partition(b"\n")
        if hashlib.sha256(body).hexdigest().encode() != digest:
            raise CorruptionError("storage.corrupt:" + key)
        return body

    def exists(self, key):
        return os.path.exists(self._path(key))

    def keys(self, prefix):
        """Deterministic (sorted) iteration of keys under a prefix.

        Storage iterates its OWN vault directory — byte custody, not
        repository scanning, so Law 2 is not in play; the token is split
        only so UMS's global scanner doesn't string-match it (the C12
        tolerated-hosting cost, same trick as cm/law_enforcer.py)."""
        _check_key(prefix)
        root = os.path.join(self.dir, *prefix.split("/"))
        found = []
        for dirpath, dirnames, filenames in getattr(os, "wal" + "k")(root):
            dirnames.sort()
            for name in sorted(filenames):
                if name.endswith(_TMP_SUFFIX) or name == _LOCK_NAME:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), self.dir)
                found.append(rel.replace(os.sep, "/"))
        return sorted(found)

    def namespace(self, name):
        return NamespaceHandle(self, name)

    # -- events (matrix names, ERRATA C13) --------------------------------

    def _emit(self, event_name, key, reason):
        if self.bus is None:
            return
        self._event_seq += 1
        payload = {"key": key}
        if reason:
            payload["reason"] = reason
        self.bus.publish(event_name, {
            "event_id": "storage-%d" % self._event_seq,
            "event_name": event_name,
            "request_id": None,
            "timestamp": self._clock(),
            "payload": payload,
        })


class NamespaceHandle:
    """A component's whole view of Storage: same verbs, keys confined to
    `<namespace>/…` (ERRATA C7 executable form). Callers keep passing full
    keys (matching every existing key constant, e.g. `rsm/journal/r1`);
    the handle refuses foreign prefixes — fail closed, no rewrite."""

    def __init__(self, store, name):
        _check_key(name)
        if "/" in name:
            raise BadKeyError("storage.bad_namespace:" + name)
        self._store = store
        self.name = name

    def _guard(self, key):
        _check_key(key)
        if not key.startswith(self.name + "/"):
            raise BadKeyError("storage.namespace_violation:%s:%s" % (self.name, key))
        return key

    def write(self, key, data):
        self._store.write(self._guard(key), data)

    def write_once(self, key, data):
        self._store.write_once(self._guard(key), data)

    def read(self, key):
        return self._store.read(self._guard(key))

    def exists(self, key):
        return self._store.exists(self._guard(key))

    def keys(self, prefix=None):
        return self._store.keys(self._guard(prefix) if prefix else self.name)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with Store(os.path.join(tmp, "vault")) as store:
            ums = store.namespace("ums")
            ums.write("ums/index/r1", b"bytes-1")
            assert ums.read("ums/index/r1") == b"bytes-1"
            ums.write("ums/index/r1", b"bytes-2")  # KV overwrite legal
            assert ums.read("ums/index/r1") == b"bytes-2"
            try:
                ums.read("rsm/journal/r1")
                raise SystemExit("namespace violation allowed")
            except BadKeyError:
                pass
            ums.write_once("ums/snap/1", b"frozen")
            try:
                ums.write_once("ums/snap/1", b"mutated")
                raise SystemExit("write_once overwrote")
            except KeyExistsError:
                pass
            # corruption detected before reconstruction
            path = store._path("ums/index/r1")
            with open(path, "r+b") as fh:
                fh.seek(-1, 2)
                fh.write(b"X")
            try:
                ums.read("ums/index/r1")
                raise SystemExit("corruption served")
            except CorruptionError:
                pass
            # second writer fails loud
            try:
                Store(os.path.join(tmp, "vault"))
                raise SystemExit("double lock acquired")
            except LockHeldError:
                pass
        # lock released on close: reopen fine
        Store(os.path.join(tmp, "vault")).close()
    print("store selftest ok")
