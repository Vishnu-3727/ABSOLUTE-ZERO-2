"""B4 / ERRATA C9 plugin-reliability conformance.

Two concepts, one seam (PRT/04 §5): PRT owns live health, Learning owns
learned reliability, `reliability.updated` flows one way into PRT's fold.
Cross-package guards the per-component enforcers cannot see:

  1. PRT never authors reliability: no publish of `reliability.updated`
     anywhere in src/prt (consumed-only).
  2. Learning never reads live health: src/lie contains no PRT import and
     no plugin.health reference.
  3. Health computation is registry-blind (PRT-H2 structural): health.py
     imports nothing from registry.py.

Deterministic replay of health state is already proven behaviorally by
tests/test_prt_phase4.py::test_fold_from_scratch_equals_incremental.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _code_of(path):
    """Comment-stripped module body; the `__main__` selftest block is cut —
    selftests may simulate the *other* side of a seam (repo convention,
    e.g. reliability_bridge.py publishing a fixture reliability.updated)."""
    text = path.read_text(encoding="utf-8").split('if __name__ ==', 1)[0]
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_prt_never_authors_reliability():
    offenders = [str(p) for p in _py_files(SRC / "prt")
                 if 'publish("reliability.updated"' in _code_of(p)]
    assert offenders == [], (
        "reliability.updated is Learning's to publish; PRT consumes only (ERRATA C9): %s"
        % offenders)


def test_learning_never_reads_live_health():
    offenders = []
    for path in _py_files(SRC / "lie"):
        code = _code_of(path)
        if re.search(r"^\s*(from|import)\s+prt\b", code, re.MULTILINE) or "plugin.health" in code:
            offenders.append(str(path))
    assert offenders == [], (
        "Learning distills closed traces, never live health (ERRATA C9): %s" % offenders)


def test_health_is_registry_blind():
    code = _code_of(SRC / "prt" / "health.py")
    assert not re.search(r"^\s*from\s+\.?registry\b|^\s*import\s+registry\b",
                         code, re.MULTILINE), (
        "health.py must import nothing from registry.py (PRT-H2)")
