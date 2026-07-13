"""Immutable, versioned configuration snapshot (Config View).

All policy lives here as data (I13): envelope schemas, routing table, gate
definitions, transition table, fault policy. The view is read-only (I14);
new snapshots arrive only as config.changed events. Invalid snapshots are
rejected by validate(); the caller retains the last-good snapshot.
"""

REQUIRED_KEYS = {
    "version": int,
    "inbound_events": list,     # allowed inbound event names
    "envelope_schemas": dict,   # event_name -> required payload keys
    "routing_table": dict,      # declared type -> owning component
    "gates": dict,              # gate name -> {"check": predicate, ...}
    "transitions": dict,        # "state|event" -> list of rows
    "fault_policy": dict,       # max_replans, max_active_requests
}


def validate(data):
    """Return (ok, reason). Pure structural check, no judgment."""
    if not isinstance(data, dict):
        return False, "config.not_mapping"
    for key, typ in REQUIRED_KEYS.items():
        if key not in data:
            return False, "config.missing:" + key
        if not isinstance(data[key], typ):
            return False, "config.bad_type:" + key
    policy = data["fault_policy"]
    for key in ("max_replans", "max_active_requests"):
        if not isinstance(policy.get(key), int) or policy[key] < 0:
            return False, "config.bad_fault_policy:" + key
    for key, rows in data["transitions"].items():
        if not isinstance(rows, list) or not rows:
            return False, "config.bad_transition:" + key
        for row in rows:
            if not isinstance(row, dict) or "next" not in row or "emit" not in row:
                return False, "config.bad_transition_row:" + key
    return True, ""


class ConfigView:
    """Read-only snapshot. Callers never mutate; a new version replaces it."""

    __slots__ = ("_data",)

    def __init__(self, data):
        ok, reason = validate(data)
        if not ok:
            raise ValueError(reason)
        object.__setattr__(self, "_data", data)

    def __setattr__(self, name, value):
        raise AttributeError("ConfigView is read-only (I14)")

    @property
    def version(self):
        return self._data["version"]

    @property
    def inbound_events(self):
        return self._data["inbound_events"]

    @property
    def envelope_schemas(self):
        return self._data["envelope_schemas"]

    @property
    def routing_table(self):
        return self._data["routing_table"]

    @property
    def gates(self):
        return self._data["gates"]

    @property
    def fault_policy(self):
        return self._data["fault_policy"]

    def rows(self, state, event):
        """Transition-table lookup; None when the (state, event) pair is unmatched."""
        return self._data["transitions"].get(state + "|" + event)


if __name__ == "__main__":
    snap = {
        "version": 1,
        "inbound_events": ["request.received"],
        "envelope_schemas": {"request.received": ["declared_type"]},
        "routing_table": {"type.a": "planning"},
        "gates": {"completion": {"check": "verdict_true"}},
        "transitions": {"created|request.received": [{"next": "initialized", "emit": []}]},
        "fault_policy": {"max_replans": 2, "max_active_requests": 10},
    }
    assert validate(snap) == (True, "")
    view = ConfigView(snap)
    assert view.version == 1
    assert view.rows("created", "request.received")[0]["next"] == "initialized"
    assert view.rows("created", "nope") is None
    try:
        view.version = 2
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass
    bad = dict(snap)
    del bad["routing_table"]
    assert validate(bad) == (False, "config.missing:routing_table")
    bad2 = dict(snap, fault_policy={"max_replans": -1, "max_active_requests": 1})
    assert validate(bad2)[0] is False
    bad3 = dict(snap, transitions={"a|b": [{"emit": []}]})
    assert validate(bad3)[0] is False
    print("config_view selftest ok")
