"""The judgment aggregate (VAE/06 Phase 2) tying intake + delegations +
static-check results into an evidence-record-in-progress. A `Judgment` is
built once (`open_judgment`) from the rules-version-derived required check
set, then grows — delegation dispatch/resolve and static-check runs each
append evidence items to its Phase 1 `EvidenceRecord` (evidence.py) — until
every required check has reached a terminal state (VAE/04 §5.1 step 1,
"evidence complete").

Closure is the whole of this module's job: `close()` marks a judgment
ready for Phase 3's derivation once all required delegations are Resulted
or Expired and all required static checks have run. **Nothing here derives
a verdict, confidence, or assurance** — a closed `Judgment` is a closed
evidence body and nothing more (VAE/06 Phase 2 scope line); Phase 3 reads
`judgment.record` and `judgment.rules_version` to do that later.

Contribution kinds this module assigns (VAE/02 §5's closed five, reused
from evidence.py, never a sixth invented here):

- A delegation's first Resulted or Expired outcome, and a static check's
  result, are each **independent** evidence for that check's claim — Phase
  2 records one first-standing item per required check; declared
  multi-sample corroboration/conflict weighing across separate delegations
  is Phase 3's derivation concern (VAE/04 §3.4 row 4), not this module's.
- A late or duplicate result surfacing for an already-terminal delegation
  is **redundant** (VAE/04 §3.4 row 2, VAE-O3: "the duplicate is Redundant
  evidence — recorded, counted once") — appended without touching the
  delegation's already-terminal state."""
from dataclasses import dataclass, replace
from types import MappingProxyType

from . import delegation as delegation_mod
from . import evidence

INDEPENDENT = "independent"
REDUNDANT = "redundant"


class JudgmentRefusal(Exception):
    """Base for judgment.py refusals."""


class DuplicateCheckNameAcrossKindsError(JudgmentRefusal):
    """A check name given to open_judgment() as both delegated and static —
    each required check is exactly one kind."""


class UnknownCheckError(JudgmentRefusal):
    """An operation named a check this judgment never declared required."""


class LateResultBeforeTerminalError(JudgmentRefusal):
    """record_late_result() called on a delegation not yet Resulted or
    Expired — there is nothing "late" about a delegation still in flight."""


class JudgmentNotReadyError(JudgmentRefusal):
    """close() called while a required delegation or static check has not
    yet reached a terminal state (VAE/04 §5.1 step 1's precondition)."""


@dataclass(frozen=True)
class Judgment:
    judgment_id: str
    artifact_ref: str
    rules_version: int
    record: object              # evidence.EvidenceRecord, grows via append_item
    delegations: MappingProxyType   # check name -> delegation.Delegation
    static_pending: frozenset        # static check names not yet run
    levels: MappingProxyType         # check name (delegated + static) -> level string
    closed: bool


def open_judgment(judgment_id, artifact_ref, rules_version, delegated_checks, static_checks_spec):
    """`delegated_checks`: mapping check name -> {"deadline": ..., "level": ...}
    (the deadline is whatever rules.py's ArtifactRules.deadlines already
    resolved — this module never reads rules.py itself). `static_checks_spec`:
    mapping check name -> {"level": ...}. The two mappings' key sets must be
    disjoint — a required check is delegated or static, never both."""
    delegated_checks = dict(delegated_checks or {})
    static_checks_spec = dict(static_checks_spec or {})
    overlap = set(delegated_checks) & set(static_checks_spec)
    if overlap:
        raise DuplicateCheckNameAcrossKindsError(
            "judgment.check_declared_both_delegated_and_static:" + repr(sorted(overlap)))

    delegations = {}
    levels = {}
    for name, spec in delegated_checks.items():
        key = judgment_id + ":" + name
        delegations[name] = delegation_mod.build_delegation(
            key, name, artifact_ref, spec["deadline"])
        levels[name] = spec["level"]
    for name, spec in static_checks_spec.items():
        levels[name] = spec["level"]

    record = evidence.build_evidence_record(artifact_ref, rules_version)
    return Judgment(
        judgment_id=judgment_id, artifact_ref=artifact_ref, rules_version=rules_version,
        record=record, delegations=MappingProxyType(delegations),
        static_pending=frozenset(static_checks_spec.keys()),
        levels=MappingProxyType(levels), closed=False)


def _require_delegation(judgment, check):
    if check not in judgment.delegations:
        raise UnknownCheckError("judgment.unknown_delegated_check:" + str(check))
    return judgment.delegations[check]


def dispatch_delegation(judgment, check, execution_double, request):
    """Send one required check's delegation to Execution. Delegates
    entirely to delegation.dispatch() for the VAE-O3 refusal and the
    unacknowledged-dispatch no-op case; this function only wires the
    result back into the judgment's delegation mapping."""
    d = _require_delegation(judgment, check)
    new_d = delegation_mod.dispatch(d, execution_double, request)
    updated = dict(judgment.delegations)
    updated[check] = new_d
    return replace(judgment, delegations=MappingProxyType(updated))


def resolve_delegation(judgment, check, execution_double, now):
    """Advance one delegation (Dispatched -> Resulted/Expired/unchanged),
    appending an evidence item exactly when this call is the transition
    into a terminal state — calling it again on an already-terminal
    delegation changes nothing (delegation.resolve()'s own idempotence)."""
    d = _require_delegation(judgment, check)
    new_d = delegation_mod.resolve(d, execution_double, now)
    updated = dict(judgment.delegations)
    updated[check] = new_d
    record = judgment.record

    if new_d.state != d.state:
        if new_d.state == delegation_mod.RESULTED:
            result_value = new_d.result["outcome"]
        elif new_d.state == delegation_mod.EXPIRED:
            result_value = "execution_failure"  # VAE/01 §11 "Execution failure"
        else:
            result_value = None
        if result_value is not None:
            item = evidence.build_evidence_item(
                rule="rule." + check, artifact_ref=judgment.artifact_ref,
                source="execution:" + new_d.key, result=result_value,
                contribution_kind=INDEPENDENT, level=judgment.levels[check])
            record = evidence.append_item(record, item)

    return replace(judgment, delegations=MappingProxyType(updated), record=record)


def record_late_result(judgment, check, execution_double, now):
    """A result surfacing for an already-terminal delegation (VAE/04 §3.3:
    "a late result arriving after expiry is recorded... but the expired
    delegation's evidentiary status stands"). Appends a Redundant evidence
    item (VAE/04 §3.4 row 2, VAE-O3) without touching the delegation's
    terminal state. Refuses (LateResultBeforeTerminalError) if the
    delegation has not yet reached Resulted or Expired — there is no such
    thing as a "late" result for one still in flight; that is an ordinary
    resolve_delegation() call. A no-op (returns the judgment unchanged) if
    no further result is available at `now`."""
    d = _require_delegation(judgment, check)
    if d.state not in delegation_mod.TERMINAL_STATES:
        raise LateResultBeforeTerminalError(
            "judgment.late_result_before_terminal:check=" + check + ":state=" + d.state)
    result = execution_double.poll(d.key, now)
    if result is None:
        return judgment
    item = evidence.build_evidence_item(
        rule="rule." + check, artifact_ref=judgment.artifact_ref,
        source="execution:" + d.key, result=result["outcome"],
        contribution_kind=REDUNDANT, level=judgment.levels[check])
    return replace(judgment, record=evidence.append_item(judgment.record, item))


def run_static_check(judgment, check, registry, metadata):
    """Run one required static check (static_checks.StaticCheckRegistry)
    and append its result as evidence. Refuses (UnknownCheckError) a check
    name this judgment never declared static, or one already run — a
    static check runs exactly once per judgment, mirroring "one judgment
    per gated occurrence" applied at the check level."""
    if check not in judgment.static_pending:
        raise UnknownCheckError(
            "judgment.unknown_or_already_run_static_check:" + str(check))
    result = registry.run(check, judgment.artifact_ref, metadata)
    item = evidence.build_evidence_item(
        rule="rule." + check, artifact_ref=judgment.artifact_ref,
        source="static:" + check, result=result["outcome"],
        contribution_kind=INDEPENDENT, level=judgment.levels[check])
    record = evidence.append_item(judgment.record, item)
    return replace(judgment, record=record, static_pending=frozenset(judgment.static_pending - {check}))


def is_closed(judgment):
    """True once every required delegation is Resulted or Expired and
    every required static check has run (VAE/04 §5.1 step 1)."""
    if judgment.static_pending:
        return False
    return all(d.state in delegation_mod.TERMINAL_STATES for d in judgment.delegations.values())


def close(judgment):
    """Seal the judgment as a closed evidence body, ready for Phase 3.
    Idempotent if already closed; refuses (JudgmentNotReadyError) if a
    required check has not yet reached a terminal state."""
    if judgment.closed:
        return judgment
    if not is_closed(judgment):
        raise JudgmentNotReadyError(
            "judgment.not_ready:" + judgment.judgment_id)
    return replace(judgment, closed=True)


if __name__ == "__main__":
    from .execution_double import ExecutionDouble
    from .static_checks import StaticCheckRegistry

    exe = ExecutionDouble()
    registry = StaticCheckRegistry()

    j = open_judgment(
        "judgment:a1", "artifact:a1", rules_version=1,
        delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
        static_checks_spec={"reference_wellformed": {"level": "reference"}})
    assert not is_closed(j)

    # static check first
    j = run_static_check(j, "reference_wellformed", registry, {})
    assert len(j.record.items) == 1
    assert j.record.items[0].contribution_kind == INDEPENDENT
    assert not is_closed(j)  # delegation still Required

    # a static check cannot be run twice
    try:
        run_static_check(j, "reference_wellformed", registry, {})
        raise SystemExit("static check ran twice")
    except UnknownCheckError:
        pass

    # dispatch + resolve the delegation to Resulted
    j = dispatch_delegation(j, "structural", exe, {"check": "structural"})
    exe.script_result("judgment:a1:structural", arrival_time=3, outcome="success")
    j = resolve_delegation(j, "structural", exe, now=1)
    assert not is_closed(j)  # not arrived yet
    j = resolve_delegation(j, "structural", exe, now=3)
    assert is_closed(j)
    assert len(j.record.items) == 2
    assert j.record.items[-1].result == "success"

    j_closed = close(j)
    assert j_closed.closed
    assert close(j_closed) is j_closed or close(j_closed).closed  # idempotent

    # closing before ready is refused
    j_open = open_judgment(
        "judgment:a2", "artifact:a2", 1,
        delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
        static_checks_spec={})
    try:
        close(j_open)
        raise SystemExit("premature close accepted")
    except JudgmentNotReadyError:
        pass

    # expiry path: deadline passes with no result -> execution_failure evidence
    j2 = open_judgment(
        "judgment:a3", "artifact:a3", 1,
        delegated_checks={"semantic": {"deadline": 5, "level": "semantic"}},
        static_checks_spec={})
    j2 = dispatch_delegation(j2, "semantic", exe, {"check": "semantic"})
    j2 = resolve_delegation(j2, "semantic", exe, now=5)
    assert is_closed(j2)
    assert j2.record.items[-1].result == "execution_failure"

    # a late result after expiry is recorded as Redundant, delegation stands Expired
    exe.script_result("judgment:a3:semantic", arrival_time=1, outcome="success")
    j2b = record_late_result(j2, "semantic", exe, now=6)
    assert j2b.delegations["semantic"].state == delegation_mod.EXPIRED  # state stands
    assert j2b.record.items[-1].contribution_kind == REDUNDANT
    assert len(j2b.record.items) == len(j2.record.items) + 1

    # late-result before terminal is refused
    j3 = open_judgment(
        "judgment:a4", "artifact:a4", 1,
        delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
        static_checks_spec={})
    try:
        record_late_result(j3, "structural", exe, now=0)
        raise SystemExit("late result accepted before terminal")
    except LateResultBeforeTerminalError:
        pass

    # a required check declared both delegated and static is refused at construction
    try:
        open_judgment("judgment:a5", "artifact:a5", 1,
                       delegated_checks={"x": {"deadline": 1, "level": "x"}},
                       static_checks_spec={"x": {"level": "x"}})
        raise SystemExit("check declared both delegated and static accepted")
    except DuplicateCheckNameAcrossKindsError:
        pass

    # unknown check name refused on every operation
    try:
        dispatch_delegation(j, "nonexistent", exe, {})
        raise SystemExit("dispatch of unknown check accepted")
    except UnknownCheckError:
        pass

    print("judgment selftest ok")
