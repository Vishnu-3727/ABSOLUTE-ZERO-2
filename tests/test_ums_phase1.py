"""UMS Phase 1 completion-criteria suite — UMS/00-implementation-blueprint.md.

Criteria: onboard fixture -> inventory -> persist -> reload identical
(round-trip determinism); mutate one file -> exactly that region stale;
corrupt persisted index -> detected loud, regions marked rebuild-needed;
no direct disk I/O in src/ums outside the Storage double (Law 3 grep check).
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ums import events, freshness, inventory, persistence
from ums.events import BusDouble
from ums.freshness import FreshnessTracker
from ums.registry import Registry
from ums.storage_double import StorageDouble

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_REPO = os.path.join(TESTS_DIR, "fixtures", "ums_repo")
UMS_DIR = os.path.join(TESTS_DIR, "..", "src", "ums")


class UmsPhase1Case(unittest.TestCase):
    def setUp(self):
        # work on a throwaway copy so the fixture stays pristine
        self.tmp = tempfile.mkdtemp()
        self.repo_root = os.path.join(self.tmp, "repo")
        shutil.copytree(FIXTURE_REPO, self.repo_root)
        self.store = StorageDouble()
        self.bus = BusDouble()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def onboard_and_index(self):
        registry = Registry()
        registry.onboard("fix", self.repo_root)
        inv = inventory.scan(registry.get("fix").root_path, self.store)
        tracker = FreshnessTracker()
        tracker.track_fresh(inv)
        persistence.save_index(self.store, "fix", inv, tracker.snapshot())
        events.emit(self.bus, "repo.indexed", "fix", {"files": len(inv)})
        return inv, tracker

    # -- criterion 1: round-trip determinism ------------------------------
    def test_roundtrip_canonical_identical(self):
        inv, tracker = self.onboard_and_index()
        self.assertEqual(sorted(inv),
                         ["README.md", "app.py", "broken.py", "pkg/__init__.py",
                          "pkg/core.py", "settings.toml", "util.py"])
        inv2, fresh2 = persistence.load_index(self.store, "fix")
        self.assertEqual(inventory.canonical(inv2), inventory.canonical(inv))
        self.assertEqual(fresh2, tracker.snapshot())
        # persist the reloaded state: byte-identical blob (determinism)
        blob1 = self.store.read(persistence.index_key("fix"))
        persistence.save_index(self.store, "fix", inv2, fresh2)
        self.assertEqual(self.store.read(persistence.index_key("fix")), blob1)
        self.assertEqual(self.bus.messages("repo.indexed")[0]["repo_id"], "fix")

    def test_restart_reload_via_dir_backed_storage(self):
        inv, tracker = self.onboard_and_index()
        disk = StorageDouble(dir_path=self.tmp)
        persistence.save_index(disk, "fix", inv, tracker.snapshot())
        fresh_process_store = StorageDouble(dir_path=self.tmp)  # "restart"
        inv2, fresh2 = persistence.load_index(fresh_process_store, "fix")
        self.assertEqual(inventory.canonical(inv2), inventory.canonical(inv))
        self.assertEqual(fresh2, tracker.snapshot())

    # -- criterion 2: change detection precision --------------------------
    def test_mutation_flags_exactly_one_region(self):
        inv, tracker = self.onboard_and_index()
        reads_before = self.store.bytes_read_calls
        with open(os.path.join(self.repo_root, "pkg", "core.py"), "a") as handle:
            handle.write("\n\ndef sub(a, b):\n    return a - b\n")
        inv2, changed = inventory.rescan(self.repo_root, self.store, inv)
        self.assertEqual(changed, ["pkg/core.py"])
        # token law: only the mutated file was re-read
        self.assertEqual(self.store.bytes_read_calls, reads_before + 1)
        tracker.mark_stale(changed)
        events.emit(self.bus, "index.stale", "fix", {"paths": changed})
        self.assertEqual(tracker.stale_paths(), ["pkg/core.py"])
        for path in ("app.py", "util.py", "pkg/__init__.py"):
            self.assertTrue(tracker.is_fresh(path))
        self.assertFalse(tracker.is_fresh("pkg/core.py"))
        # unchanged regions byte-identical in canonical form
        del inv2["pkg/core.py"]
        pruned = {p: r for p, r in inv.items() if p != "pkg/core.py"}
        self.assertEqual(inventory.canonical(inv2), inventory.canonical(pruned))

    def test_recovery_sweep_recomputes_staleness(self):
        inv, tracker = self.onboard_and_index()
        with open(os.path.join(self.repo_root, "util.py"), "a") as handle:
            handle.write("\n\ndef whisper(t):\n    return t.lower()\n")
        inv2, _ = inventory.rescan(self.repo_root, self.store, inv)
        recovered = FreshnessTracker()  # lost all state (crash)
        recovered.sweep(inv, inv2)
        self.assertEqual(recovered.stale_paths(), ["util.py"])

    # -- criterion 3: corruption is loud ----------------------------------
    def test_corrupt_index_detected_and_marked_rebuild_needed(self):
        inv, tracker = self.onboard_and_index()
        key = persistence.index_key("fix")
        blob = self.store.read(key)
        self.store.write(key, blob.replace(b"app.py", b"zzz.py", 1))
        with self.assertRaises(persistence.IndexCorruptionError):
            persistence.load_index(self.store, "fix")
        tracker.mark_rebuild_needed(inv)
        for path in inv:
            self.assertEqual(tracker.state(path), freshness.REBUILD_NEEDED)
            self.assertFalse(tracker.is_fresh(path))
        # garbage bytes are equally loud
        self.store.write(key, b"\x00garbage")
        with self.assertRaises(persistence.IndexCorruptionError):
            persistence.load_index(self.store, "fix")

    # -- criterion 4: Law 3 grep check ------------------------------------
    def test_no_direct_disk_io_outside_storage_double(self):
        pattern = re.compile(r"\bopen\(|\bwrite_text\(|\bwrite_bytes\(|\bunlink\(|os\.remove")
        for name in sorted(os.listdir(UMS_DIR)):
            if not name.endswith(".py") or name == "storage_double.py":
                continue
            with open(os.path.join(UMS_DIR, name), encoding="utf-8") as handle:
                source = handle.read()
            # law binds runtime code; __main__ selftest scaffolding is test code
            source = source.split('if __name__ == "__main__":')[0]
            self.assertIsNone(pattern.search(source),
                              "direct disk I/O in src/ums/" + name)

    # -- event discipline ---------------------------------------------------
    def test_only_the_three_contract_events_exist(self):
        self.assertEqual(events.EVENT_NAMES,
                         ("repo.indexed", "index.stale", "index.updated"))
        with self.assertRaises(ValueError):
            events.emit(self.bus, "repo.offboarded", "fix")  # not ours to publish


if __name__ == "__main__":
    unittest.main()
