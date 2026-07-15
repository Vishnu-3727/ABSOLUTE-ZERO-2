"""VAE's delegation state machine (VAE/06 Phase 2, VAE/04 §3): one
dispatched check's lifecycle on the direct VAE->Execution channel,
`Required -> Dispatched -> (Resulted | Expired)` (VAE/04 §3.2 table).
Follows the evidence.py / rules.py convention: `dataclass(frozen=True)`,
validating `build_*` factory, and pure functions that return a NEW
`Delegation` rather than mutating one in place — the same append-style
immutability append_item uses, applied to a state machine instead of a
growing tuple.

Deadlines are injected data, never negotiated at dispatch and never
extended mid-flight (VAE-O4): `build_delegation`'s `deadline` argument is
whatever the rules-as-data lookup already resolved (rules.py's
`ArtifactRules.deadlines`); this module never reads rules.py itself, it
only carries the number rules-as-data assigned. `now` is likewise always a
caller-supplied value (VAE-I6: no clock reads in judgment paths) — every
function here is a pure function of its arguments.

VAE-O3 enforcement lives here structurally: `dispatch()` refuses to send a
delegation that has already produced an outcome (Resulted or Expired) —
`ReDispatchRefusedError` — and is the only place a state can move out of
Required. A delegation stuck in Required because its one dispatch attempt
was never acknowledged (VAE/04 §3.4 row 2) stays re-dispatchable: calling
`dispatch()` again is the permitted idempotent re-issue, not a retry,
because no outcome exists yet to shop against."""
from dataclasses import dataclass, replace

REQUIRED = "required"
DISPATCHED = "dispatched"
RESULTED = "resulted"
EXPIRED = "expired"

STATES = (REQUIRED, DISPATCHED, RESULTED, EXPIRED)
TERMINAL_STATES = (RESULTED, EXPIRED)


class DelegationRefusal(Exception):
    """Base for delegation.py refusals."""


class ReDispatchRefusedError(DelegationRefusal):
    """VAE-O3: a delegation that has produced an outcome (Resulted or
    Expired), or one already Dispatched and awaiting its outcome, is never
    dispatched again within the same judgment."""


class IllegalTransitionError(DelegationRefusal):
    """A transition attempted from a state that does not permit it (e.g.
    resolving a delegation that was never dispatched)."""


@dataclass(frozen=True)
class Delegation:
    key: str            # identity on the Execution channel (also the double's lookup key)
    check: str           # the check name the rules version requires
    artifact_ref: str
    deadline: object      # rules-assigned deadline, comparable to the `now` resolve() receives
    state: str
    result: object        # None until Resulted; the scripted result dict thereafter


def build_delegation(key, check, artifact_ref, deadline):
    if not isinstance(key, str) or not key:
        raise DelegationRefusal("delegation.bad_key:" + repr(key))
    if not isinstance(check, str) or not check:
        raise DelegationRefusal("delegation.bad_check:" + repr(check))
    if not isinstance(artifact_ref, str) or not artifact_ref:
        raise DelegationRefusal("delegation.bad_artifact_ref:" + repr(artifact_ref))
    return Delegation(key=key, check=check, artifact_ref=artifact_ref, deadline=deadline,
                       state=REQUIRED, result=None)


def dispatch(delegation, execution_double, request):
    """Required -> Dispatched, via the injected Execution boundary. Refuses
    (ReDispatchRefusedError) if the delegation is Dispatched, Resulted, or
    Expired already — VAE-O3's line, drawn at the state machine itself.
    If the boundary raises ConnectionError (no acknowledgment, VAE/04 §3.4
    row 2), the delegation is returned UNCHANGED, still Required — the
    caller may call dispatch() again, which is the permitted delivery
    redundancy, not a retry (no outcome was ever produced)."""
    if delegation.state != REQUIRED:
        raise ReDispatchRefusedError(
            "delegation.redispatch_refused:key=" + delegation.key +
            ":state=" + delegation.state)
    try:
        execution_double.dispatch(delegation.key, request)
    except ConnectionError:
        return delegation
    return replace(delegation, state=DISPATCHED)


def resolve(delegation, execution_double, now):
    """Dispatched -> Resulted (a result has arrived by `now`) or -> Expired
    (no result yet and `now` has reached the deadline). Idempotent on a
    delegation already Required (nothing to resolve — IllegalTransitionError)
    or already terminal (returns the same delegation unchanged; VAE-O3 says
    a terminal delegation never transitions again — a late or duplicate
    result found by polling past this point is judgment.py's evidence
    concern, per VAE/04 §3.3, not a further state change here)."""
    if delegation.state == REQUIRED:
        raise IllegalTransitionError(
            "delegation.resolve_before_dispatch:key=" + delegation.key)
    if delegation.state in TERMINAL_STATES:
        return delegation
    result = execution_double.poll(delegation.key, now)
    if result is not None:
        return replace(delegation, state=RESULTED, result=result)
    if now >= delegation.deadline:
        return replace(delegation, state=EXPIRED, result=None)
    return delegation


if __name__ == "__main__":
    from .execution_double import ExecutionDouble

    exe = ExecutionDouble()

    # Required -> Dispatched -> Resulted (ordinary path)
    d = build_delegation("j1:structural", "structural", "artifact:a1", deadline=10)
    assert d.state == REQUIRED
    d = dispatch(d, exe, {"check": "structural", "artifact_ref": "artifact:a1"})
    assert d.state == DISPATCHED
    exe.script_result("j1:structural", arrival_time=5, outcome="success")
    d2 = resolve(d, exe, now=3)
    assert d2.state == DISPATCHED  # not arrived yet
    d3 = resolve(d2, exe, now=5)
    assert d3.state == RESULTED
    assert d3.result["outcome"] == "success"

    # Required -> Dispatched -> Expired (deadline passes with no result)
    d = build_delegation("j1:semantic", "semantic", "artifact:a1", deadline=10)
    d = dispatch(d, exe, {"check": "semantic"})
    d = resolve(d, exe, now=10)
    assert d.state == EXPIRED

    # terminal states never transition again (idempotent, not an error)
    still_expired = resolve(d, exe, now=999)
    assert still_expired.state == EXPIRED
    exe.script_result("j1:semantic", arrival_time=1, outcome="success")  # a late result exists now
    still_expired2 = resolve(d, exe, now=1000)
    assert still_expired2.state == EXPIRED  # VAE-O3: delegation state stands

    # resolving before dispatch is illegal
    fresh = build_delegation("j1:other", "other", "artifact:a1", deadline=10)
    try:
        resolve(fresh, exe, now=0)
        raise SystemExit("resolve before dispatch accepted")
    except IllegalTransitionError:
        pass

    # VAE-O3 table, all four rows:
    # row 1: Resulted delegation never redispatched
    try:
        dispatch(d3, exe, {"check": "structural"})
        raise SystemExit("redispatch of a Resulted delegation accepted")
    except ReDispatchRefusedError:
        pass
    # row 3: Expired delegation never redispatched
    try:
        dispatch(d, exe, {"check": "semantic"})
        raise SystemExit("redispatch of an Expired delegation accepted")
    except ReDispatchRefusedError:
        pass
    # a Dispatched (pending) delegation is also refused re-dispatch —
    # conservative reading: only a Required delegation with no acknowledgment
    # is re-issuable (row 2); one already sent and awaiting its outcome is not.
    pending = build_delegation("j1:pending", "pending", "artifact:a1", deadline=10)
    pending = dispatch(pending, exe, {"check": "pending"})
    assert pending.state == DISPATCHED
    try:
        dispatch(pending, exe, {"check": "pending"})
        raise SystemExit("redispatch of a Dispatched delegation accepted")
    except ReDispatchRefusedError:
        pass
    # row 2: delivery redundancy permitted — no acknowledgment, no outcome
    exe.script_no_ack("j1:noack")
    noack = build_delegation("j1:noack", "noack", "artifact:a1", deadline=10)
    noack = dispatch(noack, exe, {"check": "noack"})
    assert noack.state == REQUIRED  # unacknowledged: unchanged, re-issuable
    noack2 = dispatch(noack, exe, {"check": "noack"})  # identical re-issue succeeds
    assert noack2.state == DISPATCHED

    # bad construction refused loud
    try:
        build_delegation("", "check", "artifact:a1", 10)
        raise SystemExit("empty key accepted")
    except DelegationRefusal:
        pass

    print("delegation selftest ok")
