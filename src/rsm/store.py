"""Request-id-keyed materialization store (RSM/03-internal-design.md §2).

Two maps: `active` (states active/terminal/persisted — not yet inside the
retention window) and `retained` (state retained). Exactly one record per
request id across both maps (RSM-I1) — enforced structurally: creating a
duplicate id raises, mirroring kernel ledger.py's `_create`.

M1 wires only the birth and terminal paths (RSM/05-implementation-spec.md
M1). Reducer-driven contributing-family updates, persistence, retention and
real eviction are later milestones; `evict_gate` below is an honest stub for
M4 (see its docstring). `mark_evicted` is the direct marker M3's `query`
module needs to exercise the evicted-id read path ahead of M4's real gate.
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

    # -- eviction marking (M3: query needs a real evicted id to answer
    # against; M4: real three-precondition-gated eviction) ------------------
    def mark_evicted(self, request_id):
        """Move a record out of active/retained into the evicted-id set.

        # ponytail: no precondition check — matches `evict_gate`'s existing
        # honesty (it always answers False, since persistence/retention
        # don't exist yet). M4 wires `evict_gate` as the real gate driving
        # this call automatically; until then this is the direct marker
        # M3's `query` module tests need to exercise the evicted-id read
        # path (RSM/03 §2 "evicted ... queries answer 'evicted'").
        """
        self._active.pop(request_id, None)
        self._retained.pop(request_id, None)
        self._state.pop(request_id, None)
        self._evicted_ids.add(request_id)

    # -- eviction gate (M4 stub) ---------------------------------------------
    def evict_gate(self, request_id):
        """RSM-I11: eviction requires all three preconditions — terminal,
        journal persisted, retention elapsed.

        # ponytail: honest stub. `persistence` (M4) and `config_view` (M4,
        # retention window) don't exist yet in M1/M1-adjacent code, so
        # "persisted" can never be true here — this always answers False.
        # Upgrade path: RSM/05-implementation-spec.md M4 wires the real
        # three-precondition check and this becomes a real gate.
        """
        return False


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

    assert store.evict_gate("r1") is False  # M4 stub

    store.mark_evicted("r1")
    assert store.state_of("r1") == EVICTED
    assert store.get("r1") is None
    assert "r1" not in store  # falls out of _state, membership goes through evicted set only

    store2 = Store()
    try:
        store2.apply_terminal("never-born", None)
        raise SystemExit("terminal on absent id allowed")
    except ValueError:
        pass

    print("store selftest ok")
