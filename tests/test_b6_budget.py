"""B6 / ERRATA C6 budget-ownership conformance.

Layered budget authority (ERRATA C6): SGPE authors limits, Scheduling
allocates, Observability meters, CM/UMS/RO fit under handed ceilings.
These guards prove the prohibitions structurally:

  1. Fitting never modifies allocations — the CM/UMS fitters are pure:
     no bus, no storage, no events import; ceilings arrive as parameters.
  2. RO's reasoning budget is an immutable derived representation — the
     frozen BudgetEnvelope refuses mutation, and RO's budget module holds
     no mutable ledger.
  3. Policy never meters — SGPE emits no spend/violation accounting
     events (`cost.recorded`, `budget.exceeded` are Observability's).
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

_SIDE_EFFECT_IMPORT_RE = re.compile(
    r"^\s*(from|import)\s+\.?(bus_double|storage_double|events|persistence)\b",
    re.MULTILINE)


def test_fitters_are_pure():
    for fitter in (SRC / "cm" / "budgeter.py", SRC / "ums" / "budget.py"):
        text = fitter.read_text(encoding="utf-8")
        assert not _SIDE_EFFECT_IMPORT_RE.search(text), (
            "%s must stay a pure fitter (ERRATA C6): no bus/storage/events" % fitter)
        assert ".publish(" not in text and ".write(" not in text, (
            "%s must not emit or persist (fitting never changes allocations)" % fitter)


def test_reasoning_envelope_is_immutable():
    from ro.budget import BudgetEnvelope, allocate_budget
    env = allocate_budget(100, 1)
    try:
        env.ceiling = 200
    except Exception as exc:  # dataclasses.FrozenInstanceError
        assert type(exc).__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("BudgetEnvelope must be frozen (ERRATA C6)")
    # child allocation draws from parent remaining, never mutates the parent
    child = allocate_budget(40, 1, parent=env, already_allocated_from_parent=0)
    assert env.ceiling == 100 and child.ceiling == 40
    assert isinstance(child, BudgetEnvelope)


def test_policy_never_meters():
    offenders = []
    for path in (SRC / "sgpe").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "cost.recorded" in text or "budget.exceeded" in text:
            offenders.append(str(path))
    assert offenders == [], (
        "SGPE never meters spend; accounting events are Observability's (ERRATA C6): %s"
        % offenders)
