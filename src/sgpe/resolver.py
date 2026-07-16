"""SGPE Effective Policy Resolver (SGPE/04 §2 + ERRATA C3; SGPE/05 §8
implementation contract). Binds a request to its governance world, once,
at admission: two atomic reads, zero writes, one small immutable value —

    EP(R) = (snapshot version S, admission ledger position P₀,
             request id R, principal U, project J)

**Stateless between invocations (EPR-6):** module functions only, no
class, no registry of live bindings — EP(R) persistence is the RSM's.
The Resolver never evaluates, compiles, enforces, or writes (EPR-3);
admission refusals surface through the Kernel's existing admission
events, so this module emits nothing.

**The active-version fact arrives as a supplied reader** (a zero-argument
callable), not a Store reference: the Compiler activates and publishes
the fact (D6); who carries it to admission is the Kernel's wiring
(SGPE/04 §3 — the Store is untouched by this module, structurally).

**Frozen binding rule, not frozen row count (ERRATA C3, INV-6 reading):**
`consultation_slice()` implements SGPE/04 §2.3's closed growth rule
verbatim —

    slice(R) at P = standing grants at ≤ P₀ ∪ request-R-scoped records in (P₀, P]

No snapshot activation and no principal/project-width append after P₀
ever enters a running request's world (EPR-2); the request's own asks —
and their revocations, which inherit the request-scoped binding — land
as they are appended (EPR-4). Every consultation stamps the position it
used: the returned slice pairs with the same `position` the caller
passes to `evaluate()` as `grant_slice_position`.

**Fail-closed admission (EPR-5):** no active snapshot (bootstrap — first
activation precedes first admission, the Phase 5 obligation) or an
unreachable Ledger refuses admission with `AdmissionRefusedError`. A
request must never start with an unknown governance world; there is no
"no policy yet, allow all" path here or anywhere."""
from dataclasses import dataclass

from .evaluator import GRANT, GrantRecord
from .ledger import GrantLedger

REFUSED_NO_ACTIVE_SNAPSHOT = "no_active_snapshot"
REFUSED_SNAPSHOT_FACT_UNREADABLE = "snapshot_fact_unreadable"
REFUSED_LEDGER_UNREACHABLE = "ledger_unreachable"


class ResolverRefusal(Exception):
    """Base for resolver.py refusals."""


class MalformedAdmissionInputError(ResolverRefusal):
    """admit()/consultation_slice() was handed structurally invalid
    arguments — a caller bug, not an admission-time world defect."""


class AdmissionRefusedError(ResolverRefusal):
    """Fail-closed admission (EPR-5): the governance world could not be
    read completely and atomically, so no request begins. Carries a
    `code` naming which read failed."""

    def __init__(self, code, detail):
        super().__init__("resolver.admission_refused:" + code + ":" + detail)
        self.code = code


@dataclass(frozen=True)
class EffectivePolicy:
    snapshot_version: int
    admission_ledger_position: int  # P₀ — the grant baseline
    request_id: str
    principal: str
    project: str


def effective_policy_to_dict(ep):
    return {
        "snapshot_version": ep.snapshot_version,
        "admission_ledger_position": ep.admission_ledger_position,
        "request_id": ep.request_id, "principal": ep.principal, "project": ep.project,
    }


def effective_policy_from_dict(data):
    """Replay entry point (EPR-7): the RSM-persisted stamp reconstructs
    the identical binding value."""
    ep = EffectivePolicy(
        snapshot_version=data["snapshot_version"],
        admission_ledger_position=data["admission_ledger_position"],
        request_id=data["request_id"], principal=data["principal"], project=data["project"])
    _check_binding(ep.snapshot_version, ep.admission_ledger_position, ep.request_id,
                    ep.principal, ep.project)
    return ep


def _check_binding(snapshot_version, admission_position, request_id, principal, project):
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise MalformedAdmissionInputError("resolver.bad_snapshot_version:" + repr(snapshot_version))
    if (not isinstance(admission_position, int) or isinstance(admission_position, bool)
            or admission_position < 0):
        raise MalformedAdmissionInputError("resolver.bad_admission_position:" + repr(admission_position))
    for label, value in (("request_id", request_id), ("principal", principal), ("project", project)):
        if not isinstance(value, str) or not value:
            raise MalformedAdmissionInputError("resolver.bad_" + label + ":" + repr(value))


def admit(read_active_snapshot_version, ledger, request_id, principal, project):
    """The admission act (SGPE/04 §2.2): read the active snapshot version
    and the current ledger position P₀, emit the immutable Effective
    Policy binding. No writes happen anywhere in this function — a crash
    mid-admission leaves nothing behind, and re-admission lawfully
    re-binds to a possibly newer world (§2.4)."""
    for label, value in (("request_id", request_id), ("principal", principal), ("project", project)):
        if not isinstance(value, str) or not value:
            raise MalformedAdmissionInputError("resolver.bad_" + label + ":" + repr(value))
    if not callable(read_active_snapshot_version):
        raise MalformedAdmissionInputError(
            "resolver.snapshot_fact_reader_not_callable:" + repr(read_active_snapshot_version))
    if not isinstance(ledger, GrantLedger):
        raise MalformedAdmissionInputError("resolver.ledger_not_built:" + repr(ledger))

    # read 1: snapshot binding — the single atomically-published fact (D6)
    try:
        snapshot_version = read_active_snapshot_version()
    except Exception as exc:
        raise AdmissionRefusedError(REFUSED_SNAPSHOT_FACT_UNREADABLE, repr(exc))
    if snapshot_version is None:
        raise AdmissionRefusedError(REFUSED_NO_ACTIVE_SNAPSHOT,
                                     "bootstrap: first activation precedes first admission")
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise AdmissionRefusedError(REFUSED_SNAPSHOT_FACT_UNREADABLE, repr(snapshot_version))

    # read 2: grant baseline P₀ — standing grants at ≤ P₀ are in the
    # request's world from the start
    try:
        admission_position = ledger.position()
    except Exception as exc:
        raise AdmissionRefusedError(REFUSED_LEDGER_UNREACHABLE, repr(exc))

    return EffectivePolicy(snapshot_version=snapshot_version,
                            admission_ledger_position=admission_position,
                            request_id=request_id, principal=principal, project=project)


def consultation_slice(ledger, effective_policy, position):
    """SGPE/04 §2.3's closed rule, verbatim: standing records at ≤ P₀
    (any of the request's three scope subjects) plus request-id-scoped
    records in (P₀, position]. Returns the slice PROJECTED to the
    Evaluator's own `GrantRecord` shape (EV §6) — kind, grant identity,
    ask signature — in ledger-position order; `position` is the stamp
    the caller passes to `evaluate()` as `grant_slice_position`.

    Deterministic (EPR-7): same (ledger log, EP, position) → same slice,
    byte-for-byte — which is exactly what makes historical consultations
    reconstructible from recorded stamps."""
    if not isinstance(ledger, GrantLedger):
        raise MalformedAdmissionInputError("resolver.ledger_not_built:" + repr(ledger))
    if not isinstance(effective_policy, EffectivePolicy):
        raise MalformedAdmissionInputError(
            "resolver.effective_policy_not_built:" + repr(effective_policy))
    _check_binding(effective_policy.snapshot_version, effective_policy.admission_ledger_position,
                    effective_policy.request_id, effective_policy.principal, effective_policy.project)
    if not isinstance(position, int) or isinstance(position, bool):
        raise MalformedAdmissionInputError("resolver.bad_consultation_position:" + repr(position))
    if position < effective_policy.admission_ledger_position:
        raise MalformedAdmissionInputError(
            "resolver.consultation_precedes_admission:" + str(position) + "<"
            + str(effective_policy.admission_ledger_position))

    baseline_position = effective_policy.admission_ledger_position
    visible = []
    for record in ledger.slice(effective_policy.request_id, effective_policy.principal,
                                effective_policy.project, position):
        if record.position <= baseline_position:
            visible.append(record)  # standing world, frozen at P₀
        elif record.scope.kind == "request":
            visible.append(record)  # the one open door: this request's own asks + revocations
        # principal/project-width appends after P₀ never enter (EPR-2)
    return tuple(_project(record) for record in visible)


def _project(record):
    """Ledger record → Evaluator GrantRecord (EV §6's input shape). A
    revocation projects to the REVOKED grant's identity — that is the id
    the Evaluator's deny-overrides overlay keys on. Bounds are stored
    governance data (GL-4) and travel with the Ledger record; applying
    them is the Evaluator's evaluation-time judgment (GL-5), under a
    future evaluation ruleset version."""
    if record.kind == GRANT:
        return GrantRecord(kind=record.kind, grant_id=record.record_id,
                            ask_signature=record.ask_signature)
    return GrantRecord(kind=record.kind, grant_id=record.revoked_grant_id,
                        ask_signature=record.ask_signature)


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .ledger import build_grant_provenance, build_scope_binding
    from .storage_double import StorageDouble

    prov = build_grant_provenance("approver", 1, 0, 1, "q" * 8, "ok")
    ledger = GrantLedger(StorageDouble())

    # bootstrap: no active snapshot ⇒ fail-closed refusal
    try:
        admit(lambda: None, ledger, "req-1", "alice", "proj-x")
        raise SystemExit("admission without an active snapshot accepted")
    except AdmissionRefusedError as exc:
        assert exc.code == REFUSED_NO_ACTIVE_SNAPSHOT

    # standing principal grant exists before admission -> in the baseline
    standing = ledger.append_grant("sig-a", build_scope_binding("principal", "alice"), prov)
    ep = admit(lambda: 1, ledger, "req-1", "alice", "proj-x")
    assert ep == EffectivePolicy(1, 1, "req-1", "alice", "proj-x")

    # external principal-width grant after P₀ never enters (EPR-2)...
    ledger.append_grant("sig-b", build_scope_binding("principal", "alice"), prov)
    # ...but the request's own grant does (EPR-4), and its revocation too
    own = ledger.append_grant("sig-c", build_scope_binding("request", "req-1"), prov)
    s = consultation_slice(ledger, ep, ledger.position())
    assert [g.grant_id for g in s] == [standing.record_id, own.record_id]

    ledger.append_revocation(own.record_id, prov)
    s2 = consultation_slice(ledger, ep, ledger.position())
    assert [(g.kind, g.grant_id) for g in s2][-1] == ("revocation", own.record_id)

    # replay: EP round-trips; same stamps -> same slice
    ep2 = effective_policy_from_dict(effective_policy_to_dict(ep))
    assert ep2 == ep
    assert consultation_slice(ledger, ep2, 3) == s

    print("resolver selftest ok")
