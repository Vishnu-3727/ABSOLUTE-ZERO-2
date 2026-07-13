"""In-memory Communication TEST DOUBLE — CM's own copy.

NOT the real Communication component: per-topic FIFO queues plus failure
injection to exercise publish-failure paths. Copied from the kernel
bus.py / ums/events.py BusDouble pattern rather than imported — CM takes
no import edge onto another component's test double (blueprint: "ship
CM's own copy, never import another component's double").
"""
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

    def clear(self):
        self._topics.clear()


if __name__ == "__main__":
    bus = BusDouble()
    bus.publish("t", {"n": 1})
    assert bus.messages("t") == [{"n": 1}]
    assert bus.drain("t") == [{"n": 1}]
    assert bus.drain("t") == []
    bus.fail_publishes = True
    try:
        bus.publish("t", {})
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    print("bus_double selftest ok")
