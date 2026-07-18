"""B2 / ERRATA C5 gate-authority conformance.

Gates are layered by object (VAE/03 §3.1/§3.2, ratified by ERRATA C5):
Scheduling gates task dispatch, the Kernel gates request lifecycle
transitions. The Kernel is the gate authority — sole owner of gate
definitions and sole emitter of `gate.enforced` audit records.

Charter guards, not behavior tests: they fail the moment a future component
starts minting its own gate audit records or the Scheduling charter reclaims
gate authority.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_gate_enforced_emitted_only_by_kernel():
    offenders = []
    for path in _py_files(SRC):
        if (SRC / "kernel") in path.parents:
            continue
        if (SRC / "communication") in path.parents:
            continue  # the schema authority NAMES every event; it emits none (ERRATA C12 layering)
        if "gate.enforced" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == [], (
        "gate.enforced audit records are the Kernel's alone (ERRATA C5): %s" % offenders)


def test_kernel_gate_authority_is_real():
    # The authority claim is backed by shipped code: the kernel transition
    # table emits gate.enforced and the kernel owns gate definitions.
    table = (SRC / "kernel" / "default_config.py").read_text(encoding="utf-8")
    assert "gate.enforced" in table
    assert "gates" in table, "gate definitions live in the kernel-evaluated config"


def test_scheduling_charter_disclaims_gate_authority():
    spec = (REPO / "COMPONENTS" / "scheduling.md").read_text(encoding="utf-8")
    never_owns = spec.split("## Never Owns", 1)[1].split("##", 1)[0]
    assert "Gate authority" in never_owns, (
        "scheduling.md must disclaim gate authority (ERRATA C5)")
