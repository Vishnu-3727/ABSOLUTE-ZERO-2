"""Communication phase 1 — the real bus (COMPONENTS/communication.md,
ARCHITECTURE.md delivery table). Unit: schema gate, FIFO order,
backpressure, held-until-drained, dead-letter + delivery.failed. Replay:
persisted sequence is byte-identical to the published one. Integration:
the kernel Coordinator runs a full request lifecycle over the REAL bus —
the first cross-component execution against real substrate — and produces
the same events and ledger states as it does over its test double.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from communication import (BackpressureError, Bus,  # noqa: E402
                           DurabilityUnavailableError, SchemaViolation)


class MemoryStorage:
    def __init__(self):
        self.blobs = {}

    def write(self, key, data):
        self.blobs[key] = data

    def read(self, key):
        return self.blobs[key]


def env(eid, name, rid, payload=None):
    return {"event_id": eid, "event_name": name, "request_id": rid,
            "timestamp": 0, "payload": payload or {}}


class TestBusUnit(unittest.TestCase):
    def test_round_trip_fifo(self):
        bus = Bus()
        bus.subscribe("verify.passed", "ws")
        for i in range(5):
            bus.publish("verify.passed", env("e%d" % i, "verify.passed", "r"))
        got = [m["event_id"] for m in bus.drain("verify.passed", "ws")]
        self.assertEqual(got, ["e0", "e1", "e2", "e3", "e4"])
        self.assertEqual(bus.drain("verify.passed", "ws"), [])

    def test_schema_gate_fails_closed(self):
        bus = Bus()
        with self.assertRaises(SchemaViolation):
            bus.publish("invented.topic", env("e1", "invented.topic", None))
        with self.assertRaises(SchemaViolation):
            bus.publish("verify.passed", {"not": "an envelope"})
        with self.assertRaises(SchemaViolation):
            bus.publish("verify.passed", env("e1", "verify.failed", "r"))  # name/topic mismatch
        with self.assertRaises(SchemaViolation):
            bus.subscribe("invented.topic", "x")

    def test_lesson_learned_is_banned(self):
        bus = Bus()
        with self.assertRaises(SchemaViolation):  # ERRATA C1
            bus.publish("lesson.learned", env("e1", "lesson.learned", None))

    def test_subscriber_down_messages_held(self):
        bus = Bus()
        bus.subscribe("task.completed", "learning")
        bus.publish("task.completed", env("e1", "task.completed", "r1"))
        # subscriber "down" (not draining): nothing lost
        self.assertEqual(bus.pending("task.completed", "learning"), 1)
        self.assertEqual(
            [m["event_id"] for m in bus.drain("task.completed", "learning")], ["e1"])

    def test_backpressure_signals_never_drops(self):
        bus = Bus(max_queue_depth=1)
        bus.subscribe("cost.recorded", "obs")
        bus.publish("cost.recorded", env("e1", "cost.recorded", "r1"))
        with self.assertRaises(BackpressureError):
            bus.publish("cost.recorded", env("e2", "cost.recorded", "r2"))
        self.assertEqual(bus.pending("cost.recorded", "obs"), 1)  # e1 intact

    def test_dead_letter_and_delivery_failed(self):
        bus = Bus(max_attempts=2)
        bus.subscribe("fault.recorded", "obs")
        bus.subscribe("delivery.failed", "monitor")
        bus.publish("fault.recorded", env("e1", "fault.recorded", "r1"))

        attempts = []

        def bad_handler(message):
            attempts.append(message["event_id"])
            raise ValueError("poison")

        delivered, dead = bus.deliver_with("fault.recorded", "obs", bad_handler)
        self.assertEqual((delivered, dead), (0, 1))
        self.assertEqual(attempts, ["e1", "e1"])  # bounded, deterministic retries
        self.assertEqual(len(bus.dead_letters), 1)
        failed = bus.drain("delivery.failed", "monitor")
        self.assertEqual(failed[0]["payload"]["topic"], "fault.recorded")

    def test_durability_fail_closed(self):
        bus = Bus()  # no storage
        with self.assertRaises(DurabilityUnavailableError):
            bus.subscribe("verify.passed", "ws", durable=True)
        with self.assertRaises(DurabilityUnavailableError):
            bus.replay("verify.passed")


class TestReplay(unittest.TestCase):
    def test_replay_reproduces_published_sequence_byte_identically(self):
        storage = MemoryStorage()
        bus = Bus(storage=storage)
        bus.subscribe("plan.created", "ws", durable=True)
        published = [env("e%d" % i, "plan.created", "r%d" % i, {"n": i}) for i in range(4)]
        for message in published:
            bus.publish("plan.created", message)
        replayed = bus.replay("plan.created")
        canon = lambda ms: [json.dumps(m, sort_keys=True) for m in ms]  # noqa: E731
        self.assertEqual(canon(replayed), canon(published))
        # persist-before-ack: the log exists independent of any drain
        self.assertEqual(bus.pending("plan.created", "ws"), 4)


class TestKernelOverRealBus(unittest.TestCase):
    """C3 seed: the kernel's full request lifecycle over the real bus."""

    def _drive(self, bus):
        from kernel import envelope
        from kernel.coordinator import Coordinator
        from kernel.default_config import snapshot

        coord = Coordinator(bus, snapshot())
        e = lambda eid, name, rid, p: envelope.make(eid, name, rid, 0, None, p)  # noqa: E731
        coord.handle(e("e1", "request.received", "r1", {"declared_type": "type.alpha"}))
        coord.handle(e("e2", "plan.created", "r1", {}))
        coord.handle(e("e3", "verify.passed", "r1", {}))
        coord.handle(e("e4", "task.completed", "r1", {}))
        return coord

    def test_full_lifecycle_same_as_double(self):
        real = Bus(storage=MemoryStorage())
        watched = ("request.admitted", "routing.directive", "request.completed",
                   "gate.enforced", "transition.log")
        for topic in watched:
            real.subscribe(topic, "probe", durable=True)
        coord_real = self._drive(real)

        from kernel.bus import Bus as DoubleBus
        double = DoubleBus()
        coord_double = self._drive(double)

        self.assertEqual(coord_real.ledger.get("r1").lifecycle_state, "completed")
        self.assertFalse(coord_real.halted)
        for topic in watched:
            got = real.drain(topic, "probe")
            expected = double.messages(topic)
            self.assertEqual(got, expected, "topic %s diverged" % topic)
        # the kernel's own log replays identically after running on the real bus
        replayed = self._drive(Bus(storage=MemoryStorage()))
        self.assertEqual(replayed.log, coord_real.log)

    def test_kernel_halts_when_bus_fails(self):
        class FailingBus(Bus):
            def publish(self, topic, message):
                raise ConnectionError("down")

        coord = self._drive(FailingBus())
        self.assertTrue(coord.halted)  # degradation ladder level 1 (fail loud)


if __name__ == "__main__":
    unittest.main()
