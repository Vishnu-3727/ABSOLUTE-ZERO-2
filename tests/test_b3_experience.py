"""B3 / ERRATA C8 experience-ownership conformance.

Experience is layered (ERRATA C8): components observe, only Learning (LIE)
authors lessons/priors, consumers hold versioned replay-pinned
representations. Guards:

  1. RO never authors experience: src/ro never publishes `prior.updated`
     or `lesson.recorded`, and never imports LIE.
  2. Lessons are authored only by LIE: `lesson.recorded` appears in no
     other package.
  3. RO's PriorsStore is a representation, not an authority: append-only,
     strictly monotonic versions, stale/duplicate refused loud, recorded
     versions immutable and readable forever (replay-pinned), artifacts
     frozen.
  4. Context assembly is ephemeral: CM persists nothing (no storage —
     already guarded by test_b5_storage; here: no persistence module).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _code_of(path):
    return "\n".join(line.split("#", 1)[0]
                     for line in path.read_text(encoding="utf-8").splitlines())


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_ro_never_authors_experience():
    offenders = []
    for path in _py_files(SRC / "ro"):
        code = _code_of(path)
        if "from lie" in code or "import lie" in code:
            offenders.append("%s imports lie" % path)
        if 'publish("prior.updated"' in code or 'publish("lesson.recorded"' in code:
            offenders.append("%s publishes an experience event" % path)
    assert offenders == [], "RO observes; only LIE authors (ERRATA C8): %s" % offenders


def test_lessons_authored_only_by_lie():
    offenders = []
    for pkg in ("cm", "kernel", "prt", "ro", "rsm", "sgpe", "ums", "vae"):
        for path in _py_files(SRC / pkg):
            if "lesson.recorded" in _code_of(path):
                offenders.append(str(path))
    assert offenders == [], (
        "lesson.recorded is LIE's alone (ERRATA C1/C8): %s" % offenders)


def test_priors_store_is_versioned_representation():
    from ro.priors import PriorsStore, StaleOrDuplicateVersionError

    def payload(version):
        return {"priors_version": version, "provider_priors": {"p": version},
                "routing_priors": {}, "demand_shape_priors": {}}

    store = PriorsStore()
    store.ingest(payload(1))
    store.ingest(payload(2))
    # stale and duplicate both refused loud (RO-S6)
    for bad in (1, 2):
        try:
            store.ingest(payload(bad))
        except StaleOrDuplicateVersionError:
            pass
        else:
            raise AssertionError("version %d must be refused" % bad)
    # replay pinning: recorded versions stay readable and unchanged
    v1 = store.at_version(1)
    assert v1.provider_priors["p"] == 1 and store.current().priors_version == 2
    # artifact is frozen — representation cannot be edited in place
    try:
        v1.priors_version = 99
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("PriorsArtifact must be frozen (ERRATA C8)")


def test_context_assembly_is_ephemeral():
    assert not (SRC / "cm" / "persistence.py").exists(), (
        "Request Memory is never persisted (ARCHITECTURE.md memory tiers)")
