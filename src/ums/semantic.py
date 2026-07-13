"""Semantic layer orchestrator (Phase 3). Deterministic, zero LLM calls.

Builds summaries (through the hash-keyed SummaryStore — unchanged content
is NEVER re-summarized), relations, architecture model, and the explicit
LLM gap list. Doc-file text is read via storage.read_bytes only when that
content hash has no stored summary yet (once per hash, ever).

The architecture model is rebuilt only when structural facts changed:
pass previous_architecture + structural_changed=False to reuse it
verbatim (Phase 5 cascade discipline).
"""
from . import architecture, gaps, relations, summarize
from .extraction import canonical  # generic canonical json bytes

DOC_LANGS = ("markdown", "text")


def build(extraction, storage, repo_root, store,
          previous_architecture=None, structural_changed=True):
    """Semantic bundle for one repo: summaries/relations/architecture/gaps."""
    summaries = {}
    for path in sorted(extraction["files"]):
        entry = extraction["files"][path]

        def builder(path=path, entry=entry):
            text = None
            if (entry["classification"]["language"] in DOC_LANGS
                    and entry["unparsed"] is None):
                text = storage.read_bytes(repo_root + "/" + path).decode(
                    "utf-8", errors="replace")
            return summarize.summarize_file(entry, text)

        record = store.get_or_build(entry["content_hash"], builder)
        summaries[path] = dict(record, hash=entry["content_hash"])
    if structural_changed or previous_architecture is None:
        arch = architecture.model(extraction)
    else:
        arch = previous_architecture  # cascade: untouched, reused verbatim
    return {
        "summaries": summaries,
        "relations": relations.derive(extraction, summaries),
        "architecture": arch,
        "gaps": gaps.detect(extraction),
    }


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from ums import extraction as ext_mod
    from ums import inventory as inv_mod
    from ums.storage_double import StorageDouble
    from ums.summary_store import SummaryStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        files = {
            "app.py": b'"""App."""\n\n\ndef main():\n    pass\n',
            "README.md": b"# Fixture\n\nSee app.py\n",
        }
        for rel, content in files.items():
            with open(os.path.join(tmp, rel), "wb") as handle:
                handle.write(content)
        root = tmp.replace(os.sep, "/")
        storage = StorageDouble()
        inv = inv_mod.scan(root, storage)
        ext = ext_mod.extract_repo(inv, storage, root)

        store = SummaryStore()
        sem = build(ext, storage, root, store)
        assert sem["summaries"]["app.py"]["reference"] == "App."
        assert sem["summaries"]["README.md"]["reference"] == "Fixture"
        assert {(e["kind"], e["dst"]) for e in sem["relations"]} == {
            ("doc-mentions", "file:app.py")}
        assert sem["architecture"]["entrypoints"] == ["app.py"]
        assert [o["reason"] for o in sem["gaps"]] == ["undocumented_symbols:1"]
        builds = store.builds
        reads = storage.bytes_read_calls

        # second run: zero summarization work, zero doc re-reads
        sem2 = build(ext, storage, root, store)
        assert store.builds == builds and storage.bytes_read_calls == reads
        assert canonical(sem2) == canonical(sem)

        # non-structural rebuild reuses architecture verbatim
        sem3 = build(ext, storage, root, store,
                     previous_architecture=sem["architecture"],
                     structural_changed=False)
        assert sem3["architecture"] is sem["architecture"]
    print("semantic selftest ok")
