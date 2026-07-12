"""Event envelope: validation and canonical serialization.

Fields: event_id, event_name, request_id, timestamp, config_version, payload.
The payload is opaque and never interpreted here. Validation is a structural
table/boolean check, never judgment. config_version is required on published
envelopes only; inbound envelopes may omit it.
"""
import json

REQUIRED_FIELDS = ("event_id", "event_name", "request_id", "timestamp", "payload")


def validate(env, allowed_event_names):
    """Return (ok, reason) for an inbound envelope. Pure structural check."""
    if not isinstance(env, dict):
        return False, "envelope.not_mapping"
    for field in REQUIRED_FIELDS:
        if field not in env:
            return False, "envelope.missing_field:" + field
    if not isinstance(env["event_id"], str) or not env["event_id"]:
        return False, "envelope.bad_event_id"
    if env["event_name"] not in allowed_event_names:
        return False, "envelope.unknown_event_name"
    if not isinstance(env["payload"], dict):
        return False, "envelope.bad_payload"
    return True, ""


def make(event_id, event_name, request_id, timestamp, config_version, payload):
    """Build a published envelope (all six fields, always)."""
    return {
        "event_id": event_id,
        "event_name": event_name,
        "request_id": request_id,
        "timestamp": timestamp,
        "config_version": config_version,
        "payload": payload,
    }


def canonical(obj):
    """Canonical byte form for byte-identical comparison (replay law I17)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


if __name__ == "__main__":
    allowed = {"request.received"}
    good = make("e1", "request.received", "r1", 0, 1, {})
    assert validate(good, allowed) == (True, "")
    assert validate("junk", allowed)[0] is False
    assert validate({}, allowed)[1].startswith("envelope.missing_field")
    bad_name = make("e1", "task.started", "r1", 0, 1, {})
    assert validate(bad_name, allowed) == (False, "envelope.unknown_event_name")
    bad_id = make("", "request.received", "r1", 0, 1, {})
    assert validate(bad_id, allowed) == (False, "envelope.bad_event_id")
    bad_payload = make("e1", "request.received", "r1", 0, 1, "x")
    assert validate(bad_payload, allowed) == (False, "envelope.bad_payload")
    assert canonical({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    print("envelope selftest ok")
