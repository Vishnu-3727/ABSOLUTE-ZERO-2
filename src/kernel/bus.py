"""In-memory Communication TEST DOUBLE.

NOT the real Communication component — a stand-in for tests and local runs:
per-topic FIFO queues, at-least-once simulation via duplicate injection, and
failure injection (publish raising) to exercise the degradation ladder.
The real Communication component owns delivery, FIFO, and dead-lettering.
"""
from collections import deque


class Bus:
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
        """Pop and return all pending messages on a topic."""
        queue = self._topics.get(topic)
        if not queue:
            return []
        out = list(queue)
        queue.clear()
        return out

    def clear(self):
        self._topics.clear()

    # -- at-least-once simulation helpers -------------------------------
    def inject_duplicate(self, topic):
        """Re-append the last message on a topic (duplicate delivery)."""
        queue = self._topics.get(topic)
        if queue:
            queue.append(queue[-1])


if __name__ == "__main__":
    bus = Bus()
    bus.publish("t", {"n": 1})
    bus.publish("t", {"n": 2})
    assert bus.messages("t") == [{"n": 1}, {"n": 2}]
    bus.inject_duplicate("t")
    assert bus.drain("t") == [{"n": 1}, {"n": 2}, {"n": 2}]
    assert bus.drain("t") == []
    bus.fail_publishes = True
    try:
        bus.publish("t", {})
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    print("bus selftest ok")
