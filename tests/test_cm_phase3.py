"""CM Phase 3 suite — CM/00-implementation-blueprint.md Phase 3 (Selection
core).

Covers: dependency expansion correctness + determinism; cycle safety; depth
cap honored; dedup idempotence; contradiction surfacing; ordering stability
across shuffled input; empty candidate set; malformed dependency structure
fails loud; repeated end-to-end (gather -> resolve -> dedup -> prioritize)
runs identical.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cm import dedup as dedup_mod
from cm import prioritizer as prioritizer_mod
from cm import resolver as resolver_mod
from cm import sources, spec as spec_mod
from cm.config_view import ConfigView, DEFAULT
from fixtures.cm_bundle import build_bundle


def _cand(id_, section="files", content=None, score=1.0, stale=False):
    return {"id": id_, "section": section, "content": content or {},
            "score": score, "stale": stale, "provenance": {}}


class ResolverExpansionTests(unittest.TestCase):
    def test_expansion_finds_reachable_dependencies(self):
        seeds = [_cand("file:a.py")]
        edges = [{"src": "file:a.py", "dst": "file:b.py"},
                 {"src": "file:b.py", "dst": "file:c.py"}]
        expanded, trace = resolver_mod.expand(seeds, edges, 5)
        self.assertEqual([c["id"] for c in expanded], ["file:a.py", "file:b.py", "file:c.py"])
        self.assertEqual(trace["visited"], ["file:a.py", "file:b.py", "file:c.py"])

    def test_depth_cap_honored(self):
        seeds = [_cand("file:a.py")]
        edges = [{"src": "file:a.py", "dst": "file:b.py"},
                 {"src": "file:b.py", "dst": "file:c.py"}]
        expanded, _ = resolver_mod.expand(seeds, edges, 1)
        self.assertEqual([c["id"] for c in expanded], ["file:a.py", "file:b.py"])

    def test_depth_cap_zero_means_no_expansion(self):
        seeds = [_cand("file:a.py")]
        edges = [{"src": "file:a.py", "dst": "file:b.py"}]
        expanded, trace = resolver_mod.expand(seeds, edges, 0)
        self.assertEqual([c["id"] for c in expanded], ["file:a.py"])
        self.assertEqual(trace["frontier_by_depth"], [])

    def test_cycle_safety_terminates(self):
        seeds = [_cand("file:a.py")]
        edges = [{"src": "file:a.py", "dst": "file:b.py"},
                 {"src": "file:b.py", "dst": "file:a.py"}]
        expanded, trace = resolver_mod.expand(seeds, edges, 50)
        self.assertEqual([c["id"] for c in expanded], ["file:a.py", "file:b.py"])
        self.assertLess(trace["depth_reached"], 50)

    def test_determinism_identical_inputs_identical_output(self):
        seeds = [_cand("file:a.py")]
        edges = [{"src": "file:a.py", "dst": "file:c.py"},
                 {"src": "file:a.py", "dst": "file:b.py"}]
        e1, t1 = resolver_mod.expand(seeds, edges, 3)
        e2, t2 = resolver_mod.expand(seeds, list(reversed(edges)), 3)
        self.assertEqual(e1, e2)
        self.assertEqual(t1, t2)

    def test_empty_candidate_set(self):
        edges = [{"src": "file:a.py", "dst": "file:b.py"}]
        expanded, trace = resolver_mod.expand([], edges, 3)
        self.assertEqual(expanded, [])
        self.assertEqual(trace["visited"], [])

    def test_malformed_dependency_structure_fails_loud(self):
        seeds = [_cand("file:a.py")]
        with self.assertRaises(ValueError):
            resolver_mod.expand(seeds, "not-a-list", 3)
        with self.assertRaises(ValueError):
            resolver_mod.expand(seeds, [{"src": "a"}], 3)  # missing dst
        with self.assertRaises(ValueError):
            resolver_mod.expand(seeds, [{"src": 1, "dst": "b"}], 3)  # non-str src
        with self.assertRaises(ValueError):
            resolver_mod.expand(seeds, [{"src": "a", "dst": "b"}], -1)  # bad depth_cap


class DedupTests(unittest.TestCase):
    def test_exact_duplicate_dropped(self):
        a = _cand("x1", content={"full": "A"})
        a_dup = dict(a)
        out = dedup_mod.dedup([a, a_dup])
        self.assertEqual([c["id"] for c in out], ["x1"])

    def test_contradiction_surfaced_both_kept_flagged(self):
        a = _cand("x1", content={"full": "A"})
        a_conflict = _cand("x1", content={"full": "DIFFERENT"})
        out = dedup_mod.dedup([a, a_conflict])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(c.get("contradiction") for c in out))
        self.assertNotEqual(out[0]["content"], out[1]["content"])  # never blended

    def test_dedup_idempotence(self):
        a = _cand("x1", content={"full": "A"})
        a_dup = dict(a)
        b = _cand("x2", content={"full": "B"})
        conflict = _cand("x1", content={"full": "C"})
        once = dedup_mod.dedup([a, a_dup, b, conflict])
        twice = dedup_mod.dedup(once)
        self.assertEqual(once, twice)

    def test_ordering_stable_after_removal(self):
        items = [_cand("z"), _cand("a"), _cand("m")]
        out = dedup_mod.dedup(items)
        self.assertEqual([c["id"] for c in out], ["z", "a", "m"])

    def test_empty_input(self):
        self.assertEqual(dedup_mod.dedup([]), [])


class PrioritizerTests(unittest.TestCase):
    def setUp(self):
        self.config = ConfigView(DEFAULT)

    def test_section_weight_beats_score(self):
        high_score_low_weight = _cand("k1", section="knowledge", score=9.0)
        low_score_high_weight = _cand("s1", section="symbols", score=0.1)
        out = prioritizer_mod.prioritize([high_score_low_weight, low_score_high_weight], self.config)
        self.assertEqual([c["id"] for c in out], ["s1", "k1"])

    def test_score_breaks_tie_within_section(self):
        low = _cand("s1", section="symbols", score=0.1)
        high = _cand("s2", section="symbols", score=0.9)
        out = prioritizer_mod.prioritize([low, high], self.config)
        self.assertEqual([c["id"] for c in out], ["s2", "s1"])

    def test_id_breaks_final_tie(self):
        a = _cand("sb", section="symbols", score=0.5)
        b = _cand("sa", section="symbols", score=0.5)
        out = prioritizer_mod.prioritize([a, b], self.config)
        self.assertEqual([c["id"] for c in out], ["sa", "sb"])

    def test_none_score_sorts_last_within_section(self):
        scored = _cand("s1", section="symbols", score=0.0)
        unscored = _cand("s2", section="symbols", score=None)
        out = prioritizer_mod.prioritize([unscored, scored], self.config)
        self.assertEqual([c["id"] for c in out], ["s1", "s2"])

    def test_ordering_stability_across_shuffled_input(self):
        items = [_cand("s%d" % i, section="symbols", score=float(i % 3)) for i in range(12)]
        baseline = prioritizer_mod.prioritize(items, self.config)
        shuffled = list(items)
        random.Random(42).shuffle(shuffled)
        self.assertEqual(prioritizer_mod.prioritize(shuffled, self.config), baseline)

    def test_empty_input(self):
        self.assertEqual(prioritizer_mod.prioritize([], self.config), [])


class EndToEndSelectionTests(unittest.TestCase):
    """gather -> resolve -> dedup -> prioritize, repeated runs identical."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()
        cls.config = ConfigView(DEFAULT)

    def _run(self):
        spec = spec_mod.build(request_id="r1", objective="add", budget_tokens=200,
                               references=["knowledge:k1"])
        candidates, _ = sources.gather(spec, self.bundle, "r1")
        edges = [{"src": c["id"], "dst": c["id"] + ":dep"} for c in candidates
                  if c["provenance"]["source"] == "ums"]
        expanded, _trace = resolver_mod.expand(candidates, edges, self.config.resolver_depth_cap)
        deduped = dedup_mod.dedup(expanded)
        return prioritizer_mod.prioritize(deduped, self.config)

    def test_repeated_pipeline_runs_identical(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)

    def test_selection_is_unique_by_id_content_hash(self):
        result = self._run()
        seen = set()
        for c in result:
            key = (c["id"], dedup_mod._content_hash(c))
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_selection_is_dependency_complete(self):
        result = self._run()
        ids = {c["id"] for c in result}
        dep_ids = {c["id"] for c in result if c["provenance"].get("source") == "resolver"}
        self.assertTrue(dep_ids)
        self.assertTrue(dep_ids <= ids)


if __name__ == "__main__":
    unittest.main()
