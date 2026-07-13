"""CM Phase 5 suite — CM/00-implementation-blueprint.md Phase 5
(Freshness, incremental, integration — final phase).

Covers: cache-key determinism; cache hit on a repeated identical request
(same artifact served, pipeline not re-run -- via an injected assembler
call counter); invalidation on `index.updated` with overlapping paths +
`context.invalidated` emitted; unrelated cache entries survive an
unrelated invalidation; stale cache entries are never served; incremental
rebuild after invalidation is byte-identical to a full rebuild (the
equivalence property, CM-I2); repeated unchanged requests keep avoiding
rework after a rebuild; a contradiction pair (dedup.py: same id, both
kept, flagged) survives end-to-end through the validator; law_enforcer is
green across src/cm/.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cm import cache as cache_mod
from cm import dedup as dedup_mod
from cm import freshness as freshness_mod
from cm import law_enforcer
from cm import spec as spec_mod
from cm import validator as validator_mod
from cm.assembler import Assembler
from cm.bus_double import BusDouble
from cm.config_view import ConfigView, DEFAULT
from cm.request_memory import content_hash


def _cand(id_, section="symbols", score=1.0, path=None, source="ums", full_n=3):
    provenance = {"source": source}
    if source == "ums":
        provenance["store"] = "symbol" if section == "symbols" else "file"
    return {"id": id_, "section": section, "score": score, "stale": False,
            "provenance": provenance,
            "content": {"full": "f " * full_n, "section": "s ", "reference": "r"}}


class _CountingAssembler(Assembler):
    """Assembler subclass that counts real assemble() calls, so tests can
    assert a cache hit never re-runs the pipeline."""

    def __init__(self):
        super().__init__()
        self.assemble_calls = 0

    def assemble(self, *args, **kwargs):
        self.assemble_calls += 1
        return super().assemble(*args, **kwargs)


class CacheTests(unittest.TestCase):
    def test_key_determinism(self):
        spec = spec_mod.build("r1", "obj", 100)
        h1 = spec_mod.spec_hash(spec)
        h2 = spec_mod.spec_hash(spec_mod.build("r1", "obj", 100))
        self.assertEqual(cache_mod.key("r1", h1), cache_mod.key("r1", h2))

    def test_hit_on_repeated_identical_request_no_rework(self):
        config = ConfigView(DEFAULT)
        spec = spec_mod.build("r1", "do the thing", 100)
        candidates = [_cand("sym:core.py:add", path="core.py")]
        cache = cache_mod.Cache()
        asm = _CountingAssembler()
        k = cache_mod.key("r1", spec_mod.spec_hash(spec))
        bus = BusDouble()

        rm1, assembled1 = freshness_mod.get_or_assemble(cache, k, asm, spec, candidates, config, bus)
        rm2, assembled2 = freshness_mod.get_or_assemble(cache, k, asm, spec, candidates, config, bus)

        self.assertTrue(assembled1)
        self.assertFalse(assembled2)
        self.assertEqual(asm.assemble_calls, 1)  # pipeline ran exactly once
        self.assertIs(rm1, rm2)  # identical artifact object served
        self.assertEqual(content_hash(rm1), content_hash(rm2))

    def test_stale_entry_never_served(self):
        cache = cache_mod.Cache()
        k = cache_mod.key("r1", "h1")
        cache.put(k, "artifact")
        cache.invalidate(k)
        self.assertIsNone(cache.get(k))
        self.assertEqual(cache.peek(k), "artifact")  # inspectable, never served


class FreshnessInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.config = ConfigView(DEFAULT)

    def _cache_one(self, cache, request_id, item_ids_paths, budget=1000):
        spec = spec_mod.build(request_id, "obj " + request_id, budget)
        candidates = [_cand(iid, path=p) for iid, p in item_ids_paths]
        k = cache_mod.key(request_id, spec_mod.spec_hash(spec))
        rm, _ = freshness_mod.get_or_assemble(cache, k, Assembler(), spec, candidates,
                                              self.config, BusDouble())
        return k, rm

    def test_invalidation_on_overlapping_path_emits_event(self):
        cache = cache_mod.Cache()
        k, rm = self._cache_one(cache, "r1", [("sym:core.py:add", "core.py")])
        bus = BusDouble()
        invalidated = freshness_mod.on_index_updated(cache, bus, {"paths": ["core.py"]})
        self.assertEqual(invalidated, [k])
        self.assertIsNone(cache.get(k))
        events_seen = bus.messages("context.invalidated")
        self.assertEqual(len(events_seen), 1)
        self.assertEqual(events_seen[0]["payload"]["request_id"], "r1")
        self.assertEqual(events_seen[0]["payload"]["memory_id"], rm.memory_id)

    def test_unrelated_cache_entries_survive(self):
        cache = cache_mod.Cache()
        k_touched, _ = self._cache_one(cache, "r1", [("sym:core.py:add", "core.py")])
        k_unrelated, rm_unrelated = self._cache_one(cache, "r2", [("file:other.py", "other.py")])
        bus = BusDouble()
        freshness_mod.on_index_updated(cache, bus, {"paths": ["core.py"]})
        self.assertIsNone(cache.get(k_touched))
        self.assertIs(cache.get(k_unrelated), rm_unrelated)

    def test_no_overlap_no_invalidation(self):
        cache = cache_mod.Cache()
        k, rm = self._cache_one(cache, "r1", [("sym:core.py:add", "core.py")])
        bus = BusDouble()
        invalidated = freshness_mod.on_index_updated(cache, bus, {"paths": ["unrelated.py"]})
        self.assertEqual(invalidated, [])
        self.assertIs(cache.get(k), rm)
        self.assertEqual(bus.messages("context.invalidated"), [])

    def test_empty_paths_is_noop(self):
        cache = cache_mod.Cache()
        bus = BusDouble()
        self.assertEqual(freshness_mod.on_index_updated(cache, bus, {"paths": []}), [])
        self.assertEqual(freshness_mod.on_index_updated(cache, bus, {}), [])

    def test_replaying_same_update_is_idempotent(self):
        cache = cache_mod.Cache()
        k, _ = self._cache_one(cache, "r1", [("sym:core.py:add", "core.py")])
        bus = BusDouble()
        freshness_mod.on_index_updated(cache, bus, {"paths": ["core.py"]})
        again = freshness_mod.on_index_updated(cache, bus, {"paths": ["core.py"]})
        self.assertEqual(again, [])
        self.assertEqual(len(bus.messages("context.invalidated")), 1)


class IncrementalRebuildEquivalenceTests(unittest.TestCase):
    """The critical equivalence property: incremental rebuild after
    invalidation must byte-identically equal a full rebuild (CM-I2)."""

    def setUp(self):
        self.config = ConfigView(DEFAULT)
        self.spec = spec_mod.build("r1", "do the thing", 500)
        self.candidates = [
            _cand("sym:core.py:add", section="symbols", path="core.py", score=2.0),
            _cand("file:util.py", section="files", path="util.py", score=1.0),
        ]

    def test_incremental_equals_full_rebuild(self):
        full = Assembler().assemble(self.spec, self.candidates, self.config, BusDouble())

        cache = cache_mod.Cache()
        k = cache_mod.key("r1", spec_mod.spec_hash(self.spec))
        freshness_mod.get_or_assemble(cache, k, Assembler(), self.spec, self.candidates,
                                      self.config, BusDouble())
        freshness_mod.on_index_updated(cache, BusDouble(), {"paths": ["core.py"]})
        self.assertIsNone(cache.get(k))  # confirms invalidation actually happened

        incremental = freshness_mod.rebuild(cache, k, Assembler(), self.spec, self.candidates,
                                            self.config, BusDouble())

        self.assertEqual(content_hash(incremental), content_hash(full))
        self.assertIs(cache.get(k), incremental)

    def test_affected_sections_identifies_only_touched_section(self):
        rm = Assembler().assemble(self.spec, self.candidates, self.config, BusDouble())
        self.assertEqual(freshness_mod.affected_sections(rm, ["core.py"]), {"symbols"})
        self.assertEqual(freshness_mod.affected_sections(rm, ["util.py"]), {"files"})
        self.assertEqual(freshness_mod.affected_sections(rm, ["core.py", "util.py"]),
                         {"symbols", "files"})
        self.assertEqual(freshness_mod.affected_sections(rm, ["nope.py"]), set())

    def test_repeated_unchanged_requests_avoid_rework_after_rebuild(self):
        cache = cache_mod.Cache()
        k = cache_mod.key("r1", spec_mod.spec_hash(self.spec))
        asm = _CountingAssembler()
        freshness_mod.get_or_assemble(cache, k, asm, self.spec, self.candidates, self.config, BusDouble())
        freshness_mod.on_index_updated(cache, BusDouble(), {"paths": ["core.py"]})
        freshness_mod.rebuild(cache, k, asm, self.spec, self.candidates, self.config, BusDouble())
        self.assertEqual(asm.assemble_calls, 2)  # initial + rebuild

        # further identical requests hit the cache, no further assembly
        freshness_mod.get_or_assemble(cache, k, asm, self.spec, self.candidates, self.config, BusDouble())
        freshness_mod.get_or_assemble(cache, k, asm, self.spec, self.candidates, self.config, BusDouble())
        self.assertEqual(asm.assemble_calls, 2)


class ContradictionSeamFixTests(unittest.TestCase):
    """Seam fix (recorded Phase 4): a contradiction pair from dedup.py
    (same id, both kept, both flagged) must survive validator's zero-
    duplicate-ids gate end-to-end through the assembler."""

    def test_contradiction_pair_survives_end_to_end(self):
        config = ConfigView(DEFAULT)
        a = _cand("x1", source="test", score=1.0)
        a["provenance"] = {"source": "test"}
        b = dict(a, content={"full": "DIFFERENT", "section": "s", "reference": "r"})
        deduped = dedup_mod.dedup([a, b])
        self.assertEqual(len(deduped), 2)
        self.assertTrue(all(c["contradiction"] for c in deduped))

        spec = spec_mod.build("r1", "obj", 100)
        rm = Assembler().assemble(spec, deduped, config, BusDouble())

        ok, reason = validator_mod.validate(rm)
        self.assertTrue(ok, reason)
        survivors = rm.sections["symbols"]
        self.assertEqual(len(survivors), 2)
        self.assertTrue(all(item["contradiction"] for item in survivors))
        self.assertEqual({item["original_id"] for item in survivors}, {"x1"})
        self.assertEqual(len({item["id"] for item in survivors}), 2)


class LawEnforcerTests(unittest.TestCase):
    def test_law_enforcer_green_across_cm(self):
        cm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "cm")
        src_dir = os.path.join(cm_dir, "..")
        report = law_enforcer.check(cm_dir, src_dir)
        self.assertEqual(report["similarity_or_retrieval"], [])
        self.assertEqual(report["ums_import_scope"], [])
        self.assertEqual(report["single_assembler"], ["cm/assembler.py"])
        self.assertEqual(report["closed_events"], [])


if __name__ == "__main__":
    unittest.main()
