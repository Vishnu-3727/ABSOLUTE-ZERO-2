"""Dependency mapper: import records and the typed dependency graph.

imports_from(tree) pulls import records from an already-parsed module
(parse cost paid once, in extraction.py). classify_target() splits
internal / stdlib / third_party via the repo's own top-level names and
sys.stdlib_module_names. build_graph() assembles the typed graph:
file/module/symbol nodes; contains/imports edges. Node ids are prefixed
("file:", "module:", "sym:") so kinds never collide.
"""
import ast
import sys


def imports_from(tree):
    """Import records in source order: {"target", "line", "level"}.

    level > 0 = relative import ("from .core import x" -> target "core",
    level 1). ponytail: imported names not recorded — graph needs the
    module edge only; add names when a consumer asks for symbol-level
    import edges.
    """
    records = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append({"target": alias.name, "line": node.lineno,
                                "level": 0})
        elif isinstance(node, ast.ImportFrom):
            records.append({"target": node.module or "", "line": node.lineno,
                            "level": node.level})
    return sorted(records, key=lambda r: (r["line"], r["target"]))


def resolve(record, importer_package):
    """Absolute dotted target of an import record.

    importer_package = the package the importing file lives in ("" for a
    top-level module; a package's __init__ passes the package itself).
    Level 1 = that package, each extra level walks one package up.
    """
    if record["level"] == 0:
        return record["target"]
    parts = importer_package.split(".") if importer_package else []
    base = parts[:len(parts) - (record["level"] - 1)]
    if record["target"]:
        base.append(record["target"])
    return ".".join(base)


def classify_target(target, internal_top_level):
    """internal / stdlib / third_party for an absolute dotted target."""
    top = target.split(".")[0]
    if top in internal_top_level:
        return "internal"
    if top in sys.stdlib_module_names:
        return "stdlib"
    return "third_party"


def build_graph(files, model):
    """Typed graph from per-file extraction records + module model.

    files: {path: {"symbols": [...] | None, "imports": [...]}}
    model: module_model.build() output.
    Returns {"nodes": [{"id", "kind"}...], "edges": [...]}, both sorted.
    """
    module_of = {path: dotted for dotted, path in model["modules"].items()}
    packages = set(model["packages"])
    internal = set(model["top_level"])

    def package_of(path):
        dotted = module_of.get(path, "")
        if dotted in packages:
            return dotted  # __init__.py: the package itself
        return dotted.rsplit(".", 1)[0] if "." in dotted else ""
    nodes = [{"id": "file:" + path, "kind": "file"} for path in files]
    nodes += [{"id": "module:" + dotted, "kind": "module"}
              for dotted in model["modules"]]
    edges = [{"kind": "contains", "src": "module:" + dotted,
              "dst": "file:" + path}
             for dotted, path in model["modules"].items()]
    for path, entry in files.items():
        for symbol in entry.get("symbols") or ():
            sym_id = "sym:" + path + ":" + symbol["qualname"]
            nodes.append({"id": sym_id, "kind": "symbol"})
            edges.append({"kind": "contains", "src": "file:" + path,
                          "dst": sym_id})
        importer_package = package_of(path)
        for record in entry.get("imports") or ():
            target = resolve(record, importer_package)
            if not target:
                continue
            edges.append({"kind": "imports", "src": "file:" + path,
                          "dst": "module:" + target,
                          "dep": classify_target(target, internal)})
    nodes.sort(key=lambda n: n["id"])
    edges.sort(key=lambda e: (e["kind"], e["src"], e["dst"]))
    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    source = (
        "import os\n"
        "import numpy.linalg\n"
        "from pkg.core import add\n"
        "from .sibling import x\n"
    )
    records = imports_from(ast.parse(source))
    assert [r["target"] for r in records] == \
        ["os", "numpy.linalg", "pkg.core", "sibling"]
    assert records[3]["level"] == 1

    # importer package "pkg" covers both pkg/mod.py and pkg/__init__.py
    assert resolve({"target": "sibling", "level": 1}, "pkg") == "pkg.sibling"
    assert resolve({"target": "", "level": 1}, "pkg") == "pkg"
    assert resolve({"target": "deep", "level": 2}, "a.b") == "a.deep"
    assert resolve({"target": "os", "level": 0}, "pkg") == "os"

    internal = {"pkg", "app"}
    assert classify_target("pkg.core", internal) == "internal"
    assert classify_target("os.path", internal) == "stdlib"
    assert classify_target("numpy.linalg", internal) == "third_party"

    files = {
        "app.py": {"symbols": [{"qualname": "main"}],
                   "imports": [{"target": "pkg.core", "line": 1, "level": 0},
                               {"target": "os", "line": 2, "level": 0}]},
        "pkg/core.py": {"symbols": None, "imports": []},
    }
    model = {"modules": {"app": "app.py", "pkg.core": "pkg/core.py"},
             "packages": [], "top_level": ["app", "pkg"]}
    graph = build_graph(files, model)
    ids = [n["id"] for n in graph["nodes"]]
    assert ids == sorted(ids) and "sym:app.py:main" in ids
    imports = [e for e in graph["edges"] if e["kind"] == "imports"]
    assert {e["dst"]: e["dep"] for e in imports} == \
        {"module:pkg.core": "internal", "module:os": "stdlib"}
    # determinism: rebuild -> identical
    assert build_graph(files, model) == graph
    print("deps selftest ok")
