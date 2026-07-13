"""Summary store — keyed by CONTENT HASH. Hash unchanged = reused forever.

The biggest token-efficiency risk in UMS is sloppy hash keying silently
re-summarizing (blueprint Phase 3 risks). get_or_build() builds at most
once per content hash, ever; `builds` counts real summarization work so
tests can assert a second run does zero. Persisted through Storage via
the checksummed blob format (Law 3).
"""
from .persistence import IndexCorruptionError, load_json, save_json


def store_key(repo_id):
    return "ums/summaries/" + repo_id


class SummaryStore:
    def __init__(self):
        self._by_hash = {}
        self.builds = 0

    def get_or_build(self, content_hash, builder):
        """Return the summary for a content hash, building at most once ever."""
        record = self._by_hash.get(content_hash)
        if record is None:
            record = builder()
            self._by_hash[content_hash] = record
            self.builds += 1
        return record

    def __contains__(self, content_hash):
        return content_hash in self._by_hash

    def __len__(self):
        return len(self._by_hash)

    def save(self, storage, repo_id):
        save_json(storage, store_key(repo_id), self._by_hash)

    def load(self, storage, repo_id):
        """Replace contents from Storage (corruption raises loud upstream)."""
        self._by_hash = load_json(storage, store_key(repo_id))


if __name__ == "__main__":
    from .storage_double import StorageDouble

    store = SummaryStore()
    calls = []
    record = store.get_or_build("h1", lambda: calls.append(1) or {"reference": "r"})
    assert record == {"reference": "r"} and store.builds == 1
    again = store.get_or_build("h1", lambda: calls.append(1) or {"reference": "X"})
    assert again is record and store.builds == 1 and len(calls) == 1  # never rebuilt
    store.get_or_build("h2", lambda: {"reference": "r2"})
    assert len(store) == 2 and "h1" in store and "h3" not in store

    storage = StorageDouble()
    store.save(storage, "r1")
    loaded = SummaryStore()
    loaded.load(storage, "r1")
    assert loaded._by_hash == store._by_hash
    assert loaded.get_or_build("h1", lambda: 1 / 0) == record  # reuse, no build

    storage.write(store_key("r1"), b"garbage")
    try:
        SummaryStore().load(storage, "r1")
        raise SystemExit("corrupt store loaded silently")
    except IndexCorruptionError:
        pass
    print("summary_store selftest ok")
