"""LIE Curation Overlay store (LIE/01 §2, LIE/03 §2, LIE/04 §6 Curator
"Guarantees: overlay position advances monotonically"). Append-only store
for `Annotation` records (curation.py): rulings reference target ledger
records by identity, never mutate them. Structurally mirrors
`ExperienceLedger` (ledger.py) -- same append-then-position discipline
through the Storage double, same absence of any update/delete/edit method
-- because the curation overlay is append-only for exactly the reason the
Ledger is (LIE/01 §2: "annotations are never edited, only followed by
newer annotations").

Phase 1 leaves the overlay open to any caller (unlike the Ledger's
Gate-only `AdmissionReceipt` gate) because Curator rulings are, by LIE/04
§6, "deliberate governance acts" with no single named entry-point
component built yet in this phase -- `contracts.CuratorPort` is the seam a
later phase's real Curator implements against; this store only needs to
hold what it is given, append-only, forever."""
from dataclasses import dataclass
import json

from .curation import Annotation, to_dict as annotation_to_dict


class OverlayRefusal(Exception):
    """Base for overlay.py refusals."""


class OverlayAppendRejectedError(OverlayRefusal):
    """The Storage double reported "rejected" for this append -- an
    ordinary Storage answer, not a connectivity failure."""


class MalformedOverlayAppendError(OverlayRefusal):
    """append() was handed something other than a built Annotation."""


@dataclass(frozen=True)
class OverlayEntry:
    position: int
    annotation: Annotation


class CurationOverlay:
    def __init__(self, storage):
        self._storage = storage
        self._entries = []  # list of OverlayEntry, in overlay position order

    def append(self, annotation):
        if not isinstance(annotation, Annotation):
            raise MalformedOverlayAppendError("overlay.append_target_not_built:" + repr(annotation))
        position = len(self._entries) + 1
        key = "lie/overlay/" + str(position)
        data = json.dumps(annotation_to_dict(annotation), sort_keys=True, separators=(",", ":")).encode()
        outcome = self._storage.write(key, data)
        if outcome == "rejected":
            raise OverlayAppendRejectedError("overlay.append_rejected:position=" + str(position))
        if outcome != "committed":
            raise OverlayRefusal("overlay.unknown_storage_outcome:" + repr(outcome))
        entry = OverlayEntry(position=position, annotation=annotation)
        self._entries.append(entry)
        return entry

    # -- read/serve API; no write path other than append() above.

    def all(self):
        return tuple(self._entries)

    def by_position(self, position):
        if position < 1 or position > len(self._entries):
            return None
        return self._entries[position - 1]

    def by_target(self, target_id):
        """All annotations, in overlay-position order, that reference
        `target_id` among their target_ids -- the read path a Distillery
        or Advisory Interface would use to weigh a ledger record without
        the overlay ever mutating that record."""
        return tuple(e for e in self._entries if target_id in e.annotation.target_ids)

    def current_position(self):
        return len(self._entries)


if __name__ == "__main__":
    from . import curation as curation_mod
    from .storage_double import StorageDouble

    storage = StorageDouble()
    overlay = CurationOverlay(storage)
    assert overlay.current_position() == 0

    ann1 = curation_mod.build_annotation("supersession", ("episode:e1",), "re-attempted, better evidence",
                                          ("episode:e2",))
    entry1 = overlay.append(ann1)
    assert entry1.position == 1
    assert overlay.current_position() == 1

    ann2 = curation_mod.build_annotation("deprecation", ("episode:e3",), "stale approach", ("episode:e4",))
    entry2 = overlay.append(ann2)
    assert entry2.position == 2

    # monotonic positions, read/serve API
    assert overlay.by_position(1) == entry1
    assert overlay.by_position(2) == entry2
    assert overlay.by_position(99) is None
    assert overlay.all() == (entry1, entry2)
    assert overlay.by_target("episode:e1") == (entry1,)
    assert overlay.by_target("episode:nope") == ()

    # no update/delete/edit API exists at all -- append-only overlay (LIE/01 §2)
    assert not hasattr(overlay, "update")
    assert not hasattr(overlay, "delete")
    assert not hasattr(overlay, "edit")
    assert not hasattr(overlay, "remove")

    # a bare (unbuilt) annotation is refused
    try:
        overlay.append({"kind": "deprecation"})
        raise SystemExit("unbuilt annotation accepted")
    except MalformedOverlayAppendError:
        pass

    # storage rejection never gets a position
    storage.script_reject("lie/overlay/3")
    try:
        overlay.append(curation_mod.build_annotation("deprecation", ("episode:e5",), "r", ("episode:e6",)))
        raise SystemExit("storage-rejected overlay append accepted")
    except OverlayAppendRejectedError:
        pass
    assert overlay.current_position() == 2

    print("overlay selftest ok")
