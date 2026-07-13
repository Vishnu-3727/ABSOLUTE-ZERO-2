"""Index persistence THROUGH Storage — Law 3: UMS never writes disk itself.

Body = canonical JSON of {inventory, freshness}; the envelope wraps it with
a sha256 checksum. load_index() verifies the checksum and structure; any
mismatch or malformed byte stream raises IndexCorruptionError — loud, never
garbage. The caller then marks the repo's regions rebuild-needed and
recovers via a freshness hash sweep (freshness.py).
"""
import hashlib
import json
from dataclasses import asdict

from .inventory import FileRecord


class IndexCorruptionError(Exception):
    """Persisted index failed integrity check; region needs rebuild."""


def index_key(repo_id):
    return "ums/index/" + repo_id


def save_json(storage, key, obj):
    """Checksummed canonical-JSON blob write (any json-able object)."""
    body = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    envelope = json.dumps(
        {"checksum": hashlib.sha256(body.encode()).hexdigest(), "body": body},
        sort_keys=True, separators=(",", ":"))
    storage.write(key, envelope.encode())


def load_json(storage, key):
    """Verified blob read; corruption raises IndexCorruptionError, loud."""
    raw = storage.read(key)
    try:
        envelope = json.loads(raw)
        checksum, body = envelope["checksum"], envelope["body"]
        if hashlib.sha256(body.encode()).hexdigest() != checksum:
            raise IndexCorruptionError("index.checksum_mismatch:" + key)
        return json.loads(body)
    except IndexCorruptionError:
        raise
    except Exception as exc:  # malformed json / missing keys
        raise IndexCorruptionError("index.unreadable:" + key) from exc


def save_index(storage, repo_id, inventory, freshness_map):
    """Serialize inventory + freshness map to Storage. Single write, canonical."""
    save_json(storage, index_key(repo_id),
              {"inventory": {p: asdict(r) for p, r in inventory.items()},
               "freshness": freshness_map})


def load_index(storage, repo_id):
    """Load and verify. Returns (inventory, freshness_map) or raises loud."""
    data = load_json(storage, index_key(repo_id))
    try:
        inventory = {p: FileRecord(**fields) for p, fields in data["inventory"].items()}
        freshness_map = data["freshness"]
    except Exception as exc:  # missing keys / bad records
        raise IndexCorruptionError("index.unreadable:" + repo_id) from exc
    return inventory, freshness_map


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from ums.inventory import canonical
    from ums.storage_double import StorageDouble

    inv = {"a.py": FileRecord("a.py", 6, 123, "aa" * 32),
           "pkg/b.py": FileRecord("pkg/b.py", 7, 456, "bb" * 32)}
    fresh = {"a.py": "fresh", "pkg/b.py": "stale"}

    store = StorageDouble()
    save_index(store, "r1", inv, fresh)
    inv2, fresh2 = load_index(store, "r1")
    assert canonical(inv2) == canonical(inv)  # round-trip determinism
    assert fresh2 == fresh
    save_index(store, "r1", inv2, fresh2)  # save-of-loaded is byte-identical
    assert store.read(index_key("r1")) == store.read(index_key("r1"))

    # checksum corruption -> loud
    blob = store.read(index_key("r1"))
    store.write(index_key("r1"), blob.replace(b"a.py", b"z.py", 1))
    try:
        load_index(store, "r1")
        raise SystemExit("corrupt index loaded silently")
    except IndexCorruptionError:
        pass

    # garbage bytes -> loud
    store.write(index_key("r1"), b"\x00not json")
    try:
        load_index(store, "r1")
        raise SystemExit("garbage index loaded silently")
    except IndexCorruptionError:
        pass

    # missing index is a KeyError (absence), not corruption
    try:
        load_index(store, "never_saved")
        raise SystemExit("missing index loaded")
    except KeyError:
        pass
    print("persistence selftest ok")
