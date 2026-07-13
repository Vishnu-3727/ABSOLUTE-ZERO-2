"""Dependency-aware expansion (blueprint Phase 3): seed candidates -> a
bounded-depth BFS over already-obtained UMS dependency records (e.g.
`ums/deps.py` `build_graph()["edges"]`). No retrieval, no UMS calls that
search (Law 2, CM-I3) — this module only walks edges the caller already
gathered and hands in as plain data.

Determinism (CM-I2): the adjacency map is built once, neighbor lists are
sorted, and the frontier at every depth is sorted before it is walked or
recorded — identical (candidates, dependency_records, depth_cap) always
yields an identical expansion and an identical trace, regardless of input
order or set-iteration order.

Cycle safety: a global `visited` set (seeded with every input candidate id)
means a node is only ever added to the frontier once; A -> B -> A terminates
on its own even before the depth cap is hit.

Malformed dependency structures fail loud (kernel I6 pattern: ambiguity is
rejected, not guessed at) rather than being silently skipped.
"""


def expand(candidates, dependency_records, depth_cap):
    """Bounded BFS expansion of `candidates` over `dependency_records`.

    dependency_records: iterable of edges, each `{"src": id, "dst": id, ...}`
    (extra keys such as "kind"/"dep" are ignored — this module only cares
    about the src/dst walk, not the edge's semantic type).
    depth_cap: max hops (CM-I: resolver depth cap from `config_view`).

    Returns (expanded_candidates, trace). `expanded_candidates` is the
    original candidate list, unchanged and in place, followed by newly
    discovered dependency-node stubs in deterministic (depth, id) order —
    original candidates are never reordered or dropped here (that is
    dedup/prioritizer's job in later steps of this phase).
    """
    if not isinstance(dependency_records, (list, tuple)):
        raise ValueError("resolver.bad_dependency_records")
    if isinstance(depth_cap, bool) or not isinstance(depth_cap, int) or depth_cap < 0:
        raise ValueError("resolver.bad_depth_cap")

    adjacency = {}
    for rec in dependency_records:
        if not isinstance(rec, dict) or "src" not in rec or "dst" not in rec:
            raise ValueError("resolver.malformed_record")
        src, dst = rec["src"], rec["dst"]
        if not isinstance(src, str) or not isinstance(dst, str) or not src or not dst:
            raise ValueError("resolver.malformed_record")
        adjacency.setdefault(src, set()).add(dst)
    adjacency = {src: sorted(dsts) for src, dsts in adjacency.items()}

    visited = {c["id"] for c in candidates}
    frontier = sorted(visited)
    new_candidates = []
    frontier_by_depth = []
    depth = 0
    while frontier and depth < depth_cap:
        depth += 1
        next_frontier = set()
        for node in frontier:
            for neighbor in adjacency.get(node, ()):
                if neighbor not in visited:
                    next_frontier.add(neighbor)
        next_frontier = sorted(next_frontier)
        frontier_by_depth.append(next_frontier)
        for nid in next_frontier:
            visited.add(nid)
            new_candidates.append({
                "id": nid,
                "section": "dependency_graph",
                "content": {"full": None, "section": None, "reference": nid},
                "score": 0,
                "stale": None,
                "provenance": {"source": "resolver", "depth": depth},
            })
        frontier = next_frontier

    trace = {
        "depth_cap": depth_cap,
        "depth_reached": len(frontier_by_depth),
        "frontier_by_depth": frontier_by_depth,
        "visited": sorted(visited),
    }
    return list(candidates) + new_candidates, trace


if __name__ == "__main__":
    seeds = [{"id": "file:a.py", "section": "files", "content": {}, "score": 1,
              "stale": False, "provenance": {}}]

    # linear chain a -> b -> c, depth cap 1 stops after one hop
    edges = [{"src": "file:a.py", "dst": "file:b.py", "kind": "imports"},
              {"src": "file:b.py", "dst": "file:c.py", "kind": "imports"}]
    expanded, trace = expand(seeds, edges, 1)
    assert [c["id"] for c in expanded] == ["file:a.py", "file:b.py"]
    assert trace["depth_reached"] == 1

    # full depth reaches c
    expanded2, trace2 = expand(seeds, edges, 5)
    assert [c["id"] for c in expanded2] == ["file:a.py", "file:b.py", "file:c.py"]
    assert trace2["depth_reached"] == 3  # BFS exhausts before cap (last hop finds nothing)

    # depth 0 -> no expansion at all
    expanded0, trace0 = expand(seeds, edges, 0)
    assert [c["id"] for c in expanded0] == ["file:a.py"]
    assert trace0["frontier_by_depth"] == []

    # cycle safety: A -> B -> A terminates instead of looping
    cycle_edges = [{"src": "file:a.py", "dst": "file:b.py"},
                   {"src": "file:b.py", "dst": "file:a.py"}]
    expanded_cycle, trace_cycle = expand(seeds, cycle_edges, 10)
    assert [c["id"] for c in expanded_cycle] == ["file:a.py", "file:b.py"]
    assert trace_cycle["depth_reached"] == 2  # frontier empties after B (A already visited)

    # determinism: identical inputs -> identical graph/order, even shuffled edges
    shuffled = [edges[1], edges[0]]
    expanded3, trace3 = expand(seeds, shuffled, 5)
    assert expanded3 == expanded2
    assert trace3 == trace2

    # malformed dependency structures fail loud
    for bad in ("not-a-list",):
        try:
            expand(seeds, bad, 1)
            raise SystemExit("bad dependency_records accepted")
        except ValueError:
            pass
    for bad_rec in ([{"src": "a"}], [{"dst": "a"}], [{"src": 1, "dst": "b"}], ["not-a-dict"]):
        try:
            expand(seeds, bad_rec, 1)
            raise SystemExit("malformed record accepted")
        except ValueError:
            pass
    try:
        expand(seeds, edges, -1)
        raise SystemExit("negative depth_cap accepted")
    except ValueError:
        pass

    # empty candidate set -> no expansion, no crash
    empty_expanded, empty_trace = expand([], edges, 5)
    assert empty_expanded == []
    assert empty_trace["visited"] == []

    print("resolver selftest ok")
