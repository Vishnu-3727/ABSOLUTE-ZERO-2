"""Record-state x event-family transition table (RSM/03-internal-design.md
§2-§3), verbatim as data — table lookup, never judgment (kernel gates.py
precedent: "pure function, (state, event) -> row"). This module decides
nothing about domain content; it only classifies which family bucket an
incoming event falls into and returns the §3 row for
(state, family[, duplicate, malformed]).

lookup() is pipeline-ordered exactly like RSM/03 §4's steps 1-5: dedup
check, then evicted-state fault-no-resurrect, then unregistered-family
count, then the state x family table row itself, with "malformed" folded
into whichever row would otherwise have applied (§4 step 5, "reducer apply
... schema invalid -> fault.recorded").
"""

# -- record materialization states (RSM/03 §2) -------------------------------
ABSENT, ACTIVE, TERMINAL, PERSISTED, RETAINED, EVICTED = (
    "absent", "active", "terminal", "persisted", "retained", "evicted")

STATES = (ABSENT, ACTIVE, TERMINAL, PERSISTED, RETAINED, EVICTED)

# states where terminal/retained/persisted's shared "late-tolerant only"
# rule applies (RSM/03 §3: "persisted is not read-only-yet-mutable-again").
_TERMINAL_LIKE = (TERMINAL, PERSISTED, RETAINED)

# -- event family classification (RSM/03 §4 reducer registry) ---------------
BIRTH_FAMILY = "request.received"

# ponytail: RSM/03 §5 item 3 names this "a cancellation event" without a
# literal event name; request.cancelled matches ARCHITECTURE.md's
# request.* naming pattern. Upgrade path: rename here if Kernel's real
# cancellation event name differs once wired.
TERMINAL_FAMILIES = frozenset({
    "request.completed", "request.failed", "request.rejected", "request.cancelled",
})

LATE_TOLERANT_FAMILIES = frozenset({"cost.recorded"})  # RSM/03 §3 decision

CONTRIBUTING_FAMILIES = frozenset({
    "intent.classified", "plan.created", "plan.revised", "plan.validated",
    "plan.rejected", "task.scheduled", "task.started", "task.preempted",
    "task.completed", "task.failed", "exec.started", "exec.completed",
    "exec.timeout", "exec.failed", "context.assembled", "verify.requested",
    "verify.passed", "verify.failed", "storage.committed", "storage.rejected",
    "fault.recorded",
})

REGISTERED_FAMILIES = (
    {BIRTH_FAMILY} | CONTRIBUTING_FAMILIES | TERMINAL_FAMILIES | LATE_TOLERANT_FAMILIES
)

# -- row actions ---------------------------------------------------------
CREATE = "create"
APPLY = "apply"
APPLY_TERMINAL = "apply_terminal"
FAULT = "fault"
DROP = "drop"
UNREGISTERED = "unregistered"


class Row:
    """One transition-table outcome: what to do, and the next materialization
    state. `next_state == state` for every "unchanged" row in RSM/03 §3."""
    __slots__ = ("action", "next_state")

    def __init__(self, action, next_state):
        self.action = action
        self.next_state = next_state

    def __eq__(self, other):
        return isinstance(other, Row) and (self.action, self.next_state) == (
            other.action, other.next_state)

    def __repr__(self):
        return "Row(%s -> %s)" % (self.action, self.next_state)


def lookup(state, family, duplicate=False, malformed=False):
    """(state, family) -> Row, per RSM/03 §3's transition table."""
    if state not in STATES:
        raise ValueError("transitions.unknown_state:" + str(state))

    # step 1 (RSM/03 §4): dedup — silent drop, only once a journal can
    # exist for this id (absent/evicted have none).
    if duplicate and state in (ACTIVE,) + _TERMINAL_LIKE:
        return Row(DROP, state)

    # step 3 (RSM/03 §4): unregistered family — counted, not applied, not
    # faulted. This precedes the table row lookup (step 4), so it also
    # precedes evicted's fault-no-resurrect rule below: RSM never even
    # notices an event whose family it has no reducer for, evicted or not.
    if family not in REGISTERED_FAMILIES:
        return Row(UNREGISTERED, state)

    # evicted-state fault-no-resurrect: any *registered* event, including
    # birth (RSM-I10).
    if state == EVICTED:
        return Row(FAULT, EVICTED)

    if state == ABSENT:
        if family != BIRTH_FAMILY:
            return Row(FAULT, ABSENT)  # unknown-id non-birth event (RSM-I10)
        return Row(FAULT, ABSENT) if malformed else Row(CREATE, ACTIVE)

    if state == ACTIVE:
        if family == BIRTH_FAMILY:
            return Row(FAULT, ACTIVE)  # duplicate request.received (RSM-I1)
        if malformed:
            return Row(FAULT, ACTIVE)
        if family in TERMINAL_FAMILIES:
            return Row(APPLY_TERMINAL, TERMINAL)
        return Row(APPLY, ACTIVE)  # contributing family, incl. late-tolerant

    if state in _TERMINAL_LIKE:
        if family == BIRTH_FAMILY:
            return Row(FAULT, state)
        if family in LATE_TOLERANT_FAMILIES:
            return Row(FAULT, state) if malformed else Row(APPLY, state)
        return Row(FAULT, state)  # any other recognized family, late

    raise AssertionError("transitions.unreachable")  # pragma: no cover


if __name__ == "__main__":
    # birth
    assert lookup(ABSENT, BIRTH_FAMILY) == Row(CREATE, ACTIVE)
    assert lookup(ABSENT, "task.scheduled") == Row(FAULT, ABSENT)
    assert lookup(ABSENT, "request.completed") == Row(FAULT, ABSENT)

    # active
    assert lookup(ACTIVE, "task.scheduled") == Row(APPLY, ACTIVE)
    assert lookup(ACTIVE, "request.completed") == Row(APPLY_TERMINAL, TERMINAL)
    assert lookup(ACTIVE, BIRTH_FAMILY) == Row(FAULT, ACTIVE)  # duplicate create (RSM-I1)
    assert lookup(ACTIVE, "task.scheduled", duplicate=True) == Row(DROP, ACTIVE)

    # terminal / persisted / retained share the late-tolerant-only rule
    for st in _TERMINAL_LIKE:
        assert lookup(st, "cost.recorded") == Row(APPLY, st)
        assert lookup(st, "task.scheduled") == Row(FAULT, st)
        assert lookup(st, "cost.recorded", duplicate=True) == Row(DROP, st)
        assert lookup(st, BIRTH_FAMILY) == Row(FAULT, st)

    # evicted: fault, no resurrect, even for birth
    assert lookup(EVICTED, BIRTH_FAMILY) == Row(FAULT, EVICTED)
    assert lookup(EVICTED, "task.scheduled") == Row(FAULT, EVICTED)

    # unregistered family: any state, unchanged, not a fault
    for st in STATES:
        assert lookup(st, "memory.indexed") == Row(UNREGISTERED, st)

    # malformed event of a registered family: fault, unchanged
    assert lookup(ABSENT, BIRTH_FAMILY, malformed=True) == Row(FAULT, ABSENT)
    assert lookup(ACTIVE, "task.scheduled", malformed=True) == Row(FAULT, ACTIVE)
    assert lookup(TERMINAL, "cost.recorded", malformed=True) == Row(FAULT, TERMINAL)

    print("transitions selftest ok")
