"""Ranker — THE single similarity implementation in the system (Law 2).

One scoring function; lexical/stem/structural signals composed with the
declared WEIGHTS table (V1 core.retrieve lineage). Every hit carries a
per-signal breakdown (the explainer — results are inspectable, never a
black box). Embedding backends are a future seam behind the same ranked
interface, not built.

SCORE_FLOOR: V1 gotcha — fuzzy ratios on short strings float ~0.2 of
pure noise; anything at or below the floor is dropped, never ranked.
"""

WEIGHTS = {"lexical": 0.5, "stem": 0.3, "structural": 0.2}
SCORE_FLOOR = 0.2

_SUFFIXES = ("ing", "ers", "ies", "ed", "es", "er", "s")


def stem(token):
    """Crude deterministic stemmer. ponytail: suffix-strip only; a real
    stemmer is warranted only if golden-query quality demands it."""
    token = token.lower()
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[:-len(suffix)]
    return token


def tokens_of(text):
    out = []
    word = []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def _overlap(query_tokens, cand_tokens):
    if not query_tokens:
        return 0.0
    hits = sum(1 for t in query_tokens if t in cand_tokens)
    return hits / len(query_tokens)


def score(query_tokens, candidate):
    """One candidate's score + per-signal explanation."""
    cand_tokens = set(tokens_of(candidate["text"]))
    name_tokens = set(tokens_of(candidate["name"]))
    signals = {
        "lexical": round(_overlap(query_tokens, cand_tokens), 4),
        "stem": round(_overlap([stem(t) for t in query_tokens],
                               {stem(t) for t in cand_tokens}), 4),
        "structural": 0.0,
    }
    for token in query_tokens:
        if token in name_tokens or token == candidate["name"].lower():
            signals["structural"] = 1.0
            break
        if any(token in name for name in name_tokens):
            signals["structural"] = max(signals["structural"], 0.5)
    total = round(sum(WEIGHTS[k] * v for k, v in signals.items()), 6)
    return total, {"signals": signals, "weights": WEIGHTS}


def rank(query_tokens, candidates):
    """Ranked hits above the floor; deterministic order (score, then id)."""
    hits = []
    for candidate in candidates:
        total, explanation = score(query_tokens, candidate)
        if total <= SCORE_FLOOR:
            continue  # V1 short-string noise floor
        hits.append({"id": candidate["id"], "path": candidate["path"],
                     "kind": candidate["kind"], "score": total,
                     "explanation": explanation})
    hits.sort(key=lambda h: (-h["score"], h["id"]))
    return hits


if __name__ == "__main__":
    assert stem("running") == "runn" and stem("caches") == "cach"
    assert stem("add") == "add" and stem("as") == "as"  # length guard
    assert tokens_of("Calc.mul(a, b) -> int") == ["calc", "mul", "a", "b", "int"]

    candidates = [
        {"id": "sym:core:add", "path": "core.py", "kind": "symbol",
         "name": "add", "text": "function add(a: int, b: int) Add two numbers."},
        {"id": "sym:core:mul", "path": "core.py", "kind": "symbol",
         "name": "Calc.mul", "text": "method Calc.mul(self, a, b)"},
        {"id": "file:zzz.py", "path": "zzz.py", "kind": "file",
         "name": "zzz.py", "text": "unrelated content entirely"},
    ]
    hits = rank(tokens_of("add"), candidates)
    assert [h["id"] for h in hits] == ["sym:core:add"]  # noise floored out
    top = hits[0]
    assert top["score"] > 0.9
    assert set(top["explanation"]["signals"]) == {"lexical", "stem", "structural"}
    assert top["explanation"]["weights"] is WEIGHTS

    # deterministic: same input, identical ranked output
    assert rank(tokens_of("add"), candidates) == hits
    # tie-break by id: two identical candidates order by id
    twins = [dict(candidates[0], id="sym:b"), dict(candidates[0], id="sym:a")]
    assert [h["id"] for h in rank(tokens_of("add"), twins)] == ["sym:a", "sym:b"]
    # floor: empty/garbage query ranks nothing
    assert rank(tokens_of(""), candidates) == []
    assert rank(tokens_of("qqqq"), candidates) == []
    print("ranker selftest ok")
