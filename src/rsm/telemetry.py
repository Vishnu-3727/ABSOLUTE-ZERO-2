"""Coalesced RSM observability emissions (RSM/03-internal-design.md §8;
RSM/05-implementation-spec.md M5). `state.updated`: immediate for a
Lifecycle-block change (birth and the terminal Lifecycle family — the two
transition-table actions CREATE and APPLY_TERMINAL, RSM/03 §3), coalesced —
at most one emission per request per `config_view.coalescing_interval` —
for every other applied-event change (Plan/Work/Context/Verification/
Budget/Failure-block changes, transition-table action APPLY).
`state.evicted`: always immediate, one per eviction, never coalesced.
`fault.recorded`: passthrough, one per fault path, never coalesced.
RSM-I15: every emission here is inert data for Observability — nothing in
`src/rsm/` reads these back to gate a decision (checked by the structural
test in tests/test_rsm_phase5.py).

# ponytail: birth (CREATE) is classified as immediate alongside the
# terminal Lifecycle family. RSM/03 §8's coalescing table names only two
# categories — "Lifecycle-block change" and "Work/Context/Budget-block
# change" — and doesn't literally place record creation in either (birth
# writes the Identity block, not Lifecycle). Treating it as immediate is
# the conservative reading: a birth is exactly as rare and Frontend-
# relevant as a terminal transition (one per request, materialization-
# state-defining), so delaying it behind a coalescing interval would
# recreate the exact problem §8 designed lifecycle-immediacy to avoid.
# Ceiling: this is an interpretation, not a literal spec row. Upgrade
# path: if a future RSM/03 revision gives birth its own row, swap this
# classification for that row's literal answer.

# ponytail: "coalesced" here means cadence-limited (a leaky-bucket-style
# rate limit: an eligible change emits immediately if the configured
# interval has elapsed since this request's last emission, otherwise it is
# counted and dropped), not batched (accumulating suppressed changes into
# one combined payload). RSM-I15 already establishes state.updated carries
# no control semantics and nothing downstream depends on a merged diff —
# a reader who needs *current* state calls `query`, which is always live
# and never coalesced (query.py is untouched by telemetry entirely).
# Ceiling: a suppressed emission's specific field-level change is not
# individually recoverable from telemetry after the fact, only its count
# (`coalescing_backlog` counter). Upgrade path: accumulate a per-request
# "changed families since last emit" set if a consumer ever needs the
# merged diff rather than "something changed, go read query".
"""
from . import transitions

_IMMEDIATE_ACTIONS = (transitions.CREATE, transitions.APPLY_TERMINAL)


class Telemetry:
    """Emits onto an injected bus double (`bus_double.BusDouble`, or any
    object with a `publish(topic, message)` method — duck-typed, same shape
    `persistence` uses for its Storage double). `clock` is the same
    injectable zero-arg time source used throughout M4 (`store.mark_
    persisted`, `store.evict_gate`) — no wall-clock reads here either.
    `config_view` supplies `coalescing_interval` (RsmConfigView, M4)."""

    def __init__(self, bus, config_view, clock):
        self.bus = bus
        self.config_view = config_view
        self.clock = clock
        self._last_emit = {}  # request_id -> clock() value at last coalesced emit
        self.counters = {
            "state_updated": 0, "state_evicted": 0, "fault_recorded": 0,
            "coalescing_backlog": 0,
        }

    def state_updated(self, request_id, family, immediate=False):
        """RSM/03 §8 `state.updated` row. `immediate` is the caller's own
        classification (`ingest` passes `row.action in _IMMEDIATE_ACTIONS`
        via transitions' own CREATE/APPLY_TERMINAL vocabulary — see
        `_IMMEDIATE_ACTIONS`). Returns True if an emission actually
        happened, False if a coalesced change was suppressed (still
        counted in `coalescing_backlog` — RSM-I14: suppressed is not
        silent, it's a counted-and-deferred entry)."""
        now = self.clock()
        if not immediate:
            last = self._last_emit.get(request_id)
            if last is not None and (now - last) < self.config_view.coalescing_interval:
                self.counters["coalescing_backlog"] += 1
                return False
        self.bus.publish("state.updated",
                          {"request_id": request_id, "family": family, "at": now})
        self._last_emit[request_id] = now
        self.counters["state_updated"] += 1
        return True

    def state_evicted(self, request_id):
        """RSM/03 §8: always immediate, one per eviction, never coalesced."""
        self.bus.publish("state.evicted", {"request_id": request_id, "at": self.clock()})
        self.counters["state_evicted"] += 1

    def fault_recorded(self, request_id, family, reason):
        """RSM/03 §8: every fault path, never coalesced."""
        self.bus.publish("fault.recorded",
                          {"request_id": request_id, "family": family, "reason": reason,
                           "at": self.clock()})
        self.counters["fault_recorded"] += 1

    def health(self, ingest):
        """RSM's own counters for its own observability (RSM/03 §8 "no
        metrics beyond own counters"): dedup-drop/unregistered/fault/
        applied counts already live on `ingest.counters` (real since M2) —
        reused here rather than re-tracked a second time; coalescing
        backlog is the one counter this module owns."""
        return dict(ingest.counters, coalescing_backlog=self.counters["coalescing_backlog"])


def evict_and_notify(store, telemetry, request_id, clock, retention_window):
    """Runs `store.evict_gate` (M4) and, if eviction just happened, emits
    `state.evicted` (RSM/03 §8: one per eviction, always). Kept outside
    `Store` — `store.py` owns only the eviction bookkeeping/gate predicate
    (RSM-I11), never a telemetry dependency of its own (RSM-I15: telemetry
    is call-site wiring, not something a mutation primitive reaches into).
    Same caller-invoked-trigger shape M4 already established for
    `persistence.persist_terminal`/`maybe_checkpoint`."""
    evicted = store.evict_gate(request_id, clock, retention_window)
    if evicted:
        telemetry.state_evicted(request_id)
    return evicted


if __name__ == "__main__":
    from .config_view import RsmConfigView

    class _FakeBus:
        def __init__(self):
            self.published = []

        def publish(self, topic, message):
            self.published.append((topic, message))

    class _Clock:
        def __init__(self, t=0):
            self.t = t

        def __call__(self):
            return self.t

    bus = _FakeBus()
    cfg = RsmConfigView(retention_window=100, checkpoint_n=10, coalescing_interval=5)
    clock = _Clock(0)
    tel = Telemetry(bus, cfg, clock)

    # Lifecycle-block change (immediate): every call emits, no coalescing
    assert tel.state_updated("r1", "request.received", immediate=True) is True
    clock.t += 1
    assert tel.state_updated("r1", "request.completed", immediate=True) is True
    assert tel.counters["state_updated"] == 2

    # Work/Context/Budget-block change (coalesced): first emits, rapid
    # follow-ups within the interval are suppressed and counted
    assert tel.state_updated("r2", "task.scheduled", immediate=False) is True
    clock.t += 1
    assert tel.state_updated("r2", "cost.recorded", immediate=False) is False
    clock.t += 1
    assert tel.state_updated("r2", "cost.recorded", immediate=False) is False
    assert tel.counters["coalescing_backlog"] == 2
    # interval elapses: next change emits again
    clock.t += 5
    assert tel.state_updated("r2", "cost.recorded", immediate=False) is True
    assert tel.counters["state_updated"] == 4  # r1's 2 immediate + r2's 2 emitted

    # eviction: always immediate, never coalesced by the interval logic
    tel.state_evicted("r3")
    assert tel.counters["state_evicted"] == 1
    assert bus.published[-1] == ("state.evicted", {"request_id": "r3", "at": clock.t})

    # fault: passthrough, one per call
    tel.fault_recorded("r4", "task.started", "unknown_id")
    assert tel.counters["fault_recorded"] == 1

    # health() merges ingest's own counters with telemetry's own backlog
    class _FakeIngest:
        counters = {"applied": 5, "dedup_drop": 1, "fault": 1, "unregistered": 2}

    h = tel.health(_FakeIngest())
    assert h["applied"] == 5 and h["coalescing_backlog"] == 2

    # evict_and_notify wiring
    from .store import Store
    store = Store()
    store.create("r5", {"declared_type": "a"})
    store.apply_terminal("r5", store.get("r5").evolve(lifecycle={"state": "completed"}))
    store.mark_persisted("r5", clock)
    clock.t += 100
    fired = evict_and_notify(store, tel, "r5", clock, retention_window=100)
    assert fired is True
    assert tel.counters["state_evicted"] == 2

    print("telemetry selftest ok")
