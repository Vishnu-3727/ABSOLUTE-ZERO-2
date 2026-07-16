"""In-memory Communication TEST DOUBLE -- SGPE's own copy (`lie/bus_double.py`
and every sibling component's equivalent). NOT the real Communication
component: per-topic FIFO queues simulating at-least-once delivery,
carrying SGPE Policy Store events (`policy.authored`, `policy.deprecated`).
SGPE ships its own copy rather than importing another component's
(zero-seam rule beats DRY)."""
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
        queue = self._topics.get(topic)
        if queue:
            queue.append(queue[-1])

    def clear(self):
        self._topics.clear()


if __name__ == "__main__":
    bus = BusDouble()
    bus.publish("policy.authored", {"event_id": "e1", "n": 1})
    assert bus.messages("policy.authored") == [{"event_id": "e1", "n": 1}]

    bus.inject_duplicate("policy.authored")
    assert bus.messages("policy.authored") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]

    bus.publish("policy.deprecated", {"event_id": "p1"})
    assert bus.messages("policy.deprecated") == [{"event_id": "p1"}]
    assert bus.drain("policy.authored") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]
    assert bus.messages("policy.authored") == []
    assert bus.messages("policy.deprecated") == [{"event_id": "p1"}]  # untouched

    bus.fail_publishes = True
    try:
        bus.publish("policy.authored", {})
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False

    bus.clear()
    assert bus.messages("policy.deprecated") == []

    print("bus_double selftest ok")
