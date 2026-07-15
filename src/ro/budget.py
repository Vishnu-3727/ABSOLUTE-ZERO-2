"""RO/03 §8 — Token Budget Architecture (RO/05 §10 blueprint group G3+G4).

`BudgetEnvelope` is the immutable ceiling RO attaches to a Reasoning Request
at preparation. Numeric token ceilings ARE legal here (pre-ruled: the
architecture's numeric ban is about docs/policy vocabulary, not policy
config data — RO/03 §8's ceilings are exactly that config data).

Inheritance (RO-P7): a child envelope is allocated from the parent's
REMAINING ceiling, never a fresh grant. At preparation time nothing has been
consumed yet (consumption is RO/04 territory), so "remaining" here means
"parent ceiling minus whatever sibling children already drew from it in
this same preparation" — the caller threads `already_allocated_from_parent`
across sibling allocations (composite/escalation flows, RO/03 §8
Inheritance row).

Exhaustion is always loud (RO-P7/RO-P12): over-ceiling allocation and
"selected content doesn't fit the ceiling" both raise, never truncate.
"""
from dataclasses import dataclass


class BudgetRefusal(Exception):
    """Base for every budget-time refusal."""


class BudgetInvalidError(BudgetRefusal):
    """Ceiling/version malformed."""


class BudgetExhaustedError(BudgetRefusal):
    """Requested ceiling exceeds the parent's remaining envelope."""


class BudgetInfeasibleError(BudgetRefusal):
    """Minimum-sufficient content does not fit under the allocated ceiling
    (RO/03 §8 Exhaustion row) — never silently truncated to fit."""


@dataclass(frozen=True)
class BudgetEnvelope:
    ceiling: int
    source_policy_version: int
    parent_ref: object  # str (parent envelope's content hash) | None


def allocate_budget(ceiling, source_policy_version, parent=None,
                     already_allocated_from_parent=0):
    """Allocate one BudgetEnvelope. `parent`, if given, is the BudgetEnvelope
    this allocation draws from (RO-P7 inheritance); `already_allocated_from_parent`
    is the sum of ceilings already drawn from that same parent by sibling
    allocations in this preparation — the caller's bookkeeping, not stored
    state here (this module holds no mutable ledger, mirrors decide()'s
    purity)."""
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling <= 0:
        raise BudgetInvalidError("budget.bad_ceiling:" + repr(ceiling))
    if not isinstance(source_policy_version, int) or isinstance(source_policy_version, bool):
        raise BudgetInvalidError("budget.bad_source_policy_version:" + repr(source_policy_version))

    if parent is None:
        return BudgetEnvelope(ceiling=ceiling, source_policy_version=source_policy_version,
                               parent_ref=None)

    if not isinstance(parent, BudgetEnvelope):
        raise BudgetInvalidError("budget.bad_parent:" + repr(parent))
    remaining = parent.ceiling - already_allocated_from_parent
    if ceiling > remaining:
        raise BudgetExhaustedError(
            "budget.exceeds_parent_remaining:ceiling=" + str(ceiling) +
            ":remaining=" + str(remaining))
    return BudgetEnvelope(ceiling=ceiling, source_policy_version=source_policy_version,
                           parent_ref=_envelope_hash(parent))


def _envelope_hash(envelope):
    # ponytail: reuse records.py's canonical/content_hash pattern via a
    # tiny local canonical form rather than teaching records.py about a
    # fourth record shape it has no other reason to know.
    import hashlib
    import json
    payload = {"ceiling": envelope.ceiling, "source_policy_version": envelope.source_policy_version,
               "parent_ref": envelope.parent_ref}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_fits(envelope, content_size_bytes):
    """RO/03 §8 Exhaustion row: raise BudgetInfeasibleError, never truncate,
    if the minimum-sufficient content does not fit the ceiling."""
    if content_size_bytes > envelope.ceiling:
        raise BudgetInfeasibleError(
            "budget.content_exceeds_ceiling:size=" + str(content_size_bytes) +
            ":ceiling=" + str(envelope.ceiling))


if __name__ == "__main__":
    env = allocate_budget(1000, source_policy_version=1)
    assert env.ceiling == 1000 and env.parent_ref is None

    child = allocate_budget(400, source_policy_version=1, parent=env, already_allocated_from_parent=0)
    assert child.parent_ref is not None
    sibling = allocate_budget(500, source_policy_version=1, parent=env, already_allocated_from_parent=400)
    assert sibling.ceiling == 500

    try:
        allocate_budget(200, source_policy_version=1, parent=env, already_allocated_from_parent=900)
        raise SystemExit("over-remaining allocation accepted")
    except BudgetExhaustedError:
        pass

    try:
        allocate_budget(0, source_policy_version=1)
        raise SystemExit("zero ceiling accepted")
    except BudgetInvalidError:
        pass

    require_fits(env, 999)
    try:
        require_fits(env, 1001)
        raise SystemExit("over-ceiling content accepted")
    except BudgetInfeasibleError:
        pass

    # determinism: identical envelope construction -> identical parent_ref hash
    env2 = allocate_budget(1000, source_policy_version=1)
    child2 = allocate_budget(400, source_policy_version=1, parent=env2, already_allocated_from_parent=0)
    assert child.parent_ref == child2.parent_ref

    print("budget selftest ok")
