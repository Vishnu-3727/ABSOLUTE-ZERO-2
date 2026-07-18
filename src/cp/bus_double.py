"""CP bus TEST DOUBLE (kernel pattern; imported only by tests/selftests —
production wiring injects the real Communication bus, whose contract this
mirrors: publish + drain)."""
from collections import deque


class BusDouble:
    def __init__(self):
        self._topics = {}

    def publish(self, topic, message):
        self._topics.setdefault(topic, deque()).append(message)

    def messages(self, topic):
        return list(self._topics.get(topic, ()))

    def drain(self, topic):
        queue = self._topics.get(topic)
        out = list(queue) if queue else []
        if queue:
            queue.clear()
        return out


if __name__ == "__main__":
    bus = BusDouble()
    bus.publish("t", {"n": 1})
    assert bus.messages("t") == [{"n": 1}] and bus.drain("t") == [{"n": 1}]
    assert bus.drain("t") == []
    print("bus_double selftest ok")
