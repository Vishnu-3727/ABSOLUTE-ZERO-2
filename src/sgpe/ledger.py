"""SGPE Grant Ledger (SGPE/04 §1; SGPE/05 §8 implementation contract).
The append-only record of approval outcomes — SGPE's only runtime-mutable
state (SGPE/00 §3.5), under the Store-catalog discipline: monotonic
position, durable-write-then-position, externally caused appends, no
clock, no self-initiated behavior (PS-5/PS-7 mirrored). A SIBLING record
to the Policy Store, never a Store tenant (SGPE/04 §3): grants are
runtime facts, not authored policy documents, so this module keeps its
own log under its own storage namespace ("sgpe/ledger/…") rather than
adding tenant kinds to the Store's catalog.

**Stores, never judges (GL-2/GL-5):** no evaluation, no expiry, no
compaction, no enforcement, no reading of compiled policy — there is no
code path here that can see a snapshot, a rule, or a Question. Ask
signatures are stored as opaque strings and never parsed (SGPE/04 §4:
one canonical signature definition, owned by the Evaluator). A grant's
bound is stored as declarative condition DATA (condition.py's closed
grammar, reused — never a timer, never applied here); lapse is an
evaluation-time judgment.

**Two record kinds only (GL-3):** grant and revocation. A revocation is
a new record naming a grant id — it inherits the revoked grant's ask
signature and scope binding (copied at append, so it travels in exactly
the slices its grant travels in), and it never edits or deletes
anything. No supersession machinery exists: duplicate grants coexist,
revocation outranks by deny-overrides at evaluation (SGPE/00 §6 rule 2).

**Record ids** are position-derived ("grant-<position>" /
"revocation-<position>") — unique, never reused, and byte-identical
under replay (GL-1/GL-6)."""
from dataclasses import dataclass
import json

from . import condition as condition_mod
from . import events as events_mod
from .condition import BooleanComposition, Comparison, SetMembership
from .evaluator import GRANT, REVOCATION

SCOPE_KINDS = ("request", "principal", "project")  # SGPE/00 §3.5's three widths — closed

_CONDITION_TYPES = (Comparison, SetMembership, BooleanComposition)


class LedgerRefusal(Exception):
    """Base for ledger.py refusals."""


class MalformedGrantAppendError(LedgerRefusal):
    """append_grant/append_revocation was handed structurally invalid
    parts (bad signature/scope/provenance/bound)."""


class UnknownGrantIdError(LedgerRefusal):
    """A revocation names a grant id the Ledger has never recorded, or
    names a record that is not a grant — refused loud (a revocation of
    nothing is not a governance fact)."""


class LedgerAppendRejectedError(LedgerRefusal):
    """The Storage double reported "rejected" for this append — the
    Ledger stays uncorrupted and gains no position for the failed write
    (durable-write-then-position, catalog discipline)."""


@dataclass(frozen=True)
class ScopeBinding:
    kind: str     # "request" | "principal" | "project"
    subject: str  # the one request id / principal / project the grant covers


def build_scope_binding(kind, subject):
    if kind not in SCOPE_KINDS:
        raise MalformedGrantAppendError("ledger.unknown_scope_kind:" + repr(kind))
    if not isinstance(subject, str) or not subject:
        raise MalformedGrantAppendError("ledger.bad_scope_subject:" + repr(subject))
    return ScopeBinding(kind=kind, subject=subject)


@dataclass(frozen=True)
class GrantProvenance:
    grantor: str                       # the approving principal
    snapshot_version: int              # stamps of the Decision that raised the ask (SGPE/04 §1.2)
    grant_slice_position: int
    evaluation_ruleset_version: int
    question_hash: str
    reason: str                        # grant-time reason text


def build_grant_provenance(grantor, snapshot_version, grant_slice_position,
                            evaluation_ruleset_version, question_hash, reason):
    for label, value in (("grantor", grantor), ("question_hash", question_hash), ("reason", reason)):
        if not isinstance(value, str) or not value:
            raise MalformedGrantAppendError("ledger.bad_" + label + ":" + repr(value))
    for label, value in (("snapshot_version", snapshot_version),
                          ("grant_slice_position", grant_slice_position),
                          ("evaluation_ruleset_version", evaluation_ruleset_version)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MalformedGrantAppendError("ledger.bad_" + label + ":" + repr(value))
    return GrantProvenance(grantor=grantor, snapshot_version=snapshot_version,
                            grant_slice_position=grant_slice_position,
                            evaluation_ruleset_version=evaluation_ruleset_version,
                            question_hash=question_hash, reason=reason)


@dataclass(frozen=True)
class LedgerRecord:
    record_id: str            # "grant-<position>" / "revocation-<position>" — never reused
    kind: str                 # GRANT or REVOCATION (evaluator.py's constants — one vocabulary)
    ask_signature: str        # opaque; the ENTIRE matching surface besides scope (GL-4)
    revoked_grant_id: object  # str for revocations, None for grants
    scope: ScopeBinding
    bound: object             # None or a condition.py node — declared data, never applied here
    provenance: GrantProvenance
    position: int             # monotonic ledger position of the append


def record_to_dict(record):
    return {
        "record_id": record.record_id, "kind": record.kind, "ask_signature": record.ask_signature,
        "revoked_grant_id": record.revoked_grant_id,
        "scope": {"kind": record.scope.kind, "subject": record.scope.subject},
        "bound": condition_mod.to_dict(record.bound) if record.bound is not None else None,
        "provenance": {
            "grantor": record.provenance.grantor,
            "snapshot_version": record.provenance.snapshot_version,
            "grant_slice_position": record.provenance.grant_slice_position,
            "evaluation_ruleset_version": record.provenance.evaluation_ruleset_version,
            "question_hash": record.provenance.question_hash,
            "reason": record.provenance.reason,
        },
        "position": record.position,
    }


def record_from_dict(data):
    provenance = data["provenance"]
    return LedgerRecord(
        record_id=data["record_id"], kind=data["kind"], ask_signature=data["ask_signature"],
        revoked_grant_id=data["revoked_grant_id"],
        scope=build_scope_binding(data["scope"]["kind"], data["scope"]["subject"]),
        bound=condition_mod.from_dict(data["bound"]) if data["bound"] is not None else None,
        provenance=build_grant_provenance(
            provenance["grantor"], provenance["snapshot_version"], provenance["grant_slice_position"],
            provenance["evaluation_ruleset_version"], provenance["question_hash"], provenance["reason"]),
        position=data["position"])


class GrantLedger:
    """Append-only, monotonic-position record of grants and revocations.
    Entire observable state is a pure function of the ordered append
    sequence (GL-1/GL-6, PS-5 discipline) — which is what makes
    `rebuild_from_log` exact. No update/delete/expire/compact API exists
    at all."""

    def __init__(self, storage, bus=None):
        self._storage = storage
        self._bus = bus
        self._records = []        # position order — the log itself
        self._by_id = {}          # record_id -> LedgerRecord

    # -- appends (the only writes; externally caused, GL-2) -----------------

    def append_grant(self, ask_signature, scope, provenance, bound=None):
        if not isinstance(ask_signature, str) or not ask_signature:
            raise MalformedGrantAppendError("ledger.bad_ask_signature:" + repr(ask_signature))
        if not isinstance(scope, ScopeBinding):
            raise MalformedGrantAppendError("ledger.scope_not_built:" + repr(scope))
        if not isinstance(provenance, GrantProvenance):
            raise MalformedGrantAppendError("ledger.provenance_not_built:" + repr(provenance))
        if bound is not None and not isinstance(bound, _CONDITION_TYPES):
            raise MalformedGrantAppendError("ledger.bound_not_a_condition:" + repr(bound))
        position = len(self._records) + 1
        record = LedgerRecord(record_id="grant-" + str(position), kind=GRANT,
                               ask_signature=ask_signature, revoked_grant_id=None, scope=scope,
                               bound=bound, provenance=provenance, position=position)
        return self._apply(record, "grant.recorded")

    def append_revocation(self, revoked_grant_id, provenance):
        """A revocation is a NEW record: it names the grant id it revokes
        and inherits that grant's signature and scope binding, so it is
        visible in exactly the slices the grant is (SGPE/04 §1.2, §2.3 —
        revocations use the same scoped door). Revoking an already-revoked
        grant is a harmless additional fact, not an error."""
        if not isinstance(provenance, GrantProvenance):
            raise MalformedGrantAppendError("ledger.provenance_not_built:" + repr(provenance))
        revoked = self._by_id.get(revoked_grant_id)
        if revoked is None or revoked.kind != GRANT:
            raise UnknownGrantIdError("ledger.revocation_names_unknown_grant:" + repr(revoked_grant_id))
        position = len(self._records) + 1
        record = LedgerRecord(record_id="revocation-" + str(position), kind=REVOCATION,
                               ask_signature=revoked.ask_signature, revoked_grant_id=revoked.record_id,
                               scope=revoked.scope, bound=None, provenance=provenance, position=position)
        return self._apply(record, "grant.revoked")

    def _apply(self, record, event_name):
        canonical_dict = record_to_dict(record)
        data = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode()
        outcome = self._storage.write("sgpe/ledger/" + str(record.position), data)
        if outcome == "rejected":
            raise LedgerAppendRejectedError("ledger.append_rejected:" + str(record.position))
        if outcome != "committed":
            raise LedgerRefusal("ledger.unknown_storage_outcome:" + repr(outcome))
        self._records.append(record)
        self._by_id[record.record_id] = record
        if self._bus is not None:
            # GL-7: every append is a bus event; Observability is the sole
            # audit sink beyond the Ledger's own log
            events_mod.emit(self._bus, event_name, event_name + ":" + record.record_id,
                             "sgpe/ledger", canonical_dict)
        return record

    # -- deterministic, position-stamped reads (GL-6) ------------------------

    def position(self):
        return len(self._records)

    def record(self, record_id):
        return self._by_id.get(record_id)

    def all(self):
        return tuple(self._records)

    def slice(self, request_id, principal, project, position):
        """SGPE/04 §1.4: all records at ≤ position whose scope binding
        names this request, principal, or project. Same arguments, same
        slice, byte-for-byte — a plain prefix filter over an append-only
        log, position-ordered by construction."""
        wanted = {("request", request_id), ("principal", principal), ("project", project)}
        return tuple(record for record in self._records
                     if record.position <= position
                     and (record.scope.kind, record.scope.subject) in wanted)

    # -- replay (GL-1/GL-6: state is a pure function of the append log) ------

    def export_log(self):
        return tuple(record_to_dict(record) for record in self._records)

    @classmethod
    def rebuild_from_log(cls, storage, log, bus=None):
        """Reconstruct a Ledger by re-applying a recorded append sequence
        in order. Positions and record ids are re-derived and must agree
        with the recorded ones — a corrupted log (gap, reorder, edited
        id) is refused loud, never silently accepted."""
        ledger = cls(storage, bus=bus)
        for entry in log:
            record = record_from_dict(entry)
            expected_position = len(ledger._records) + 1
            expected_id = ("grant-" if record.kind == GRANT else "revocation-") + str(expected_position)
            if record.position != expected_position or record.record_id != expected_id:
                raise MalformedGrantAppendError(
                    "ledger.replay_position_mismatch:expected=" + str(expected_position) +
                    ":got=" + repr((record.record_id, record.position)))
            if record.kind == GRANT:
                ledger.append_grant(record.ask_signature, record.scope, record.provenance,
                                     bound=record.bound)
            elif record.kind == REVOCATION:
                ledger.append_revocation(record.revoked_grant_id, record.provenance)
            else:
                raise MalformedGrantAppendError("ledger.replay_unknown_kind:" + repr(record.kind))
        return ledger


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .storage_double import StorageDouble

    bus = BusDouble()
    ledger = GrantLedger(StorageDouble(), bus=bus)
    prov = build_grant_provenance("approver", 1, 0, 1, "q" * 8, "looks fine")

    g1 = ledger.append_grant("sig-a", build_scope_binding("request", "req-1"), prov)
    g2 = ledger.append_grant("sig-a", build_scope_binding("principal", "alice"), prov)
    assert (g1.record_id, g1.position) == ("grant-1", 1)
    assert ledger.position() == 2
    assert bus.messages("grant.recorded")[0]["payload"]["record_id"] == "grant-1"

    # revocation inherits scope + signature, outranks nothing here — it's data
    rv = ledger.append_revocation("grant-1", prov)
    assert (rv.kind, rv.revoked_grant_id, rv.ask_signature) == (REVOCATION, "grant-1", "sig-a")
    assert rv.scope == g1.scope
    assert bus.messages("grant.revoked")[0]["payload"]["revoked_grant_id"] == "grant-1"

    # deterministic position-stamped slices (GL-6)
    s = ledger.slice("req-1", "alice", "proj-x", 3)
    assert s == ledger.slice("req-1", "alice", "proj-x", 3) == (g1, g2, rv)
    assert ledger.slice("req-1", "nobody", "proj-x", 1) == (g1,)
    assert ledger.slice("req-2", "bob", "proj-y", 3) == ()

    # unknown / non-grant revocation targets refused
    try:
        ledger.append_revocation("grant-99", prov)
        raise SystemExit("revocation of unknown grant accepted")
    except UnknownGrantIdError:
        pass
    try:
        ledger.append_revocation("revocation-3", prov)
        raise SystemExit("revocation of a revocation accepted")
    except UnknownGrantIdError:
        pass

    # replay: byte-identical rebuild (GL-1)
    rebuilt = GrantLedger.rebuild_from_log(StorageDouble(), ledger.export_log())
    assert rebuilt.export_log() == ledger.export_log()
    assert rebuilt.slice("req-1", "alice", "proj-x", 3) == s

    # no edit/delete/expire API exists at all
    for name in ("update", "delete", "remove", "expire", "compact", "edit"):
        assert not hasattr(ledger, name)

    print("ledger selftest ok")
