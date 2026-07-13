"""UMS event emitter — exactly the three names COMPONENTS/memory.md publishes.

repo.indexed / index.stale / index.updated. Inventing event names is a
known failure mode, so emit() refuses anything outside EVENT_NAMES.
BusDouble is a local copy of the kernel bus.py test-double pattern —
src/ums takes no import edge onto frozen src/kernel.
"""
from collections import deque

EVENT_NAMES = ("repo.indexed", "index.stale", "index.updated")


def emit(bus, event_name, repo_id, payload=None):
    """Publish one UMS event. Closed name set; unknown name = loud."""
    if event_name not in EVENT_NAMES:
        raise ValueError("events.unknown_event:" + event_name)
    bus.publish(event_name, {"event_name": event_name, "repo_id": repo_id,
                             "payload": payload if payload is not None else {}})


class BusDouble:
    """In-memory Communication TEST DOUBLE (kernel bus.py pattern).

    NOT the real Communication component: per-topic FIFO queues plus
    failure injection to exercise publish-failure paths.
    """

    def __init__(self):
        self._topics = {}
        self.fail_publishes = False

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
    emit(bus, "repo.indexed", "r1", {"files": 3})
    emit(bus, "index.stale", "r1", {"paths": ["a.py"]})
    emit(bus, "index.updated", "r1")
    assert bus.messages("repo.indexed") == [
        {"event_name": "repo.indexed", "repo_id": "r1", "payload": {"files": 3}}]
    assert bus.messages("index.updated")[0]["payload"] == {}
    try:
        emit(bus, "index.rebuilt", "r1")  # invented event name
        raise SystemExit("invented event accepted")
    except ValueError:
        pass
    assert bus.messages("index.rebuilt") == []  # nothing leaked onto the bus
    bus.fail_publishes = True
    try:
        emit(bus, "repo.indexed", "r1")
        raise SystemExit("publish should have raised")
    except ConnectionError:
        pass
    bus.fail_publishes = False
    assert len(bus.drain("index.stale")) == 1
    assert bus.drain("index.stale") == []
    print("events selftest ok")
