"""Query planner — query class -> stores to consult, bounded depth.

Table lookup, never judgment, never a full-repo scan: every plan carries
max_candidates, and the engine slices the (deterministically ordered)
candidate list to that cap before scoring.
"""
import re

_SYMBOLISH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\Z")

PLANS = {
    "symbol": {"stores": ("symbols",), "max_candidates": 200},
    "file": {"stores": ("files",), "max_candidates": 200},
    "concept": {"stores": ("symbols", "files"), "max_candidates": 400},
}


def classify_query(text):
    """Deterministic query class from surface shape."""
    stripped = text.strip()
    if "/" in stripped or stripped.endswith(".py") or stripped.endswith(".md"):
        return "file"
    if " " not in stripped and _SYMBOLISH.match(stripped):
        return "symbol"
    return "concept"


def plan(text, query_class=None):
    """Plan for a query: {"class", "stores", "max_candidates"}."""
    if query_class is None:
        query_class = classify_query(text)
    if query_class not in PLANS:
        raise ValueError("planner.unknown_query_class:" + query_class)
    entry = PLANS[query_class]
    return {"class": query_class, "stores": entry["stores"],
            "max_candidates": entry["max_candidates"]}


if __name__ == "__main__":
    assert classify_query("add") == "symbol"
    assert classify_query("Calc.mul") == "symbol"
    assert classify_query("pkg/core.py") == "file"
    assert classify_query("app.py") == "file"
    assert classify_query("how do I add numbers") == "concept"
    p = plan("add")
    assert p == {"class": "symbol", "stores": ("symbols",),
                 "max_candidates": 200}
    assert plan("x", "concept")["stores"] == ("symbols", "files")
    assert plan("anything", "file")["class"] == "file"
    try:
        plan("x", "everything")
        raise SystemExit("unknown class accepted")
    except ValueError:
        pass
    assert plan("add") == plan("add")  # deterministic
    print("planner selftest ok")
