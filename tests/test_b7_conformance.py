"""B7 / ERRATA C12 — the repo conformance layer's front door for the two
GLOBAL invariant checks provisionally hosted in peer modules.

Local invariants stay with their components (their own law_enforcers,
exercised by the phase-5 suites). Global invariants have one authority:
this layer. Invoking the hosted global checks directly from here means
they keep running in CI even if a phase suite is refactored away.

  1. Law 2, system-wide: no component outside UMS scans repositories or
     implements similarity; exactly one similarity implementation exists
     (ums/ranker.py). Hosted in ums/law_enforcer.py (custodian: UMS).
  2. CM-I8, system-wide: exactly one `class Assembler` definition exists
     (cm/assembler.py). Hosted in cm/law_enforcer.py (custodian: CM).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

SRC = str(Path(__file__).resolve().parent.parent / "src")


def test_law2_no_foreign_retrieval_or_similarity():
    from ums import law_enforcer
    from ums.storage_double import StorageDouble

    violations = law_enforcer.check(SRC, StorageDouble())
    assert violations == [], (
        "Law 2 (global): retrieval/similarity outside UMS — %s" % violations)


def test_law2_single_similarity_owner():
    from ums import law_enforcer
    from ums.storage_double import StorageDouble

    owners = law_enforcer.similarity_owners(SRC, StorageDouble())
    assert owners == ["ums/ranker.py"], (
        "exactly one similarity implementation system-wide — found %s" % owners)


def test_single_assembler_system_wide():
    from cm import law_enforcer

    hits = law_enforcer.check_single_assembler(SRC)
    assert hits == ["cm/assembler.py"], (
        "CM-I8 (global): exactly one Assembler class — found %s" % hits)
