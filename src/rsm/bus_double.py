"""Communication subscription test double (RSM/05-implementation-spec.md §1
`bus_double` row; precedent `src/kernel/bus.py`'s in-memory FIFO double,
referenced by name only — RSM/05 §5 item 2 keeps `src/rsm/` free of
internals imports from `src/kernel/`/`src/ums/` (doubles included), so this
is a fresh, RSM-scoped instance of the same small pattern, not a wrapper
around kernel's own `Bus`.

Per-topic FIFO queues (durable, at-least-once semantics simulated via
`inject_duplicate`). `deliver*` methods are the "publishes into ingest's
pipeline in a controllable, test-scriptable order" contract (RSM/05 §1):
callers choose exactly which topic drains, in which order, one message (or
one topic's full backlog) at a time — this is what lets a test script
simulated redelivery (`inject_duplicate`) or cross-topic skew
(`deliver_in_order`'s caller-chosen interleaving).
"""
from collections import deque


class BusDouble:
    def __init__(self):
        self._topics = {}

    def publish(self, topic, message):
        self._topics.setdefault(topic, deque()).append(message)

    def pending(self, topic):
        """Snapshot of everything still queued on a topic, FIFO order."""
        return list(self._topics.get(topic, ()))

    def inject_duplicate(self, topic):
        """Re-append the last published message on a topic — simulated
        redelivery, for dedup tests (RSM/05 §1)."""
        queue = self._topics.get(topic)
        if queue:
            queue.append(queue[-1])

    def deliver_one(self, ingest, topic):
        """Pop and process exactly one pending message on `topic`. Returns
        the `ingest.process()` outcome, or None if `topic` is empty — the
        single-message primitive callers compose into any interleaving
        (cross-topic skew property tests, RSM/05 §1)."""
        queue = self._topics.get(topic)
        if not queue:
            return None
        return ingest.process(queue.popleft())

    def deliver_all(self, ingest, topic):
        """Drain every pending message on `topic`, in FIFO order, feeding
        each into `ingest.process()`. Returns the list of outcomes."""
        results = []
        while self.pending(topic):
            results.append(self.deliver_one(ingest, topic))
        return results

    def deliver_in_order(self, ingest, topics):
        """Deliver exactly one message per entry of `topics`, in list
        order — the test-scriptable cross-topic interleaving primitive: a
        caller builds `topics` as e.g. ["task.scheduled", "cost.recorded",
        "task.scheduled", ...] to script a specific arrival skew across
        families, then calls this once. Entries whose topic has nothing
        pending are skipped (no outcome appended)."""
        results = []
        for topic in topics:
            outcome = self.deliver_one(ingest, topic)
            if outcome is not None:
                results.append(outcome)
        return results


if __name__ == "__main__":
    from .store import Store
    from .journal import Journal
    from .ingest import Ingest, make_event, APPLIED, DROPPED

    bus = BusDouble()
    store, journal = Store(), Journal()
    ing = Ingest(store, journal)

    bus.publish("request.received", make_event("e0", "request.received", "r1", 1,
                                                 {"declared_type": "a", "origin": "fe"}))
    assert len(bus.pending("request.received")) == 1
    assert bus.deliver_one(ing, "request.received") == APPLIED
    assert bus.pending("request.received") == []
    assert store.get("r1").identity["declared_type"] == "a"

    bus.publish("cost.recorded", make_event("e1", "cost.recorded", "r1", 1, {"amount": 3}))
    bus.publish("cost.recorded", make_event("e2", "cost.recorded", "r1", 1, {"amount": 4}))
    assert bus.deliver_all(ing, "cost.recorded") == [APPLIED, APPLIED]
    assert store.get("r1").budget == {"consumed": 7}

    # simulated redelivery: duplicate lands, dedup drops it (RSM-I4)
    bus.publish("task.scheduled", make_event("e3", "task.scheduled", "r1", 1,
                                              {"task_id": "t1", "budget_granted": 5}))
    bus.inject_duplicate("task.scheduled")
    assert len(bus.pending("task.scheduled")) == 2
    outcomes = bus.deliver_all(ing, "task.scheduled")
    assert outcomes == [APPLIED, DROPPED]

    # cross-topic-skew scripting: deliver_in_order drains one message per
    # named topic, in the caller's chosen sequence
    bus.publish("verify.requested", make_event("e4", "verify.requested", "r1", 1,
                                                {"gate": "g1"}))
    bus.publish("cost.recorded", make_event("e5", "cost.recorded", "r1", 1, {"amount": 1}))
    outcomes = bus.deliver_in_order(ing, ["cost.recorded", "verify.requested"])
    assert outcomes == [APPLIED, APPLIED]
    assert store.get("r1").budget == {"consumed": 8, "granted": 5}
    assert store.get("r1").verification == {"g1": {"state": "requested"}}

    print("bus_double selftest ok")
