"""RO event emitter — the closed publish/consume sets RO/05 §2 fixes (RO-S2).

Publishes exactly the four `reasoning.*` events (RO/05 §2 table):
`reasoning.decided` (one event for all five RO/02 outcomes, outcome class
carried in payload), `reasoning.invoked` (a quarantine crossing began,
RO/04 §2 Initiated), `reasoning.completed` (an attempt sealed RETURNED),
`reasoning.failed` (an attempt sealed FAILED/EXPIRED/CANCELLED).

Consumes exactly `context.assembled` (CM) and `prior.updated` (Learning) —
RO/05 §2's consume table; the third consumed row ("Config/policy versions")
is Storage discipline, not event consumption, so it names no event here.

Replay ruling (RO/05 §2 "Replay" row + Fable R1): events are re-derivable
from sealed records — records are the truth, events the notification.
Nothing in this module wraps or instruments Phase 1-4's frozen builders;
every payload builder below is a pure function FROM an already-sealed
record (decision_gate.DecisionRecord / outcome.SealedOutcomeRecord) TO an
event payload. Event ids are deterministic content-hash derivations
(kernel rid:seq:index precedent), never counters or clocks: `<record
content hash>:decided`/`:invoked`/`:sealed` — RETURNED and non-RETURNED
terminal events both use the `:sealed` suffix (the record sealed either
way; `event_name` alone tells a consumer which of the two it got).

Payloads are reference-shaped (RO/05 §2 Replay row, R2): record content
hashes + coordinates + routing facts (outcome/recovery/failure class) —
never a verbatim output. `reasoning.completed`'s payload omits
`sealed_record.output` entirely; the sealed record itself, not the event,
is the audit object.

Dead/foreign event vocabulary is refused loud, naming RO/05 §2, mirroring
PRT-S2/PRT/05 §4's discipline — this module is RO's own copy (bus_double.py
docstring explains the zero-seam-over-DRY rule the same way)."""
import hashlib
import json

PUBLISHED = ("reasoning.decided", "reasoning.invoked", "reasoning.completed", "reasoning.failed")

CONSUMED = ("context.assembled", "prior.updated")


def _reject(event_name):
    raise ValueError("events.unknown_event:" + str(event_name) + ":RO/05 §2 closed set")


def emit(bus, event_name, event_id, subject_id, payload):
    """Publish one RO event. Closed name set; unknown name = loud (RO-S2)."""
    if event_name not in PUBLISHED:
        _reject(event_name)
    bus.publish(event_name, {
        "event_name": event_name, "event_id": event_id,
        "subject_id": subject_id, "payload": payload,
    })


def check_consumed(event_name):
    """Structural gate for the consume side: raise unless `event_name` is
    one RO actually consumes (RO/05 §2 table)."""
    if event_name not in CONSUMED:
        _reject(event_name)


def _unfreeze(value):
    from types import MappingProxyType
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _unfreeze(v) for k, v in dict(value).items()}
    if isinstance(value, (tuple, list)):
        return [_unfreeze(v) for v in value]
    return value


def _canon(value):
    return json.dumps(_unfreeze(value), sort_keys=True, separators=(",", ":"))


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


# -- reasoning.decided ------------------------------------------------------

def decided_event_id(decision_record, decision_record_hash):
    return decision_record_hash + ":decided"


def decided_payload(decision_record, decision_record_hash):
    """Reference-shaped: the outcome class + the decision's own reference
    coordinates (already hashes/versions, decision_gate.py's `decided_from`
    — RO/05 §2 "one event, not five: all outcomes share the same consumer
    set")."""
    return {
        "decision_record_content_hash": decision_record_hash,
        "outcome": decision_record.outcome,
        "approved_capability_id": decision_record.approved_capability_id,
        "approved_required_rung": decision_record.approved_required_rung,
        "decided_from": _unfreeze(decision_record.decided_from),
    }


# -- reasoning.invoked (the crossing began — one per attempt, R1) ----------

def invoked_event_id(record_hash):
    return record_hash + ":invoked"


def invoked_payload(sealed_record, record_hash):
    return {
        "record_content_hash": record_hash,
        "request_content_hash": sealed_record.request_content_hash,
        "resolution_content_hash": sealed_record.resolution_content_hash,
        "attempt_index": sealed_record.attempt_index,
    }


# -- reasoning.completed (RETURNED) / reasoning.failed (FAILED/EXPIRED/ ----
# CANCELLED) -- both terminal-per-attempt, share the ":sealed" id suffix ---

def sealed_event_id(record_hash):
    return record_hash + ":sealed"


class TerminalEventRefusal(Exception):
    """A caller asked for the wrong terminal payload builder for this
    record's recovery_kind."""


def completed_payload(sealed_record, record_hash):
    if sealed_record.recovery_kind != "RETURNED":
        raise TerminalEventRefusal(
            "events.completed_payload_wants_returned:" + sealed_record.recovery_kind)
    return {
        "record_content_hash": record_hash,
        "request_content_hash": sealed_record.request_content_hash,
        "resolution_content_hash": sealed_record.resolution_content_hash,
        "attempt_index": sealed_record.attempt_index,
        "recovery_kind": sealed_record.recovery_kind,
        "provider_id": sealed_record.provider_id,
        "budget_consumed": sealed_record.budget_consumed,
        "budget_remaining": sealed_record.budget_remaining,
    }


def failed_payload(sealed_record, record_hash):
    if sealed_record.recovery_kind not in ("FAILED", "EXPIRED", "CANCELLED"):
        raise TerminalEventRefusal(
            "events.failed_payload_wants_nonreturned:" + sealed_record.recovery_kind)
    return {
        "record_content_hash": record_hash,
        "request_content_hash": sealed_record.request_content_hash,
        "resolution_content_hash": sealed_record.resolution_content_hash,
        "attempt_index": sealed_record.attempt_index,
        "recovery_kind": sealed_record.recovery_kind,
        "failure_class": sealed_record.failure_class,
        "cancellation_origin": sealed_record.cancellation_origin,
        "provider_id": sealed_record.provider_id,
        "budget_consumed": sealed_record.budget_consumed,
        "budget_remaining": sealed_record.budget_remaining,
    }


if __name__ == "__main__":
    from types import MappingProxyType

    from .bus_double import BusDouble
    from .decision_gate import DecisionRecord, content_hash as decision_hash
    from .outcome import build_sealed_outcome, content_hash as outcome_hash

    bus = BusDouble()

    decision = DecisionRecord(
        outcome="REASONING_APPROVED", justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({"demand_content_hash": "d1", "priors_version": 1}),
        approved_capability_id="ro.cap.x", approved_required_rung="C1",
        approved_scope=MappingProxyType({"description": "d", "granularity": "g", "narrowing": None}),
    )
    dhash = decision_hash(decision)
    emit(bus, "reasoning.decided", decided_event_id(decision, dhash), "ro.cap.x",
         decided_payload(decision, dhash))
    msg = bus.messages("reasoning.decided")[0]
    assert msg["event_id"] == dhash + ":decided"
    assert msg["payload"]["outcome"] == "REASONING_APPROVED"
    assert "output" not in msg["payload"]

    returned = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
        provider_id="p", budget_consumed=1, budget_remaining=9, output={"summary": "secret"},
    )
    rhash = outcome_hash(returned)
    emit(bus, "reasoning.invoked", invoked_event_id(rhash), "p", invoked_payload(returned, rhash))
    emit(bus, "reasoning.completed", sealed_event_id(rhash), "p", completed_payload(returned, rhash))
    completed_msg = bus.messages("reasoning.completed")[0]
    assert completed_msg["event_id"] == rhash + ":sealed"
    assert "output" not in completed_msg["payload"]  # RO/05 §2 Replay row: never a verbatim output
    assert "summary" not in json.dumps(completed_msg["payload"])

    failed = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED", failure_class="F1",
        provider_id="p", budget_consumed=1, budget_remaining=9,
    )
    fhash = outcome_hash(failed)
    emit(bus, "reasoning.failed", sealed_event_id(fhash), "p", failed_payload(failed, fhash))
    assert bus.messages("reasoning.failed")[0]["payload"]["failure_class"] == "F1"

    # wrong-kind payload builder refused loud
    try:
        completed_payload(failed, fhash)
        raise SystemExit("completed_payload accepted a non-RETURNED record")
    except TerminalEventRefusal:
        pass
    try:
        failed_payload(returned, rhash)
        raise SystemExit("failed_payload accepted a RETURNED record")
    except TerminalEventRefusal:
        pass

    # invented event name refused, both sides
    try:
        emit(bus, "reasoning.rejected", "x:decided", "s", {})
        raise SystemExit("invented event accepted")
    except ValueError as exc:
        assert "RO/05" in str(exc)
    assert bus.messages("reasoning.rejected") == []
    try:
        check_consumed("reasoning.decided")
        raise SystemExit("published-only name accepted as consumed")
    except ValueError:
        pass

    check_consumed("context.assembled")
    check_consumed("prior.updated")

    # deterministic ids: identical record -> identical event id
    returned2 = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
        provider_id="p", budget_consumed=1, budget_remaining=9, output={"summary": "secret"},
    )
    assert invoked_event_id(outcome_hash(returned2)) == invoked_event_id(rhash)

    print("events selftest ok")
