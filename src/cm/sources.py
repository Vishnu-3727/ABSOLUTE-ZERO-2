"""Source adapters — Assembly Spec -> raw candidate set from UMS + RSM
(blueprint Phase 2). Adapters translate/normalize only: selection, dedup,
prioritization, and budgeting live in Phases 3-4, not here.

Candidate shape (blueprint Phase 2 "Data produced"): {id, section, content,
score, stale, provenance}. `content` carries the fidelity tiers
(full/section/reference) UMS already produces; this module never invents
its own.

Zero retrieval/similarity code lives here (CM-I3, Law 2): the UMS adapter's
only path to repository material is `ums.query.query`, called exactly once
per assembly (CM-I10 — a single call already visits every store its query
plan names, so one call covers "one query per planned store"). The RSM
adapter only reads already-materialized blocks (`rsm.query.snapshot` /
`.block`) and never mutates `store` (CM-I6). Knowledge/experience
references are direct, spec-declared lookups (CM-I9: spec-driven
justification), not retrieval, so Law 2 does not apply to them.

`bundle` (UMS) and `store` (RSM) are both caller-injected — real
Lifecycle/Kernel wiring that supplies them is future work.
# ponytail: this module takes them as plain parameters rather than pulling
# them from a registry/singleton; upgrade path is whatever Phase the real
# Lifecycle wiring lands in, not here.
"""
from rsm import query as rsm_query
from ums import query as ums_query

# UMS hit "kind" -> CM closed section (request_memory.SECTION_NAMES).
_SECTION_BY_KIND = {"symbol": "symbols", "file": "files"}

# blueprint text names "identity/plan/constraints/budget" as the RSM blocks
# CM reads. rsm.record.BLOCK_NAMES has no "constraints" block (it has
# identity/lifecycle/plan/work/context/verification/budget/failure/
# journal_meta) — "constraints" does not exist in the real RSM record
# shape. Substituting the three that do exist and are relevant to CM
# assembly (who/what, capability scope, remaining budget headroom).
# ponytail: if a real "constraints" concept lands in RSM's block set later,
# add it here; nothing else in this module changes.
RSM_BLOCKS = ("identity", "plan", "budget")

_REFERENCE_SECTIONS = ("knowledge", "experience")


class UmsAdapter:
    """One `query_fn` call per `gather()` (CM-I10). `query_fn` defaults to
    `ums.query.query`; tests inject a counting wrapper to assert
    zero-duplicated-retrieval directly."""

    def __init__(self, query_fn=None):
        self.query_fn = query_fn or ums_query.query
        self.call_count = 0

    def gather(self, bundle, spec, query_class="concept"):
        self.call_count += 1
        result = self.query_fn(bundle, spec["objective"], spec["budget_tokens"], query_class)
        candidates = []
        for hit in result["hits"]:
            section = _SECTION_BY_KIND.get(hit["kind"])
            if section is None:
                continue  # store kind CM has no section for; nothing to translate
            candidates.append({
                "id": hit["id"],
                "section": section,
                "content": hit["content"],
                "score": hit["score"],
                "stale": hit["stale"],  # pass through verbatim (CM-I5) — never re-derived
                "provenance": {"source": "ums", "store": hit["kind"],
                               "query_class": result["class"], "query": spec["objective"]},
            })
        return candidates


def gather_rsm(store, request_id, blocks=RSM_BLOCKS):
    """Read-only RSM block reads (CM-I6: never mutates `store`). Absent or
    evicted requests are handled loud-but-graceful: no exception (RSM reads
    are optional, per blueprint "Fixed assumptions"), but the absence is
    surfaced as an explicit candidate carrying the status in provenance
    rather than silently returning nothing."""
    status = rsm_query.status(store, request_id)
    if status in (rsm_query.ABSENT, rsm_query.EVICTED):
        return [{
            "id": "rsm:" + request_id + ":absent",
            "section": "knowledge",
            "content": {"full": None, "section": None, "reference": None},
            "score": None,
            "stale": None,  # not applicable — RSM has no freshness concept (CM-I5 is UMS-only)
            "provenance": {"source": "rsm", "request_id": request_id, "status": status},
        }]
    candidates = []
    for block_name in blocks:
        value = rsm_query.block(store, request_id, block_name)
        candidates.append({
            "id": "rsm:" + request_id + ":" + block_name,
            "section": "knowledge",
            "content": {"full": value, "section": block_name + ":" + str(value),
                       "reference": block_name},
            "score": None,
            "stale": None,
            "provenance": {"source": "rsm", "request_id": request_id,
                           "block": block_name, "status": status},
        })
    return candidates


def resolve_references(references):
    """Direct reference resolution for the closed knowledge/experience
    sections (blueprint "knowledge/experience reference resolvers"). Not
    retrieval (Law 2 does not apply): references are explicit ids the
    caller already declared in the Assembly Spec (CM-I9 — nothing enters
    without spec-driven justification), so there is nothing to rank or
    search for. Format is "<section>:<id>"; malformed or unknown-section
    references fail loud rather than being silently dropped."""
    candidates = []
    for ref in references:
        section, _, ref_id = ref.partition(":")
        if not ref_id or section not in _REFERENCE_SECTIONS:
            raise ValueError("sources.bad_reference:" + ref)
        candidates.append({
            "id": "ref:" + ref,
            "section": section,
            "content": {"full": ref_id, "section": ref_id, "reference": ref_id},
            "score": None,
            "stale": None,
            "provenance": {"source": "reference", "ref": ref},
        })
    return candidates


def gather(spec, bundle, request_id, store=None, query_fn=None,
           rsm_blocks=RSM_BLOCKS, query_class="concept"):
    """Full Phase-2 gather for one assembly: UMS (one query) + RSM (read-
    only, skipped entirely when `store` is None — RSM reads are optional)
    + spec references. Order is deterministic: UMS hits (ranker-ordered),
    then RSM blocks (fixed tuple order), then references (spec.build
    already sorts them) — same spec + same UMS/RSM state always yields the
    same candidate list in the same order (CM-I2, Law 6)."""
    adapter = UmsAdapter(query_fn=query_fn)
    candidates = adapter.gather(bundle, spec, query_class=query_class)
    if store is not None:
        candidates.extend(gather_rsm(store, request_id, blocks=rsm_blocks))
    candidates.extend(resolve_references(spec["references"]))
    return candidates, adapter.call_count


if __name__ == "__main__":
    from rsm.ingest import Ingest, make_event, APPLIED
    from rsm.journal import Journal
    from rsm.store import Store
    from ums.freshness import FreshnessTracker

    # -- tiny hand-built UMS bundle (ums/query.py __main__ pattern) --------
    extraction = {"files": {
        "core.py": {"symbols": [
            {"kind": "function", "qualname": "add",
             "signature": "(a, b)", "doc": "Add two numbers."}]},
    }}
    semantic_bundle = {"summaries": {
        "core.py": {"full": "Core module | function add(a, b): Add two numbers.",
                    "section": "Core module | function add",
                    "reference": "Core module."},
    }}
    tracker = FreshnessTracker()
    tracker.track_fresh(["core.py"])
    bundle = {"extraction": extraction, "semantic": semantic_bundle, "freshness": tracker}

    spec = {"request_id": "r1", "objective": "add", "budget_tokens": 100,
            "capabilities": [], "constraints": {}, "references": ["knowledge:k1"]}

    # single UMS call covers both stores for a "concept" query
    candidates, call_count = gather(spec, bundle, "r1")
    assert call_count == 1
    assert any(c["section"] == "symbols" for c in candidates)
    assert any(c["section"] == "knowledge" and c["provenance"]["source"] == "reference"
              for c in candidates)
    for c in candidates:
        assert set(c) == {"id", "section", "content", "score", "stale", "provenance"}
        assert "source" in c["provenance"]

    # UMS stale passed through verbatim, never re-derived (CM-I5)
    tracker.mark_stale(["core.py"])
    candidates2, _ = gather(spec, bundle, "r1")
    symbol_hit = next(c for c in candidates2 if c["section"] == "symbols")
    assert symbol_hit["stale"] is True

    # determinism: identical spec + identical state -> identical candidates
    candidates3, _ = gather(spec, bundle, "r1")
    assert candidates2 == candidates3

    # RSM: read-only, absent request handled loud-but-graceful
    store = Store()
    journal = Journal()
    rsm_candidates = gather_rsm(store, "ghost")
    assert rsm_candidates[0]["provenance"]["status"] == rsm_query.ABSENT

    ing = Ingest(store, journal)
    assert ing.process(make_event("e0", "request.received", "r1", 1,
                                  {"declared_type": "a", "origin": "fe"})) == APPLIED
    before = rsm_query.snapshot(store, "r1")
    rsm_candidates2 = gather_rsm(store, "r1")
    after = rsm_query.snapshot(store, "r1")
    assert before == after  # never mutates (CM-I6)
    assert {c["provenance"]["block"] for c in rsm_candidates2} == set(RSM_BLOCKS)
    assert all(c["stale"] is None for c in rsm_candidates2)

    # store=None entirely skips RSM (optional per blueprint)
    candidates_no_rsm, _ = gather(spec, bundle, "r1", store=None)
    assert not any(c["provenance"]["source"] == "rsm" for c in candidates_no_rsm)

    # invalid reference fails loud
    try:
        resolve_references(["bad_ref_no_colon"])
        raise SystemExit("malformed reference accepted")
    except ValueError:
        pass
    try:
        resolve_references(["not_a_section:x"])
        raise SystemExit("unknown-section reference accepted")
    except ValueError:
        pass

    print("sources selftest ok")
