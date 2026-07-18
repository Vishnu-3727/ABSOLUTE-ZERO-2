"""Default Config View snapshot: the phase-3 transition table and gate
definitions as pure data. Policy content lives here, never in coordinator
logic (I13). Requests are opaque typed work; the routing table entries below
are placeholders that deployments replace via config.changed.

Custody note (ERRATA C4): the request transition table below is
Lifecycle-owned *content* provisionally hosted in the Kernel's tree until
Lifecycle is implemented. Changing TRANSITIONS is a Lifecycle-policy change,
not a Kernel change; the Kernel only evaluates it.

Row schema:
  when     guard name evaluated by the coordinator (None = unconditional)
  next     state after the transition
  emit     event names published (in order) after the record is logged
  gate     gate name for gate.enforced payloads (optional)
  decision explicit permit/block override (optional; default: permit for the
           first row, block for a fallthrough row)
  actions  mechanical ledger mutations applied by the coordinator (optional)
  chain    internal follow-up trigger applied in the same event processing
"""

_NON_TERMINAL = ("created", "initialized", "scheduled", "executing", "verifying")
_TERMINAL = ("completed", "failed", "cancelled")

_CANCEL_ROW = [{
    "when": None, "next": "cancelled",
    "emit": ["request.cancelled", "gate.enforced"],
    "gate": "cancellation", "actions": ["set_cancel_flag"],
}]

TRANSITIONS = {
    "created|request.received": [
        {"when": "admission_ok", "next": "initialized",
         "emit": ["request.admitted", "gate.enforced"], "gate": "admission",
         "chain": "__routing__"},
        {"when": None, "next": "failed",
         "emit": ["request.rejected", "gate.enforced"], "gate": "admission",
         "decision": "block"},
    ],
    # Routing lookup happens in the same event processing as admission.
    "initialized|__routing__": [
        {"when": "routing_ok", "next": "scheduled",
         "emit": ["routing.directive"], "gate": "routing",
         "actions": ["set_routing_target"]},
        {"when": None, "next": "failed",
         "emit": ["request.rejected", "gate.enforced"], "gate": "routing",
         "decision": "block"},
    ],
    "scheduled|plan.created": [
        {"when": None, "next": "executing", "emit": []},
    ],
    "scheduled|plan.rejected": [
        {"when": None, "next": "scheduled", "emit": []},
    ],
    # Verdicts are recorded while executing; no transition.
    "executing|verify.passed": [
        {"when": None, "next": "executing", "emit": [], "actions": ["record_verdict"]},
    ],
    "executing|verify.failed": [
        {"when": None, "next": "executing", "emit": [], "actions": ["record_verdict"]},
    ],
    # Completion gate: a recorded verify.passed, never a default permit (I5).
    "executing|task.completed": [
        {"when": "gate:completion", "next": "completed",
         "emit": ["request.completed", "gate.enforced"], "gate": "completion"},
        {"when": None, "next": "verifying",
         "emit": ["gate.enforced"], "gate": "completion", "decision": "block"},
    ],
    # Replan loop bounded by fault policy max_replans (phase 7).
    "executing|task.failed": [
        {"when": "replans_remaining", "next": "scheduled", "emit": [],
         "actions": ["increment_replan"]},
        {"when": None, "next": "failed", "emit": ["request.failed"],
         "decision": "block"},
    ],
    "verifying|verify.passed": [
        {"when": None, "next": "completed",
         "emit": ["request.completed", "gate.enforced"], "gate": "completion",
         "actions": ["record_verdict"]},
    ],
    "verifying|verify.failed": [
        {"when": None, "next": "scheduled",
         "emit": ["gate.enforced"], "gate": "completion", "decision": "block",
         "actions": ["record_verdict"]},
    ],
}
# Cancellation is legal from every non-terminal state.
for _state in _NON_TERMINAL:
    TRANSITIONS[_state + "|request.cancelled"] = _CANCEL_ROW
# Terminal states: cancellation is a no-op, no state change, nothing emitted.
for _state in _TERMINAL:
    TRANSITIONS[_state + "|request.cancelled"] = [
        {"when": None, "next": _state, "emit": []},
    ]

DEFAULT = {
    "version": 1,
    "inbound_events": [
        "request.received", "request.cancelled",
        "plan.created", "plan.rejected",
        "task.completed", "task.failed",
        "verify.passed", "verify.failed",
        "config.changed", "session.wake", "session.sleep",
    ],
    "envelope_schemas": {
        "request.received": ["declared_type"],
        "config.changed": ["snapshot"],
    },
    "routing_table": {
        "type.alpha": "planning",
        "type.beta": "scheduling",
    },
    "gates": {
        "completion": {"check": "verdict_true", "verdict": "verification"},
    },
    "transitions": TRANSITIONS,
    "fault_policy": {"max_replans": 2, "max_active_requests": 1000},
}


def snapshot(**overrides):
    """Deep-copied default snapshot; keyword overrides replace top-level keys."""
    import copy
    data = copy.deepcopy(DEFAULT)
    data.update(overrides)
    return data


if __name__ == "__main__":
    from kernel.config_view import validate  # run: PYTHONPATH=src python -m kernel.default_config
    ok, reason = validate(DEFAULT)
    assert ok, reason
    assert DEFAULT["transitions"]["completed|request.cancelled"][0]["next"] == "completed"
    assert "created|request.cancelled" in DEFAULT["transitions"]
    two = snapshot(version=2)
    assert two["version"] == 2 and DEFAULT["version"] == 1
    two["routing_table"]["x"] = "y"
    assert "x" not in DEFAULT["routing_table"]
    print("default_config selftest ok")
