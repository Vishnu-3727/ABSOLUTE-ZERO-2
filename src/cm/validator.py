"""Structural validation gates (blueprint Phase 4): the last check before
`assembler.py` emits `context.assembled`. Every gate is explicit and fails
loud — `validate()` never repairs an artifact, it only reports (ok, reason)
so the caller can raise (CM-I: fail loud, never silently degrade).

Independent from `budgeter.py`: this module imports only `request_memory`
(the shared frozen-artifact type both modules operate on), never
`budgeter` itself — the two are checked separately by design.

Gates, in order:
  1. required sections present  -- every SECTION_NAMES key exists
  2. ceiling respected          -- budget_meta tokens_used <= budget_tokens (CM-I1)
  3. zero duplicate ids         -- no id repeated across all sections
  4. provenance present         -- every item carries a non-empty provenance dict (CM-I5)
  5. stale flagged, not hidden  -- every item still carries a "stale" key (CM-I5)
  6. deterministic ordering     -- score is non-increasing within each section (CM-I2)
  7. content-hash stability     -- canonical()/content_hash() are pure and repeatable (CM-I2)
"""
from .request_memory import SECTION_NAMES, canonical, content_hash


def _score_key(score):
    """Same convention as prioritizer._score_key: non-numeric/None scores
    (RSM blocks, references) sort last rather than breaking comparison."""
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return score
    return float("-inf")


def validate(rm):
    """Return (ok, reason). Pure structural check against a built
    RequestMemory; never mutates or repairs `rm`."""
    if set(rm.sections) != set(SECTION_NAMES):
        return False, "validator.missing_section"

    budget_tokens = rm.budget_meta.get("budget_tokens")
    tokens_used = rm.budget_meta.get("tokens_used")
    if not isinstance(budget_tokens, int) or isinstance(budget_tokens, bool):
        return False, "validator.missing_budget_meta:budget_tokens"
    if not isinstance(tokens_used, int) or isinstance(tokens_used, bool):
        return False, "validator.missing_budget_meta:tokens_used"
    if tokens_used > budget_tokens:
        return False, "validator.ceiling_exceeded"

    seen_ids = set()
    for section in SECTION_NAMES:
        prev_score = None
        for item in rm.sections[section]:
            if not isinstance(item, dict):
                return False, "validator.malformed_item"
            item_id = item.get("id")
            if item_id is None:
                return False, "validator.missing_id"
            if item_id in seen_ids:
                return False, "validator.duplicate_id:" + str(item_id)
            seen_ids.add(item_id)

            provenance = item.get("provenance")
            if not isinstance(provenance, dict) or not provenance:
                return False, "validator.missing_provenance:" + str(item_id)

            if "stale" not in item:
                return False, "validator.missing_stale_flag:" + str(item_id)

            score = _score_key(item.get("score"))
            if prev_score is not None and score > prev_score:
                return False, "validator.order_violation:" + str(item_id)
            prev_score = score

    # content-hash stability: pure functions, repeated calls must agree
    if canonical(rm) != canonical(rm) or content_hash(rm) != content_hash(rm):
        return False, "validator.hash_unstable"

    return True, ""


if __name__ == "__main__":
    from .request_memory import build

    def item(iid, score, provenance=None, stale=False):
        return {"id": iid, "section": "symbols", "score": score, "stale": stale,
                "fidelity": "full", "content": "x",
                "provenance": provenance if provenance is not None else {"source": "test"}}

    good = build("r1", "h1", "obj",
                  sections={"symbols": (item("s2", 2.0), item("s1", 1.0))},
                  budget_meta={"budget_tokens": 100, "tokens_used": 10})
    ok, reason = validate(good)
    assert ok and reason == ""

    # missing section
    from types import MappingProxyType
    import dataclasses
    broken = dataclasses.replace(good, sections=MappingProxyType(
        {k: v for k, v in good.sections.items() if k != "knowledge"}))
    ok, reason = validate(broken)
    assert not ok and reason == "validator.missing_section"

    # ceiling breach
    over = build("r1", "h1", "obj", sections={"symbols": (item("s1", 1.0),)},
                 budget_meta={"budget_tokens": 5, "tokens_used": 10})
    ok, reason = validate(over)
    assert not ok and reason == "validator.ceiling_exceeded"

    # duplicate ids
    dup = build("r1", "h1", "obj",
               sections={"symbols": (item("s1", 2.0), item("s1", 1.0))},
               budget_meta={"budget_tokens": 100, "tokens_used": 2})
    ok, reason = validate(dup)
    assert not ok and reason.startswith("validator.duplicate_id")

    # missing provenance
    no_prov = build("r1", "h1", "obj",
                   sections={"symbols": (item("s1", 1.0, provenance={}),)},
                   budget_meta={"budget_tokens": 100, "tokens_used": 1})
    ok, reason = validate(no_prov)
    assert not ok and reason.startswith("validator.missing_provenance")

    # missing stale key
    stale_missing = item("s1", 1.0)
    del stale_missing["stale"]
    no_stale = build("r1", "h1", "obj", sections={"symbols": (stale_missing,)},
                    budget_meta={"budget_tokens": 100, "tokens_used": 1})
    ok, reason = validate(no_stale)
    assert not ok and reason.startswith("validator.missing_stale_flag")

    # ordering violation (increasing score where descending is required)
    bad_order = build("r1", "h1", "obj",
                     sections={"symbols": (item("s1", 1.0), item("s2", 2.0))},
                     budget_meta={"budget_tokens": 100, "tokens_used": 2})
    ok, reason = validate(bad_order)
    assert not ok and reason.startswith("validator.order_violation")

    # missing budget_meta entirely
    no_budget = build("r1", "h1", "obj", sections={})
    ok, reason = validate(no_budget)
    assert not ok and reason.startswith("validator.missing_budget_meta")

    print("validator selftest ok")
