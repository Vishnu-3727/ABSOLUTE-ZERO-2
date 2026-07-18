"""Execution substrate — the sole process spawner (COMPONENTS/execution.md;
Global Law 3; V1-H4 containment; ERRATA C14).

`Engine` executes exactly what it is given — an execution spec naming an
argv command, a timeout, and a bounded retry budget — and owns nothing
else: no planning, no routing, no policy, no interpretation of outputs.

Deterministic state machine per execution:

    PENDING --run()--> RUNNING --> COMPLETED | FAILED | TIMEOUT
    PENDING --cancel()--> CANCELLED

  Containment   run() NEVER raises for anything the child process does:
                non-zero exit, crash, hang — all become a definite
                terminal result returned to the caller (V1-H4: a runaway
                tool can never take down its caller). Engine-level
                refusals (malformed spec, illegal transition) raise, fail
                closed.
  Timeout       enforced on every attempt (subprocess timeout + kill);
                a timeout is immediately terminal — never retried, never
                a silent hang. Every execution yields exactly one
                terminal event.
  Retries       bounded: non-zero exit retries up to `max_retries`, then
                FAILED. Never infinite.
  Records       every attempt and the terminal outcome are appended to an
                execution journal (Storage-owned bytes, append-only,
                ERRATA C7 namespace `execution/`). Records carry exit
                codes, attempt counts, and output sha256 digests — never
                wall-clock durations, so the journal is byte-identical
                across replays of deterministic tools. Outputs themselves
                (stdout/stderr) are returned to the caller, not persisted
                (execution.md Never Owns: callers decide what outlives
                the call).
  Events        `exec.started` per attempt; exactly one terminal
                `exec.completed` / `exec.failed` / `exec.timeout`
                (ERRATA C14 canon; PRT/05 §4 D2). Deterministic event ids
                `<execution_id>:<attempt>:<name>`. Bus optional — no bus,
                no events, same execution.
  Caps          a spec declaring resource caps is REFUSED
                (CapsUnsupportedError) until a sandbox backend exists —
                fail closed, never accept-and-ignore (ERRATA C14 §3).
"""
import hashlib
import json
import subprocess

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
TIMEOUT = "timeout"
CANCELLED = "cancelled"
TERMINAL = (COMPLETED, FAILED, TIMEOUT, CANCELLED)

_EVENT_BY_STATE = {COMPLETED: "exec.completed", FAILED: "exec.failed",
                   TIMEOUT: "exec.timeout"}


class ExecutionRefusal(Exception):
    """Base for engine-level refusals (never used for child failures)."""


class BadSpecError(ExecutionRefusal):
    """Malformed execution spec."""


class CapsUnsupportedError(ExecutionRefusal):
    """Spec declares resource caps no backend can enforce (ERRATA C14 §3)."""


class IllegalTransitionError(ExecutionRefusal):
    """run()/cancel() against a state that forbids it."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class ExecutionHandle:
    """One execution's identity + state + result. Engine is sole mutator."""

    def __init__(self, execution_id, spec):
        self.execution_id = execution_id
        self.spec = spec
        self.state = PENDING
        self.attempts = 0
        self.result = None  # terminal dict: state/exit_code/stdout/stderr


class Engine:
    def __init__(self, storage=None, bus=None, runner=None):
        """storage: Storage namespace handle for `execution/` (record
        journal); bus: Communication bus (events); runner: injectable
        attempt runner for tests — defaults to a real subprocess run.
        All three optional; with none, the engine still executes and
        contains, it just leaves no trail."""
        self.storage = storage
        self.bus = bus
        self._runner = runner if runner is not None else self._subprocess_runner
        self._handles = {}
        self._next_id = 1

    # -- submission (Scheduling's task.scheduled carries these specs) ----

    def submit(self, spec):
        """spec: {"command": [argv...], "timeout_seconds": num > 0,
        "max_retries": int >= 0, optional "request_id", optional
        "resource_caps"}. Execution never interprets anything else."""
        if not isinstance(spec, dict):
            raise BadSpecError("execution.spec_not_mapping:" + repr(spec))
        command = spec.get("command")
        if (not isinstance(command, (list, tuple)) or not command
                or not all(isinstance(part, str) for part in command)):
            raise BadSpecError("execution.bad_command:" + repr(command))
        timeout = spec.get("timeout_seconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise BadSpecError("execution.bad_timeout:" + repr(timeout))
        retries = spec.get("max_retries", 0)
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
            raise BadSpecError("execution.bad_max_retries:" + repr(retries))
        if spec.get("resource_caps"):
            raise CapsUnsupportedError(
                "execution.caps_unenforceable:" + repr(spec["resource_caps"]))
        handle = ExecutionHandle("x-%06d" % self._next_id, dict(spec))
        self._next_id += 1
        self._handles[handle.execution_id] = handle
        return handle

    def get(self, execution_id):
        return self._handles.get(execution_id)

    # -- lifecycle --------------------------------------------------------

    def cancel(self, handle):
        """Legal only while PENDING (a RUNNING attempt is bounded by its
        timeout; a terminal execution is history)."""
        if handle.state != PENDING:
            raise IllegalTransitionError(
                "execution.cancel_illegal:" + handle.state)
        handle.state = CANCELLED
        handle.result = {"state": CANCELLED, "exit_code": None}
        self._record(handle, "terminal", {"outcome": CANCELLED})
        return handle.result

    def run(self, handle):
        """Execute to a definite terminal state. Child-process behavior
        never raises — containment is the whole point (V1-H4)."""
        if handle.state != PENDING:
            raise IllegalTransitionError("execution.run_illegal:" + handle.state)
        handle.state = RUNNING
        retries = handle.spec.get("max_retries", 0)
        outcome = None
        for attempt in range(1, retries + 2):
            handle.attempts = attempt
            self._record(handle, "attempt", {"attempt": attempt})
            self._emit(handle, "exec.started", attempt, {"attempt": attempt})
            outcome = self._runner(handle.spec)
            if outcome["state"] == TIMEOUT:
                break  # terminal immediately: definite, never retried
            if outcome["exit_code"] == 0:
                outcome["state"] = COMPLETED
                break
            outcome["state"] = FAILED  # retry if budget remains
        handle.state = outcome["state"]
        handle.result = outcome
        self._record(handle, "terminal", {
            "outcome": outcome["state"],
            "exit_code": outcome["exit_code"],
            "attempts": handle.attempts,
            "stdout_sha256": _sha256(outcome.get("stdout", b"")),
            "stderr_sha256": _sha256(outcome.get("stderr", b"")),
        })
        self._emit(handle, _EVENT_BY_STATE[outcome["state"]], handle.attempts, {
            "exit_code": outcome["exit_code"], "attempts": handle.attempts})
        return outcome

    # -- the one real spawn site in the whole operating system ------------

    def _subprocess_runner(self, spec):
        try:
            proc = subprocess.run(
                list(spec["command"]), capture_output=True,
                timeout=spec["timeout_seconds"])
            return {"state": None, "exit_code": proc.returncode,
                    "stdout": proc.stdout, "stderr": proc.stderr}
        except subprocess.TimeoutExpired as exc:
            return {"state": TIMEOUT, "exit_code": None,
                    "stdout": exc.stdout or b"", "stderr": exc.stderr or b""}
        except OSError as exc:
            # unlaunchable command: a definite failure, not a caller crash
            return {"state": None, "exit_code": 127,
                    "stdout": b"", "stderr": repr(exc).encode()}

    # -- records + events --------------------------------------------------

    def _record(self, handle, kind, fields):
        if self.storage is None:
            return
        from storage import Journal
        journal = Journal(self.storage, handle.execution_id)
        doc = {"execution_id": handle.execution_id, "kind": kind}
        doc.update(fields)
        journal.append(json.dumps(doc, sort_keys=True,
                                  separators=(",", ":")).encode())

    def records(self, execution_id):
        """Replay hook: the execution's full journal, decoded, in order."""
        if self.storage is None:
            return []
        from storage import Journal
        journal = Journal(self.storage, execution_id)
        return [json.loads(entry.decode()) for entry in journal.entries()]

    def _emit(self, handle, event_name, attempt, payload):
        if self.bus is None:
            return
        body = {"execution_id": handle.execution_id}
        body.update(payload)
        self.bus.publish(event_name, {
            "event_id": "%s:%d:%s" % (handle.execution_id, attempt, event_name),
            "event_name": event_name,
            "request_id": handle.spec.get("request_id"),
            "timestamp": 0,
            "payload": body,
        })


if __name__ == "__main__":
    import sys

    engine = Engine()
    ok = engine.submit({"command": [sys.executable, "-c", "print('hi')"],
                        "timeout_seconds": 30})
    result = engine.run(ok)
    assert result["state"] == COMPLETED and result["exit_code"] == 0
    assert b"hi" in result["stdout"]

    bad = engine.submit({"command": [sys.executable, "-c", "raise SystemExit(3)"],
                         "timeout_seconds": 30, "max_retries": 1})
    result = engine.run(bad)
    assert result["state"] == FAILED and result["exit_code"] == 3 and bad.attempts == 2

    hang = engine.submit({"command": [sys.executable, "-c",
                                      "import time; time.sleep(60)"],
                          "timeout_seconds": 1})
    result = engine.run(hang)  # caller survives; definite terminal event
    assert result["state"] == TIMEOUT and hang.attempts == 1

    gone = engine.submit({"command": ["definitely-not-a-real-binary-xyz"],
                          "timeout_seconds": 5})
    assert engine.run(gone)["state"] == FAILED  # unlaunchable = contained failure

    pend = engine.submit({"command": ["x"], "timeout_seconds": 1})
    engine.cancel(pend)
    assert pend.state == CANCELLED
    try:
        engine.run(pend)
        raise SystemExit("ran a cancelled execution")
    except IllegalTransitionError:
        pass
    for bad_spec in ({}, {"command": [], "timeout_seconds": 1},
                     {"command": ["x"], "timeout_seconds": 0},
                     {"command": ["x"], "timeout_seconds": 1,
                      "resource_caps": {"mem_mb": 64}}):
        try:
            engine.submit(bad_spec)
            raise SystemExit("bad spec accepted: %r" % bad_spec)
        except ExecutionRefusal:
            pass
    print("engine selftest ok")
