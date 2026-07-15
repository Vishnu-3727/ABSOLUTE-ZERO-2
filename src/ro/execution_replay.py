"""RO/04 §9-§10, G4 replay (RO/05 §10 blueprint group G5). Governance-side
replay from a sealed record sequence ALONE — no live boundary, no engine,
nothing but the artifacts. The engine's answer is DATA READ BACK, never
re-generated (RO/04 §9 "Purpose", RO-E4).

Re-verifies what a single record's own construction (outcome.py) cannot: the
SEQUENCE-level invariants — attempt indices contiguous from 1, each
record's `attempt_history_refs` chains correctly by content hash (this is
the tamper detector: rebuilding a record with one changed field changes its
own content hash, so the NEXT record's frozen reference to the OLD hash no
longer matches — a poisoned/rewritten record is caught here, not by
re-deriving anything about the changed record itself), budget arithmetic
consistent (ceiling constant across the sequence, consumed
monotonically non-decreasing, consumed+remaining == ceiling on every
record), and — when a policy is supplied — that the sequence didn't stop
prematurely (its terminal record is either non-retryable-by-class,
cancelled, ceiling-exhausted, or budget-exhausted).

Kept as its own module rather than folded into invocation.py: the checks
below exceed the ~40-line fold-in threshold once every RO/04 §9 element is
actually re-verified (interpretation call, see report).
"""
from . import outcome as _outcome


class ReplayRefusal(Exception):
    """A poisoned or malformed audit trail — always loud, never tolerated."""


def replay_attempts(records, policy=None):
    """Re-derive and re-verify the governed decision sequence from `records`
    alone (a tuple of `outcome.SealedOutcomeRecord`, as returned by
    `invocation.run_attempts`). Returns `records` unchanged on success —
    replay reads the answer back as data, it never regenerates it. Raises
    `ReplayRefusal` loud on the first inconsistency found."""
    if not records:
        raise ReplayRefusal("execution_replay.empty_record_sequence")

    request_hash = records[0].request_content_hash
    resolution_hash = records[0].resolution_content_hash
    ceiling = None
    consumed_total = 0

    for i, rec in enumerate(records):
        if rec.attempt_index != i + 1:
            raise ReplayRefusal(
                "execution_replay.attempt_index_gap:expected=" + str(i + 1) +
                ":got=" + str(rec.attempt_index))
        if rec.request_content_hash != request_hash or rec.resolution_content_hash != resolution_hash:
            raise ReplayRefusal("execution_replay.mixed_sequence:index=" + str(i))

        expected_refs = tuple(_outcome.content_hash(r) for r in records[:i])
        if rec.attempt_history_refs != expected_refs:
            raise ReplayRefusal("execution_replay.history_chain_broken:index=" + str(i))

        if rec.budget_consumed < 0 or rec.budget_remaining < 0:
            raise ReplayRefusal("execution_replay.negative_budget:index=" + str(i))
        consumed_total += rec.budget_consumed
        implied_ceiling = consumed_total + rec.budget_remaining
        if ceiling is None:
            ceiling = implied_ceiling
        elif implied_ceiling != ceiling:
            raise ReplayRefusal("execution_replay.budget_arithmetic_inconsistent:index=" + str(i))

    final = records[-1]
    if policy is not None:
        retryable = (
            (final.recovery_kind == "FAILED" and final.failure_class in policy.retryable_classes) or
            (final.recovery_kind == "EXPIRED" and "F7" in policy.retryable_classes)
        )
        if retryable:
            ceiling_exhausted = len(records) >= policy.attempt_ceiling
            budget_exhausted = final.budget_remaining <= 0
            if not (ceiling_exhausted or budget_exhausted):
                raise ReplayRefusal("execution_replay.premature_termination")

    return records


if __name__ == "__main__":
    from types import MappingProxyType

    from .execution_policy import build_execution_policy_view
    from .outcome import build_sealed_outcome, content_hash as _rec_hash

    def _rec(idx, refs, kind, consumed, remaining, failure_class=None, cancellation_origin=None):
        return build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=idx, attempt_history_refs=refs, recovery_kind=kind,
            provider_id="p", budget_consumed=consumed, budget_remaining=remaining,
            failure_class=failure_class, cancellation_origin=cancellation_origin,
        )

    r1 = _rec(1, (), "FAILED", 10, 90, failure_class="F1")
    r2 = _rec(2, (_rec_hash(r1),), "RETURNED", 10, 80)
    chain = (r1, r2)
    assert replay_attempts(chain) is chain

    policy = build_execution_policy_view(policy_version=1, attempt_ceiling=5, retryable_classes={"F1"})
    assert replay_attempts(chain, policy=policy) is chain  # terminal is RETURNED, always fine

    # tampered record: rebuild r1 with a changed field -> its hash changes,
    # but r2 still references the ORIGINAL hash -> chain broken
    r1_tampered = _rec(1, (), "FAILED", 999, 1, failure_class="F1")
    tampered_chain = (r1_tampered, r2)
    try:
        replay_attempts(tampered_chain)
        raise SystemExit("tampered chain accepted")
    except ReplayRefusal:
        pass

    # attempt index gap refused
    r2_bad_index = _rec(3, (_rec_hash(r1),), "RETURNED", 10, 80)
    try:
        replay_attempts((r1, r2_bad_index))
        raise SystemExit("attempt index gap accepted")
    except ReplayRefusal:
        pass

    # premature termination against policy: a retryable terminal failure
    # with budget AND attempts still available is illegal
    r_premature = _rec(1, (), "FAILED", 1, 99, failure_class="F1")
    loose_policy = build_execution_policy_view(policy_version=1, attempt_ceiling=5,
                                                retryable_classes={"F1"})
    try:
        replay_attempts((r_premature,), policy=loose_policy)
        raise SystemExit("premature termination accepted")
    except ReplayRefusal:
        pass

    # empty sequence refused
    try:
        replay_attempts(())
        raise SystemExit("empty sequence accepted")
    except ReplayRefusal:
        pass

    print("execution_replay selftest ok")
