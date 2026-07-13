"""Structural extraction orchestrator (Phase 2). Deterministic, zero LLM.

Consumes ONLY the Phase-1 inventory plus storage.read_bytes — never walks
disk itself. Each changed file is read once and its AST parsed once;
symbols, imports, and convention counters all come from that single parse.
Token law: a file whose content_hash is unchanged since `previous` reuses
its whole per-file record — zero reads, zero parses.

Unparseable files are recorded loud: per-file "unparsed" reason plus the
top-level "unparsed" list. Never silently skipped.
"""
import ast
import json

from . import classify, conventions, deps, module_model, symbols


def extract_file(path, rec, storage, repo_root):
    """One file's extraction record (public: onboarding slices reuse it)."""
    raw = storage.read_bytes(repo_root + "/" + path)
    cls = classify.classify(path, raw[:128])
    entry = {"content_hash": rec.content_hash, "classification": cls,
             "symbols": None, "imports": [], "measures": None,
             "module_doc": None, "unparsed": None}
    if cls["language"] != "python":
        return entry  # file-level record; no extractor for this language
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=path)
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        entry["unparsed"] = type(exc).__name__ + ":" + str(exc)
        return entry
    entry["symbols"] = symbols.extract(cls["language"], tree)
    entry["imports"] = deps.imports_from(tree)
    entry["measures"] = conventions.measure(source, tree)
    entry["module_doc"] = ast.get_docstring(tree)
    return entry


def assemble(files):
    """Repo-level extraction output from per-file records (no disk work).

    Also serves partial file sets: onboarding assembles a queryable
    extraction from the slices indexed so far.
    """
    model = module_model.build(files)
    graph = deps.build_graph(files, model)
    measured = [e["measures"] for e in files.values()
                if e["measures"] is not None]
    return {
        "files": files,
        "modules": model,
        "graph": graph,
        "conventions": conventions.profile(measured),
        "unparsed": sorted(p for p, e in files.items()
                           if e["unparsed"] is not None),
    }


def extract_repo(inventory, storage, repo_root, previous=None):
    """Full extraction output for one repo.

    previous = a prior extract_repo() result; per-file records are reused
    verbatim when the content hash is unchanged (never re-read/re-parse).
    """
    prev_files = (previous or {}).get("files", {})
    files = {}
    for path in sorted(inventory):
        rec = inventory[path]
        prev = prev_files.get(path)
        if prev is not None and prev["content_hash"] == rec.content_hash:
            files[path] = prev
            continue
        files[path] = extract_file(path, rec, storage, repo_root)
    return assemble(files)


def canonical(extraction):
    """Canonical byte form (round-trip / determinism comparisons)."""
    return json.dumps(extraction, sort_keys=True,
                      separators=(",", ":")).encode()


if __name__ == "__main__":
    import os
    import sys
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from ums import inventory as inv_mod
    from ums.storage_double import StorageDouble

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "pkg"))
        fixture = {
            "app.py": b'"""App."""\nimport os\nfrom pkg.core import add\n\n\ndef main() -> None:\n    print(add(1, 2))\n',
            "pkg/__init__.py": b"from .core import add\n",
            "pkg/core.py": b'def add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n',
            "broken.py": b"def nope(:\n",
            "README.md": b"# Fixture\n",
        }
        for rel, content in fixture.items():
            with open(os.path.join(tmp, rel), "wb") as handle:
                handle.write(content)
        root = tmp.replace(os.sep, "/")

        store = StorageDouble()
        inv = inv_mod.scan(root, store)
        reads = store.bytes_read_calls
        out = extract_repo(inv, store, root)
        assert store.bytes_read_calls == reads + len(fixture)

        assert out["unparsed"] == ["broken.py"]
        assert out["files"]["broken.py"]["unparsed"].startswith("SyntaxError")
        assert out["files"]["README.md"]["symbols"] is None  # file-level
        assert [s["qualname"] for s in out["files"]["pkg/core.py"]["symbols"]] == ["add"]
        assert out["modules"]["packages"] == ["pkg"]
        edge_deps = {e["dst"]: e["dep"] for e in out["graph"]["edges"]
                     if e["kind"] == "imports"}
        assert edge_deps == {"module:os": "stdlib",
                             "module:pkg.core": "internal"}
        assert out["conventions"]["files_measured"] == 3

        # token law: unchanged repo, previous supplied -> zero new reads
        reads = store.bytes_read_calls
        out2 = extract_repo(inv, store, root, previous=out)
        assert store.bytes_read_calls == reads
        assert canonical(out2) == canonical(out)

        # run-to-run determinism without reuse
        assert canonical(extract_repo(inv, store, root)) == canonical(out)
    print("extraction selftest ok")
