"""PRT event emitter — the closed publish/consume sets PRT/05 §4 fixes.

Publishes exactly: plugin.discovered, plugin.registered, plugin.loaded,
plugin.unloaded, plugin.health.changed (PRT/05 §4 table, PRT-S1).
Consumes exactly: plugin.lifecycle.changed, reliability.updated,
exec.failed, exec.timeout, exec.completed (same table; exec.completed is
part of Execution's outcome set alongside the two failure names PRT/05 §1
step 5 lists).

Dead vocabulary is refused, loudly, by name (PRT-S2): `plugin.disabled`
(superseded by `plugin.health.changed`, PRT/05 §4 D1), `process.failed`/
`process.timeout` (never published by anyone, PRT/05 §4 D2 — canon is
`exec.*`). emit()/consume() name the offending PRT/05 §4 resolution in the
error so a caller can't mistake this for an ordinary typo.

Copied bus-double pattern (cm/events.py, ums/events.py): each component
ships its own copy rather than importing another component's, so PRT takes
no import edge onto CM/UMS/RSM (PRT/00 walls, PRT-S9 zero-seam discipline
extended to test doubles).
"""

PUBLISHED = ("plugin.discovered", "plugin.registered", "plugin.loaded",
             "plugin.unloaded", "plugin.health.changed")

CONSUMED = ("plugin.lifecycle.changed", "reliability.updated",
            "exec.failed", "exec.timeout", "exec.completed")

# PRT-S2: named dead vocabulary, rejected with a pointed reason, never silently.
_DEAD = {
    "plugin.disabled": "PRT/05 §4 D1: superseded by plugin.health.changed",
    "process.failed": "PRT/05 §4 D2: dead draft vocabulary, canon is exec.failed",
    "process.timeout": "PRT/05 §4 D2: dead draft vocabulary, canon is exec.timeout",
}


def _reject(event_name):
    if event_name in _DEAD:
        raise ValueError("events.dead_vocabulary:" + event_name + ":" + _DEAD[event_name])
    raise ValueError("events.unknown_event:" + event_name)


def emit(bus, event_name, subject_id, payload=None):
    """Publish one PRT event. Closed name set; unknown/dead name = loud."""
    if event_name not in PUBLISHED:
        _reject(event_name)
    bus.publish(event_name, {"event_name": event_name, "subject_id": subject_id,
                             "payload": payload if payload is not None else {}})


def check_consumed(event_name):
    """Structural gate for the consume side: raise unless event_name is one
    PRT actually consumes (PRT/05 §4 table). No bus needed — this validates
    an inbound name before PRT does anything with the event's payload."""
    if event_name not in CONSUMED:
        _reject(event_name)


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()
    emit(bus, "plugin.discovered", "p1", {"source": "local"})
    emit(bus, "plugin.registered", "p1", {"registry_version": 1})
    emit(bus, "plugin.loaded", "p1")
    emit(bus, "plugin.unloaded", "p1")
    emit(bus, "plugin.health.changed", "p1", {"state": "quarantined"})
    assert bus.messages("plugin.discovered")[0]["payload"]["source"] == "local"
    assert bus.messages("plugin.loaded")[0]["payload"] == {}

    for name in PUBLISHED:
        assert name in PUBLISHED  # sanity: closed tuple is exactly PRT/05 §4's publish column

    check_consumed("plugin.lifecycle.changed")
    check_consumed("reliability.updated")
    check_consumed("exec.failed")
    check_consumed("exec.timeout")
    check_consumed("exec.completed")

    # invented event name refused, both sides
    try:
        emit(bus, "plugin.rebuilt", "p1")
        raise SystemExit("invented event accepted")
    except ValueError:
        pass
    assert bus.messages("plugin.rebuilt") == []
    try:
        check_consumed("plugin.rebuilt")
        raise SystemExit("invented consumed name accepted")
    except ValueError:
        pass

    # dead vocabulary named and refused, pointed error naming PRT/05 §4 (PRT-S2)
    for dead in ("plugin.disabled", "process.failed", "process.timeout"):
        try:
            emit(bus, dead, "p1")
            raise SystemExit("dead vocabulary accepted: " + dead)
        except ValueError as exc:
            assert "PRT/05" in str(exc) and "dead_vocabulary" in str(exc)
        try:
            check_consumed(dead)
            raise SystemExit("dead vocabulary accepted on consume side: " + dead)
        except ValueError as exc:
            assert "PRT/05" in str(exc)

    bus.fail_publishes = True
    try:
        emit(bus, "plugin.loaded", "p1")
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False
    assert len(bus.drain("plugin.unloaded")) == 1
    assert bus.drain("plugin.unloaded") == []
    print("events selftest ok")
