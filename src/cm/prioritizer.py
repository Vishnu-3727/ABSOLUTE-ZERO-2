"""Deterministic priority ordering (blueprint Phase 3): section class >
relevance score > id tie-break. No randomness, no dependence on input or
set-iteration order (CM-I2, Law 6) — the sort key always includes `id` as
the final tiebreak, so equal-priority items land in the same order no
matter how they were shuffled going in.

Section class weight comes from `config_view` (policy as data, CM-I8: CM
applies policy, it does not invent it) — this module never hardcodes a
per-section ranking of its own.
"""


def _score_key(score):
    """None/non-numeric scores (RSM blocks, references) sort after every
    real score rather than crashing the comparison."""
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return score
    return float("-inf")


def prioritize(candidates, config):
    """Return a new list ordered by (section weight desc, score desc, id
    asc). `config` is a `config_view.ConfigView` (or anything exposing
    `weight_of(section)`)."""
    def key(c):
        return (-config.weight_of(c["section"]), -_score_key(c["score"]), c["id"])
    return sorted(candidates, key=key)


if __name__ == "__main__":
    from .config_view import ConfigView, DEFAULT

    config = ConfigView(DEFAULT)  # symbols:3, files:3, dependency_graph:2, knowledge:1, experience:1

    high_sym = {"id": "s2", "section": "symbols", "content": {}, "score": 0.9,
                "stale": False, "provenance": {}}
    low_sym = {"id": "s1", "section": "symbols", "content": {}, "score": 0.1,
               "stale": False, "provenance": {}}
    know = {"id": "k1", "section": "knowledge", "content": {}, "score": 5.0,
            "stale": False, "provenance": {}}
    no_score = {"id": "s3", "section": "symbols", "content": {}, "score": None,
                "stale": False, "provenance": {}}
    tie_a = {"id": "sb", "section": "symbols", "content": {}, "score": 0.5,
             "stale": False, "provenance": {}}
    tie_b = {"id": "sa", "section": "symbols", "content": {}, "score": 0.5,
             "stale": False, "provenance": {}}

    out = prioritize([know, low_sym, high_sym, no_score], config)
    # higher section weight (symbols=3) beats higher score in a lower-weight
    # section (knowledge=1), even though knowledge scored higher
    assert [c["id"] for c in out] == ["s2", "s1", "s3", "k1"]

    # equal section + equal score -> id tie-break, deterministic regardless
    # of input order
    out_a = prioritize([tie_a, tie_b], config)
    out_b = prioritize([tie_b, tie_a], config)
    assert out_a == out_b
    assert [c["id"] for c in out_a] == ["sa", "sb"]

    # ordering stability across shuffled input: same set, different input
    # order -> identical output
    import random
    items = [know, low_sym, high_sym, no_score, tie_a, tie_b]
    shuffled = list(items)
    random.Random(7).shuffle(shuffled)
    assert prioritize(shuffled, config) == prioritize(items, config)

    # empty input
    assert prioritize([], config) == []

    print("prioritizer selftest ok")
