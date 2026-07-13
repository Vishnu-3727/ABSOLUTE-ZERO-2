"""Request-id-keyed materialization store (RSM/03-internal-design.md §2).

Two maps: `active` (states active/terminal/persisted — not yet inside the
retention window) and `retained` (state retained). Exactly one record per
request id across both maps (RSM-I1) — enforced structurally: creating a
duplicate id raises, mirroring kernel ledger.py's `_create`.

M1 wires only the birth and terminal paths (RSM/05-implementation-spec.md
M1). `mark_persisted` and the real `evict_gate` land here in M4 (terminal ->
persisted, RSM/03 §2, driving `mark_evicted` per RSM-I11's three
preconditions). `mark_evicted` itself is unchanged from M3 — it stays the
one place the evicted-id bookkeeping move happens; `evict_gate` is now its
real caller instead of a test-only direct marker.

# ponytail: the state diagram (RSM/03 §2) has an intermediate `retained`
# state ("persisted -> retention window opens -> retained -> retention
# window elapses -> evicted") between `persisted` and `evicted`. Nothing in
# RSM/03 gives "retention window opens" its own trigger distinct from the
# persist moment itself, so this module folds the two: `persisted_at` is
# both "durably written" and "retention window start," and `state_of`
# reports `persisted` for the whole window rather than a separate
# `retained` label. Ceiling: `query.status()` never returns "retained".
# Upgrade path: if a real distinct "window opens" trigger ever exists, add
# `mark_retained` and a RETAINED entry in `_state`, gated on that trigger,
# without touching `evict_gate`'s three-precondition logic below.
"""
from . import record as record_mod
from . import transitions

ABSENT = transitions.ABSENT
ACTIVE = transitions.ACTIVE
TERMINAL = transitions.TERMINAL
PERSISTED = transitions.PERSISTED
RETAINED = transitions.RETAINED
EVICTED = transitions.EVICTED


class Store:
    def __init__(self):
        self._active = {}    # request_id -> RequestRecord (active/terminal/persisted)
        self._retained = {}  # request_id -> RequestRecord (retained)
        self._state = {}     # request_id -> ACTIVE/TERMINAL/PERSISTED/RETAINED
        # ponytail: membership-only, unbounded — M4's real eviction will
        # replace this with whatever bounded record real eviction needs.
        self._evicted_ids = set()
        # request_id -> clock() value at mark_persisted time (M4). Doubles
        # as "is this id persisted" membership check and as the retention
        # window's start time for evict_gate's third precondition.
        self._persisted_at = {}

    # -- read side (anyone) ------------------------------------------------
    def state_of(self, request_id):
        if request_id in self._evicted_ids:
            return EVICTED
        return self._state.get(request_id, ABSENT)

    def get(self, request_id):
        """Current RequestRecord snapshot, or None (absent/evicted)."""
        rec = self._active.get(request_id)
        return rec if rec is not None else self._retained.get(request_id)

    def __contains__(self, request_id):
        return request_id in self._state

    def request_ids(self):
        return list(self._state)

    # -- birth path (RSM-I1, RSM-I10) --------------------------------------
    def create(self, request_id, identity_fields):
        """Birth: request.received is the sole creation trigger (RSM-I10).
        Raises if a record already exists for this id, in any state
        (RSM-I1 — exactly one record per id, no silent re-create)."""
        if self.state_of(request_id) != ABSENT:
            raise ValueError("store.duplicate_create:" + request_id)
        rec = record_mod.birth(request_id, identity_fields)
        self._active[request_id] = rec
        self._state[request_id] = ACTIVE
        return rec

    # -- contributing-family apply (M2) --------------------------------------
    def apply(self, request_id, new_record):
        """active -> active, or terminal/persisted/retained -> unchanged
        (late-tolerant family, RSM/03 §3). `new_record` is already the full
        post-reducer snapshot (`ingest` computed it via `reducers`) — store
        only swaps the pointer in whichever bucket currently holds this id.
        No materialization-state change; the caller (`ingest`) already
        resolved that from the transition-table row.
        """
        if request_id in self._active:
            self._active[request_id] = new_record
        elif request_id in self._retained:
            self._retained[request_id] = new_record
        else:
            raise ValueError("store.not_found:" + request_id)
        return new_record

    # -- terminal path (M2: reducer-dispatched) ------------------------------
    def apply_terminal(self, request_id, new_record):
        """active -> terminal (RSM/03 §2/§3, row "active | terminal family").

        `new_record` is the full post-reducer snapshot (Lifecycle block
        already updated by the terminal reducer in `reducers`) — store only
        performs the state-machine move and pointer swap. Replaces M1's
        hardcoded `mark_terminal(lifecycle_update)` path now that M2's
        reducer registry exists (RSM/05-implementation-spec.md M2).
        """
        if self.state_of(request_id) != ACTIVE:
            raise ValueError("store.not_active:" + request_id)
        self._active[request_id] = new_record
        self._state[request_id] = TERMINAL
        return new_record

    # -- persistence (M4) ----------------------------------------------------
    def mark_persisted(self, request_id, clock):
        """terminal -> persisted (RSM/03 §2), once `persistence.
        persist_terminal` has durably written the journal index + terminal
        snapshot via Storage. `clock` is a zero-arg callable returning a
        number (injectable, no wall-clock reads here) — its value at this
        moment becomes the retention window's start time for `evict_gate`.
        Precondition: currently TERMINAL, same not-the-right-state-raises
        style as `apply_terminal`'s ACTIVE-only guard."""
        if self.state_of(request_id) != TERMINAL:
            raise ValueError("store.not_terminal:" + request_id)
        self._state[request_id] = PERSISTED
        self._persisted_at[request_id] = clock()

    # -- eviction marking (M3: query needs a real evicted id to answer
    # against; M4: real three-precondition-gated eviction) ------------------
    def mark_evicted(self, request_id):
        """Move a record out of active/retained into the evicted-id set.

        # ponytail: no precondition check of its own — `evict_gate` (below)
        # is now the real, precondition-checked caller (M4); this method's
        # own semantics are unchanged from M3, where it was also the direct
        # marker M3's `query` tests used to exercise the evicted-id read
        # path (RSM/03 §2 "evicted ... queries answer 'evicted'"). Kept
        # argument-free and unconditional so both callers (tests, and
        # `evict_gate`) share one code path with no drift between them.
        """
        self._active.pop(request_id, None)
        self._retained.pop(request_id, None)
        self._state.pop(request_id, None)
        self._persisted_at.pop(request_id, None)
        self._evicted_ids.add(request_id)

    # -- recovery seeding (M5) ------------------------------------------------
    def seed(self, request_id, record):
        """Recovery-only bootstrap (RSM/05-implementation-spec.md M5,
        RSM/03 §1/§11): plant a checkpoint-derived record as the starting
        point for resuming a non-terminal request's fold, instead of
        refolding from event 1. The other legitimate direct writer of
        `_active`/`_state` besides `create` — distinct from the live
        reducer-mutation discipline RSM-I2 governs (this is RSM's own
        restart-time reconstruction, RSM/03 §1 bullets 2-3, a different
        phase entirely, running before the read surface has even reopened).
        Seeds as ACTIVE only — the recovery scenario this exists for is
        non-terminal-request resumption (§1 "identify non-terminal requests
        as of the crash"); a terminal-and-later request is already durably
        finalized and needs only `recovery.replay_journal` for byte-
        identical verification, not a bounded-cost resume. Raises if the id
        is already present — seed is a once-per-recovery bootstrap, never
        an overwrite of a live record."""
        if self.state_of(request_id) != ABSENT:
            raise ValueError("store.seed_conflict:" + request_id)
        self._active[request_id] = record
        self._state[request_id] = ACTIVE

    # -- eviction gate (M4) ---------------------------------------------------
    def evict_gate(self, request_id, clock, retention_window):
        """RSM-I11: eviction requires all three preconditions — terminal,
        journal persisted, retention elapsed. `clock` is a zero-arg callable
        (injectable time source); `retention_window` is the caller-supplied
        number (read from `config_view`'s `retention_window` upstream —
        `store` holds no config dependency of its own, same shape as
        `apply()` already receiving an already-computed `new_record`).

        Drives `mark_evicted` when all three hold; otherwise a no-op,
        returning False. Returns True exactly when eviction just happened.
        """
        state = self.state_of(request_id)
        terminal = state in (TERMINAL, PERSISTED, RETAINED)
        persisted_at = self._persisted_at.get(request_id)
        persisted = persisted_at is not None
        retention_elapsed = persisted and (clock() - persisted_at) >= retention_window
        if eviction_allowed(terminal, persisted, retention_elapsed):
            self.mark_evicted(request_id)
            return True
        return False


def eviction_allowed(terminal, persisted, retention_elapsed):
    """RSM-I11's three-precondition predicate, kept as a pure free function
    deliberately separate from `evict_gate`'s store plumbing: `evict_gate`
    only ever observes combinations the store's own transition coupling can
    reach (e.g. `persisted` implies `terminal` already happened), but the
    M4 property test (RSM/05-implementation-spec.md M4: "all 2^3 - 1
    partial-precondition combinations, each must NOT evict") needs to drive
    every combination directly, including ones the real state machine can
    never produce. Testing the predicate in isolation is how that coverage
    is achieved without forcing `Store` into unreachable internal states.
    """
    return bool(terminal and persisted and retention_elapsed)


if __name__ == "__main__":
    store = Store()
    assert store.state_of("r1") == ABSENT and "r1" not in store

    rec = store.create("r1", {"declared_type": "type.alpha"})
    assert store.state_of("r1") == ACTIVE
    assert store.get("r1") is rec and "r1" in store

    try:
        store.create("r1", {})
        raise SystemExit("duplicate create allowed")
    except ValueError:
        pass

    term = store.apply_terminal("r1", rec.evolve(lifecycle={"state": "completed"}))
    assert store.state_of("r1") == TERMINAL
    assert term.version == 1 and term.lifecycle == {"state": "completed"}
    assert store.get("r1") is term

    try:
        store.apply_terminal("r1", term.evolve(lifecycle={"state": "completed"}))
        raise SystemExit("terminal-from-terminal allowed")
    except ValueError:
        pass

    clock_box = [100]
    clock = lambda: clock_box[0]  # noqa: E731 — injectable time source, test-local

    # not yet persisted: gate refuses regardless of elapsed time
    assert store.evict_gate("r1", clock, retention_window=0) is False
    assert store.state_of("r1") == TERMINAL

    store.mark_persisted("r1", clock)
    assert store.state_of("r1") == PERSISTED

    try:
        store.mark_persisted("r1", clock)  # not TERMINAL anymore
        raise SystemExit("re-persist from persisted allowed")
    except ValueError:
        pass

    # persisted, but retention window has not elapsed yet
    assert store.evict_gate("r1", clock, retention_window=50) is False
    assert store.state_of("r1") == PERSISTED

    # retention elapses -> gate fires and drives mark_evicted
    clock_box[0] += 50
    assert store.evict_gate("r1", clock, retention_window=50) is True
    assert store.state_of("r1") == EVICTED
    assert store.get("r1") is None
    assert "r1" not in store  # falls out of _state, membership goes through evicted set only

    # eviction_allowed: pure predicate, all 2^3-1 partial combos False, all-True True
    for terminal in (False, True):
        for persisted in (False, True):
            for retention_elapsed in (False, True):
                expect = terminal and persisted and retention_elapsed
                assert eviction_allowed(terminal, persisted, retention_elapsed) is expect

    store2 = Store()
    try:
        store2.apply_terminal("never-born", None)
        raise SystemExit("terminal on absent id allowed")
    except ValueError:
        pass

    # seed (M5 recovery bootstrap): plants a record directly as ACTIVE
    seeded = record_mod.birth("r9", {"declared_type": "a"}).evolve(work={"tasks": {}})
    store3 = Store()
    store3.seed("r9", seeded)
    assert store3.state_of("r9") == ACTIVE
    assert store3.get("r9") is seeded

    try:
        store3.seed("r9", seeded)  # already present
        raise SystemExit("re-seed over existing id allowed")
    except ValueError:
        pass

    print("store selftest ok")
