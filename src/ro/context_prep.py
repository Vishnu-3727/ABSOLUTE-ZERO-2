"""RO/03 §6-§7 — Context Architecture + Context Reduction (RO/05 §10
blueprint group G3+G4). Consumes a sealed Request Memory (RQM) — an
injected frozen structure, NOT imported from src/cm (RO stays
self-contained, same discipline as its zero seam with src/prt, RO-I9).

**RQM shape** (caller-sealed, documented here in code since RO owns no
import of the producing module): a mapping from section name (str) -> a
tuple of items, each item a mapping with at least
{"id": str, "content": str, "provenance": str} and optionally
{"tier": str, "score": float}. Nothing else about RQM's producer (CM) is
assumed or read.

**Selection** (RO/03 §6): which sections to draw from and how much is a
deterministic data table keyed by the demand capability's
(knowledge_dependency, context_sensitivity) characteristic bands — never
ad-hoc judgment. Every included element carries a recorded inclusion
justification + provenance (RO-P5).

**Reduction** (RO/03 §7): deterministic, recorded shrink above the
sufficiency floor — dedup by content hash, then a relevance-threshold drop
(RO-P6). RO never runs reasoning to reduce reasoning input (mirrors RO-D8).

**Floor** (RO/03 §7 "Reduction floor" + RO-P12): if the capability demands
knowledge (knowledge_dependency band medium/high) but the elements surviving
selection+reduction are empty, that is a loud preparation failure — never a
silently smaller request. Callers construct this failure via
`EmptyContextError` raised from `select_and_reduce`.
"""
import hashlib
import json

# ponytail: size classes as a closed vocabulary + a sane-default item cap
# table (config data), not a numeric ad-hoc choice; upgrade path = make the
# cap table itself policy-supplied per RO/03 §6-§7's "deterministic, not
# ad-hoc judgment" rule, once a real policy surface exists for it.
SIZE_CLASSES = ("none", "minimal", "standard", "extensive")
_SIZE_CLASS_ITEM_CAP = {"none": 0, "minimal": 2, "standard": 5, "extensive": None}  # None = uncapped

# RO/03 §6 Relevance row: inclusion justified by knowledge_dependency +
# context_sensitivity bands. Deterministic table, not ad-hoc logic. Keys are
# (knowledge_dependency, context_sensitivity) bands from records.py's
# CHARACTERISTIC_BANDS; sections named here must exist as RQM section keys
# to actually contribute anything (a missing section simply yields nothing
# from that slot — not an error, RO never fabricates RQM content).
CONTEXT_SELECTION_TABLE = {
    ("low", "low"): ((), "none"),
    ("low", "medium"): (("core",), "minimal"),
    ("low", "high"): (("core",), "minimal"),
    ("medium", "low"): (("core",), "minimal"),
    ("medium", "medium"): (("core", "supporting"), "standard"),
    ("medium", "high"): (("core", "supporting"), "standard"),
    ("high", "low"): (("core", "supporting"), "standard"),
    ("high", "medium"): (("core", "supporting", "background"), "extensive"),
    ("high", "high"): (("core", "supporting", "background"), "extensive"),
}


class ContextRefusal(Exception):
    """Base for context-preparation-time refusals."""


class MalformedRQMError(ContextRefusal):
    """RQM does not match the documented shape."""


class StaleRQMError(ContextRefusal):
    """Caller-signaled stale flag, or an expected-hash mismatch (RO-P12)."""


class EmptyContextError(ContextRefusal):
    """Capability demands knowledge but selection+reduction left zero
    elements (RO/03 §7 floor, RO-P12) — never a silently empty request."""


def _canonical_item(item):
    return {
        "id": item["id"], "content": item["content"], "provenance": item["provenance"],
        "tier": item.get("tier"), "score": item.get("score"),
    }


def validate_rqm(rqm):
    """Shape-only check of the documented RQM structure. Raises
    MalformedRQMError; returns nothing on success."""
    if not isinstance(rqm, dict):
        raise MalformedRQMError("context_prep.rqm_not_a_mapping:" + repr(type(rqm)))
    for section, items in rqm.items():
        if not isinstance(section, str):
            raise MalformedRQMError("context_prep.rqm_section_not_str:" + repr(section))
        if not isinstance(items, tuple):
            raise MalformedRQMError("context_prep.rqm_section_items_not_tuple:" + section)
        for item in items:
            if not isinstance(item, dict):
                raise MalformedRQMError("context_prep.rqm_item_not_mapping:" + section)
            for key in ("id", "content", "provenance"):
                if not isinstance(item.get(key), str) or not item.get(key):
                    raise MalformedRQMError("context_prep.rqm_item_missing:" + section + ":" + key)


def rqm_content_hash(rqm):
    """Deterministic content hash over the whole sealed RQM (records.py
    canonical-JSON pattern), used as one of the preparation determinism
    coordinates (RO/03 §12) and to detect staleness against a caller's
    expected hash."""
    payload = {section: [_canonical_item(item) for item in items]
               for section, items in rqm.items()}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_freshness(rqm, rqm_stale=False, expected_rqm_hash=None):
    """RO/03 §6 Freshness row + RO-P12: a stale-RQM discovery is a
    preparation failure routed back, never silent re-retrieval. Returns the
    actual content hash on success."""
    actual = rqm_content_hash(rqm)
    if rqm_stale:
        raise StaleRQMError("context_prep.caller_signaled_stale")
    if expected_rqm_hash is not None and actual != expected_rqm_hash:
        raise StaleRQMError(
            "context_prep.hash_mismatch:expected=" + expected_rqm_hash + ":actual=" + actual)
    return actual


def _selection_plan(capability_record):
    chars = capability_record.characteristics
    key = (chars["knowledge_dependency"], chars["context_sensitivity"])
    return CONTEXT_SELECTION_TABLE.get(key, ((), "none"))


def _knowledge_demanded(capability_record):
    return capability_record.characteristics["knowledge_dependency"] in ("medium", "high")


def select_and_reduce(rqm, capability_record, relevance_threshold=0.0):
    """RO/03 §6 selection then §7 reduction, in one deterministic pass.

    Returns (included, inclusion_records, reduction_records):
      - included: tuple of item dicts (canonicalized, in stable order)
      - inclusion_records: tuple of {"id", "section", "justification",
        "provenance"} — RO-P5
      - reduction_records: tuple of {"id", "section", "reason"} for every
        dropped element — RO-P6

    Raises EmptyContextError if the capability demands knowledge but zero
    elements survive (RO/03 §7 floor)."""
    validate_rqm(rqm)
    sections, size_class = _selection_plan(capability_record)
    cap = _SIZE_CLASS_ITEM_CAP[size_class]

    included = []
    inclusion_records = []
    reduction_records = []
    seen_hashes = set()

    for section in sections:
        items = rqm.get(section, ())
        taken = 0
        for item in items:
            if cap is not None and taken >= cap:
                reduction_records.append({
                    "id": item["id"], "section": section, "reason": "size_class_cap_reached",
                })
                continue
            canon = _canonical_item(item)
            # RO/03 §7: dedup keys on CONTENT alone — same fact under two ids
            # or provenances is still one fact in the request.
            item_hash = hashlib.sha256(item["content"].encode()).hexdigest()
            if item_hash in seen_hashes:
                reduction_records.append({
                    "id": item["id"], "section": section, "reason": "duplicate_content",
                })
                continue
            score = item.get("score")
            if score is not None and score < relevance_threshold:
                reduction_records.append({
                    "id": item["id"], "section": section, "reason": "below_relevance_threshold",
                })
                continue
            seen_hashes.add(item_hash)
            included.append(canon)
            inclusion_records.append({
                "id": item["id"], "section": section,
                "justification": (
                    "capability characteristics knowledge_dependency=" +
                    capability_record.characteristics["knowledge_dependency"] +
                    ",context_sensitivity=" +
                    capability_record.characteristics["context_sensitivity"] +
                    " -> size_class=" + size_class + ",section=" + section
                ),
                "provenance": item["provenance"],
            })
            taken += 1

    if not included and _knowledge_demanded(capability_record):
        raise EmptyContextError(
            "context_prep.empty_context_for_knowledge_demanding_capability:" + capability_record.id)

    return tuple(included), tuple(inclusion_records), tuple(reduction_records)


if __name__ == "__main__":
    rqm_ok = {
        "core": (
            {"id": "c1", "content": "alpha fact", "provenance": "doc:1"},
            {"id": "c1dup", "content": "alpha fact", "provenance": "doc:1b"},  # dup content
            {"id": "c2", "content": "beta fact", "provenance": "doc:2", "score": -1.0},
        ),
        "supporting": (
            {"id": "s1", "content": "gamma detail", "provenance": "doc:3"},
        ),
    }
    validate_rqm(rqm_ok)
    h1 = rqm_content_hash(rqm_ok)
    h2 = rqm_content_hash(dict(rqm_ok))
    assert h1 == h2

    try:
        validate_rqm({"core": [{"id": "x", "content": "y", "provenance": "z"}]})  # list not tuple
        raise SystemExit("non-tuple section items accepted")
    except MalformedRQMError:
        pass

    assert check_freshness(rqm_ok, rqm_stale=False, expected_rqm_hash=h1) == h1
    try:
        check_freshness(rqm_ok, rqm_stale=True)
        raise SystemExit("stale flag ignored")
    except StaleRQMError:
        pass
    try:
        check_freshness(rqm_ok, expected_rqm_hash="deadbeef")
        raise SystemExit("hash mismatch ignored")
    except StaleRQMError:
        pass

    class _FakeCap:
        id = "ro.cap.test"
        characteristics = {"knowledge_dependency": "medium", "context_sensitivity": "medium"}

    included, inclusion, reduction = select_and_reduce(rqm_ok, _FakeCap(), relevance_threshold=0.0)
    ids = [e["id"] for e in included]
    assert "c1" in ids and "c1dup" not in ids  # dedup by content hash
    assert "c2" not in ids  # score below threshold
    assert "s1" in ids  # standard size_class pulls supporting too
    assert any(r["reason"] == "duplicate_content" for r in reduction)
    assert any(r["reason"] == "below_relevance_threshold" for r in reduction)
    assert len(inclusion) == len(included)

    # determinism
    included2, inclusion2, reduction2 = select_and_reduce(rqm_ok, _FakeCap(), relevance_threshold=0.0)
    assert included == included2 and inclusion == inclusion2 and reduction == reduction2

    # floor: knowledge demanded, RQM has nothing in the selected sections
    class _FakeCapHungry:
        id = "ro.cap.hungry"
        characteristics = {"knowledge_dependency": "high", "context_sensitivity": "high"}

    try:
        select_and_reduce({}, _FakeCapHungry())
        raise SystemExit("empty context for knowledge-demanding capability accepted")
    except EmptyContextError:
        pass

    # low knowledge_dependency + empty RQM is NOT a floor violation
    class _FakeCapLow:
        id = "ro.cap.low"
        characteristics = {"knowledge_dependency": "low", "context_sensitivity": "low"}

    included3, _, _ = select_and_reduce({}, _FakeCapLow())
    assert included3 == ()

    print("context_prep selftest ok")
