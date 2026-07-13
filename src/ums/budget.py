"""Budget fitter — pack hits under the caller's token ceiling.

Fidelity tiers full -> section -> reference, degraded per hit until it
fits the remaining budget; hits that fit at no tier are dropped. The
ceiling is NEVER exceeded and truncation is always reported, never
silent (component failure-mode contract). Token = whitespace word,
same convention as summarize.py.
"""
TIERS = ("full", "section", "reference")


def fit(hits, budget_tokens):
    """Return {"hits": [...], "tokens_used", "truncated", "dropped"}.

    Each input hit needs a "content" dict with the TIERS keys; each
    output hit gains "fidelity" and "content" (the chosen tier's text).
    """
    fitted = []
    used = 0
    dropped = 0
    for hit in hits:
        chosen = None
        for tier in TIERS:
            text = hit["content"][tier]
            cost = len(text.split())
            if used + cost <= budget_tokens:
                chosen = (tier, text, cost)
                break
        if chosen is None:
            dropped += 1
            continue
        tier, text, cost = chosen
        used += cost
        out = {k: v for k, v in hit.items() if k != "content"}
        out["fidelity"] = tier
        out["content"] = text
        fitted.append(out)
    return {"hits": fitted, "tokens_used": used,
            "truncated": dropped > 0 or any(h["fidelity"] != "full"
                                            for h in fitted),
            "dropped": dropped}


if __name__ == "__main__":
    def hit(hid, full_n, section_n, ref_n):
        return {"id": hid, "score": 1.0,
                "content": {"full": "f " * full_n, "section": "s " * section_n,
                            "reference": "r " * ref_n}}

    # everything fits at full fidelity
    result = fit([hit("a", 5, 3, 1), hit("b", 5, 3, 1)], 100)
    assert [h["fidelity"] for h in result["hits"]] == ["full", "full"]
    assert result["tokens_used"] == 10 and not result["truncated"]

    # second hit degrades, ceiling never exceeded
    result = fit([hit("a", 8, 4, 2), hit("b", 8, 4, 2)], 12)
    assert [h["fidelity"] for h in result["hits"]] == ["full", "section"]
    assert result["tokens_used"] <= 12 and result["truncated"]
    result = fit([hit("a", 8, 4, 2), hit("b", 8, 4, 2)], 10)
    assert [h["fidelity"] for h in result["hits"]] == ["full", "reference"]

    # hit dropped entirely when even reference cannot fit — reported
    result = fit([hit("a", 8, 4, 2), hit("b", 8, 4, 3)], 9)
    assert result["dropped"] == 1 and result["truncated"]
    assert result["tokens_used"] <= 9

    # zero budget: everything dropped, loudly
    result = fit([hit("a", 2, 2, 1)], 0)
    assert result["hits"] == [] and result["dropped"] == 1

    # property: ceiling holds across a sweep of budgets
    hits = [hit(str(i), 7, 5, 2) for i in range(6)]
    for budget in range(0, 60):
        assert fit(hits, budget)["tokens_used"] <= budget
    print("budget selftest ok")
