"""Incremental update pipeline: change events -> stale -> reindex -> updated.

One cohesive flow (change consumer -> invalidation cascade -> reindex
scheduler):
- consume_changes(): drains write.committed / commit.created from the
  bus, marks regions stale, publishes index.stale IMMEDIATELY (before
  any reindex work — queries in between see honest flags).
- reindex(): stale regions re-run through Phase 2-3 extractors. Cascade
  precision comes from hash gating: unchanged files' records are reused
  by object identity, so untouched regions stay byte-identical; the
  architecture model is rebuilt ONLY when structural facts (symbols or
  imports) actually changed. Persists via Storage, then publishes
  index.updated. Work is proportional to the change set.
"""
from . import events, extraction, inventory, persistence, semantic

CHANGE_EVENTS = ("write.committed", "commit.created")


def consume_changes(in_bus, repo_id, tracker, out_bus):
    """Drain change events; mark stale; publish index.stale. Returns paths."""
    paths = set()
    for topic in CHANGE_EVENTS:
        for message in in_bus.drain(topic):
            if message.get("repo_id", repo_id) != repo_id:
                continue  # not our repo
            paths.update(message["payload"]["paths"])
    changed = sorted(paths)
    if changed:
        tracker.mark_stale(changed)
        events.emit(out_bus, "index.stale", repo_id, {"paths": changed})
    return changed


def structural_change(prev_extraction, new_extraction, paths):
    """Did symbols or import facts change on any of these paths?"""
    for path in paths:
        old = prev_extraction["files"].get(path)
        new = new_extraction["files"].get(path)
        if old is None or new is None:  # added or removed file
            return True
        if old["symbols"] != new["symbols"] or old["imports"] != new["imports"]:
            return True
    return False


def reindex(repo_id, repo_root, storage, out_bus, tracker, store, state):
    """Process stale regions; persist; publish index.updated.

    state = {"inventory", "extraction", "semantic"} from the last build.
    Returns the new state (untouched sub-records reused by identity).
    """
    inv, changed = inventory.rescan(repo_root, storage, state["inventory"])
    ext = extraction.extract_repo(inv, storage, repo_root,
                                  previous=state["extraction"])
    touched = sorted(set(changed) | set(tracker.stale_paths()))
    structural = structural_change(state["extraction"], ext, touched)
    sem = semantic.build(
        ext, storage, repo_root, store,
        previous_architecture=state["semantic"]["architecture"],
        structural_changed=structural)
    tracker.drop(p for p in state["inventory"] if p not in inv)
    tracker.mark_fresh(sorted(inv))  # every surviving region just reindexed
    persistence.save_index(storage, repo_id, inv, tracker.snapshot())
    store.save(storage, repo_id)
    events.emit(out_bus, "index.updated", repo_id,
                {"paths": touched, "structural": structural})
    return {"inventory": inv, "extraction": ext, "semantic": sem}


if __name__ == "__main__":
    import os
    import tempfile

    from .events import BusDouble
    from .freshness import FreshnessTracker
    from .storage_double import StorageDouble
    from .summary_store import SummaryStore

    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in (("a.py", b'"""A."""\nimport os\n'),
                             ("b.py", b'"""B."""\nX = 1\n')):
            with open(os.path.join(tmp, rel), "wb") as handle:
                handle.write(content)
        root = tmp.replace(os.sep, "/")
        storage, bus, out_bus = StorageDouble(), BusDouble(), BusDouble()
        tracker, store = FreshnessTracker(), SummaryStore()

        inv = inventory.scan(root, storage)
        ext = extraction.extract_repo(inv, storage, root)
        sem = semantic.build(ext, storage, root, store)
        tracker.track_fresh(inv)
        state = {"inventory": inv, "extraction": ext, "semantic": sem}

        # no events -> no work, no publications
        assert consume_changes(bus, "r1", tracker, out_bus) == []
        assert out_bus.messages("index.stale") == []

        # comment-only change: stale -> reindex -> fresh, NOT structural
        with open(os.path.join(tmp, "b.py"), "wb") as handle:
            handle.write(b'"""B."""\nX = 1  # tweaked comment\n')
        bus.publish("write.committed",
                    {"repo_id": "r1", "payload": {"paths": ["b.py"]}})
        assert consume_changes(bus, "r1", tracker, out_bus) == ["b.py"]
        assert not tracker.is_fresh("b.py") and tracker.is_fresh("a.py")
        assert out_bus.messages("index.stale")[0]["payload"]["paths"] == ["b.py"]

        state2 = reindex("r1", root, storage, out_bus, tracker, store, state)
        assert tracker.is_fresh("b.py")
        updated = out_bus.messages("index.updated")[0]["payload"]
        assert updated["paths"] == ["b.py"] and updated["structural"] is False
        # cascade precision: untouched file record reused by identity;
        # architecture reused verbatim (no structural change)
        assert state2["extraction"]["files"]["a.py"] is ext["files"]["a.py"]
        assert state2["semantic"]["architecture"] is sem["architecture"]

        # structural change: new symbol -> architecture rebuilt
        with open(os.path.join(tmp, "b.py"), "wb") as handle:
            handle.write(b'"""B."""\n\n\ndef main():\n    pass\n')
        bus.publish("commit.created",
                    {"repo_id": "r1", "payload": {"paths": ["b.py"]}})
        consume_changes(bus, "r1", tracker, out_bus)
        state3 = reindex("r1", root, storage, out_bus, tracker, store, state2)
        assert out_bus.messages("index.updated")[1]["payload"]["structural"] is True
        assert state3["semantic"]["architecture"] is not sem["architecture"]
        assert "b.py" in state3["semantic"]["architecture"]["entrypoints"]

        # persisted freshness survives "crash": reload sees fresh states
        loaded_inv, loaded_fresh = persistence.load_index(storage, "r1")
        assert loaded_fresh["b.py"] == "fresh"
    print("updates selftest ok")
