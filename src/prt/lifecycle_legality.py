"""PRT lifecycle-legality adapter — PRT/05 boundary ruling (reviewer):
"replace remaining doubles" applies ONLY to PRT-side stand-ins; Lifecycle
itself is a SEPARATE, unbuilt subsystem (PRT/00 §2 C7, PRT-A4) and PRT
absorbing it would violate the ownership wall. This module is therefore
NOT a Lifecycle implementation — it is the Lifecycle-CONTRACT adapter PRT
enacts against until the real Lifecycle component exists: a real
transition-table legality machine (not an allow-everything stand-in) that
encodes exactly the plugin operational-state legality health.py (PRT/04
§3) and load_policy.py (PRT/03 §9) already request, data-driven from the
frozen ARCHITECTURE.md/PRT/03/PRT/04 tables.

Callable signature matches the existing injected legality callables
verbatim: `(subject_id, from_state, to_state) -> bool`. Two tables, one
class (`LifecycleLegality(table)`) — a health-state instance and a
load-state instance, since PRT/03 Ruling 3 / PRT/04 §3 keep the two state
machines separate (never one merged legality surface).

`on_lifecycle_event` lets an eventual real Lifecycle publish an
authoritative decision (`plugin.lifecycle.changed`) that PRT must enact
regardless of the local table (PRT-A4: PRT enacts, never originates) —
recorded so it is auditable, and so a subsequent legality check for that
exact (subject, from, to) is granted even where the local table alone
would refuse it. Registry-entity lifecycle events (capability/provider
retirement, entity="capability"/"provider") are a DIFFERENT concern,
already fully handled by retirement.py's enact_lifecycle_event — this
module only overrides HEALTH/LOAD operational-state legality, keyed by
{"subject_id", "from_state", "to_state"} in the event payload.
"""
from . import events

# Exactly the (from, to) pairs health.py's own _step ever proposes to its
# injected legality callable — grep-verified against every branch of
# _step (PRT/04 §3). UNAVAILABLE and every admin-driven transition
# (force_quarantine/force_release/disable/enable) bypass the legality gate
# entirely inside health.py itself (its own comment: "Administrative acts
# ... bypass the evidence-threshold legality gate entirely"), so they are
# never presented to a legality callable and are correctly absent below —
# refusing everything not listed here is exactly "refuse everything else."
HEALTH_TRANSITIONS = frozenset({
    ("HEALTHY", "DEGRADED"),
    ("HEALTHY", "QUARANTINED"),
    ("DEGRADED", "QUARANTINED"),
    ("DEGRADED", "HEALTHY"),
    ("QUARANTINED", "RECOVERING"),
    ("RECOVERING", "QUARANTINED"),
    ("RECOVERING", "RECOVERED"),
    ("RECOVERED", "QUARANTINED"),
    ("RECOVERED", "DEGRADED"),
    ("RECOVERED", "HEALTHY"),
})

# PRT/03 §9's frozen load-state diagram: Not Loaded -> Loading -> Prepared
# -> Loaded -> Released, Unavailable reachable from any of these, Released
# -> Loading on reload. Mirrors load_policy.py's own (private, leading-
# underscore) shape-gate table verbatim — duplicated as frozen module data
# here rather than reached-into, since that name is private to
# load_policy.py and this module must not cross into another module's
# internals to read it (single source of truth is PRT/03 §9 itself; both
# tables are its restatement, not each other's).
LOAD_TRANSITIONS = frozenset({
    ("NOT_LOADED", "LOADING"), ("NOT_LOADED", "UNAVAILABLE"),
    ("LOADING", "PREPARED"), ("LOADING", "UNAVAILABLE"),
    ("PREPARED", "LOADED"), ("PREPARED", "UNAVAILABLE"),
    ("LOADED", "RELEASED"), ("LOADED", "UNAVAILABLE"),
    ("RELEASED", "LOADING"), ("RELEASED", "UNAVAILABLE"),
    ("UNAVAILABLE", "NOT_LOADED"),
})

_OVERRIDE_KEYS = ("subject_id", "from_state", "to_state")


class LifecycleLegality:
    """A real transition-table legality machine — `(subject_id, from_state,
    to_state) -> bool`, injectable and overridable by an externally-decided
    `plugin.lifecycle.changed` event, per the boundary ruling's Lifecycle-
    contract-adapter framing. Every call and every consumed event is
    recorded (auditable, PRT-A12-style discipline extended here)."""

    def __init__(self, table):
        self._table = frozenset(table)
        self.calls = []       # (subject_id, from_state, to_state) audit
        self.events = []      # every plugin.lifecycle.changed payload consumed
        self._overrides = set()  # {(subject_id, from_state, to_state)}

    def __call__(self, subject_id, from_state, to_state):
        self.calls.append((subject_id, from_state, to_state))
        if (subject_id, from_state, to_state) in self._overrides:
            return True
        return (from_state, to_state) in self._table

    def on_lifecycle_event(self, event):
        """Consume one plugin.lifecycle.changed payload. Recorded
        unconditionally (auditable); becomes a standing override only if it
        carries the health/load operational-state shape
        ({"subject_id", "from_state", "to_state"}) — a registry-entity
        shaped payload ({"entity", "id", "to_state"}) is retirement.py's
        concern, not this module's, and is simply logged here, not acted
        on."""
        events.check_consumed("plugin.lifecycle.changed")
        self.events.append(dict(event))
        if all(key in event for key in _OVERRIDE_KEYS):
            self._overrides.add(
                (event["subject_id"], event["from_state"], event["to_state"]))


def default_health_legality():
    """One fresh HEALTH_TRANSITIONS-table machine — the new src/ default
    replacing AllowAllLegality (boundary ruling: AllowAllLegality survives
    only as an explicit test fixture from here on)."""
    return LifecycleLegality(HEALTH_TRANSITIONS)


def default_load_legality():
    """One fresh LOAD_TRANSITIONS-table machine — the load-lifecycle
    counterpart, constructed explicitly by whoever wires a LoadStateTracker
    (runtime.py), never a hidden default inside load_policy.py itself."""
    return LifecycleLegality(LOAD_TRANSITIONS)


if __name__ == "__main__":
    health_legality = default_health_legality()

    # every transition health.py's _step can request is legal
    for pair in HEALTH_TRANSITIONS:
        assert health_legality("prov.x", *pair) is True

    # everything else is refused: same-state, reverse, and any UNAVAILABLE
    # edge (admin-only in health.py, never presented here in practice, but
    # the table itself must still refuse it defensively)
    assert health_legality("prov.x", "HEALTHY", "HEALTHY") is False
    assert health_legality("prov.x", "QUARANTINED", "HEALTHY") is False
    assert health_legality("prov.x", "HEALTHY", "UNAVAILABLE") is False
    assert len(health_legality.calls) == len(HEALTH_TRANSITIONS) + 3

    load_legality = default_load_legality()
    for pair in LOAD_TRANSITIONS:
        assert load_legality("prov.y", *pair) is True
    assert load_legality("prov.y", "LOADED", "LOADING") is False

    # override: an authoritative plugin.lifecycle.changed decision wins
    # even where the table alone would refuse
    fresh = default_health_legality()
    assert fresh("prov.z", "QUARANTINED", "DEGRADED") is False  # not in table
    fresh.on_lifecycle_event({"subject_id": "prov.z", "from_state": "QUARANTINED",
                             "to_state": "DEGRADED"})
    assert fresh("prov.z", "QUARANTINED", "DEGRADED") is True  # now overridden
    assert len(fresh.events) == 1

    # registry-entity shaped event: recorded, but not acted on as an override
    fresh.on_lifecycle_event({"entity": "provider", "id": "prov.q", "to_state": "retired"})
    assert len(fresh.events) == 2
    assert fresh("prov.q", "HEALTHY", "QUARANTINED") is True  # already legal via table

    # on_lifecycle_event gates through events.check_consumed("plugin.
    # lifecycle.changed") unconditionally -- this is PRT's own declared
    # consume vocabulary, never the payload's own (there is no payload
    # event_name field here); a partial payload lacking the override keys
    # is simply logged, never raises.
    fresh.on_lifecycle_event({})
    assert len(fresh.events) == 3

    print("lifecycle_legality selftest ok")
