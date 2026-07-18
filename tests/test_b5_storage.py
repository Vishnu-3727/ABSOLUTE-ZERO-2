"""B5 / ERRATA C7 storage-mediation conformance.

Storage serves bytes only to the state's owner; cross-component reads go
through the owner's query surface. Guards:

  1. CM never touches Storage — no storage import, no read/write call
     anywhere in src/cm (its reads are ums.query / rsm.query, the owner
     doors its own law enforcer licenses).
  2. Storage key namespaces are owner-disjoint: any quoted key prefix of
     the form "<pkg>/..." appearing in a package's source names that
     package alone — no component writes or reads another owner's keys.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

_PACKAGES = ("cm", "communication", "kernel", "lie", "prt", "ro", "rsm", "sgpe",
             "ums", "vae")
_KEY_RE = re.compile(r'["\'](%s)/' % "|".join(_PACKAGES))
_STORAGE_IMPORT_RE = re.compile(r"^\s*(from|import)\s+\.?storage", re.MULTILINE)


def _py_files(root):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_cm_never_touches_storage():
    offenders = []
    for path in _py_files(SRC / "cm"):
        code = "\n".join(line.split("#", 1)[0]
                         for line in path.read_text(encoding="utf-8").splitlines())
        if _STORAGE_IMPORT_RE.search(code) or "storage.read" in code or "storage.write" in code:
            offenders.append(str(path))
    assert offenders == [], (
        "CM reads through owner query surfaces, never Storage (ERRATA C7): %s" % offenders)


def test_storage_key_namespaces_are_owner_disjoint():
    offenders = []
    for pkg in _PACKAGES:
        for path in _py_files(SRC / pkg):
            for match in _KEY_RE.finditer(path.read_text(encoding="utf-8")):
                if match.group(1) != pkg:
                    offenders.append("%s uses key prefix %s/" % (path, match.group(1)))
    assert offenders == [], (
        "storage keys are owner-namespaced; no cross-owner keys (ERRATA C7): %s" % offenders)
