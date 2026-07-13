"""Per-region freshness — the single staleness authority. Region = file.

States: fresh, stale, rebuild-needed. Never serve stale as fresh: an
untracked region is never fresh (is_fresh -> False), state() of an unknown
region is a loud KeyError, never a default. Recovery path when events may
have been lost (crash, bus outage): sweep() recomputes staleness from a
full inventory hash comparison — freshness is always reconstructible from
inventory, never trapped in lost events.
"""

FRESH = "fresh"
STALE = "stale"
REBUILD_NEEDED = "rebuild-needed"


class FreshnessTracker:
    def __init__(self):
        self._state = {}

    def track_fresh(self, paths):
        for path in paths:
            self._state[path] = FRESH

    def mark_stale(self, paths):
        for path in paths:
            self._state[path] = STALE

    def mark_fresh(self, paths):
        for path in paths:
            self._state[path] = FRESH

    def mark_rebuild_needed(self, paths):
        for path in paths:
            self._state[path] = REBUILD_NEEDED

    def drop(self, paths):
        for path in paths:
            self._state.pop(path, None)

    def state(self, path):
        return self._state[path]  # unknown region = loud, never a default

    def is_fresh(self, path):
        return self._state.get(path) == FRESH

    def stale_paths(self):
        return sorted(p for p, s in self._state.items() if s != FRESH)

    def snapshot(self):
        """Plain dict copy for persistence."""
        return dict(self._state)

    def restore(self, mapping):
        self._state = dict(mapping)

    def sweep(self, old_inventory, new_inventory):
        """Recovery: recompute staleness from a full hash sweep.

        Added or hash-changed regions -> stale; removed -> dropped;
        hash-unchanged regions keep their current state (a pending stale
        mark is never laundered to fresh by a sweep).
        """
        for path, record in new_inventory.items():
            old = old_inventory.get(path)
            if old is None or old.content_hash != record.content_hash:
                self._state[path] = STALE
            elif path not in self._state:
                self._state[path] = FRESH
        self.drop([p for p in old_inventory if p not in new_inventory])


if __name__ == "__main__":
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Rec:  # minimal inventory stand-in: only content_hash is swept
        content_hash: str

    tracker = FreshnessTracker()
    tracker.track_fresh(["a.py", "b.py"])
    assert tracker.is_fresh("a.py") and tracker.stale_paths() == []
    tracker.mark_stale(["b.py"])
    assert not tracker.is_fresh("b.py") and tracker.stale_paths() == ["b.py"]
    tracker.mark_fresh(["b.py"])
    assert tracker.is_fresh("b.py")
    tracker.mark_rebuild_needed(["a.py"])
    assert tracker.state("a.py") == REBUILD_NEEDED and not tracker.is_fresh("a.py")
    assert not tracker.is_fresh("never_seen.py")  # unknown is never fresh
    try:
        tracker.state("never_seen.py")
        raise SystemExit("unknown region state defaulted")
    except KeyError:
        pass

    # round-trip through snapshot/restore
    copy = FreshnessTracker()
    copy.restore(tracker.snapshot())
    assert copy.state("a.py") == REBUILD_NEEDED

    # recovery sweep: changed -> stale, removed -> dropped, pending stale kept
    tracker = FreshnessTracker()
    old = {"a.py": Rec("h1"), "b.py": Rec("h2"), "c.py": Rec("h3")}
    tracker.track_fresh(old)
    tracker.mark_stale(["c.py"])  # pending stale from a lost event
    new = {"a.py": Rec("h1"), "b.py": Rec("hX"), "c.py": Rec("h3"), "d.py": Rec("h4")}
    tracker.sweep(old, new)
    assert tracker.state("a.py") == FRESH
    assert tracker.state("b.py") == STALE
    assert tracker.state("c.py") == STALE  # sweep never launders stale to fresh
    assert tracker.state("d.py") == STALE
    tracker.sweep(new, {"a.py": Rec("h1")})
    assert tracker.stale_paths() == [] and tracker.is_fresh("a.py")
    print("freshness selftest ok")
