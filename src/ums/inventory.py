"""Per-file identity: path, sha256 content hash, size, mtime.

Directory walking (repository scanning) lives here — UMS's exclusive job
under Law 2. File BYTES are read only through the Storage interface
(storage.read_bytes), per COMPONENTS/memory.md Dependencies. Token law:
rescan() hashes a file only when mtime or size changed (prefilter);
unchanged files cost a stat, never a read.

mtime is stored as st_mtime_ns (int) so canonical form has no float drift.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FileRecord:
    path: str          # posix-style, relative to repo root
    size: int
    mtime_ns: int
    content_hash: str  # sha256 hex of file bytes


def _walk(repo_root):
    """Yield (rel_posix_path, abs_path) for every file, sorted, .git skipped."""
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
            yield rel, abs_path


def scan(repo_root, storage):
    """Full inventory build: stat and hash every file. Returns {path: FileRecord}."""
    inventory = {}
    for rel, abs_path in _walk(repo_root):
        stat = os.stat(abs_path)
        digest = hashlib.sha256(storage.read_bytes(abs_path)).hexdigest()
        inventory[rel] = FileRecord(rel, stat.st_size, stat.st_mtime_ns, digest)
    return inventory


def rescan(repo_root, storage, previous):
    """Incremental inventory against `previous`. Returns (inventory, changed).

    changed = added + content-changed + removed paths, sorted. mtime+size
    prefilter: only files where either differs get read and hashed; a hash
    that comes back identical (touch without edit) is not reported changed.
    """
    inventory = {}
    changed = []
    for rel, abs_path in _walk(repo_root):
        stat = os.stat(abs_path)
        prev = previous.get(rel)
        if prev is not None and prev.size == stat.st_size and prev.mtime_ns == stat.st_mtime_ns:
            inventory[rel] = prev  # prefilter hit: no byte read, no hash
            continue
        digest = hashlib.sha256(storage.read_bytes(abs_path)).hexdigest()
        inventory[rel] = FileRecord(rel, stat.st_size, stat.st_mtime_ns, digest)
        if prev is None or prev.content_hash != digest:
            changed.append(rel)
    changed.extend(path for path in previous if path not in inventory)
    return inventory, sorted(changed)


def canonical(inventory):
    """Deterministic byte form of an inventory (round-trip comparison)."""
    return json.dumps({path: asdict(rec) for path, rec in inventory.items()},
                      sort_keys=True, separators=(",", ":")).encode()


if __name__ == "__main__":
    import tempfile

    from storage_double import StorageDouble

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "pkg"))
        for rel, content in (("a.py", b"a = 1\n"), ("pkg/b.py", b"b = 2\n")):
            with open(os.path.join(tmp, rel), "wb") as handle:
                handle.write(content)

        store = StorageDouble()
        inv = scan(tmp, store)
        assert sorted(inv) == ["a.py", "pkg/b.py"]
        assert store.bytes_read_calls == 2
        assert canonical(inv) == canonical(dict(reversed(list(inv.items()))))

        # unchanged rescan: zero byte reads, zero changes (token law)
        inv2, changed = rescan(tmp, store, inv)
        assert changed == [] and store.bytes_read_calls == 2
        assert canonical(inv2) == canonical(inv)

        # mutate one file (different size defeats mtime granularity issues)
        with open(os.path.join(tmp, "pkg/b.py"), "wb") as handle:
            handle.write(b"b = 22  # changed\n")
        inv3, changed = rescan(tmp, store, inv)
        assert changed == ["pkg/b.py"]
        assert store.bytes_read_calls == 3  # only the mutated file re-read
        assert inv3["a.py"] is inv["a.py"]  # unchanged record reused

        # removed file reported
        os.remove(os.path.join(tmp, "a.py"))
        inv4, changed = rescan(tmp, store, inv3)
        assert changed == ["a.py"] and "a.py" not in inv4
    print("inventory selftest ok")
