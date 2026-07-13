"""Query engine — ranked, explained, budget-fitted, freshness-flagged.

The only consumer-facing retrieval surface (Law 2). Law 6: identical
query + identical index state -> identical results (all candidate
enumeration is sorted before the planner's depth cap slices it).

Freshness gate: the STALE flag is attached here, by the store, from the
FreshnessTracker — never caller courtesy. A hit from a non-fresh region
always carries stale=True. Serving stale as fresh is structurally
impossible: there is no path around the gate.

Bundle = {"extraction", "semantic", "freshness" (FreshnessTracker),
optional "coverage" (partial onboarding metadata, passed through)}.
"""
from . import budget as budget_mod
from . import planner, ranker


def _symbol_candidates(extraction, semantic_bundle):
    for path in sorted(extraction["files"]):
        entry = extraction["files"][path]
        for sym in entry["symbols"] or ():
            text = " ".join((sym["kind"], sym["qualname"], sym["signature"],
                             sym["doc"] or ""))
            full = text
            yield {"id": "sym:" + path + ":" + sym["qualname"], "path": path,
                   "kind": "symbol", "name": sym["qualname"], "text": text,
                   "content": {"full": full, "section": full,
                               "reference": sym["kind"] + " " + sym["qualname"]}}


def _file_candidates(extraction, semantic_bundle):
    summaries = semantic_bundle["summaries"]
    for path in sorted(extraction["files"]):
        record = summaries.get(path)
        if record is None:
            continue  # not yet summarized (partial onboarding)
        yield {"id": "file:" + path, "path": path, "kind": "file",
               "name": path, "text": path + " " + record["full"],
               "content": {"full": record["full"],
                           "section": record["section"],
                           "reference": record["reference"]}}

_STORES = {"symbols": _symbol_candidates, "files": _file_candidates}


def query(bundle, text, budget_tokens, query_class=None):
    """One retrieval: plan -> rank -> freshness-flag -> budget-fit."""
    the_plan = planner.plan(text, query_class)
    candidates = []
    for store in the_plan["stores"]:
        candidates.extend(_STORES[store](bundle["extraction"], bundle["semantic"]))
    considered = candidates[:the_plan["max_candidates"]]  # bounded depth
    hits = ranker.rank(ranker.tokens_of(text), considered)

    tracker = bundle["freshness"]
    for hit in hits:
        # content dict lives on the candidate; re-join for the fitter
        hit["stale"] = not tracker.is_fresh(hit["path"])
    by_id = {c["id"]: c for c in considered}
    for hit in hits:
        hit["content"] = by_id[hit["id"]]["content"]

    fitted = budget_mod.fit(hits, budget_tokens)
    result = {
        "query": text,
        "class": the_plan["class"],
        "hits": fitted["hits"],
        "tokens_used": fitted["tokens_used"],
        "truncated": fitted["truncated"],
        "dropped": fitted["dropped"],
        "candidates_considered": len(considered),
    }
    if "coverage" in bundle:  # partial onboarding answers with coverage
        result["index_coverage"] = bundle["coverage"]
    return result


if __name__ == "__main__":
    from .freshness import FreshnessTracker

    extraction = {"files": {
        "core.py": {"symbols": [
            {"kind": "function", "qualname": "add",
             "signature": "(a, b)", "doc": "Add two numbers."}]},
        "README.md": {"symbols": None},
    }}
    semantic_bundle = {"summaries": {
        "core.py": {"full": "Core module | function add(a, b): Add two numbers.",
                    "section": "Core module | function add",
                    "reference": "Core module."},
        "README.md": {"full": "Fixture readme mentions add function usage",
                      "section": "Fixture readme", "reference": "Fixture"},
    }}
    tracker = FreshnessTracker()
    tracker.track_fresh(["core.py", "README.md"])
    bundle = {"extraction": extraction, "semantic": semantic_bundle,
              "freshness": tracker}

    result = query(bundle, "add", 100)
    assert result["class"] == "symbol"
    assert result["hits"][0]["id"] == "sym:core.py:add"
    assert result["hits"][0]["stale"] is False
    assert "signals" in result["hits"][0]["explanation"]
    assert query(bundle, "add", 100) == result  # Law 6 determinism

    # freshness gate: stale region -> flagged, attached by the engine
    tracker.mark_stale(["core.py"])
    stale_result = query(bundle, "add", 100)
    assert stale_result["hits"][0]["stale"] is True

    # concept query consults both stores; budget ceiling respected
    wide = query(bundle, "add numbers function", 8, query_class="concept")
    assert wide["tokens_used"] <= 8
    assert wide["candidates_considered"] == 3

    # coverage passthrough (partial onboarding)
    partial = dict(bundle, coverage={"indexed": 1, "total": 2, "complete": False})
    assert query(partial, "add", 50)["index_coverage"]["complete"] is False
    print("query selftest ok")
