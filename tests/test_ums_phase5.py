"""UMS Phase 5 completion-criteria suite — UMS/00-implementation-blueprint.md.

Criteria: mutate one fixture file -> index.stale then index.updated, only
that region's knowledge changed (canon diff); mid-update queries flag
staleness; partial onboarding answers with coverage; crash mid-reindex ->
reload -> staleness not lost; law check green against src/. Also: reindex
work proportional to the change set (storage read counters), end-to-end
lifecycle.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ums import (events, extraction, inventory, law_enforcer, persistence,
                 query, semantic, updates)
from ums.events import BusDouble
from ums.freshness import FreshnessTracker
from ums.onboarding import Onboarding
from ums.storage_double import StorageDouble
from ums.summary_store import SummaryStore

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_REPO = os.path.join(TESTS_DIR, "fixtures", "ums_repo")
SRC_DIR = os.path.join(TESTS_DIR, "..", "src")


class RecordingBus(BusDouble):
    """BusDouble that also records global publish order across topics."""

    def __init__(self):
        super().__init__()
        self.sequence = []

    def publish(self, topic, message):
        super().publish(topic, message)
        self.sequence.append(topic)


class UmsPhase5Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo").replace(os.sep, "/")
        shutil.copytree(FIXTURE_REPO, self.root)
        self.storage = StorageDouble()
        self.in_bus = BusDouble()
        self.out_bus = RecordingBus()
        self.tracker = FreshnessTracker()
        self.store = SummaryStore()
        inv = inventory.scan(self.root, self.storage)
        ext = extraction.extract_repo(inv, self.storage, self.root)
        sem = semantic.build(ext, self.storage, self.root, self.store)
        self.tracker.track_fresh(inv)
        persistence.save_index(self.storage, "fix", inv, self.tracker.snapshot())
        self.state = {"inventory": inv, "extraction": ext, "semantic": sem}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mutate(self, rel, extra):
        with open(os.path.join(self.root, rel), "a") as handle:
            handle.write(extra)
        self.in_bus.publish("write.committed",
                            {"repo_id": "fix", "payload": {"paths": [rel]}})

    def bundle(self, state):
        return {"extraction": state["extraction"],
                "semantic": state["semantic"], "freshness": self.tracker}

    # -- criterion: stale then updated; only that region changed -------------
    def test_mutation_stale_then_updated_one_region(self):
        self.mutate("util.py", "\n\ndef extra():\n    pass\n")
        changed = updates.consume_changes(self.in_bus, "fix", self.tracker,
                                          self.out_bus)
        self.assertEqual(changed, ["util.py"])
        new_state = updates.reindex("fix", self.root, self.storage,
                                    self.out_bus, self.tracker, self.store,
                                    self.state)
        # event order: index.stale strictly before index.updated
        self.assertEqual([t for t in self.out_bus.sequence
                          if t.startswith("index.")],
                         ["index.stale", "index.updated"])
        # canon diff: exactly one file record differs
        old_files = self.state["extraction"]["files"]
        new_files = new_state["extraction"]["files"]
        differing = [p for p in old_files
                     if extraction.canonical(old_files[p])
                     != extraction.canonical(new_files[p])]
        self.assertEqual(differing, ["util.py"])
        # untouched records reused by identity (cascade precision)
        for path in old_files:
            if path != "util.py":
                self.assertIs(new_files[path], old_files[path])
        self.assertTrue(self.tracker.is_fresh("util.py"))
        # comment-only mutation is non-structural: architecture untouched
        payload = self.out_bus.messages("index.updated")[0]["payload"]
        self.assertTrue(payload["structural"])  # new symbol = structural

    # -- criterion: mid-update queries flag staleness -------------------------
    def test_mid_update_queries_flag_staleness(self):
        self.mutate("pkg/core.py", "\n\ndef extra():\n    pass\n")
        updates.consume_changes(self.in_bus, "fix", self.tracker, self.out_bus)
        # between index.stale and index.updated: hit flagged, never hidden
        result = query.query(self.bundle(self.state), "add", 200)
        self.assertEqual(result["hits"][0]["path"], "pkg/core.py")
        self.assertTrue(result["hits"][0]["stale"])
        new_state = updates.reindex("fix", self.root, self.storage,
                                    self.out_bus, self.tracker, self.store,
                                    self.state)
        after = query.query(self.bundle(new_state), "add", 200)
        self.assertFalse(after["hits"][0]["stale"])

    # -- criterion: reindex work proportional to change set -------------------
    def test_reindex_cost_proportional(self):
        self.mutate("util.py", "\n\nX = 1\n")
        updates.consume_changes(self.in_bus, "fix", self.tracker, self.out_bus)
        reads_before = self.storage.bytes_read_calls
        updates.reindex("fix", self.root, self.storage, self.out_bus,
                        self.tracker, self.store, self.state)
        # 1 changed file of 7: one re-hash read + one extraction read
        self.assertEqual(self.storage.bytes_read_calls, reads_before + 2)

    # -- criterion: crash mid-reindex -> staleness not lost --------------------
    def test_crash_mid_reindex_staleness_survives_reload(self):
        self.mutate("util.py", "\n\nX = 2\n")
        updates.consume_changes(self.in_bus, "fix", self.tracker, self.out_bus)
        # persist freshness with the stale mark, then "crash" pre-reindex
        persistence.save_index(self.storage, "fix", self.state["inventory"],
                               self.tracker.snapshot())
        loaded_inv, loaded_fresh = persistence.load_index(self.storage, "fix")
        recovered = FreshnessTracker()
        recovered.restore(loaded_fresh)
        self.assertEqual(recovered.state("util.py"), "stale")
        self.assertFalse(recovered.is_fresh("util.py"))
        # recovery sweep rediscovers it from hashes alone (lost-event path)
        swept = FreshnessTracker()
        new_inv, _ = inventory.rescan(self.root, self.storage, loaded_inv)
        swept.sweep(loaded_inv, new_inv)
        self.assertIn("util.py", swept.stale_paths())

    # -- criterion: partial onboarding answers with coverage -------------------
    def test_partial_onboarding_answers_with_coverage(self):
        inv = self.state["inventory"]
        job = Onboarding("fix", self.root, inv, slice_size=3)
        job.step(self.storage)
        self.assertFalse(job.complete)
        partial = job.bundle(self.storage, SummaryStore())
        result = query.query(partial, "fixture", 200, query_class="concept")
        self.assertEqual(result["index_coverage"],
                         {"indexed": 3, "total": len(inv), "complete": False})
        while not job.complete:
            job.step(self.storage)
        events.emit(self.out_bus, "repo.indexed", "fix", job.coverage())
        done = job.bundle(self.storage, SummaryStore())
        self.assertTrue(done["coverage"]["complete"])
        self.assertEqual(self.out_bus.messages("repo.indexed")[0]["payload"],
                         {"indexed": len(inv), "total": len(inv),
                          "complete": True})

    # -- criterion: law check green against src/ --------------------------------
    def test_law_check_green_against_src(self):
        self.assertEqual(law_enforcer.check(SRC_DIR, self.storage), [])
        self.assertEqual(law_enforcer.similarity_owners(SRC_DIR, self.storage),
                         ["ums/ranker.py"])

    # -- end-to-end: restart -> mutate -> events -> reindex -> query -------------
    def test_end_to_end_lifecycle(self):
        loaded_inv, _ = persistence.load_index(self.storage, "fix")
        self.assertEqual(inventory.canonical(loaded_inv),
                         inventory.canonical(self.state["inventory"]))
        self.mutate("app.py", "\n\ndef cli():\n    main()\n")
        updates.consume_changes(self.in_bus, "fix", self.tracker, self.out_bus)
        new_state = updates.reindex("fix", self.root, self.storage,
                                    self.out_bus, self.tracker, self.store,
                                    self.state)
        result = query.query(self.bundle(new_state), "cli", 100)
        self.assertEqual(result["hits"][0]["id"], "sym:app.py:cli")
        self.assertFalse(result["hits"][0]["stale"])
        payload = self.out_bus.messages("index.updated")[0]["payload"]
        self.assertTrue(payload["structural"])  # new symbol
        # persisted store reloads with zero rebuild work
        reloaded = SummaryStore()
        reloaded.load(self.storage, "fix")
        self.assertEqual(len(reloaded), len(self.store))


if __name__ == "__main__":
    unittest.main()
