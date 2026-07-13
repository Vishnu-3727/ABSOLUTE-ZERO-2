"""Architecture modeler — top-dir roles, entrypoints, dependency layering.

Deterministic heuristics over the extraction output only (V1
bootstrap-engine lineage). Measured facts, no LLM, no judgment beyond
the declared rules:
- top_dirs: file/role counts per first path component ("." = repo root)
- entrypoints: file defines a top-level main() or is named like one
- layers: internal-import depth; modules importing no internal module =
  layer 0, importers sit one above their deepest dependency.
"""
ENTRYPOINT_NAMES = ("__main__", "main", "app", "cli")
MAX_LAYER_PASSES = 50  # ponytail: bounded relaxation; cycles keep last value


def model(extraction):
    files = extraction["files"]
    modules = extraction["modules"]["modules"]  # dotted -> path

    top_dirs = {}
    for path, entry in files.items():
        top = path.split("/", 1)[0] if "/" in path else "."
        bucket = top_dirs.setdefault(top, {"files": 0, "roles": {}})
        bucket["files"] += 1
        role = entry["classification"]["role"]
        bucket["roles"][role] = bucket["roles"].get(role, 0) + 1

    entrypoints = []
    for dotted, path in modules.items():
        entry = files.get(path, {})
        has_main = any(s["qualname"] == "main"
                       for s in entry.get("symbols") or ())
        if has_main or dotted.rsplit(".", 1)[-1] in ENTRYPOINT_NAMES:
            entrypoints.append(path)
    entrypoints.sort()

    # internal module -> internal modules it imports (from the typed graph)
    module_of_file = {path: dotted for dotted, path in modules.items()}
    imports = {dotted: set() for dotted in modules}
    for edge in extraction["graph"]["edges"]:
        if edge["kind"] != "imports" or edge["dep"] != "internal":
            continue
        src = module_of_file.get(edge["src"][len("file:"):])
        dst = edge["dst"][len("module:"):]
        if src and dst in imports and dst != src:
            imports[src].add(dst)

    layers = {dotted: 0 for dotted in modules}
    for _ in range(MAX_LAYER_PASSES):
        changed = False
        for dotted, targets in imports.items():
            if targets:
                want = max(layers[t] for t in targets) + 1
                if layers[dotted] != want:
                    layers[dotted] = want
                    changed = True
        if not changed:
            break

    return {"top_dirs": dict(sorted(top_dirs.items())),
            "entrypoints": entrypoints,
            "layers": dict(sorted(layers.items()))}


if __name__ == "__main__":
    extraction = {
        "files": {
            "app.py": {"classification": {"role": "source"},
                       "symbols": [{"qualname": "main"}]},
            "pkg/core.py": {"classification": {"role": "source"},
                            "symbols": [{"qualname": "add"}]},
            "pkg/__init__.py": {"classification": {"role": "source"},
                                "symbols": []},
            "README.md": {"classification": {"role": "doc"}, "symbols": None},
        },
        "modules": {"modules": {"app": "app.py", "pkg": "pkg/__init__.py",
                                "pkg.core": "pkg/core.py"}},
        "graph": {"edges": [
            {"kind": "imports", "src": "file:app.py",
             "dst": "module:pkg.core", "dep": "internal"},
            {"kind": "imports", "src": "file:pkg/__init__.py",
             "dst": "module:pkg.core", "dep": "internal"},
            {"kind": "imports", "src": "file:app.py", "dst": "module:os",
             "dep": "stdlib"},
        ]},
    }
    arch = model(extraction)
    assert arch["top_dirs"]["."] == {"files": 2, "roles": {"source": 1, "doc": 1}}
    assert arch["top_dirs"]["pkg"]["files"] == 2
    assert arch["entrypoints"] == ["app.py"]
    assert arch["layers"] == {"app": 1, "pkg": 1, "pkg.core": 0}
    assert model(extraction) == arch  # deterministic
    # cycle safety: a imports b imports a — bounded, still terminates
    cyc = {
        "files": {"a.py": {"classification": {"role": "source"}, "symbols": []},
                  "b.py": {"classification": {"role": "source"}, "symbols": []}},
        "modules": {"modules": {"a": "a.py", "b": "b.py"}},
        "graph": {"edges": [
            {"kind": "imports", "src": "file:a.py", "dst": "module:b",
             "dep": "internal"},
            {"kind": "imports", "src": "file:b.py", "dst": "module:a",
             "dep": "internal"},
        ]},
    }
    assert set(model(cyc)["layers"]) == {"a", "b"}  # terminated, both present
    print("architecture selftest ok")
