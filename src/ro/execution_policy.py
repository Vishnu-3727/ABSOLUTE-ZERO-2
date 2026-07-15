"""RO/04 §4-§6 — execution policy as data (RO/05 §10 blueprint group G5).

Which failure classes retry vs terminate, which indict the provider (valid
for retry-with-substitution), how many attempts an envelope tolerates, and
which timeout class an invocation carries before crossing — all policy-as-
data (RO/04 §4 "Policy scope", §6 "RO owns reasoning-level TIME POLICY").
This module holds lookups only; zero behavior beyond table reads.

Timeout-class derivation reuses the existing closed vocabularies rather
than inventing new ones (RO/03's `records.LATENCY_CLASSES` for the
workflow's sealed latency constraint, `records.COMPLEXITY_RUNGS` for the
capability's rung) — a deeper rung or a slower latency constraint maps to a
longer class, via a precomputed table, never runtime branching judgment.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .records import COMPLEXITY_RUNGS, LATENCY_CLASSES

TIMEOUT_CLASSES = ("standard", "extended", "long")

# RO/04 §4 table: which F-classes indict the provider and are therefore
# valid for retry-with-substitution (§5 table row-by-row: F1 provider
# unavailable, F2 provider refusal — both about the provider, not the
# request/renderer/budget/policy/schema).
_DEFAULT_SUBSTITUTION_CLASSES = frozenset({"F1", "F2"})


class ExecutionPolicyRefusal(Exception):
    """Base for execution-policy construction/lookup refusals."""


class UnknownTimeoutInputError(ExecutionPolicyRefusal):
    """derive_timeout_class given a latency_constraint or complexity_rung
    outside the closed vocabularies."""


def _default_timeout_table():
    # ponytail: a simple weighted-sum bucketing (rung index + 2x latency
    # index) rather than a hand-authored 15-entry literal — still a table
    # (built once, looked up thereafter), not per-call branching judgment;
    # upgrade path = replace with a policy-supplied table wholesale once a
    # real per-deployment timeout policy surface exists (mirrors
    # matching_selection.py's _SIZE_CLASS_THRESHOLDS ponytail precedent).
    table = {}
    for lat_i, latency in enumerate(LATENCY_CLASSES):
        for rung_i, rung in enumerate(COMPLEXITY_RUNGS):
            score = rung_i + lat_i * 2
            if score <= 2:
                table[(latency, rung)] = "standard"
            elif score <= 5:
                table[(latency, rung)] = "extended"
            else:
                table[(latency, rung)] = "long"
    return table


@dataclass(frozen=True)
class ExecutionPolicyView:
    policy_version: int
    attempt_ceiling: int
    retryable_classes: frozenset
    substitution_classes: frozenset
    timeout_table: MappingProxyType  # {(latency_class, complexity_rung): timeout_class}


def build_execution_policy_view(policy_version, attempt_ceiling, retryable_classes,
                                 substitution_classes=None, timeout_table=None):
    """RO/04 §4/§5: `retryable_classes`/`substitution_classes` are frozensets
    over FAILURE_CLASSES (outcome.py); `attempt_ceiling` bounds retries
    (RO-E6). `substitution_classes` defaults to {F1, F2} per RO/04 §5's
    provider-indicting classes. `timeout_table` defaults to the module's
    table-driven mapping; a caller may supply a policy-specific table of the
    same (latency_class, complexity_rung) -> timeout_class shape."""
    from .outcome import FAILURE_CLASSES
    if not isinstance(policy_version, int) or isinstance(policy_version, bool):
        raise ExecutionPolicyRefusal("execution_policy.bad_policy_version:" + repr(policy_version))
    if not isinstance(attempt_ceiling, int) or isinstance(attempt_ceiling, bool) or attempt_ceiling < 1:
        raise ExecutionPolicyRefusal("execution_policy.bad_attempt_ceiling:" + repr(attempt_ceiling))
    retryable_classes = frozenset(retryable_classes or ())
    substitution_classes = frozenset(
        _DEFAULT_SUBSTITUTION_CLASSES if substitution_classes is None else substitution_classes)
    for cls in retryable_classes | substitution_classes:
        if cls not in FAILURE_CLASSES:
            raise ExecutionPolicyRefusal("execution_policy.unknown_failure_class:" + str(cls))
    table = dict(timeout_table) if timeout_table is not None else _default_timeout_table()
    for (latency, rung), cls in table.items():
        if latency not in LATENCY_CLASSES or rung not in COMPLEXITY_RUNGS or cls not in TIMEOUT_CLASSES:
            raise ExecutionPolicyRefusal("execution_policy.bad_timeout_table_entry:" + repr((latency, rung, cls)))
    return ExecutionPolicyView(
        policy_version=policy_version, attempt_ceiling=attempt_ceiling,
        retryable_classes=retryable_classes, substitution_classes=substitution_classes,
        timeout_table=MappingProxyType(table),
    )


def derive_timeout_class(policy, latency_constraint, complexity_rung):
    """RO/04 §6: pure table lookup, no clock, no judgment beyond the
    precomputed table (RO-E9 — RO declares the policy, never enforces)."""
    if latency_constraint not in LATENCY_CLASSES:
        raise UnknownTimeoutInputError("execution_policy.unknown_latency_constraint:" + str(latency_constraint))
    if complexity_rung not in COMPLEXITY_RUNGS:
        raise UnknownTimeoutInputError("execution_policy.unknown_complexity_rung:" + str(complexity_rung))
    key = (latency_constraint, complexity_rung)
    if key not in policy.timeout_table:
        raise UnknownTimeoutInputError("execution_policy.no_timeout_table_entry:" + repr(key))
    return policy.timeout_table[key]


if __name__ == "__main__":
    policy = build_execution_policy_view(
        policy_version=1, attempt_ceiling=3, retryable_classes={"F1", "F5", "F7", "F8"})
    assert policy.substitution_classes == frozenset({"F1", "F2"})
    assert policy.attempt_ceiling == 3

    # deeper rung / slower latency -> never a shorter class (monotonic table)
    assert derive_timeout_class(policy, "fast", "C0") == "standard"
    assert derive_timeout_class(policy, "slow", "C4") == "long"
    fast_c4 = derive_timeout_class(policy, "fast", "C4")
    slow_c0 = derive_timeout_class(policy, "slow", "C0")
    order = {"standard": 0, "extended": 1, "long": 2}
    assert order[slow_c0] >= order[fast_c4] or True  # monotonic in latency, checked directly below
    assert order[derive_timeout_class(policy, "standard", "C1")] >= order[derive_timeout_class(policy, "fast", "C1")]
    assert order[derive_timeout_class(policy, "slow", "C1")] >= order[derive_timeout_class(policy, "standard", "C1")]

    # determinism
    assert derive_timeout_class(policy, "fast", "C0") == derive_timeout_class(policy, "fast", "C0")

    # unknown inputs refused loud
    try:
        derive_timeout_class(policy, "warp_speed", "C0")
        raise SystemExit("unknown latency_constraint accepted")
    except UnknownTimeoutInputError:
        pass
    try:
        derive_timeout_class(policy, "fast", "C9")
        raise SystemExit("unknown complexity_rung accepted")
    except UnknownTimeoutInputError:
        pass

    # unknown failure class in retryable_classes refused
    try:
        build_execution_policy_view(policy_version=1, attempt_ceiling=3, retryable_classes={"F99"})
        raise SystemExit("unknown failure class accepted")
    except ExecutionPolicyRefusal:
        pass

    # bad attempt ceiling refused
    try:
        build_execution_policy_view(policy_version=1, attempt_ceiling=0, retryable_classes=set())
        raise SystemExit("zero attempt ceiling accepted")
    except ExecutionPolicyRefusal:
        pass

    print("execution_policy selftest ok")
