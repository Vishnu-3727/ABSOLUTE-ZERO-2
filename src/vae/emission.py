"""VAE Phase 4 -- Verdict emission choreography (VAE/06 Phase 4, VAE/04 §5,
VAE-O5, VAE-O6, VAE-K1, VAE-K2, VAE-K8, VAE/03 §2.1-§2.4).

Persist-then-publish, exactly: a closed Judgment (judgment.py -- §5.1 step 1,
"evidence complete", is already satisfied by judgment.close()) is (2) derived
via derivation.attach_derivation (Phase 3, pure), (3) persisted via Storage's
single-writer path -- storage.write()'s "committed"/"rejected" OUTCOME
decides everything downstream, never an exception (storage_double.py's own
docstring: rejection is an ordinary Storage answer, not a connectivity
failure) -- and only on "committed" is (4) exactly one verify.passed /
verify.failed published on the bus (VAE-O5: no verdict before durability).

A rejected write is loud absence (VAE-O6): `fault.recorded` is published
instead, naming the persistence failure by reference; no verify.* event is
ever published for that attempt, and no verdict is manufactured. The
enforcers' existing absence-as-fail machinery (VAE-K5/K6) then governs --
this module's only job on rejection is to make the failure loud and stop.

Both the verdict event id and the fault event id are derived from the
account-bearing record's own content hash (evidence.py's `content_hash`),
never from a clock or random source (VAE-I6) -- the RO family's
`<record_hash>:<suffix>` pattern, reused verbatim rather than reinvented.

Exactly-one-emission (VAE/04 §5.3, "never re-emit") is enforced by reusing
intake.py's terminal-verdict tracking rather than inventing a second ledger:
`intake.mark_terminal()` is literally the seam intake.py's own docstring
names for "a later phase's verdict-emission choreography" to call once a
verdict is durably persisted and published, and `intake.terminal_verdict()`
is what this module checks before doing any work at all -- a second
emission attempt for an artifact that already has one is refused loud,
never a silent no-op and never a second bus event.

**Interpretation calls flagged:**

1. Storage key / evidence_record_ref is content-addressed:
   `"vae/ev/" + content_hash(account_record)`. VAE/04 §7.1 fixes the
   record's shape, not its key naming; content-addressing is the same
   determinism discipline the record's own identity already uses
   (VAE-A1), so this module invents no separate identifier scheme.
2. `verdict_id` in the VAE/03 §2.1 payload is the bare record hash (the
   same string `evidence_record_ref` is built from, minus the "storage:"
   prefix) -- distinct field, same deterministic source, per VAE-K2's
   "same evidence -> same everything" spirit.
3. `reasons` on `verify.failed` (VAE/03 §2.4, VAE-K8) is built from the
   closed body's own failing/conflicting items plus the derivation
   account's `uncertainty` statements -- reference-shaped identifiers
   (rule/level/result strings already on the record), never prose and
   never artifact content.
4. A judgment not yet `close()`-sealed, or a second emission attempt for
   an already-terminal artifact, are refused loud (raise) rather than
   returned as an outcome -- both are caller misuse of the choreography,
   not an operational answer the way a Storage rejection is."""
from dataclasses import dataclass

from . import derivation
from . import evidence
from . import events

EMITTED = "emitted"
REJECTED = "rejected"


class EmissionRefusal(Exception):
    """Base for emission.py refusals."""


class JudgmentNotClosedError(EmissionRefusal):
    """emit_verdict() called on a Judgment that judgment.close() has not
    sealed -- evidence must be complete before it is derived (VAE/04 §5.1
    step 1)."""


class AlreadyEmittedError(EmissionRefusal):
    """emit_verdict() called for an artifact that already holds a terminal
    verdict (per the shared Intake) -- one verdict per gated occurrence,
    never re-emitted (VAE/04 §5.3)."""


@dataclass(frozen=True)
class EmissionResult:
    outcome: str                 # EMITTED or REJECTED
    artifact_ref: str
    storage_key: str
    event: object                  # the published envelope (verify.*/fault.recorded)
    evidence_record_ref: object     # str on EMITTED, None on REJECTED
    verdict: object                 # "passed"/"failed" on EMITTED, None on REJECTED


def _failure_reasons(record, account):
    """Structured, reference-shaped reasons (VAE/03 §2.4, VAE-K8): which
    items failed or conflicted, plus the derivation account's own
    uncertainty statements (missing evidence) -- never prose, never
    artifact content, only rule/level/result identifiers already present
    on the closed evidence body."""
    reasons = []
    for item in record.items:
        if item.contribution_kind == "missing":
            continue
        if item.contribution_kind == "conflicting" or item.result not in derivation.PASSING_RESULTS:
            reasons.append({"rule": item.rule, "level": item.level,
                             "result": item.result, "contribution_kind": item.contribution_kind})
    for statement in account["uncertainty"]:
        reasons.append({"rule": statement["rule"], "level": statement["level"],
                         "reason": statement["reason"]})
    return tuple(reasons)


def build_verdict_envelope(record_hash, account_record):
    """Pure: the verdict event name/id/payload VAE/03 §2.1 fixes, built
    from an account-bearing record's own content hash and derivation
    account alone -- no Storage write, no bus publish. Factored out of
    emit_verdict() (Phase 5, VAE/05 §8: "every verdict event re-derives
    from its persisted evidence record") so replay can reconstruct the
    EXACT envelope emit_verdict() would have published for the same
    record, without repeating a live persist -- replay only ever reads
    (VAE-O10)."""
    account = account_record.derivation_account
    verdict = account["verdict"]
    evidence_record_ref = "storage:vae/ev/" + record_hash
    passed = verdict == derivation.VERDICT_PASSED
    event_name = "verify.passed" if passed else "verify.failed"
    event_id = record_hash + (":passed" if passed else ":failed")

    payload = {
        "verdict_id": record_hash,
        "artifact_id": account_record.artifact_ref,
        "rules_version": account_record.rules_version,
        "evidence_record_ref": evidence_record_ref,
        "assurance_level": account["assurance_level"],
    }
    if not passed:
        payload["failure_cause"] = account["failure_cause"]
        payload["reasons"] = _failure_reasons(account_record, account)
    return event_name, event_id, payload


def emit_verdict(judgment, policy, storage, bus, intake):
    """The whole Phase 4 choreography for one closed judgment: derive ->
    persist via Storage -> publish exactly one verdict (or, on rejection,
    exactly one fault.recorded and no verdict). Returns an EmissionResult;
    never raises for an ordinary storage rejection (that is an expected
    outcome, not an error) -- only raises for a judgment that is not
    actually closed, or a second attempt at an artifact already terminal."""
    if not judgment.closed:
        raise JudgmentNotClosedError("emission.judgment_not_closed:" + judgment.judgment_id)
    if intake.terminal_verdict(judgment.artifact_ref) is not None:
        raise AlreadyEmittedError("emission.already_emitted:" + judgment.artifact_ref)

    account_record = derivation.attach_derivation(judgment.record, policy)
    record_hash = evidence.content_hash(account_record)
    storage_key = "vae/ev/" + record_hash

    # (3) Persist, via Storage's single-writer path -- BEFORE any publish (VAE-O5).
    outcome = storage.write(storage_key, evidence.canonical(account_record))

    if outcome == "rejected":
        fault_id = record_hash + ":fault"
        payload = {
            "artifact_id": judgment.artifact_ref,
            "rules_version": judgment.rules_version,
            "reason": "storage_rejected",
            "attempted_ref": "storage:" + storage_key,
        }
        env = events.emit(bus, "fault.recorded", fault_id, judgment.artifact_ref, payload)
        return EmissionResult(REJECTED, judgment.artifact_ref, storage_key, env, None, None)

    if outcome != "committed":
        raise EmissionRefusal("emission.unknown_storage_outcome:" + repr(outcome))

    # (4) Publish -- only reached after durable confirmation.
    event_name, event_id, payload = build_verdict_envelope(record_hash, account_record)
    evidence_record_ref = payload["evidence_record_ref"]
    verdict = account_record.derivation_account["verdict"]

    env = events.emit(bus, event_name, event_id, judgment.artifact_ref, payload)
    intake.mark_terminal(judgment.artifact_ref, evidence_record_ref)
    return EmissionResult(EMITTED, judgment.artifact_ref, storage_key, env, evidence_record_ref, verdict)


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .execution_double import ExecutionDouble
    from .intake import Intake
    from .judgment import close, dispatch_delegation, open_judgment, resolve_delegation, run_static_check
    from .static_checks import StaticCheckRegistry
    from .storage_double import StorageDouble

    policy = derivation.build_derivation_policy(1, coverage_moderate_min_fraction=0.5,
                                                 coverage_strong_min_fraction=0.9)

    def closed_pass_judgment(artifact_ref="artifact:a1", judgment_id="judgment:a1"):
        exe = ExecutionDouble()
        registry = StaticCheckRegistry()
        j = open_judgment(judgment_id, artifact_ref, rules_version=1,
                           delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
                           static_checks_spec={"reference_wellformed": {"level": "system"}})
        j = run_static_check(j, "reference_wellformed", registry, {})
        j = dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result(judgment_id + ":structural", arrival_time=1, outcome="success")
        j = resolve_delegation(j, "structural", exe, now=1)
        return close(j)

    def closed_fail_judgment(artifact_ref="artifact:a2", judgment_id="judgment:a2"):
        exe = ExecutionDouble()
        j = open_judgment(judgment_id, artifact_ref, rules_version=1,
                           delegated_checks={"structural": {"deadline": 5, "level": "structural"}},
                           static_checks_spec={})
        j = dispatch_delegation(j, "structural", exe, {"check": "structural"})
        j = resolve_delegation(j, "structural", exe, now=5)  # no result scripted -> expiry
        return close(j)

    # -- ordinary commit path: persist then publish exactly one verify.passed --
    storage, bus, intake = StorageDouble(), BusDouble(), Intake()
    j_pass = closed_pass_judgment()
    result = emit_verdict(j_pass, policy, storage, bus, intake)
    assert result.outcome == EMITTED
    assert result.verdict == "passed"
    assert storage.exists(result.storage_key)
    assert bus.messages("verify.passed")[-1]["event_name"] == "verify.passed"
    assert bus.messages("verify.failed") == []
    assert bus.messages("fault.recorded") == []
    payload = bus.messages("verify.passed")[-1]["payload"]
    for field in ("verdict_id", "artifact_id", "rules_version", "evidence_record_ref", "assurance_level"):
        assert field in payload
    assert "failure_cause" not in payload and "reasons" not in payload
    assert intake.terminal_verdict("artifact:a1") == result.evidence_record_ref

    # -- build_verdict_envelope reproduces the same envelope emit_verdict published --
    account_record_reloaded = derivation.attach_derivation(j_pass.record, policy)
    reloaded_hash = evidence.content_hash(account_record_reloaded)
    reloaded_name, reloaded_id, reloaded_payload = build_verdict_envelope(
        reloaded_hash, account_record_reloaded)
    assert reloaded_name == "verify.passed"
    assert reloaded_id == result.event["event_id"]
    assert reloaded_payload == result.event["payload"]

    # -- fail path: verify.failed carries failure_cause + reasons (VAE-K8) --
    storage2, bus2, intake2 = StorageDouble(), BusDouble(), Intake()
    j_fail = closed_fail_judgment()
    result2 = emit_verdict(j_fail, policy, storage2, bus2, intake2)
    assert result2.outcome == EMITTED and result2.verdict == "failed"
    fail_payload = bus2.messages("verify.failed")[-1]["payload"]
    assert fail_payload["failure_cause"] == derivation.EXECUTION_FAILURE
    assert fail_payload["reasons"]
    assert bus2.messages("verify.passed") == []

    # -- deterministic event ids: same closed body -> same event id, twice --
    storage3, bus3, intake3 = StorageDouble(), BusDouble(), Intake()
    j_pass_again = closed_pass_judgment(artifact_ref="artifact:a1", judgment_id="judgment:a1")
    r3 = emit_verdict(j_pass_again, policy, storage3, bus3, intake3)
    assert r3.event["event_id"] == result.event["event_id"]  # identical evidence body -> identical id

    # -- persistence rejection (VAE-O6): fault.recorded, zero verify.*, no record --
    storage4, bus4, intake4 = StorageDouble(), BusDouble(), Intake()
    j_pass2 = closed_pass_judgment(artifact_ref="artifact:a3", judgment_id="judgment:a3")
    account_preview = derivation.attach_derivation(j_pass2.record, policy)
    rejected_key = "vae/ev/" + evidence.content_hash(account_preview)
    storage4.script_reject(rejected_key)
    result4 = emit_verdict(j_pass2, policy, storage4, bus4, intake4)
    assert result4.outcome == REJECTED
    assert not storage4.exists(rejected_key)
    assert bus4.messages("verify.passed") == [] and bus4.messages("verify.failed") == []
    assert bus4.messages("fault.recorded")[-1]["payload"]["reason"] == "storage_rejected"
    assert intake4.terminal_verdict("artifact:a3") is None  # loud absence, never a recordless verdict

    # -- exactly-one-emission: a second attempt is refused loud --
    try:
        emit_verdict(j_pass, policy, storage, bus, intake)
        raise SystemExit("second emission attempt accepted")
    except AlreadyEmittedError:
        pass

    # -- emission before close() is refused loud --
    exe = ExecutionDouble()
    j_open = open_judgment("judgment:a4", "artifact:a4", 1,
                            delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
                            static_checks_spec={})
    try:
        emit_verdict(j_open, policy, StorageDouble(), BusDouble(), Intake())
        raise SystemExit("emission of an unclosed judgment accepted")
    except JudgmentNotClosedError:
        pass

    print("emission selftest ok")
