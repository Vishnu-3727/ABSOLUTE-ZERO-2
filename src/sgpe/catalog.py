"""SGPE Policy Store — the catalog (SGPE/01 §5, §8). The Store's single
append-only index: every append (document version, vocabulary version,
deprecation marker, manifest, activation fact) advances a monotonic
catalog position (same discipline as LIE's Ledger position). The catalog
is the sole serialization point (SGPE/01 §8) -- durable-write-then-
position, mirroring `lie/ledger.py`'s ordering exactly."""
from dataclasses import dataclass
import json

ENTRY_KINDS = ("document_version", "vocabulary_version", "deprecation", "manifest", "activation")


class CatalogRefusal(Exception):
    """Base for catalog.py refusals."""


class UnknownEntryKindError(CatalogRefusal):
    """append() was asked to record an entry kind outside the Store's
    closed catalog-entry vocabulary."""


class CatalogAppendRejectedError(CatalogRefusal):
    """The Storage double reported "rejected" for this append -- an
    ordinary Storage answer, not a connectivity failure; propagated so the
    catalog stays uncorrupted and gains no position for the failed write."""


@dataclass(frozen=True)
class CatalogEntry:
    position: int
    kind: str
    payload: object       # the typed record (PolicyDocument/Vocabulary/etc.), kept for in-memory reads
    canonical_dict: dict  # the exact dict written to Storage -- the replay anchor (PS-5)


class Catalog:
    def __init__(self, storage):
        self._storage = storage
        self._entries = []

    def append(self, kind, payload, payload_to_dict):
        if kind not in ENTRY_KINDS:
            raise UnknownEntryKindError("catalog.unknown_entry_kind:" + repr(kind))
        position = len(self._entries) + 1
        canonical_dict = {"position": position, "kind": kind, "payload": payload_to_dict(payload)}
        data = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode()
        key = "sgpe/catalog/" + str(position)
        outcome = self._storage.write(key, data)
        if outcome == "rejected":
            raise CatalogAppendRejectedError("catalog.append_rejected:" + str(position))
        if outcome != "committed":
            raise CatalogRefusal("catalog.unknown_storage_outcome:" + repr(outcome))
        entry = CatalogEntry(position=position, kind=kind, payload=payload, canonical_dict=canonical_dict)
        self._entries.append(entry)
        return entry

    # -- position-stamped reads (SGPE/01 §5, PS-9) --------------------------

    def all(self):
        return tuple(self._entries)

    def by_position(self, position):
        if position < 1 or position > len(self._entries):
            return None
        return self._entries[position - 1]

    def as_of(self, position, kind=None):
        """Deterministic: identical (kind, position) -> identical result,
        byte-for-byte (PS-9). Entries are naturally position-ordered
        (append-only), so this is a plain prefix filter."""
        return tuple(e for e in self._entries if e.position <= position and (kind is None or e.kind == kind))

    def current_position(self):
        return len(self._entries)


if __name__ == "__main__":
    from .storage_double import StorageDouble

    cat = Catalog(StorageDouble())
    assert cat.current_position() == 0

    e1 = cat.append("document_version", {"x": 1}, lambda p: p)
    e2 = cat.append("manifest", {"y": 2}, lambda p: p)
    assert e1.position == 1
    assert e2.position == 2
    assert cat.current_position() == 2

    assert cat.by_position(1) == e1
    assert cat.by_position(99) is None
    assert cat.all() == (e1, e2)

    # position-stamped, deterministic reads (PS-9)
    r1 = cat.as_of(1)
    r2 = cat.as_of(1)
    assert r1 == r2 == (e1,)
    assert cat.as_of(2, kind="manifest") == (e2,)
    assert cat.as_of(2, kind="document_version") == (e1,)

    # unknown entry kind refused
    try:
        cat.append("mystery", {}, lambda p: p)
        raise SystemExit("unknown entry kind accepted")
    except UnknownEntryKindError:
        pass
    assert cat.current_position() == 2  # refused attempt left the catalog untouched

    # storage rejection gets no position
    storage2 = StorageDouble()
    storage2.script_reject("sgpe/catalog/1")
    cat2 = Catalog(storage2)
    try:
        cat2.append("document_version", {"z": 1}, lambda p: p)
        raise SystemExit("storage-rejected append accepted")
    except CatalogAppendRejectedError:
        pass
    assert cat2.current_position() == 0

    # no update/delete/edit API exists at all
    assert not hasattr(cat, "update")
    assert not hasattr(cat, "delete")
    assert not hasattr(cat, "edit")
    assert not hasattr(cat, "remove")

    print("catalog selftest ok")
