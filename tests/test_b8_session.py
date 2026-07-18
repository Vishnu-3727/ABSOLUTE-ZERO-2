"""B8 / ERRATA C11 session-ownership conformance.

Sessions decompose (ERRATA C11): Lifecycle owns identity + boundary events;
each stateful component housekeeps only its own state at the boundary.

  1. Nobody mints session boundaries: no `publish("session.…")` in any
     module body (Lifecycle, the sole chartered publisher, is unbuilt).
  2. The invented names `session.woke` / `session.slept` appear nowhere.
  3. Runtime: at `session.sleep` the Kernel evicts only its own *terminal*
     ledger entries — an in-flight request survives — and each eviction is
     logged as `__cleanup__` first (eviction is not deletion).
  4. Replay: `recover()` over a log containing `__cleanup__` records
     reproduces the post-eviction ledger exactly.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _module_body(path):
    text = path.read_text(encoding="utf-8").split('if __name__ ==', 1)[0]
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_nobody_mints_session_boundaries():
    offenders = [str(p) for p in _py_files(SRC)
                 if 'publish("session.' in _module_body(p)]
    assert offenders == [], (
        "session.wake/sleep are Lifecycle's alone to publish (ERRATA C11): %s" % offenders)


def test_invented_session_names_do_not_exist():
    offenders = [str(p) for p in _py_files(SRC)
                 if "session.woke" in _module_body(p) or "session.slept" in _module_body(p)]
    assert offenders == [], (
        "canonical names are session.wake/session.sleep (ERRATA C11): %s" % offenders)


def _run_to_sleep():
    from kernel import envelope
    from kernel.bus import Bus
    from kernel.coordinator import Coordinator
    from kernel.default_config import snapshot

    def env(eid, name, rid, payload):
        return envelope.make(eid, name, rid, 0, None, payload)

    coord = Coordinator(Bus(), snapshot())
    # r1 driven to terminal state
    coord.handle(env("e1", "request.received", "r1", {"declared_type": "type.alpha"}))
    coord.handle(env("e2", "plan.created", "r1", {}))
    coord.handle(env("e3", "verify.passed", "r1", {}))
    coord.handle(env("e4", "task.completed", "r1", {}))
    # r2 left in flight
    coord.handle(env("e5", "request.received", "r2", {"declared_type": "type.alpha"}))
    coord.handle(env("e6", "session.sleep", None, {}))
    return coord


def test_sleep_evicts_only_own_terminal_entries():
    coord = _run_to_sleep()
    assert coord.ledger.get("r1") is None, "terminal entry evicted at sleep"
    assert coord.ledger.get("r2") is not None, "in-flight request must survive sleep"
    cleanups = [r for r in coord.log if r.get("event") == "__cleanup__"]
    assert [r["request_id"] for r in cleanups] == ["r1"], (
        "every eviction is logged before the entry goes (eviction is not deletion)")


def test_cleanup_replays_deterministically():
    from kernel.bus import Bus
    from kernel.coordinator import Coordinator
    from kernel.default_config import snapshot

    coord = _run_to_sleep()
    replayed = Coordinator(Bus(), snapshot())
    assert replayed.recover(list(coord.log)) is True
    assert replayed.ledger.get("r1") is None
    assert replayed.ledger.get("r2") is not None
    assert replayed.ledger.get("r2").lifecycle_state == coord.ledger.get("r2").lifecycle_state
