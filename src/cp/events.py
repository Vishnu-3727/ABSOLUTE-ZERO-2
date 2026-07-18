"""CP events — the closed 4-name set (CP/05 foundation; CP-IMPL 10;
ERRATA C16: `intent.classified` is canonical, `classify.completed` is the
banned stale matrix name).
"""
EVENT_NAMES = ("intent.classified", "plan.created", "plan.rejected",
               "plan.revised")

_PAYLOAD_KEYS = {
    "intent.classified": ("request_id", "label", "confidence", "alternatives"),
    "plan.created": ("request_id", "plan_id", "hash", "confidence",
                     "gap_count", "predecessor"),
    "plan.rejected": ("request_id", "gate", "reason"),
    "plan.revised": ("request_id", "plan_id", "hash", "confidence",
                     "gap_count", "predecessor"),
}


def emit(bus, event_name, event_id, payload):
    """Structural refusal of any fifth name or malformed payload."""
    if event_name not in EVENT_NAMES:
        raise ValueError("cp.events.unknown:" + repr(event_name))
    missing = [k for k in _PAYLOAD_KEYS[event_name] if k not in payload]
    if missing:
        raise ValueError("cp.events.missing:%s:%s" % (event_name, missing))
    bus.publish(event_name, {"event_id": event_id, "event_name": event_name,
                             "request_id": payload["request_id"],
                             "timestamp": 0, "payload": dict(payload)})


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()
    emit(bus, "plan.rejected", "e1",
         {"request_id": "r1", "gate": "acyclicity", "reason": "cycle"})
    assert bus.messages("plan.rejected")[0]["payload"]["gate"] == "acyclicity"
    for bad in (lambda: emit(bus, "classify.completed", "e2", {}),  # C16 stale
                lambda: emit(bus, "plan.sealed", "e3", {}),
                lambda: emit(bus, "plan.created", "e4", {"request_id": "r"})):
        try:
            bad()
            raise SystemExit("closed set violated")
        except ValueError:
            pass
    print("events selftest ok")
