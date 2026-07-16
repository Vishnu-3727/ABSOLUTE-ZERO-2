"""LIE event canon (LIE/00 §4.4, LIE/03 §7, `COMPONENTS/learning.md`;
mirrors `vae/events.py`'s pattern). Publishes exactly the three
change-notification events LIE/00 §4.4 and LIE/04 §6 name -- signals that
re-consultation may be worthwhile, never advice payloads (LIE/03 §7):
`lesson.recorded`, `reliability.updated`, `prior.updated`.

Consumes exactly one demand: `trace.closed` -- closed, verdict-tagged
trace events from Observability. Pre-ruled (architecture-audit resolution
carried into this implementation): LIE consumes `trace.closed`, never a
`lesson.learned` event -- that name does not exist in this canon and is
refused the same way any invented name is.

No other event is LIE's to publish or consume. Constructors structurally
refuse any invented name, both sides, exactly as `vae/events.py` does."""

PUBLISHED = ("lesson.recorded", "reliability.updated", "prior.updated")

CONSUMED = ("trace.closed",)


class EventRefusal(Exception):
    """Base for events.py refusals."""


class UnknownEventError(EventRefusal):
    """An invented event name outside this module's closed canon."""


def _reject(event_name):
    raise UnknownEventError("events.unknown_event:" + str(event_name) + ":LIE/00 §4.4 closed set")


def build_envelope(event_name, event_id, subject_ref, payload):
    """A published event's reference-shaped envelope. `payload` must be a
    mapping of hashes/refs/routing facts -- never advice content (LIE/03
    §7: "notifications ... never carry advice as payload")."""
    if event_name not in PUBLISHED:
        _reject(event_name)
    if not isinstance(payload, dict):
        raise EventRefusal("events.payload_not_a_mapping:" + repr(payload))
    return {
        "event_name": event_name, "event_id": event_id,
        "subject_ref": subject_ref, "payload": dict(payload),
    }


def emit(bus, event_name, event_id, subject_ref, payload):
    """Publish one LIE event onto `bus`. Closed name set; unknown name is
    loud."""
    envelope = build_envelope(event_name, event_id, subject_ref, payload)
    bus.publish(event_name, envelope)
    return envelope


def check_consumed(event_name):
    """Structural gate for the consume side: raise unless `event_name` is
    the one event LIE actually consumes."""
    if event_name not in CONSUMED:
        _reject(event_name)


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()

    env = emit(bus, "lesson.recorded", "e1", "episode:e1", {"derivation_state": "3:1:1"})
    assert bus.messages("lesson.recorded") == [env]
    assert env["payload"]["derivation_state"] == "3:1:1"

    for name in PUBLISHED:
        emit(bus, name, "id:" + name, "subj", {"ref": name})
        assert bus.messages(name)[-1]["event_name"] == name

    for name in CONSUMED:
        check_consumed(name)  # must not raise

    # invented publish name refused, both build and emit paths
    try:
        build_envelope("lesson.learned", "e", "s", {})
        raise SystemExit("invented event (lesson.learned) accepted by build_envelope")
    except UnknownEventError as exc:
        assert "LIE/00" in str(exc)
    try:
        emit(bus, "lesson.learned", "e", "s", {})
        raise SystemExit("invented event accepted by emit")
    except UnknownEventError:
        pass
    assert bus.messages("lesson.learned") == []

    # published-only name is not a consumed name, and vice versa
    try:
        check_consumed("lesson.recorded")
        raise SystemExit("published-only name accepted as consumed")
    except UnknownEventError:
        pass
    for name in CONSUMED:
        assert name not in PUBLISHED
    for name in PUBLISHED:
        assert name not in CONSUMED

    # payload must be a mapping
    try:
        build_envelope("lesson.recorded", "e", "s", ["not", "a", "dict"])
        raise SystemExit("non-mapping payload accepted")
    except EventRefusal:
        pass

    print("events selftest ok")
