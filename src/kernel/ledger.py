"""In-memory Request Ledger. Coordinator is the sole mutator (I1).

Mutator methods are module-private (leading underscore) and must only be
called from the coordinator module — the structural test IT-7 enforces this
by source scan. Everyone else reads via get()/active_count(). The Ledger is
in-memory only (I16); the transition log is the durable record.
"""
from dataclasses import dataclass, field

NON_TERMINAL_STATES = ("created", "initialized", "scheduled", "executing", "verifying")
TERMINAL_STATES = ("completed", "failed", "cancelled")


@dataclass
class RequestState:
    """Phase-4 RequestState entry. Fields mutated only by the coordinator."""
    request_id: str
    declared_type: str = ""
    lifecycle_state: str = "created"
    config_version: int = 0
    recorded_verdicts: dict = field(default_factory=dict)  # gate -> bool
    # ponytail: phase-4 pending_gates dropped — derivable from the transition
    # table (gates pending = guarded rows not yet permitted); never read.
    routing_target: str | None = None
    cancellation_flag: bool = False
    transition_sequence: int = 0
    last_applied_event_id: str | None = None  # inbound dedup key (D6a)
    replan_count: int = 0


class Ledger:
    def __init__(self):
        self._entries = {}

    # -- read side (anyone) --------------------------------------------
    def get(self, request_id):
        return self._entries.get(request_id)

    def __len__(self):
        return len(self._entries)

    def __contains__(self, request_id):
        return request_id in self._entries

    def active_count(self):
        return sum(1 for e in self._entries.values()
                   if e.lifecycle_state in NON_TERMINAL_STATES)

    def request_ids(self):
        return list(self._entries)

    # -- write side (coordinator module ONLY, per I1) -------------------
    def _create(self, entry):
        if entry.request_id in self._entries:
            raise ValueError("ledger.duplicate_entry")
        self._entries[entry.request_id] = entry

    def _evict(self, request_id):
        self._entries.pop(request_id, None)


if __name__ == "__main__":
    ledger = Ledger()
    entry = RequestState(request_id="r1", declared_type="type.alpha")
    ledger._create(entry)
    assert ledger.get("r1") is entry
    assert "r1" in ledger and len(ledger) == 1
    assert ledger.active_count() == 1
    entry.lifecycle_state = "completed"
    assert ledger.active_count() == 0
    try:
        ledger._create(RequestState(request_id="r1"))
        raise SystemExit("duplicate create allowed")
    except ValueError:
        pass
    ledger._evict("r1")
    assert "r1" not in ledger
    ledger._evict("r1")  # idempotent
    print("ledger selftest ok")
