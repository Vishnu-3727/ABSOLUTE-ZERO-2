"""SGPE Policy Store event canon (SGPE/05 §4, SGPE/01 §9). Publishes
exactly the two catalog-append notifications the Store itself is
responsible for: `policy.authored` (a document version was appended) and
`policy.deprecated` (a deprecation marker was appended). `policy.activated`
exists in the same overall canon (SGPE/00 §4) but is emitted by the
Admission Compiler's activation act (Phase 2), never by the Store -- the
Store only records the activation FACT (an append); it does not perform or
announce activation itself.

The Store consumes nothing at all (PS-7: no clock, no triggers, no
self-initiated behavior, no causal wiring in) -- `CONSUMED` is the empty
set and `check_consumed` always refuses, structurally."""

PUBLISHED = ("policy.authored", "policy.deprecated")

CONSUMED = ()


class EventRefusal(Exception):
    """Base for events.py refusals."""


class UnknownEventError(EventRefusal):
    """An invented event name outside this module's closed canon."""


def _reject(event_name):
    raise UnknownEventError("events.unknown_event:" + str(event_name) + ":SGPE/05 §4 closed set")


def build_envelope(event_name, event_id, subject_ref, payload):
    """A published event's reference-shaped envelope. `payload` must be a
    mapping of ids/positions/hashes -- structural facts only."""
    if event_name not in PUBLISHED:
        _reject(event_name)
    if not isinstance(payload, dict):
        raise EventRefusal("events.payload_not_a_mapping:" + repr(payload))
    return {
        "event_name": event_name, "event_id": event_id,
        "subject_ref": subject_ref, "payload": dict(payload),
    }


def emit(bus, event_name, event_id, subject_ref, payload):
    envelope = build_envelope(event_name, event_id, subject_ref, payload)
    bus.publish(event_name, envelope)
    return envelope


def check_consumed(event_name):
    """The Store consumes nothing -- always refuses (PS-7)."""
    _reject(event_name)


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()
    env = emit(bus, "policy.authored", "e1", "system/baseline",
               {"doc_id": ["system", "baseline"], "version": 1})
    assert bus.messages("policy.authored") == [env]

    for name in PUBLISHED:
        emit(bus, name, "id:" + name, "subj", {"ref": name})
        assert bus.messages(name)[-1]["event_name"] == name

    # policy.activated is NOT this module's to emit -- that's the Compiler's
    # activation act (Phase 2), the Store only records the activation fact.
    try:
        emit(bus, "policy.activated", "e", "s", {})
        raise SystemExit("policy.activated accepted by the Store's event module")
    except UnknownEventError:
        pass

    try:
        build_envelope("policy.made_up", "e", "s", {})
        raise SystemExit("invented event accepted")
    except UnknownEventError:
        pass

    # the Store consumes nothing -- check_consumed must always refuse
    try:
        check_consumed("policy.authored")
        raise SystemExit("check_consumed accepted a name -- Store consumes nothing (PS-7)")
    except UnknownEventError:
        pass

    try:
        build_envelope("policy.authored", "e", "s", ["not", "a", "dict"])
        raise SystemExit("non-mapping payload accepted")
    except EventRefusal:
        pass

    print("events selftest ok")
