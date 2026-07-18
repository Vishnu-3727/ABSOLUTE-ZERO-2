"""The Communication bus — real transport, per communication.md and the
ARCHITECTURE.md delivery-semantics table.

Guarantees implemented (single-process, deterministic):

  Ordering       per-topic FIFO; a subscriber sees one topic's messages in
                 publish order (Law 6: identical publish sequence ->
                 identical delivery order).
  Delivery       at-least-once to durable subscribers: a message stays in
                 the subscriber's queue until drained (subscriber down =
                 held, never lost) and, for durable subscriptions, is
                 persisted through the injected Storage port BEFORE publish
                 returns (persist-before-ack).
  Backpressure   a full subscriber queue raises BackpressureError to the
                 publisher — a signal, never a drop. (The Kernel's
                 degradation ladder treats a raising bus as "communication
                 unavailable" and halts admission: exactly the chartered
                 fail-loud behavior.)
  Poison         push delivery (`deliver_with`) retries a failing handler a
                 bounded, deterministic number of times, then dead-letters
                 the message and publishes `delivery.failed` — never a
                 silent drop.
  Replay         durable topics are an append-only, sequence-numbered log
                 in Storage (`communication/log/<topic>/<seq>`); `replay`
                 returns the exact published sequence for audit/re-run.

Storage is an injected PORT with `.write(key, bytes)` / `.read(key)`
(Law 3: Communication writes nothing durable itself). With no storage
injected the bus refuses durable subscriptions — fail closed, not
silently non-durable.
"""
import json
from collections import deque

from .schema import SchemaViolation, default_registry, validate

DELIVERY_FAILED_TOPIC = "delivery.failed"
_LOG_KEY = "communication/log/%s/%d"


class BusRefusal(Exception):
    """Base for bus-level refusals."""


class BackpressureError(BusRefusal):
    """Subscriber queue full: publisher must slow down; nothing dropped."""


class DurabilityUnavailableError(BusRefusal):
    """Durable subscription or durable publish without a Storage port."""


class Bus:
    def __init__(self, storage=None, max_queue_depth=10000, max_attempts=3):
        self.storage = storage
        self.max_queue_depth = max_queue_depth
        self.max_attempts = max_attempts
        self.registry = default_registry()
        self.dead_letters = []
        self._queues = {}        # (topic, subscriber_id) -> deque
        self._subscribers = {}   # topic -> [subscriber_id, ...] in registration order
        self._durable = set()    # (topic, subscriber_id)
        self._log_seq = {}       # topic -> next sequence number

    # -- contracts ------------------------------------------------------

    def register_topic(self, topic, kind):
        """Explicit schema/topic definition (communication.md Inputs)."""
        if topic in self.registry:
            raise SchemaViolation("schema.topic_already_registered:" + topic)
        self.registry[topic] = kind

    def subscribe(self, topic, subscriber_id, durable=False):
        if topic not in self.registry:
            raise SchemaViolation("schema.unknown_topic:" + repr(topic))
        if durable and self.storage is None:
            raise DurabilityUnavailableError("bus.no_storage_for_durable:" + topic)
        key = (topic, subscriber_id)
        if key in self._queues:
            raise BusRefusal("bus.duplicate_subscription:%s:%s" % (topic, subscriber_id))
        self._queues[key] = deque()
        self._subscribers.setdefault(topic, []).append(subscriber_id)
        if durable:
            self._durable.add(key)

    # -- publish --------------------------------------------------------

    def publish(self, topic, message):
        """Validate -> persist (durable) -> enqueue to every subscriber.
        Raises on schema violation or backpressure; delivery to a topic
        with zero subscribers is legal (the log still records it when the
        topic has ever been durable or storage is present)."""
        validate(topic, message, self.registry)
        for subscriber_id in self._subscribers.get(topic, ()):
            if len(self._queues[(topic, subscriber_id)]) >= self.max_queue_depth:
                raise BackpressureError(
                    "bus.backpressure:%s:%s" % (topic, subscriber_id))
        if self.storage is not None:
            seq = self._seq_floor(topic)
            body = json.dumps(message, sort_keys=True, separators=(",", ":"))
            self.storage.write(_LOG_KEY % (topic, seq), body.encode())
            self._log_seq[topic] = seq + 1  # persist-before-ack
        for subscriber_id in self._subscribers.get(topic, ()):
            self._queues[(topic, subscriber_id)].append(message)

    # -- pull delivery (at-least-once: held until drained) ---------------

    def drain(self, topic, subscriber_id):
        """Pop and return everything pending for one subscription, FIFO."""
        queue = self._queues.get((topic, subscriber_id))
        if queue is None:
            raise BusRefusal("bus.unknown_subscription:%s:%s" % (topic, subscriber_id))
        out = list(queue)
        queue.clear()
        return out

    def pending(self, topic, subscriber_id):
        queue = self._queues.get((topic, subscriber_id))
        return len(queue) if queue is not None else 0

    # -- push delivery with dead-lettering -------------------------------

    def deliver_with(self, topic, subscriber_id, handler):
        """Deliver each pending message to `handler`. A message whose
        handler raises `max_attempts` times is dead-lettered and
        `delivery.failed` is published (communication.md Events Published)
        — never silently dropped. Returns (delivered, dead_lettered)."""
        delivered = 0
        dead = 0
        for message in self.drain(topic, subscriber_id):
            for attempt in range(1, self.max_attempts + 1):
                try:
                    handler(message)
                    delivered += 1
                    break
                except Exception as exc:
                    if attempt == self.max_attempts:
                        dead += 1
                        self.dead_letters.append(
                            {"topic": topic, "subscriber": subscriber_id,
                             "message": message, "reason": repr(exc)})
                        self.publish(DELIVERY_FAILED_TOPIC, {
                            "event_id": "dlq-%d" % len(self.dead_letters),
                            "event_name": DELIVERY_FAILED_TOPIC,
                            "request_id": message.get("request_id")
                            if isinstance(message, dict) else None,
                            "timestamp": 0,
                            "payload": {"topic": topic, "subscriber": subscriber_id,
                                        "reason": repr(exc)},
                        })
        return delivered, dead

    # -- replay -----------------------------------------------------------

    def _seq_floor(self, topic):
        """Next sequence number for a topic, recovered from storage on
        first use — a fresh Bus over an existing log CONTINUES it, never
        overwrites history (append-only across restarts). Deterministic
        forward probe over read(); works against any storage port."""
        if topic in self._log_seq:
            return self._log_seq[topic]
        seq = 0
        while True:
            try:
                self.storage.read(_LOG_KEY % (topic, seq))
            except Exception:
                break
            seq += 1
        self._log_seq[topic] = seq
        return seq

    def replay(self, topic):
        """The exact persisted publish sequence for a topic (audit/re-run).
        Requires storage; without it there is nothing durable to replay."""
        if self.storage is None:
            raise DurabilityUnavailableError("bus.no_storage_to_replay:" + topic)
        out = []
        for seq in range(self._seq_floor(topic)):
            out.append(json.loads(self.storage.read(_LOG_KEY % (topic, seq)).decode()))
        return out


if __name__ == "__main__":
    class _MemoryStorage:  # selftest-only port stand-in
        def __init__(self):
            self.blobs = {}

        def write(self, key, data):
            self.blobs[key] = data

        def read(self, key):
            return self.blobs[key]

    def env(eid, name, rid):
        return {"event_id": eid, "event_name": name, "request_id": rid,
                "timestamp": 0, "payload": {}}

    bus = Bus(storage=_MemoryStorage(), max_queue_depth=2, max_attempts=2)
    bus.subscribe("verify.passed", "scheduler", durable=True)
    bus.publish("verify.passed", env("e1", "verify.passed", "r1"))
    bus.publish("verify.passed", env("e2", "verify.passed", "r2"))
    assert [m["event_id"] for m in bus.drain("verify.passed", "scheduler")] == ["e1", "e2"]
    assert [m["event_id"] for m in bus.replay("verify.passed")] == ["e1", "e2"]

    # backpressure signals, never drops
    bus.publish("verify.passed", env("e3", "verify.passed", "r3"))
    bus.publish("verify.passed", env("e4", "verify.passed", "r4"))
    try:
        bus.publish("verify.passed", env("e5", "verify.passed", "r5"))
        raise SystemExit("backpressure not signalled")
    except BackpressureError:
        pass
    assert bus.pending("verify.passed", "scheduler") == 2  # e5 nowhere = not enqueued, not dropped silently: publisher was refused

    # poison -> dead letter + delivery.failed
    bus2 = Bus(max_attempts=2)
    bus2.subscribe("fault.recorded", "obs")
    bus2.subscribe("delivery.failed", "obs2")
    bus2.publish("fault.recorded", env("e6", "fault.recorded", None))
    delivered, dead = bus2.deliver_with("fault.recorded", "obs",
                                        lambda m: (_ for _ in ()).throw(ValueError("boom")))
    assert (delivered, dead) == (0, 1) and len(bus2.dead_letters) == 1
    assert bus2.drain("delivery.failed", "obs2")[0]["payload"]["topic"] == "fault.recorded"

    # fail closed: durable without storage, unknown topic
    try:
        bus2.subscribe("verify.passed", "x", durable=True)
        raise SystemExit("durable without storage accepted")
    except DurabilityUnavailableError:
        pass
    try:
        bus2.publish("invented.topic", env("e7", "invented.topic", None))
        raise SystemExit("unknown topic accepted")
    except SchemaViolation:
        pass
    print("bus selftest ok")
