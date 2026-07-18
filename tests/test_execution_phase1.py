"""Execution phase 1 — the real spawner (COMPONENTS/execution.md, ERRATA
C14). Unit: deterministic lifecycle, containment, retries, timeout,
cancellation, fail-closed specs. Integration: records through real
Storage (append-only, byte-identical across identical runs, restart
recovery), `exec.*` events through the real Communication bus (schema-
validated). Guard: Execution is the only module in src that spawns.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from execution import (BadSpecError, CANCELLED, CapsUnsupportedError,  # noqa: E402
                       COMPLETED, Engine, FAILED, IllegalTransitionError,
                       TIMEOUT)

PY = sys.executable
REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def spec(code, timeout=30, retries=0, **extra):
    out = {"command": [PY, "-c", code], "timeout_seconds": timeout,
           "max_retries": retries}
    out.update(extra)
    return out


class TestEngineUnit(unittest.TestCase):
    def test_completed(self):
        engine = Engine()
        handle = engine.submit(spec("print('ok')"))
        result = engine.run(handle)
        self.assertEqual((result["state"], result["exit_code"]), (COMPLETED, 0))
        self.assertIn(b"ok", result["stdout"])
        self.assertEqual(handle.state, COMPLETED)

    def test_failure_contained_never_raises(self):
        engine = Engine()
        result = engine.run(engine.submit(spec("raise SystemExit(9)")))
        self.assertEqual((result["state"], result["exit_code"]), (FAILED, 9))

    def test_unlaunchable_contained(self):
        engine = Engine()
        handle = engine.submit({"command": ["no-such-binary-zzz"],
                                "timeout_seconds": 5})
        self.assertEqual(engine.run(handle)["state"], FAILED)

    def test_bounded_retries_then_failed(self):
        engine = Engine()
        handle = engine.submit(spec("raise SystemExit(1)", retries=2))
        self.assertEqual(engine.run(handle)["state"], FAILED)
        self.assertEqual(handle.attempts, 3)  # 1 + 2 retries, never infinite

    def test_retry_stops_at_first_success(self):
        calls = []

        def flaky_runner(s):
            calls.append(1)
            code = 1 if len(calls) < 2 else 0
            return {"state": None, "exit_code": code, "stdout": b"", "stderr": b""}

        engine = Engine(runner=flaky_runner)
        handle = engine.submit(spec("ignored", retries=5))
        self.assertEqual(engine.run(handle)["state"], COMPLETED)
        self.assertEqual(handle.attempts, 2)

    def test_timeout_definite_terminal_no_retry_caller_survives(self):
        engine = Engine()
        handle = engine.submit(spec("import time; time.sleep(60)",
                                    timeout=1, retries=5))
        result = engine.run(handle)
        self.assertEqual(result["state"], TIMEOUT)
        self.assertEqual(handle.attempts, 1)  # timeout never retried

    def test_cancellation(self):
        engine = Engine()
        handle = engine.submit(spec("print(1)"))
        engine.cancel(handle)
        self.assertEqual(handle.state, CANCELLED)
        with self.assertRaises(IllegalTransitionError):
            engine.run(handle)
        with self.assertRaises(IllegalTransitionError):
            engine.cancel(handle)

    def test_fail_closed_specs(self):
        engine = Engine()
        for bad in ({}, {"command": "not-argv", "timeout_seconds": 1},
                    {"command": ["x"], "timeout_seconds": -1},
                    {"command": ["x"], "timeout_seconds": 1, "max_retries": -1}):
            with self.assertRaises(BadSpecError):
                engine.submit(bad)

    def test_declared_caps_refused_not_ignored(self):
        engine = Engine()
        with self.assertRaises(CapsUnsupportedError):  # ERRATA C14 §3
            engine.submit(spec("print(1)", resource_caps={"mem_mb": 64}))


class TestStorageIntegration(unittest.TestCase):
    def test_journal_byte_identical_across_identical_runs_and_restart(self):
        from storage import Store

        def run_once(vault):
            with Store(vault) as store:
                engine = Engine(storage=store.namespace("execution"))
                handle = engine.submit(spec("print('det')", retries=1))
                engine.run(handle)
                return handle.execution_id

        with tempfile.TemporaryDirectory() as tmp:
            xid_a = run_once(os.path.join(tmp, "a"))
            xid_b = run_once(os.path.join(tmp, "b"))
            self.assertEqual(xid_a, xid_b)
            with Store(os.path.join(tmp, "a")) as sa, \
                 Store(os.path.join(tmp, "b")) as sb:
                keys_a = sa.keys("execution")
                self.assertEqual(keys_a, sb.keys("execution"))
                for key in keys_a:  # byte-identical journals
                    self.assertEqual(sa.read(key), sb.read(key))
                # restart recovery: a fresh engine reconstructs the records
                fresh = Engine(storage=sa.namespace("execution"))
                records = fresh.records(xid_a)
                self.assertEqual([r["kind"] for r in records],
                                 ["attempt", "terminal"])
                self.assertEqual(records[-1]["outcome"], COMPLETED)
                self.assertEqual(records[-1]["exit_code"], 0)
                self.assertIn("stdout_sha256", records[-1])


class TestCommunicationIntegration(unittest.TestCase):
    def test_exec_events_validate_and_flow(self):
        from communication import Bus

        bus = Bus()
        for topic in ("exec.started", "exec.completed", "exec.failed",
                      "exec.timeout"):
            bus.subscribe(topic, "probe")
        engine = Engine(bus=bus)

        engine.run(engine.submit(spec("print(1)", request_id="r1")))
        started = bus.drain("exec.started", "probe")
        completed = bus.drain("exec.completed", "probe")
        self.assertEqual(len(started), 1)
        self.assertEqual(completed[0]["request_id"], "r1")
        self.assertEqual(completed[0]["payload"]["exit_code"], 0)

        engine.run(engine.submit(spec("raise SystemExit(2)", retries=1)))
        self.assertEqual(len(bus.drain("exec.started", "probe")), 2)  # per attempt
        failed = bus.drain("exec.failed", "probe")
        self.assertEqual(failed[0]["payload"]["attempts"], 2)

        engine.run(engine.submit(spec("import time; time.sleep(60)", timeout=1)))
        self.assertEqual(len(bus.drain("exec.timeout", "probe")), 1)


def test_execution_is_the_only_spawner():
    offenders = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts or (SRC / "execution") in path.parents:
            continue
        text = "\n".join(line.split("#", 1)[0]
                         for line in path.read_text(encoding="utf-8").splitlines())
        if "subprocess" in text or "os.system" in text or "Popen" in text:
            offenders.append(str(path))
    assert offenders == [], (
        "Execution is the sole process spawner (Global Law 3): %s" % offenders)


if __name__ == "__main__":
    unittest.main()
