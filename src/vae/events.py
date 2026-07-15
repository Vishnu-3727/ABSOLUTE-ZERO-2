"""VAE event canon — the closed publish/consume sets VAE/05 §2 fixes
(VAE-S2-equivalent discipline, mirroring `ro/events.py`'s pattern).

Publishes exactly the four terminal-verdict/plan-outcome events plus the
shared loud-absence event (VAE/05 §2.1):
`verify.passed`, `verify.failed`, `plan.validated`, `plan.rejected`,
`fault.recorded`.

Consumes exactly the four demand-and-artifact rows VAE/05 §2.2 fixes:
`verify.requested`, `plan.created`, `exec.completed`, `reasoning.completed`.

No other event is VAE's to publish or consume (VAE/05 §2.1 "No other event
is VAE's to publish"; VAE-O2). Constructors structurally refuse any
invented name, both sides, mirroring PRT-S2/RO-S2's discipline — this
module is VAE's own copy (bus_double.py's docstring explains the
zero-seam-over-DRY rule the same way).

Payloads are reference-shaped (record hashes/refs + routing facts) —
Phase 1 does not yet derive verdicts, so this module only fixes the closed
name sets and the structural envelope; verdict-specific payload builders
(à la `ro/events.py`'s `decided_payload`/`completed_payload`) are Phase 3/4
territory once a derivation account exists to reference."""

PUBLISHED = ("verify.passed", "verify.failed", "plan.validated", "plan.rejected", "fault.recorded")

CONSUMED = ("verify.requested", "plan.created", "exec.completed", "reasoning.completed")


class EventRefusal(Exception):
    """Base for events.py refusals."""


class UnknownEventError(EventRefusal):
    """An invented event name outside VAE/05 §2's closed canon."""


def _reject(event_name):
    raise UnknownEventError("events.unknown_event:" + str(event_name) + ":VAE/05 §2 closed set")


def build_envelope(event_name, event_id, subject_ref, payload):
    """A published event's reference-shaped envelope. `payload` must be a
    mapping of hashes/refs/routing facts, never artifact content — this
    module enforces the closed name set structurally; the "never content"
    discipline is enforced by callers only ever holding references (Phase 1
    has no artifact content in scope to leak in the first place)."""
    if event_name not in PUBLISHED:
        _reject(event_name)
    if not isinstance(payload, dict):
        raise EventRefusal("events.payload_not_a_mapping:" + repr(payload))
    return {
        "event_name": event_name, "event_id": event_id,
        "subject_ref": subject_ref, "payload": dict(payload),
    }


def emit(bus, event_name, event_id, subject_ref, payload):
    """Publish one VAE event onto `bus`. Closed name set; unknown name is
    loud (VAE/05 §2, VAE-O2)."""
    envelope = build_envelope(event_name, event_id, subject_ref, payload)
    bus.publish(event_name, envelope)
    return envelope


def check_consumed(event_name):
    """Structural gate for the consume side: raise unless `event_name` is
    one VAE actually consumes (VAE/05 §2.2 table)."""
    if event_name not in CONSUMED:
        _reject(event_name)


if __name__ == "__main__":
    from .bus_double import BusDouble

    bus = BusDouble()

    env = emit(bus, "verify.passed", "e1", "artifact:a1",
               {"evidence_record_ref": "storage:vae/ev/a1", "rules_version": 1})
    assert bus.messages("verify.passed") == [env]
    assert env["payload"]["rules_version"] == 1

    for name in PUBLISHED:
        emit(bus, name, "id:" + name, "subj", {"ref": name})
        assert bus.messages(name)[-1]["event_name"] == name

    for name in CONSUMED:
        check_consumed(name)  # must not raise

    # invented publish name refused, both build and emit paths
    try:
        build_envelope("verify.maybe", "e", "s", {})
        raise SystemExit("invented event accepted by build_envelope")
    except UnknownEventError as exc:
        assert "VAE/05" in str(exc)
    try:
        emit(bus, "verify.maybe", "e", "s", {})
        raise SystemExit("invented event accepted by emit")
    except UnknownEventError:
        pass
    assert bus.messages("verify.maybe") == []

    # published-only name is not a consumed name, and vice versa
    try:
        check_consumed("verify.passed")
        raise SystemExit("published-only name accepted as consumed")
    except UnknownEventError:
        pass
    for name in CONSUMED:
        assert name not in PUBLISHED
    for name in PUBLISHED:
        assert name not in CONSUMED

    # payload must be a mapping
    try:
        build_envelope("verify.passed", "e", "s", ["not", "a", "dict"])
        raise SystemExit("non-mapping payload accepted")
    except EventRefusal:
        pass

    print("events selftest ok")
