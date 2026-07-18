"""B1 / ERRATA C4 ownership conformance — request lifecycle state.

Static checks that the corrected ownership model holds structurally:

  1. The Kernel never reads RSM (ADR-RSM-2's rejected alternative stays
     rejected; C4 point 1): no `import rsm` / `from rsm` anywhere in
     src/kernel/.
  2. The Kernel is the sole mutator of request lifecycle state (kernel I1;
     C4 point 1): no assignment to `lifecycle_state` outside src/kernel/.
  3. Lifecycle never publishes `request.completed` (C4 point 3): the
     component spec does not list it under Events Published, and the
     shipped kernel transition table does emit it — exactly one publisher.

These are charter guards, not behavior tests: they fail the moment a future
change reintroduces the dual ownership C4 closed.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

_RSM_IMPORT_RE = re.compile(r"^\s*(from rsm\b|import rsm\b)", re.MULTILINE)
_LIFECYCLE_WRITE_RE = re.compile(r"\.lifecycle_state\s*=[^=]|\blifecycle_state\s*=[^=]")


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_kernel_never_imports_rsm():
    offenders = [str(p) for p in _py_files(SRC / "kernel")
                 if _RSM_IMPORT_RE.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], "kernel must never read RSM (ERRATA C4): %s" % offenders


def test_lifecycle_state_mutated_only_in_kernel():
    offenders = []
    for path in _py_files(SRC):
        if (SRC / "kernel") in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.split("#", 1)[0]
            if "lifecycle_state" in stripped and _LIFECYCLE_WRITE_RE.search(stripped):
                offenders.append(str(path))
                break
    assert offenders == [], (
        "request lifecycle_state has one mutator, the Kernel (ERRATA C4): %s" % offenders)


def test_request_completed_has_one_publisher():
    spec = (REPO / "COMPONENTS" / "lifecycle.md").read_text(encoding="utf-8")
    published = spec.split("## Events Published", 1)[1].split("##", 1)[0]
    listed = [ln for ln in published.splitlines()
              if ln.lstrip().startswith("-") and "request.completed" in ln]
    assert listed == [], "lifecycle.md must not list request.completed as published (ERRATA C4)"
    table = (SRC / "kernel" / "default_config.py").read_text(encoding="utf-8")
    assert "request.completed" in table, "kernel transition table is the one publisher"
