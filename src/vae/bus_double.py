"""In-memory Communication TEST DOUBLE — VAE's own copy (`ro/bus_double.py`,
`rsm/bus_double.py`, `ums`/`prt`/`cm` equivalents). NOT the real
Communication component: per-topic FIFO queues simulating at-least-once
delivery. VAE ships its own copy rather than importing another component's
double (zero-seam rule beats DRY — VAE/06 "Global laws" table, mirrored by
every sibling's own bus_double.py docstring).

At-least-once delivery means a consumer may see the same event twice;
`inject_duplicate` (mirrors `rsm/bus_double.py`) makes that redelivery
test-scriptable so Phase 2's demand-intake dedup (VAE/04 §2, "event-id
dedup + one-judgment-per-occurrence") has something to dedup against.
Phase 1 itself does no deduplication — this double only makes duplicate
arrival reproducible in a test; the dedup logic is Phase 2's to build."""
from collections import deque


class BusDouble:
    def __init__(self):
        self._topics = {}
        self.fail_publishes = False  # failure injection: communication down

    def publish(self, topic, message):
        if self.fail_publishes:
            raise ConnectionError("communication.unavailable")
        self._topics.setdefault(topic, deque()).append(message)

    def messages(self, topic):
        """Snapshot of everything published to a topic, FIFO order."""
        return list(self._topics.get(topic, ()))

    def drain(self, topic):
        queue = self._topics.get(topic)
        if not queue:
            return []
        out = list(queue)
        queue.clear()
        return out

    def inject_duplicate(self, topic):
        """Re-append the last published message on a topic — simulated
        at-least-once redelivery, for event-id dedup tests (VAE/04 §2)."""
        queue = self._topics.get(topic)
        if queue:
            queue.append(queue[-1])

    def clear(self):
        self._topics.clear()


if __name__ == "__main__":
    bus = BusDouble()
    bus.publish("verify.passed", {"event_id": "e1", "n": 1})
    assert bus.messages("verify.passed") == [{"event_id": "e1", "n": 1}]

    # at-least-once: duplicate arrival is test-scriptable
    bus.inject_duplicate("verify.passed")
    assert bus.messages("verify.passed") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]

    # per-topic FIFO order preserved across topics independently
    bus.publish("fault.recorded", {"event_id": "f1"})
    assert bus.messages("fault.recorded") == [{"event_id": "f1"}]
    assert bus.drain("verify.passed") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]
    assert bus.messages("verify.passed") == []
    assert bus.messages("fault.recorded") == [{"event_id": "f1"}]  # untouched

    bus.fail_publishes = True
    try:
        bus.publish("verify.passed", {})
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False

    bus.clear()
    assert bus.messages("fault.recorded") == []

    print("bus_double selftest ok")
