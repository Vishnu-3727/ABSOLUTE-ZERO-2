"""CM event emitter — the closed set CM-I7 / COMPONENTS/context-management.md
"Events Published" + `context.invalidated` (blueprint Phase 5 note, named
here since the closed set is fixed in Phase 1).

context.assembled / context.overflow / context.invalidated only.
Inventing event names is a known failure mode elsewhere in this codebase
(ums/events.py), so emit() refuses anything outside EVENT_NAMES — a
structural refusal, not a judgment call (kernel I6: ambiguity = reject).

`context.assembled` payload contract (blueprint Phase 1 "Data produced"):
{request_id, memory_id, hash, tokens_used, coverage}. Not enforced here
(payload is opaque to the emitter, same as envelope.py/ums.events.emit) —
the assembler (Phase 4) is responsible for shaping it correctly.
"""

EVENT_NAMES = ("context.assembled", "context.overflow", "context.invalidated")


def emit(bus, event_name, request_id, payload=None):
    """Publish one CM event. Closed name set; unknown name = loud (CM-I7)."""
    if event_name not in EVENT_NAMES:
        raise ValueError("events.unknown_event:" + event_name)
    bus.publish(event_name, {"event_name": event_name, "request_id": request_id,
                             "payload": payload if payload is not None else {}})


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()
    emit(bus, "context.assembled", "r1", {"memory_id": "m1", "hash": "abc",
                                          "tokens_used": 10, "coverage": 1.0})
    emit(bus, "context.overflow", "r1", {"dropped": 2})
    emit(bus, "context.invalidated", "r1")
    assert bus.messages("context.assembled")[0]["payload"]["memory_id"] == "m1"
    assert bus.messages("context.invalidated")[0]["payload"] == {}
    try:
        emit(bus, "context.rebuilt", "r1")  # invented event name
        raise SystemExit("invented event accepted")
    except ValueError:
        pass
    assert bus.messages("context.rebuilt") == []  # nothing leaked onto the bus
    bus.fail_publishes = True
    try:
        emit(bus, "context.assembled", "r1")
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False
    assert len(bus.drain("context.overflow")) == 1
    assert bus.drain("context.overflow") == []
    print("events selftest ok")
