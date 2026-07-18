"""Communication schema authority — the one versioned dotted-event
vocabulary and per-topic message-shape rules (communication.md "Owns:
message schema registry and event-name vocabulary"; Global Law 3).

Two topic kinds:
  ENVELOPE — carries kernel-shaped event envelopes (the six fields of
             `kernel/envelope.py`; event_name must equal the topic).
  RECORD   — carries opaque structured records (e.g. `transition.log`);
             only "is a mapping" is enforced, content is the publisher's.

The vocabulary below is the ARCHITECTURE.md publish/consume matrix, plus
the kernel's own emissions (transition.log, routing.directive,
gate.enforced, request.cancelled, config.changed) and Communication's own
`delivery.failed`. `lesson.recorded` per ERRATA C1 — `lesson.learned` is a
banned invented name and is deliberately absent. Registration of new
topics is an explicit act (communication.md Inputs: "Schema/topic
definitions"), never implicit on first publish — unknown topics are
rejected loud (fail closed).
"""

SCHEMA_VERSION = 1

ENVELOPE = "envelope"
RECORD = "record"

_ENVELOPE_FIELDS = ("event_id", "event_name", "request_id", "timestamp", "payload")

_MATRIX_TOPICS = (
    "request.received", "request.admitted", "request.rejected",
    "request.completed", "request.failed", "request.cancelled",
    "intent.classified",
    "plan.created", "plan.validated", "plan.rejected", "plan.revised",
    "task.scheduled", "task.started", "task.preempted", "task.completed",
    "task.failed",
    "workflow.created",  # ERRATA C15; task.dispatched = dead draft name, banned
    "context.assembled", "context.overflow", "context.invalidated",
    "exec.started", "exec.completed", "exec.timeout", "exec.failed",
    "verify.requested", "verify.passed", "verify.failed",
    "repo.indexed", "index.stale", "index.updated",
    "repo.onboarded", "repo.offboarded",
    "plugin.discovered", "plugin.registered", "plugin.loaded",
    "plugin.unloaded", "plugin.health.changed", "plugin.lifecycle.changed",
    "reliability.updated", "lesson.recorded", "prior.updated",
    "fault.recorded",
    "storage.committed", "storage.rejected",
    "telemetry.emitted", "cost.recorded", "budget.exceeded",
    "trace.opened", "trace.closed", "alert.raised",
    "session.wake", "session.sleep",
    "state.updated", "state.evicted",
    "reasoning.decided", "reasoning.invoked", "reasoning.completed",
    "reasoning.failed",
    "gate.enforced", "routing.directive", "config.changed",
    "delivery.failed",
)

_RECORD_TOPICS = ("transition.log",) + (
    # SGPE event canon (SGPE/05 §4, registered by ERRATA C17): nine closed
    # names carrying SGPE's own reference-shaped envelopes (event_name,
    # event_id, subject_ref, payload — no request_id: policy authorship
    # and grants are not request-scoped). RECORD kind: the shape belongs
    # to the publisher's closed canon; registering here is the explicit
    # act the vocabulary requires. C3 integration caught these unregistered
    # the first time the real Bus carried a policy bootstrap.
    "policy.authored", "policy.deprecated", "policy.compiled",
    "policy.rejected", "policy.activated", "policy.decided",
    "policy.illposed", "grant.recorded", "grant.revoked",
)


class SchemaViolation(Exception):
    """Malformed message or unknown topic — rejected at publish, never
    propagated (communication.md Failure Modes)."""


def default_registry():
    """topic -> kind, the versioned vocabulary."""
    registry = {name: ENVELOPE for name in _MATRIX_TOPICS}
    registry.update({name: RECORD for name in _RECORD_TOPICS})
    return registry


def validate(topic, message, registry):
    """Raise SchemaViolation on any contract breach; return None on pass."""
    kind = registry.get(topic)
    if kind is None:
        raise SchemaViolation("schema.unknown_topic:" + repr(topic))
    if not isinstance(message, dict):
        raise SchemaViolation("schema.message_not_mapping:" + topic)
    if kind == RECORD:
        return
    for field in _ENVELOPE_FIELDS:
        if field not in message:
            raise SchemaViolation("schema.missing_field:%s:%s" % (topic, field))
    if message["event_name"] != topic:
        raise SchemaViolation(
            "schema.event_name_topic_mismatch:%s:%s" % (message["event_name"], topic))
    if not isinstance(message["event_id"], str) or not message["event_id"]:
        raise SchemaViolation("schema.bad_event_id:" + topic)
    if not isinstance(message["payload"], dict):
        raise SchemaViolation("schema.bad_payload:" + topic)


if __name__ == "__main__":
    registry = default_registry()
    assert registry["transition.log"] == RECORD
    assert registry["verify.passed"] == ENVELOPE
    assert "lesson.learned" not in registry and "lesson.recorded" in registry  # ERRATA C1
    env = {"event_id": "e1", "event_name": "verify.passed", "request_id": "r1",
           "timestamp": 0, "payload": {}}
    validate("verify.passed", env, registry)
    validate("transition.log", {"anything": 1}, registry)
    for bad_topic, bad_msg in (("nope.topic", env), ("verify.passed", {}),
                               ("verify.failed", env), ("verify.passed", "x")):
        try:
            validate(bad_topic, bad_msg, registry)
            raise SystemExit("schema violation not caught")
        except SchemaViolation:
            pass
    print("schema selftest ok")
