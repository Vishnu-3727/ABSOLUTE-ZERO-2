"""Module model: Python files grouped into dotted modules and packages.

Pure path arithmetic over the inventory's file set — no disk access.
pkg/__init__.py names the package itself; pkg/core.py -> pkg.core.
top_level feeds deps.classify_target (internal vs external).
"""


def build(paths):
    """Model from an iterable of repo-relative posix paths.

    Returns {"modules": {dotted: path}, "packages": [dotted...],
             "top_level": [name...]} — all sorted/deterministic.
    """
    modules = {}
    packages = set()
    for path in sorted(paths):
        if not path.endswith(".py"):
            continue
        parts = path[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:  # ponytail: repo-root __init__.py — not a package
                continue
            packages.add(".".join(parts))
        modules[".".join(parts)] = path
    top_level = sorted({dotted.split(".")[0] for dotted in modules})
    return {"modules": dict(sorted(modules.items())),
            "packages": sorted(packages), "top_level": top_level}


if __name__ == "__main__":
    model = build(["app.py", "pkg/core.py", "pkg/__init__.py",
                   "README.md", "pkg/sub/deep.py"])
    assert model["modules"] == {
        "app": "app.py", "pkg": "pkg/__init__.py",
        "pkg.core": "pkg/core.py", "pkg.sub.deep": "pkg/sub/deep.py"}
    assert model["packages"] == ["pkg"]
    assert model["top_level"] == ["app", "pkg"]
    assert build([]) == {"modules": {}, "packages": [], "top_level": []}
    assert build(["__init__.py"])["modules"] == {}  # root guard
    # deterministic regardless of input order
    assert build(reversed(["app.py", "pkg/__init__.py", "pkg/core.py"])) == \
        build(["pkg/core.py", "app.py", "pkg/__init__.py"])
    print("module_model selftest ok")
