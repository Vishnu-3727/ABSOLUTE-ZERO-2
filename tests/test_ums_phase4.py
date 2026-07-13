"""UMS Phase 4 completion-criteria suite — UMS/00-implementation-blueprint.md.

Criteria: golden-query fixture suite (fixed repo, fixed queries, asserted
ranked order); identical query + state -> identical results (Law 6); no
result set exceeds its ceiling (randomized-budget property); stale-region
hits always flagged; every hit explains its score.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ums import extraction, inventory, query, ranker, semantic
from ums.freshness import FreshnessTracker
from ums.storage_double import StorageDouble
from ums.summary_store import SummaryStore

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_REPO = os.path.join(TESTS_DIR, "fixtures", "ums_repo").replace(os.sep, "/")


def build_bundle():
    storage = StorageDouble()
    inv = inventory.scan(FIXTURE_REPO, storage)
    ext = extraction.extract_repo(inv, storage, FIXTURE_REPO)
    sem = semantic.build(ext, storage, FIXTURE_REPO, SummaryStore())
    tracker = FreshnessTracker()
    tracker.track_fresh(inv)
    return {"extraction": ext, "semantic": sem, "freshness": tracker}


class UmsPhase4Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()

    # -- golden queries -------------------------------------------------------
    def test_golden_query_add(self):
        result = query.query(self.bundle, "add", 200)
        self.assertEqual(result["class"], "symbol")
        self.assertEqual(result["hits"][0]["id"], "sym:pkg/core.py:add")
        self.assertGreater(result["hits"][0]["score"], 0.9)

    def test_golden_query_calc_mul(self):
        result = query.query(self.bundle, "Calc.mul", 200)
        self.assertEqual(result["hits"][0]["id"], "sym:pkg/core.py:Calc.mul")

    def test_golden_query_file(self):
        result = query.query(self.bundle, "pkg/core.py", 200)
        self.assertEqual(result["class"], "file")
        self.assertEqual(result["hits"][0]["id"], "file:pkg/core.py")

    def test_golden_query_concept(self):
        result = query.query(self.bundle, "add two numbers", 400,
                             query_class="concept")
        ids = [h["id"] for h in result["hits"]]
        self.assertEqual(ids[0], "sym:pkg/core.py:add")
        self.assertTrue(result["candidates_considered"] <= 400)

    # -- Law 6: determinism ----------------------------------------------------
    def test_identical_query_identical_results(self):
        first = query.query(self.bundle, "add two numbers", 100,
                            query_class="concept")
        for _ in range(3):
            self.assertEqual(
                query.query(self.bundle, "add two numbers", 100,
                            query_class="concept"), first)
        # a fresh, independently built index state agrees too
        self.assertEqual(
            query.query(build_bundle(), "add two numbers", 100,
                        query_class="concept"), first)

    # -- budget ceiling property ------------------------------------------------
    def test_budget_never_exceeded_randomized(self):
        rng = random.Random(42)  # fixed seed: reproducible property sweep
        for _ in range(50):
            budget = rng.randrange(0, 120)
            result = query.query(self.bundle, "add numbers module", budget,
                                 query_class="concept")
            self.assertLessEqual(result["tokens_used"], budget)
            if result["dropped"]:
                self.assertTrue(result["truncated"])  # never silent

    # -- explanation completeness ------------------------------------------------
    def test_every_hit_explains_its_score(self):
        result = query.query(self.bundle, "add two numbers", 400,
                             query_class="concept")
        self.assertTrue(result["hits"])
        for hit in result["hits"]:
            signals = hit["explanation"]["signals"]
            self.assertEqual(set(signals), {"lexical", "stem", "structural"})
            self.assertEqual(hit["explanation"]["weights"], ranker.WEIGHTS)
            recomputed = round(sum(ranker.WEIGHTS[k] * v
                                   for k, v in signals.items()), 6)
            self.assertEqual(hit["score"], recomputed)

    # -- freshness gate -----------------------------------------------------------
    def test_stale_region_hit_always_flagged(self):
        bundle = build_bundle()
        bundle["freshness"].mark_stale(["pkg/core.py"])
        result = query.query(bundle, "add", 200)
        top = result["hits"][0]
        self.assertEqual(top["path"], "pkg/core.py")
        self.assertTrue(top["stale"])
        # untouched regions still fresh
        other = query.query(bundle, "app.py", 200)
        self.assertFalse(other["hits"][0]["stale"])

    # -- score floor: noise queries return nothing ---------------------------------
    def test_score_floor_drops_noise(self):
        result = query.query(self.bundle, "zzzz qqqq xxxx", 200,
                             query_class="concept")
        self.assertEqual(result["hits"], [])


if __name__ == "__main__":
    unittest.main()
