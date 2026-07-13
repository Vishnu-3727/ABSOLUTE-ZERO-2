"""Fixture UMS bundle for CM Phase 2 tests (blueprint Phase 2 deliverable:
"Fixture UMS bundle under tests/fixtures/"). Builds a real, queryable UMS
bundle from the existing `ums_repo` fixture repo (shared with the UMS
phase suites) rather than inventing a second fixture repo — same pattern
as `tests/test_ums_phase4.py::build_bundle`.
"""
import os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
UMS_REPO = os.path.join(TESTS_DIR, "ums_repo").replace(os.sep, "/")


def build_bundle():
    from ums import extraction, inventory, semantic
    from ums.freshness import FreshnessTracker
    from ums.storage_double import StorageDouble
    from ums.summary_store import SummaryStore

    storage = StorageDouble()
    inv = inventory.scan(UMS_REPO, storage)
    ext = extraction.extract_repo(inv, storage, UMS_REPO)
    sem = semantic.build(ext, storage, UMS_REPO, SummaryStore())
    tracker = FreshnessTracker()
    tracker.track_fresh(inv)
    return {"extraction": ext, "semantic": sem, "freshness": tracker}
