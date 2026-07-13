"""Relationship deriver — edges beyond imports. Deterministic.

doc-mentions: a doc file's identifier tokens (harvested hash-pure by the
summarizer) matched against module dotted names and file basenames.
spec-implements: a doc whose filename stem equals a module name.

ponytail: git co-change edges skipped — Storage has no git-history API
yet; add a derive_cochange() when Storage exposes commit history.
"""


def derive(extraction, summaries):
    """Relation edges: {"kind", "src" (doc path), "dst" (node id)}. Sorted."""
    modules = extraction["modules"]["modules"]  # dotted -> path
    stem_to_file = {}
    for path in extraction["files"]:
        stem = path.rsplit("/", 1)[-1]
        stem_to_file.setdefault(stem, path)          # "core.py"
        stem_to_file.setdefault(stem.rsplit(".", 1)[0], path)  # "core"
    edges = set()
    for path, record in summaries.items():
        tokens = set(record.get("tokens") or ())
        if not tokens:
            continue
        for dotted in modules:
            if dotted in tokens:
                edges.add(("doc-mentions", path, "module:" + dotted))
        for token in tokens:
            target = stem_to_file.get(token)
            if target is not None and target != path:
                edges.add(("doc-mentions", path, "file:" + target))
        doc_stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        for dotted in modules:
            if doc_stem == dotted.lower():
                edges.add(("spec-implements", path, "module:" + dotted))
    return [{"kind": k, "src": s, "dst": d} for k, s, d in sorted(edges)]


if __name__ == "__main__":
    extraction = {
        "files": {"app.py": {}, "pkg/core.py": {}, "README.md": {},
                  "docs/app.md": {}},
        "modules": {"modules": {"app": "app.py", "pkg.core": "pkg/core.py"}},
    }
    summaries = {
        "README.md": {"tokens": ["app.py", "pkg.core", "unrelated"]},
        "docs/app.md": {"tokens": ["core.py"]},
        "app.py": {"tokens": []},
    }
    edges = derive(extraction, summaries)
    triples = {(e["kind"], e["src"], e["dst"]) for e in edges}
    assert ("doc-mentions", "README.md", "module:pkg.core") in triples
    assert ("doc-mentions", "README.md", "file:app.py") in triples
    assert ("doc-mentions", "docs/app.md", "file:pkg/core.py") in triples
    assert ("spec-implements", "docs/app.md", "module:app") in triples
    # a doc never "mentions" itself; python files contribute no tokens
    assert not any(e["src"] == e["dst"] for e in edges)
    assert derive(extraction, summaries) == edges  # deterministic
    assert derive(extraction, {}) == []
    print("relations selftest ok")
