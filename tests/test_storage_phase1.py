"""Storage phase 1 — the real substrate (COMPONENTS/storage.md, ERRATA
C7/C10/C13). Unit: atomicity, append-only, immutable snapshots, namespace
isolation, hash verification/corruption rejection, lock discipline, fail
closed. Integration: Communication persists + replays through real
Storage; RSM's persistence module runs unmodified over a real namespace
handle; SGPE-style immutable snapshot bytes; and the full stack — kernel
Coordinator over the real Bus over the real Store — survives a process
"restart" with byte-identical replay from disk.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from storage import (BadKeyError, CorruptionError, Journal,  # noqa: E402
                     KeyExistsError, LockHeldError, MissingKeyError,
                     Store, WriteFailedError)


class StorageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self._tmp.name, "vault"))

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()


class TestStoreUnit(StorageCase):
    def test_round_trip_and_overwrite(self):
        ns = self.store.namespace("ums")
        ns.write("ums/index/r1", b"v1")
        ns.write("ums/index/r1", b"v2")
        self.assertEqual(ns.read("ums/index/r1"), b"v2")

    def test_namespace_isolation_fails_closed(self):
        ums = self.store.namespace("ums")
        for op in (lambda: ums.write("rsm/journal/r1", b"x"),
                   lambda: ums.read("rsm/journal/r1"),
                   lambda: ums.exists("rsm/journal/r1"),
                   lambda: ums.write("plain-key", b"x")):
            with self.assertRaises(BadKeyError):
                op()

    def test_write_once_never_mutates(self):
        ns = self.store.namespace("sgpe")
        ns.write_once("sgpe/snapshot/7", b"policy-bytes")
        with self.assertRaises(KeyExistsError):
            ns.write_once("sgpe/snapshot/7", b"tampered")
        self.assertEqual(ns.read("sgpe/snapshot/7"), b"policy-bytes")

    def test_corruption_detected_before_reconstruction(self):
        ns = self.store.namespace("ums")
        ns.write("ums/blob", b"precious")
        with open(self.store._path("ums/blob"), "r+b") as fh:
            fh.seek(-1, os.SEEK_END)
            fh.write(b"!")
        with self.assertRaises(CorruptionError):
            ns.read("ums/blob")

    def test_atomicity_failed_write_leaves_prior_state(self):
        ns = self.store.namespace("ums")
        ns.write("ums/blob", b"old")
        real_replace = os.replace
        os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(WriteFailedError):
                ns.write("ums/blob", b"new")
        finally:
            os.replace = real_replace
        self.assertEqual(ns.read("ums/blob"), b"old")  # torn write impossible

    def test_missing_key_and_bad_types_fail_closed(self):
        ns = self.store.namespace("ums")
        with self.assertRaises(MissingKeyError):
            ns.read("ums/never")
        with self.assertRaises(WriteFailedError):
            ns.write("ums/blob", "a string")
        with self.assertRaises(BadKeyError):
            self.store.write("../escape", b"x")

    def test_lock_second_writer_fails_loud(self):
        with self.assertRaises(LockHeldError):
            Store(self.store.dir)
        self.store.close()
        Store(self.store.dir).close()  # released lock reopens fine
        self.store = Store(self.store.dir)  # for tearDown

    def test_deterministic_iteration(self):
        ns = self.store.namespace("ums")
        for name in ("b", "a", "c"):
            ns.write("ums/set/" + name, b"x")
        self.assertEqual(ns.keys("ums/set"), ["ums/set/a", "ums/set/b", "ums/set/c"])
        self.assertEqual(ns.keys("ums/set"), ns.keys("ums/set"))


class TestJournal(StorageCase):
    def test_append_only_checkpoint_reconstruct(self):
        journal = Journal(self.store.namespace("rsm"), "r1")
        for i in range(3):
            self.assertEqual(journal.append(b"e%d" % i), i)
        journal.checkpoint(1, b"state@1")
        snap, tail = journal.reconstruct()
        self.assertEqual((snap, tail), (b"state@1", [b"e2"]))
        with self.assertRaises(KeyExistsError):  # history frozen
            journal.checkpoint(1, b"revision")

    def test_reopen_resumes_and_replays_identically(self):
        journal = Journal(self.store.namespace("rsm"), "r1")
        journal.append(b"e0")
        journal.append(b"e1")
        reopened = Journal(self.store.namespace("rsm"), "r1")
        self.assertEqual(reopened.append(b"e2"), 2)
        self.assertEqual(reopened.entries(), [b"e0", b"e1", b"e2"])
        self.assertEqual(reopened.entries(),
                         Journal(self.store.namespace("rsm"), "r1").entries())


class TestCommunicationOverStorage(StorageCase):
    def test_durable_publish_and_replay(self):
        from communication import Bus

        bus = Bus(storage=self.store.namespace("communication"))
        bus.subscribe("plan.created", "ws", durable=True)
        published = [{"event_id": "e%d" % i, "event_name": "plan.created",
                      "request_id": "r", "timestamp": 0, "payload": {"n": i}}
                     for i in range(3)]
        for message in published:
            bus.publish("plan.created", message)
        self.assertEqual(bus.replay("plan.created"), published)
        self.assertEqual(len(self.store.keys("communication/log/plan.created")), 3)
        # a FRESH bus over the same storage continues the log, never rewrites it
        bus2 = Bus(storage=self.store.namespace("communication"))
        bus2.publish("plan.created",
                     {"event_id": "e3", "event_name": "plan.created",
                      "request_id": "r", "timestamp": 0, "payload": {"n": 3}})
        self.assertEqual([m["event_id"] for m in bus2.replay("plan.created")],
                         ["e0", "e1", "e2", "e3"])

    def test_storage_events_on_bus(self):
        from communication import Bus

        bus = Bus()
        bus.subscribe("storage.committed", "obs")
        with tempfile.TemporaryDirectory() as tmp:
            with Store(os.path.join(tmp, "v"), bus=bus) as eventful:
                eventful.namespace("ums").write("ums/blob", b"x")
        committed = bus.drain("storage.committed", "obs")
        self.assertEqual(committed[0]["payload"]["key"], "ums/blob")
        self.assertEqual(committed[0]["event_name"], "storage.committed")  # ERRATA C13


class TestRsmOverStorage(StorageCase):
    def test_rsm_persistence_runs_unmodified_on_real_storage(self):
        from rsm import persistence
        from rsm.ingest import APPLIED, Ingest, make_event
        from rsm.journal import Journal as RsmJournal
        from rsm.store import Store as RsmStore

        rsm_store = RsmStore()
        journal = RsmJournal()
        ing = Ingest(rsm_store, journal)
        birth = make_event("e1", "request.received", "r1", 1,
                           {"declared_type": "type.alpha", "origin": "frontend"})
        self.assertEqual(ing.process(birth), APPLIED)
        handle = self.store.namespace("rsm")
        persistence.write_journal_index(handle, "r1", journal)
        doc = json.loads(handle.read("rsm/journal/r1").decode("utf-8"))
        self.assertEqual(persistence.read_journal_index(handle, "r1"), doc)


class TestFullStack(unittest.TestCase):
    """Kernel over real Bus over real Store: restart + byte-identical replay."""

    def test_kernel_bus_storage_restart_replay(self):
        from communication import Bus
        from kernel import envelope
        from kernel.coordinator import Coordinator
        from kernel.default_config import snapshot

        def drive(coordinator):
            e = lambda i, n, r, p: envelope.make(i, n, r, 0, None, p)  # noqa: E731
            coordinator.handle(e("e1", "request.received", "r1",
                                 {"declared_type": "type.alpha"}))
            coordinator.handle(e("e2", "plan.created", "r1", {}))
            coordinator.handle(e("e3", "verify.passed", "r1", {}))
            coordinator.handle(e("e4", "task.completed", "r1", {}))

        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "vault")
            with Store(vault) as store:
                bus = Bus(storage=store.namespace("communication"))
                coord = Coordinator(bus, snapshot())
                drive(coord)
                self.assertEqual(coord.ledger.get("r1").lifecycle_state, "completed")
                live_log = list(coord.log)
            # "process restart": new Store + new Bus over the same directory
            with Store(vault) as store2:
                bus2 = Bus(storage=store2.namespace("communication"))
                persisted = bus2.replay("transition.log")
                self.assertEqual(persisted, live_log)  # byte-identical reconstruction
                coord2 = Coordinator(bus2, snapshot())
                self.assertTrue(coord2.recover(persisted))
                self.assertEqual(coord2.ledger.get("r1").lifecycle_state, "completed")


if __name__ == "__main__":
    unittest.main()
