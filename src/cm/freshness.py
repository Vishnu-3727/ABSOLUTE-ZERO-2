"""Freshness (blueprint Phase 5): consumes `index.updated{"paths":[...]}` --
the sole invalidation trigger (blueprint "Event-name canon"; CM never
watches a clock, CM-I2/Law 6 determinism forbids wall-clock-driven
behaviour) -- and invalidates ONLY the cached artifacts whose items trace
back to a changed path, emitting one `context.invalidated` per invalidated
artifact. Unrelated cache entries are never touched.

Also carries the "on next demand, incremental rebuild of affected sections
only; result must equal full rebuild" half of the update flow
(blueprint Data flow). `affected_sections()` names which of the closed
SECTION_NAMES sections held an item touching the change set -- reporting
metadata for the invalidation record / observability, not a separate code
path: `rebuild()` always re-runs the one pure `Assembler.assemble()`
pipeline (the same function a full rebuild calls), so incremental and full
rebuild are byte-identical by construction (CM-I2) rather than by proof
about a second, divergent implementation.
# ponytail: budgeter.fit()'s global ceiling is accounted across ALL
# sections in priority order (budgeter.py), so a section's fitted content
# is not independent of what happened in every other section first --
# genuinely re-running only the "affected" slice of the pipeline can't be
# proven to reproduce the shared-global-ceiling interaction without
# redoing that computation anyway, i.e. without calling assemble() on the
# full candidate list. Upgrade path: only worth it if budgeter grows
# section-independent envelopes with no shared global remainder, or if
# profiling shows assemble() itself (not upstream candidate gathering) is
# the incremental-rebuild cost driver.
"""
from . import events
from .request_memory import SECTION_NAMES


def _item_paths(item):
    """Repo path(s) an item's provenance traces back to, if any.

    UMS-origin items (sources.py UmsAdapter) don't carry an explicit
    provenance["path"] -- the id encodes it ("sym:<path>:<name>" /
    "file:<path>") -- so it is recovered from there. RSM and reference
    items have no repo-path provenance and never invalidate on
    `index.updated` (CM-I5 staleness is a UMS-only concept; RSM/reference
    items already carry stale=None for the same reason, sources.py).
    # ponytail: id-parsing instead of a stamped provenance["path"] field --
    # sources.py (Phase 2, already shipped) doesn't stamp one. Upgrade
    # path: have sources.py's UmsAdapter add provenance["path"] = hit["path"]
    # directly and switch this to read it; nothing else here changes.
    """
    provenance = item.get("provenance") or {}
    if "path" in provenance:
        return (provenance["path"],)
    if provenance.get("source") != "ums":
        return ()
    item_id = item.get("id", "")
    if item_id.startswith("sym:"):
        rest = item_id[len("sym:"):]
        path, _, _ = rest.rpartition(":")
        return (path,) if path else ()
    if item_id.startswith("file:"):
        rest = item_id[len("file:"):]
        return (rest,) if rest else ()
    return ()


def artifact_paths(rm):
    """All repo paths a Request Memory artifact's items trace back to."""
    paths = set()
    for items in rm.sections.values():
        for item in items:
            paths.update(_item_paths(item))
    return paths


def affected_sections(rm, changed_paths):
    """Which closed sections (SECTION_NAMES) hold at least one item whose
    provenance overlaps `changed_paths` -- section-scoped rebuild target
    set (reporting metadata, see module docstring)."""
    changed = set(changed_paths)
    affected = set()
    for name in SECTION_NAMES:
        for item in rm.sections[name]:
            if set(_item_paths(item)) & changed:
                affected.add(name)
                break
    return affected


def on_index_updated(cache, bus, payload):
    """Handle one `index.updated` payload: invalidate every cached
    artifact whose provenance paths overlap `payload["paths"]`, emit
    `context.invalidated` per invalidated artifact (blueprint Phase 5
    "Data produced": invalidation records). Returns the list of
    invalidated cache keys. No-op on an empty/missing path list."""
    changed = set(payload.get("paths") or ())
    if not changed:
        return []
    invalidated_keys = []
    for cache_key in cache.keys():
        rm = cache.peek(cache_key)
        if rm is None or cache.is_invalidated(cache_key):
            continue  # already gone / already invalidated -- idempotent
        if set(artifact_paths(rm)) & changed:
            cache.invalidate(cache_key)
            invalidated_keys.append(cache_key)
            events.emit(bus, "context.invalidated", rm.request_id, {
                "request_id": rm.request_id, "memory_id": rm.memory_id,
                "spec_hash": rm.spec_hash,
                "affected_sections": tuple(sorted(affected_sections(rm, changed))),
            })
    return invalidated_keys


def get_or_assemble(cache, cache_key, assembler, spec, candidates, config, bus):
    """Cache-first assembly: a hit returns the cached artifact without
    re-running the pipeline (repeated identical requests avoid rework); a
    miss or an invalidated entry re-assembles and re-caches. Returns
    (artifact, assembled: bool) -- assembled is False on a cache hit, so
    callers/tests can assert the pipeline was not re-run."""
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, False
    rm = assembler.assemble(spec, candidates, config, bus)
    cache.put(cache_key, rm)
    return rm, True


def rebuild(cache, cache_key, assembler, spec, candidates, config, bus):
    """Rebuild after invalidation and re-cache. Always the full pipeline
    (see module docstring ponytail note) so it is byte-identical to any
    other full rebuild of the same (spec, candidates, config) -- the
    equivalence property CM-I2/Law 6 requires."""
    rm = assembler.assemble(spec, candidates, config, bus)
    cache.put(cache_key, rm)
    return rm


if __name__ == "__main__":
    from . import cache as cache_mod
    from .assembler import Assembler
    from .bus_double import BusDouble
    from .config_view import ConfigView, DEFAULT
    from .request_memory import content_hash
    from .spec import build as build_spec, spec_hash as compute_spec_hash

    config = ConfigView(DEFAULT)

    def cand(cid, section, path, score=1.0):
        return {"id": cid, "section": section, "score": score, "stale": False,
                "provenance": {"source": "ums", "store": "symbol" if section == "symbols" else "file"},
                "content": {"full": "f " * 5, "section": "s " * 3, "reference": "r"}}

    # UMS-shaped ids: "sym:<path>:<name>" / "file:<path>" so _item_paths recovers them
    c_sym = cand("sym:core.py:add", "symbols", "core.py")
    c_file = cand("file:util.py", "files", "util.py")
    candidates = [c_sym, c_file]

    spec = build_spec("r1", "do the thing", 1000)
    spec_h = compute_spec_hash(spec)
    k = cache_mod.key("r1", spec_h)

    # -- artifact_paths / affected_sections -------------------------------
    bus = BusDouble()
    asm = Assembler()
    rm = asm.assemble(spec, candidates, config, bus)
    assert artifact_paths(rm) == {"core.py", "util.py"}
    assert affected_sections(rm, ["core.py"]) == {"symbols"}
    assert affected_sections(rm, ["nope.py"]) == set()
    assert affected_sections(rm, ["core.py", "util.py"]) == {"symbols", "files"}

    # -- cache-hit avoids rework -------------------------------------------
    cache = cache_mod.Cache()
    bus2 = BusDouble()
    asm2 = Assembler()
    rm1, assembled1 = get_or_assemble(cache, k, asm2, spec, candidates, config, bus2)
    assert assembled1 is True
    rm2, assembled2 = get_or_assemble(cache, k, asm2, spec, candidates, config, bus2)
    assert assembled2 is False  # cache hit, pipeline not re-run
    assert rm1 is rm2  # identical artifact object served, not rebuilt
    assert content_hash(rm1) == content_hash(rm2)

    # -- invalidation on index.updated: overlapping path -------------------
    unrelated_spec = build_spec("r2", "unrelated", 1000)
    unrelated_h = compute_spec_hash(unrelated_spec)
    k_unrelated = cache_mod.key("r2", unrelated_h)
    only_util = [cand("file:only.py", "files", "only.py")]
    rm_unrelated, _ = get_or_assemble(cache, k_unrelated, Assembler(), unrelated_spec,
                                       only_util, config, bus2)

    invalidated = on_index_updated(cache, bus2, {"paths": ["core.py"]})
    assert invalidated == [k]
    assert cache.get(k) is None  # stale never served
    assert cache.get(k_unrelated) is rm_unrelated  # unrelated entry untouched
    events_seen = bus2.messages("context.invalidated")
    assert len(events_seen) == 1
    assert events_seen[0]["payload"]["request_id"] == "r1"
    assert events_seen[0]["payload"]["affected_sections"] == ("symbols",)

    # replaying the same index.updated is a safe no-op (idempotent)
    assert on_index_updated(cache, bus2, {"paths": ["core.py"]}) == []
    assert len(bus2.messages("context.invalidated")) == 1  # no duplicate event

    # no paths -> no-op
    assert on_index_updated(cache, bus2, {"paths": []}) == []
    assert on_index_updated(cache, bus2, {}) == []

    # -- rebuild after invalidation == full rebuild, byte-identical --------
    full_rebuild = Assembler().assemble(spec, candidates, config, BusDouble())
    incremental = rebuild(cache, k, Assembler(), spec, candidates, config, bus2)
    assert content_hash(incremental) == content_hash(full_rebuild)
    assert cache.get(k) is incremental  # re-cached, fresh again

    # repeated unchanged request after rebuild avoids rework again
    _, assembled3 = get_or_assemble(cache, k, Assembler(), spec, candidates, config, bus2)
    assert assembled3 is False

    print("freshness selftest ok")
