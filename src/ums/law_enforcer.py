"""Law enforcer — automated Law 2 check across src/ (Phase 5).

No component outside UMS scans repositories or implements similarity;
exactly ONE similarity implementation exists system-wide (ums/ranker.py).
Runs as part of verifier/selftest. Walking OUR OWN source tree here is
compliance checking, not repository-content indexing; file bytes still
go through storage.read_bytes like every other UMS read.

Token match is plain substring over source text (comments included —
a components's docstring advertising os.walk is worth a look anyway).
"""
import os

# split literals so the enforcer never matches its own source (grep -v self)
_FLOOR = "SCORE" "_" "FLOOR"
SCAN_TOKENS = ("os." "walk", "os." "scandir", "os." "listdir",
               "glob." "glob", "rglob(", "iterdir(")
SIMILARITY_TOKENS = ("difflib", "Sequence" "Matcher", "similarity(",
                     "levenshtein", "cosine", _FLOOR, "fuzz")


def _py_files(src_dir, skip_dir):
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames.sort()
        if os.path.basename(dirpath) == skip_dir:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def check(src_dir, storage):
    """Violations outside src/ums: [{"file", "token"}]. Empty = law holds."""
    violations = []
    for path in _py_files(src_dir, skip_dir="ums"):
        source = storage.read_bytes(path).decode("utf-8", errors="replace")
        rel = os.path.relpath(path, src_dir).replace(os.sep, "/")
        for token in SCAN_TOKENS + SIMILARITY_TOKENS:
            if token in source:
                violations.append({"file": rel, "token": token})
    return violations


def similarity_owners(src_dir, storage):
    """Files (all of src/, UMS included) containing the ranking floor —
    must be exactly ["ums/ranker.py"]: one similarity implementation."""
    owners = []
    for path in _py_files(src_dir, skip_dir=None):
        source = storage.read_bytes(path).decode("utf-8", errors="replace")
        if _FLOOR in source:
            owners.append(os.path.relpath(path, src_dir).replace(os.sep, "/"))
    return sorted(owners)


if __name__ == "__main__":
    import tempfile

    from .storage_double import StorageDouble

    storage = StorageDouble()
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    # the real tree is law-compliant right now
    assert check(src_dir, storage) == []
    assert similarity_owners(src_dir, storage) == ["ums/ranker.py"]

    # a rogue component gets caught
    with tempfile.TemporaryDirectory() as tmp:
        rogue_pkg = os.path.join(tmp, "rogue")
        os.makedirs(rogue_pkg)
        with open(os.path.join(rogue_pkg, "sneaky.py"), "w") as handle:
            handle.write("import difflib\nfor f in os.walk('.'): pass\n")
        caught = check(tmp, storage)
        assert {v["token"] for v in caught} == {"os.walk", "difflib"}
        assert caught[0]["file"] == "rogue/sneaky.py"
        # but the same file inside a ums/ dir is licensed
        ums_pkg = os.path.join(tmp, "ums")
        os.makedirs(ums_pkg)
        os.rename(os.path.join(rogue_pkg, "sneaky.py"),
                  os.path.join(ums_pkg, "licensed.py"))
        assert check(tmp, storage) == []
    print("law_enforcer selftest ok")
