"""Pipeline orchestrator (blueprint Phase 4): the last leg of intake ->
gather -> resolve -> dedup -> prioritize -> budget -> order -> validate ->
emit. `Assembler.assemble()` picks up from Phase 3's output (an already
prioritized, deduped, dependency-expanded candidate list) and:

  1. runs `budgeter.fit()` in the caller's priority order (progressive load)
  2. groups the surviving items back into the closed SECTION_NAMES sections,
     preserving priority order within each section (stable grouping)
  3. populates the canonical frozen Request Memory (Phase 1 `request_memory.build`)
  4. runs `validator.validate()` on the built artifact -- BEFORE emit
  5. logs, then publishes `context.assembled` (and `context.overflow` when
     material was degraded or dropped) -- log-before-publish (I7/I8), same
     discipline as `kernel/coordinator.py`

# ponytail: this module does not itself call sources.gather / resolver.expand
# / dedup.dedup / prioritizer.prioritize -- those need a UMS bundle / RSM
# store / dependency records that are per-caller inputs (see sources.py's
# own ponytail note on injected bundle/store). Assembler takes Phase 3's
# *output* as its input; wiring the full gather-through-prioritize chain is
# Lifecycle/Kernel's job, not CM's, and does not change this module.

Never mutates the candidates handed in (budgeter already copies each
surviving item into a new dict). Same (spec, candidates, config) -> the
same RequestMemory bytes and hash, replay after replay (CM-I2, Law 6).

Seam fix (recorded Phase 4, closed here): `dedup.py` keeps BOTH sides of a
contradiction under the SAME id by design ("never blended" -- both variants
survive, each tagged `contradiction: True`), but `validator.py`'s
zero-duplicate-ids gate (CM structural correctness, not negotiable) then
rejects that pair. Disambiguating here -- a deterministic content-hash
suffix applied only to contradiction-flagged items, right before grouping
into sections -- keeps dedup's "never blend, always surface" contract
intact (both variants still visible, still flagged, original id preserved
under `original_id`) while satisfying the validator. This is the smallest
in-architecture fix per the recorded upgrade path; dedup.py's own contract
(same id in, both kept, flagged) is unchanged.
"""
import hashlib
import json

from . import budgeter, events, validator
from .request_memory import SECTION_NAMES, build as build_request_memory, content_hash
from .spec import spec_hash as compute_spec_hash


def _disambiguate_contradictions(items):
    """Deterministic id suffix (content-hash prefix, CM-I2) for any item
    dedup.py flagged `contradiction: True`, so two variants that share an
    id no longer collide in validator's duplicate-id gate. Non-contradicted
    items pass through untouched; the original id survives under
    `original_id` and `contradiction: True` stays visible either way."""
    out = []
    for item in items:
        if not item.get("contradiction"):
            out.append(item)
            continue
        original_id = item["id"]
        digest = hashlib.sha256(
            json.dumps(item.get("content"), sort_keys=True, default=str).encode()
        ).hexdigest()[:8]
        out.append(dict(item, id=original_id + "#" + digest, original_id=original_id))
    return out


class Assembler:
    """Holds an internal transition log, kernel-coordinator style, so every
    assembly is recorded before it is published (I7/I8)."""

    def __init__(self):
        self.log = []

    def assemble(self, spec, candidates, config, bus, request_id=None):
        if not isinstance(candidates, (list, tuple)):
            raise ValueError("assembler.bad_candidates")
        request_id = request_id or spec["request_id"]
        spec_h = compute_spec_hash(spec)
        budget_tokens = spec["budget_tokens"]

        result = budgeter.fit(candidates, budget_tokens, config)
        fitted_items = _disambiguate_contradictions(result["items"])

        sections = {name: [] for name in SECTION_NAMES}
        for item in fitted_items:
            sections[item["section"]].append(item)

        coverage = (len(result["items"]) / len(candidates)) if candidates else 1.0

        assembly_meta = {
            "candidate_count": len(candidates),
            "selected_count": len(result["items"]),
            "dropped": result["dropped"],
            "degraded": tuple(result["degraded"]),
        }
        budget_meta = {
            "budget_tokens": budget_tokens,
            "tokens_used": result["tokens_used"],
            "section_budgets": result["section_budgets"],
            "section_used": result["section_used"],
            "truncated": result["truncated"],
        }
        # ponytail: validation_meta is a static "gates checked" marker set
        # before validate() runs, not its live result -- if validate() then
        # fails we raise below and this artifact is discarded, never
        # returned or emitted, so the marker is never seen in a failing
        # state. Avoids a two-pass build just to record a boolean.
        validation_meta = {"gates": ("sections", "ceiling", "duplicate_ids",
                                     "provenance", "stale_flag", "ordering", "hash_stability")}

        rm = build_request_memory(
            request_id, spec_h, spec["objective"],
            constraints=spec.get("constraints"), sections=sections,
            assembly_meta=assembly_meta, validation_meta=validation_meta,
            budget_meta=budget_meta,
        )

        ok, reason = validator.validate(rm)
        if not ok:
            raise ValueError("assembler.validation_failed:" + reason)

        rm_hash = content_hash(rm)
        record = {"request_id": request_id, "memory_id": rm.memory_id, "hash": rm_hash,
                  "tokens_used": result["tokens_used"], "truncated": result["truncated"]}
        self.log.append(record)  # log before publish (I7/I8)

        events.emit(bus, "context.assembled", request_id, {
            "request_id": request_id, "memory_id": rm.memory_id, "hash": rm_hash,
            "tokens_used": result["tokens_used"], "coverage": coverage,
        })
        if result["truncated"]:
            events.emit(bus, "context.overflow", request_id, {
                "dropped": result["dropped"], "degraded": tuple(result["degraded"]),
                "tokens_used": result["tokens_used"], "budget_tokens": budget_tokens,
            })

        return rm


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .config_view import ConfigView, DEFAULT
    from .spec import build as build_spec

    config = ConfigView(DEFAULT)

    def cand(cid, section, score, full_n=3, section_n=2, ref_n=1):
        return {"id": cid, "section": section, "score": score, "stale": False,
                "provenance": {"source": "test"},
                "content": {"full": "f " * full_n, "section": "s " * section_n,
                            "reference": "r " * ref_n}}

    spec = build_spec("r1", "do the thing", 100)
    candidates = [cand("s1", "symbols", 2.0), cand("f1", "files", 1.0)]

    bus = BusDouble()
    asm = Assembler()
    rm = asm.assemble(spec, candidates, config, bus)

    assert rm.request_id == "r1"
    assembled = bus.messages("context.assembled")
    assert len(assembled) == 1
    payload = assembled[0]["payload"]
    assert payload["memory_id"] == rm.memory_id
    assert payload["hash"] == content_hash(rm)
    assert payload["tokens_used"] == rm.budget_meta["tokens_used"]
    assert bus.messages("context.overflow") == []  # everything fit, no overflow
    assert len(asm.log) == 1 and asm.log[0]["memory_id"] == rm.memory_id

    # source candidates never mutated
    assert candidates == [cand("s1", "symbols", 2.0), cand("f1", "files", 1.0)]

    # determinism: identical spec + candidates -> identical bytes/hash
    bus2 = BusDouble()
    rm2 = Assembler().assemble(spec, candidates, config, bus2)
    assert content_hash(rm) == content_hash(rm2)

    # overflow path: tiny budget forces degradation/drop -> context.overflow fires
    tight_spec = build_spec("r2", "do the thing", 3)
    bus3 = BusDouble()
    rm3 = Assembler().assemble(tight_spec, candidates, config, bus3)
    assert rm3.budget_meta["tokens_used"] <= 3
    if rm3.budget_meta["truncated"]:
        assert len(bus3.messages("context.overflow")) == 1

    # seam fix: a contradiction pair (same id, dedup.py kept both, flagged)
    # survives end-to-end through validator -- both variants present,
    # both flagged, ids disambiguated so validator's duplicate-id gate
    # doesn't reject the artifact
    from . import dedup as dedup_mod
    raw_a = cand("x1", "symbols", 1.0, full_n=2)
    raw_b = dict(raw_a, content={"full": "DIFFERENT", "section": "s ", "reference": "r "})
    contradiction_candidates = dedup_mod.dedup([raw_a, raw_b])
    assert len(contradiction_candidates) == 2
    assert all(c["contradiction"] for c in contradiction_candidates)

    rm4 = Assembler().assemble(build_spec("r3", "x", 100), contradiction_candidates, config, BusDouble())
    survivors = rm4.sections["symbols"]
    assert len(survivors) == 2
    assert all(item["contradiction"] for item in survivors)
    assert {item["original_id"] for item in survivors} == {"x1"}
    assert len({item["id"] for item in survivors}) == 2  # disambiguated, no collision
    ok, reason = validator.validate(rm4)
    assert ok, reason

    # malformed candidates raise loud
    try:
        Assembler().assemble(spec, "not-a-list", config, bus)
        raise SystemExit("bad candidates accepted")
    except ValueError:
        pass

    print("assembler selftest ok")
