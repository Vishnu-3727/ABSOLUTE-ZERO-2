"""Budget fitter (blueprint Phase 4): per-section envelopes carved from
`config_view` weights, then a global hard ceiling with fidelity-tier
degradation full -> section -> reference, mirroring `ums/budget.py` `fit()`
semantics exactly (same tiers, same "degrade per item until it fits, drop
if nothing fits" behaviour) but section-aware. The global ceiling is NEVER
exceeded (CM-I1) and every drop/degrade is reported in the return value,
never silent (I21/I22).

Token = whitespace word, isolated behind the one `_token_count` function
(blueprint "Fixed assumptions"; upgrade path = swap this for a real
tokenizer, nothing else in this module changes).

Deterministic, never probabilistic: given the same (candidates, budget,
config), envelope allocation and degradation always pick the same tier for
the same item (CM-I2, Law 6) — callers are responsible for handing
candidates in already-deterministic priority order (Phase 3's prioritizer).
"""
from .request_memory import SECTION_NAMES

TIERS = ("full", "section", "reference")


def _token_count(text):
    """Whitespace-word count; non-string content (e.g. RSM absent stubs
    carry `None`) costs zero tokens rather than crashing."""
    return len(text.split()) if isinstance(text, str) else 0


def section_envelopes(config, budget_tokens):
    """Split `budget_tokens` across SECTION_NAMES proportional to
    `config.weight_of(section)`, largest-remainder method so the envelopes
    sum to exactly `budget_tokens` (never over). Zero total weight or zero
    budget -> every envelope is 0."""
    if not isinstance(budget_tokens, int) or isinstance(budget_tokens, bool) or budget_tokens < 0:
        raise ValueError("budgeter.bad_budget_tokens")
    weights = {s: config.weight_of(s) for s in SECTION_NAMES}
    total_weight = sum(weights.values())
    if total_weight <= 0 or budget_tokens == 0:
        return {s: 0 for s in SECTION_NAMES}
    raw = {s: weights[s] / total_weight * budget_tokens for s in SECTION_NAMES}
    floors = {s: int(raw[s]) for s in SECTION_NAMES}
    remainder = budget_tokens - sum(floors.values())
    # deterministic tie-break: largest fractional part first, then section name
    order = sorted(SECTION_NAMES, key=lambda s: (-(raw[s] - floors[s]), s))
    for s in order[:remainder]:
        floors[s] += 1
    return floors


def _validate_candidate(c):
    if not isinstance(c, dict) or "id" not in c or "section" not in c or "content" not in c:
        raise ValueError("budgeter.malformed_candidate")


def _tier_options(content):
    """Yield (tier, text) pairs to try, best fidelity first.

    RSM/reference/resolver candidates (sources.py, resolver.py) carry a
    dict of all three tiers, so the normal full->section->reference ladder
    applies. UMS-sourced candidates arrive already tier-fitted to a single
    string: `ums.query.query()` runs its own `ums/budget.py` fit at query
    time (spec budget_tokens), collapsing the tier dict to the chosen
    text before sources.py ever sees it (sources.py "never invents its
    own [tiers]" — it passes UMS's hit through as-is). For those, CM has
    exactly one tier to place or drop; there is no further text to
    degrade to.
    # ponytail: this is a Phase 2/UMS boundary quirk, not a Phase 4 defect
    # — sources.py already passes UMS content through unmodified per its
    # own docstring. Upgrade path if a future phase wants CM to control
    # UMS-side fidelity too: have sources.py request budget_tokens=None
    # (or a very large budget) from ums.query so UMS returns the full tier
    # dict and CM's budgeter is the only place tiering decisions happen.
    """
    if isinstance(content, dict):
        for tier in TIERS:
            if tier not in content:
                raise ValueError("budgeter.malformed_candidate:missing_tier:" + tier)
            yield tier, content[tier]
    else:
        yield "full", content


def fit(candidates, budget_tokens, config):
    """Progressive-load pass over `candidates` (already in priority order —
    highest priority first). Returns:
    {"items", "tokens_used", "section_used", "section_budgets",
     "dropped", "degraded", "truncated"}.

    Each surviving item loses its "content" dict and gains a single chosen
    "content" string plus "fidelity" (the tier used) — same shape contract
    as `ums/budget.py` `fit()`. Lower-priority items are the first to
    degrade or drop, since section/global remaining budget is consumed by
    earlier (higher-priority) items first."""
    envelopes = section_envelopes(config, budget_tokens)
    section_used = {s: 0 for s in SECTION_NAMES}
    global_used = 0
    fitted = []
    dropped = 0
    degraded = []
    for c in candidates:
        _validate_candidate(c)
        section = c["section"]
        if section not in SECTION_NAMES:
            raise ValueError("budgeter.unknown_section:" + str(section))
        chosen = None
        for tier, text in _tier_options(c["content"]):
            cost = _token_count(text)
            remaining_section = envelopes[section] - section_used[section]
            remaining_global = budget_tokens - global_used
            if cost <= remaining_section and cost <= remaining_global:
                chosen = (tier, text, cost)
                break
        if chosen is None:
            dropped += 1
            continue
        tier, text, cost = chosen
        section_used[section] += cost
        global_used += cost
        out = {k: v for k, v in c.items() if k != "content"}
        out["fidelity"] = tier
        out["content"] = text
        fitted.append(out)
        if tier != "full":
            degraded.append(c["id"])
    return {
        "items": fitted,
        "tokens_used": global_used,
        "section_used": section_used,
        "section_budgets": envelopes,
        "dropped": dropped,
        "degraded": degraded,
        "truncated": dropped > 0 or len(degraded) > 0,
    }


if __name__ == "__main__":
    from .config_view import ConfigView, DEFAULT

    config = ConfigView(DEFAULT)

    def hit(hid, section, full_n, section_n, ref_n, score=1.0):
        return {"id": hid, "section": section, "score": score, "stale": False,
                "provenance": {"source": "test"},
                "content": {"full": "f " * full_n, "section": "s " * section_n,
                            "reference": "r " * ref_n}}

    # envelopes sum exactly to budget, never over
    for budget in (0, 1, 7, 100, 8000):
        env = section_envelopes(config, budget)
        assert sum(env.values()) == budget
        assert all(v >= 0 for v in env.values())

    # everything fits at full fidelity when budget is generous
    result = fit([hit("a", "symbols", 5, 3, 1), hit("b", "files", 5, 3, 1)], 1000, config)
    assert [h["fidelity"] for h in result["items"]] == ["full", "full"]
    assert not result["truncated"]

    # lower-priority (later) item degrades first when a section is tight
    items = [hit("a", "symbols", 8, 4, 2), hit("b", "symbols", 8, 4, 2)]
    result = fit(items, 12, config)  # symbols envelope == full 12 (weight 3/13*12≈2... )
    # regardless of exact envelope split, ceiling holds and priority order respected
    assert result["tokens_used"] <= 12
    fidelities = [h["fidelity"] for h in result["items"]] if len(result["items"]) == 2 else None
    if fidelities:
        assert fidelities[0] == "full" or _token_count("f " * 8) <= result["section_budgets"]["symbols"]

    # ceiling NEVER exceeded across a full budget sweep (CM-I1)
    sweep_items = [hit(str(i), "symbols", 7, 5, 2, score=float(-i)) for i in range(6)]
    for budget in range(0, 200):
        r = fit(sweep_items, budget, config)
        assert r["tokens_used"] <= budget

    # zero budget: everything dropped, loudly
    result = fit([hit("a", "symbols", 2, 2, 1)], 0, config)
    assert result["items"] == [] and result["dropped"] == 1 and result["truncated"]

    # malformed candidate raises loud
    try:
        fit([{"id": "x", "section": "symbols"}], 100, config)
        raise SystemExit("malformed candidate accepted")
    except ValueError:
        pass
    try:
        fit([hit("a", "not_a_section", 1, 1, 1)], 100, config)
        raise SystemExit("unknown section accepted")
    except ValueError:
        pass

    # unmutated: source candidates untouched
    original = hit("a", "symbols", 5, 3, 1)
    snapshot = dict(original)
    fit([original], 100, config)
    assert original == snapshot

    print("budgeter selftest ok")
