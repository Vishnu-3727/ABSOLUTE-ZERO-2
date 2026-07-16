"""In-memory Communication TEST DOUBLE -- LIE's own copy
(`vae/bus_double.py` and every sibling component's equivalent). NOT the
real Communication component: per-topic FIFO queues simulating
at-least-once delivery, carrying LIE's published change-notification
events (`lesson.recorded`, `reliability.updated`, `prior.updated`) and
LIE's one consumed event (`trace.closed`). LIE ships its own copy rather
than importing another component's (zero-seam rule beats DRY)."""
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
        """Re-append the last published message on a topic -- simulated
        at-least-once redelivery, for OPS-5 idempotency tests."""
        queue = self._topics.get(topic)
        if queue:
            queue.append(queue[-1])

    def clear(self):
        self._topics.clear()


if __name__ == "__main__":
    bus = BusDouble()
    bus.publish("lesson.recorded", {"event_id": "e1", "n": 1})
    assert bus.messages("lesson.recorded") == [{"event_id": "e1", "n": 1}]

    bus.inject_duplicate("lesson.recorded")
    assert bus.messages("lesson.recorded") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]

    bus.publish("prior.updated", {"event_id": "p1"})
    assert bus.messages("prior.updated") == [{"event_id": "p1"}]
    assert bus.drain("lesson.recorded") == [
        {"event_id": "e1", "n": 1}, {"event_id": "e1", "n": 1}]
    assert bus.messages("lesson.recorded") == []
    assert bus.messages("prior.updated") == [{"event_id": "p1"}]  # untouched

    bus.fail_publishes = True
    try:
        bus.publish("lesson.recorded", {})
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False

    bus.clear()
    assert bus.messages("prior.updated") == []

    print("bus_double selftest ok")
