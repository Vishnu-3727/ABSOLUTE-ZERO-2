"""SGPE event canon (SGPE/05 §4), shared by the Policy Store (Phase 1),
the Admission Compiler (Phase 2), and the Evaluator (Phase 3). Seven
closed names, no others, ever:

- `policy.authored` / `policy.deprecated` -- Store: a document version or
  a deprecation marker was appended (SGPE/01 §9).
- `policy.compiled` / `policy.rejected` -- Compiler: one Compile Report was
  produced, on success or on rejection respectively (SGPE/02 §6).
- `policy.activated` -- Compiler's activation act: the atomic publication
  of a new active snapshot, carrying old/new snapshot versions (SGPE/00
  §4, SGPE/02 §7). The Store never emits this itself -- it only records
  the activation FACT as an append; announcing activation is the
  Compiler's act, not the Store's.
- `policy.decided` / `policy.illposed` -- Evaluator: one Decision or one
  ill-posed verdict was produced (SGPE/03 §5, §9; EV-10 -- Observability
  is the sole audit sink, the Evaluator persists nothing).

Every publisher shares this one module (not a separate copy per phase)
because the event canon is one closed vocabulary for the whole engine,
not a per-component one -- SGPE/05 §4 names these together as "the
event canon," and splitting it would risk two components drifting on
what "policy.activated" means."""

PUBLISHED = ("policy.authored", "policy.deprecated", "policy.compiled", "policy.rejected", "policy.activated",
             "policy.decided", "policy.illposed")

CONSUMED = ()


class EventRefusal(Exception):
    """Base for events.py refusals."""


class UnknownEventError(EventRefusal):
    """An invented event name outside this module's closed canon."""


def _reject(event_name):
    raise UnknownEventError("events.unknown_event:" + str(event_name) + ":SGPE/05 §4 closed set")


def build_envelope(event_name, event_id, subject_ref, payload):
    """A published event's reference-shaped envelope. `payload` must be a
    mapping of ids/positions/hashes/report-shaped data -- structural facts
    only."""
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
    """Neither the Store nor the Compiler consumes anything -- always
    refuses (PS-7/AC-10: no triggers, never self-initiating)."""
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

    # confirm the full closed set -- Store's two, Compiler's three, and the
    # Evaluator's two (SGPE/03 §5/§9) -- is usable, and nothing else.
    assert set(PUBLISHED) == {"policy.authored", "policy.deprecated", "policy.compiled",
                               "policy.rejected", "policy.activated",
                               "policy.decided", "policy.illposed"}

    try:
        build_envelope("policy.made_up", "e", "s", {})
        raise SystemExit("invented event accepted")
    except UnknownEventError:
        pass

    # nothing is consumed -- check_consumed must always refuse
    try:
        check_consumed("policy.authored")
        raise SystemExit("check_consumed accepted a name -- nothing is consumed (PS-7/AC-10)")
    except UnknownEventError:
        pass

    try:
        build_envelope("policy.authored", "e", "s", ["not", "a", "dict"])
        raise SystemExit("non-mapping payload accepted")
    except EventRefusal:
        pass

    print("events selftest ok")
