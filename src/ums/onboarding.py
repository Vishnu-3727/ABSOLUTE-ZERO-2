"""Onboarding orchestrator — large repos indexed in slices, never blocking.

step() extracts the next slice of files; bundle() assembles a queryable
partial index with coverage metadata at any point mid-build. Queries
against a partial bundle answer honestly (coverage attached by the query
engine) instead of blocking until the build finishes. When complete, the
caller persists and publishes repo.indexed (events.py).
"""
from . import extraction, semantic
from .freshness import FreshnessTracker


class Onboarding:
    def __init__(self, repo_id, repo_root, inventory_map, slice_size=2):
        self.repo_id = repo_id
        self.repo_root = repo_root
        self.inventory = inventory_map
        self.slice_size = slice_size
        self._pending = sorted(inventory_map)
        self._files = {}

    def step(self, storage):
        """Extract the next slice. Returns the paths indexed this step."""
        batch, self._pending = (self._pending[:self.slice_size],
                                self._pending[self.slice_size:])
        for path in batch:
            self._files[path] = extraction.extract_file(
                path, self.inventory[path], storage, self.repo_root)
        return batch

    @property
    def complete(self):
        return not self._pending

    def coverage(self):
        return {"indexed": len(self._files),
                "total": len(self.inventory),
                "complete": self.complete}

    def bundle(self, storage, store):
        """Queryable (partial) bundle with coverage metadata attached."""
        ext = extraction.assemble(dict(self._files))
        sem = semantic.build(ext, storage, self.repo_root, store)
        tracker = FreshnessTracker()
        tracker.track_fresh(self._files)
        return {"extraction": ext, "semantic": sem, "freshness": tracker,
                "coverage": self.coverage()}


if __name__ == "__main__":
    import os
    import tempfile

    from . import inventory, query
    from .storage_double import StorageDouble
    from .summary_store import SummaryStore

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(5):
            with open(os.path.join(tmp, "m%d.py" % i), "wb") as handle:
                handle.write(b'"""Module %d."""\ndef fn%d():\n    pass\n'
                             % (i, i))
        root = tmp.replace(os.sep, "/")
        storage = StorageDouble()
        inv = inventory.scan(root, storage)

        job = Onboarding("r1", root, inv, slice_size=2)
        assert job.step(storage) == ["m0.py", "m1.py"]
        assert not job.complete
        assert job.coverage() == {"indexed": 2, "total": 5, "complete": False}

        # mid-build query: answered, with coverage metadata, not blocked
        store = SummaryStore()
        partial = job.bundle(storage, store)
        result = query.query(partial, "fn1", 100)
        assert result["hits"][0]["id"] == "sym:m1.py:fn1"
        assert result["index_coverage"]["complete"] is False
        # not-yet-indexed file simply absent, never a wrong answer
        assert query.query(partial, "fn4", 100)["hits"] == []

        assert job.step(storage) == ["m2.py", "m3.py"]
        assert job.step(storage) == ["m4.py"]
        assert job.complete and job.step(storage) == []
        full = job.bundle(storage, SummaryStore())
        assert full["coverage"] == {"indexed": 5, "total": 5, "complete": True}
        assert query.query(full, "fn4", 100)["hits"][0]["id"] == "sym:m4.py:fn4"
    print("onboarding selftest ok")
