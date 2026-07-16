"""LIE Experience Ledger (LIE/00 §4.2, LIE/03 §2, LIE/04 §6 Ledger
contract). The append-only system of record for the experience layer:

- **Required:** append-only record store with monotonic Ledger Position;
  serve reads.
- **Forbidden:** update or delete of any record; any content
  transformation; any logic beyond append and serve.

Structural enforcement, not convention:

- **INV-2 (immutable experience).** There is no edit/remove/update method
  on this class at all -- the same "absence of a mutating method IS the
  enforcement" discipline `evidence.py` and `vocabulary.py` already use.
- **INV-1 (single door).** `append()` requires an `AdmissionReceipt`
  (admission_receipt.py), minted only by `AdmissionGate.admit()` once
  provenance and vocabulary checks passed -- a caller cannot durably write
  experience without going through the Gate's checks to obtain one.
- **Durability before position.** `append()` writes through the injected
  Storage double FIRST (content-addressed by the record's own envelope
  identity, mirroring `emission.py`'s persist-then-acknowledge order); a
  Ledger Position is assigned only once that write reports "committed" --
  a record without durable provenance never gets a position (LIE/04 §8:
  "a record without durable provenance must not exist").
- **Identity uniqueness (INV-2's "never reused").** A second append for an
  envelope identity already durable is refused loud
  (`DuplicateIdentityError`) rather than silently re-appended -- the Gate
  is expected to treat this as the redelivery-safe case (OPS-5) and
  answer from the existing entry, never retry the write."""
from dataclasses import dataclass
import json

from .admission_receipt import AdmissionReceipt
from . import decision as decision_mod
from . import episode as episode_mod


class LedgerRefusal(Exception):
    """Base for ledger.py refusals."""


class UnauthorizedAppendError(LedgerRefusal):
    """append() called without a valid AdmissionReceipt -- INV-1's
    structural enforcement: only the Gate's checks produce one."""


class DuplicateIdentityError(LedgerRefusal):
    """append() called for an envelope identity already durable in this
    Ledger -- identities are never reused (INV-2); the Gate is the
    redelivery-safe caller and should answer from the existing entry."""


class LedgerAppendRejectedError(LedgerRefusal):
    """The Storage double reported "rejected" for this append -- an
    ordinary Storage answer (per storage_double.py), not raised as a
    connectivity failure; propagated so the Gate can record a rejection
    and leave the ledger uncorrupted (LIE/04 §8)."""


class UnknownRecordKindError(LedgerRefusal):
    """append() was handed a record that is neither a built Episode nor a
    built Decision -- the Ledger's only two experience-layer record kinds
    (LIE/01 §2)."""


@dataclass(frozen=True)
class LedgerEntry:
    position: int
    record: object  # Episode or Decision


def _canonical_bytes(record):
    if isinstance(record, episode_mod.Episode):
        return json.dumps(episode_mod.to_dict(record), sort_keys=True, separators=(",", ":")).encode()
    if isinstance(record, decision_mod.Decision):
        return json.dumps(decision_mod.to_dict(record), sort_keys=True, separators=(",", ":")).encode()
    raise UnknownRecordKindError("ledger.unknown_record_kind:" + repr(type(record)))


class ExperienceLedger:
    def __init__(self, storage):
        self._storage = storage
        self._entries = []       # list of LedgerEntry, in Ledger Position order
        self._by_identity = {}   # envelope identity -> LedgerEntry

    def append(self, receipt):
        if not isinstance(receipt, AdmissionReceipt):
            raise UnauthorizedAppendError("ledger.append_requires_admission_receipt:" + repr(receipt))
        record = receipt.record
        identity = record.envelope.identity
        if identity in self._by_identity:
            raise DuplicateIdentityError("ledger.duplicate_identity:" + identity)

        key = "lie/ledger/" + identity
        outcome = self._storage.write(key, _canonical_bytes(record))
        if outcome == "rejected":
            raise LedgerAppendRejectedError("ledger.append_rejected:" + identity)
        if outcome != "committed":
            raise LedgerRefusal("ledger.unknown_storage_outcome:" + repr(outcome))

        position = len(self._entries) + 1
        entry = LedgerEntry(position=position, record=record)
        self._entries.append(entry)
        self._by_identity[identity] = entry
        return entry

    # -- read/serve API (LIE/04 §6 Ledger: "serve reads to Distillery,
    # Advisory, Curator") -- no write path other than append() above.

    def all(self):
        return tuple(self._entries)

    def by_position(self, position):
        if position < 1 or position > len(self._entries):
            return None
        return self._entries[position - 1]

    def by_identity(self, identity):
        return self._by_identity.get(identity)

    def current_position(self):
        return len(self._entries)


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .storage_double import StorageDouble

    def _episode(identity, attestation_ref="trace:t1"):
        env = envelope_mod.build_envelope(
            identity,
            envelope_mod.build_attestation(attestation_ref, True, 1),
            envelope_mod.build_origin("asunama", "isaac-sim", None, "epoch-0"),
            ("ros2",), ())
        return episode_mod.build_episode(env, situation={"a": 1}, approach={"b": 1},
                                          outcome={"c": 1}, cost={"d": 1})

    storage = StorageDouble()
    ledger = ExperienceLedger(storage)
    assert ledger.current_position() == 0

    ep1 = _episode("episode:e1")
    entry1 = ledger.append(AdmissionReceipt(ep1))
    assert entry1.position == 1
    assert ledger.current_position() == 1
    assert storage.exists("lie/ledger/episode:e1")

    ep2 = _episode("episode:e2", attestation_ref="trace:t2")
    entry2 = ledger.append(AdmissionReceipt(ep2))
    assert entry2.position == 2

    # monotonic positions, read/serve API
    assert ledger.by_position(1).record.envelope.identity == "episode:e1"
    assert ledger.by_position(2).record.envelope.identity == "episode:e2"
    assert ledger.by_position(99) is None
    assert ledger.by_identity("episode:e1") == entry1
    assert ledger.all() == (entry1, entry2)

    # INV-1: append() without a real AdmissionReceipt is refused loud
    try:
        ledger.append(ep1)
        raise SystemExit("append accepted a bare record, not a receipt")
    except UnauthorizedAppendError:
        pass

    # INV-2: identities are never reused -- a second append for the same
    # identity is refused, never silently re-appended
    try:
        ledger.append(AdmissionReceipt(_episode("episode:e1", attestation_ref="trace:t3")))
        raise SystemExit("duplicate identity append accepted")
    except DuplicateIdentityError:
        pass
    assert ledger.current_position() == 2  # untouched by the refused attempt

    # INV-2 structurally: no update/delete/edit API exists at all
    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "delete")
    assert not hasattr(ledger, "edit")
    assert not hasattr(ledger, "remove")

    # durable-append-then-position: a storage rejection never gets a position
    storage.script_reject("lie/ledger/episode:e3")
    try:
        ledger.append(AdmissionReceipt(_episode("episode:e3", attestation_ref="trace:t4")))
        raise SystemExit("storage-rejected append accepted")
    except LedgerAppendRejectedError:
        pass
    assert ledger.current_position() == 2
    assert ledger.by_identity("episode:e3") is None

    print("ledger selftest ok")
