"""Workflow compiler — sealed Capability Graph -> immutable Execution
Workflow artifact (WS/01, invariants WS-W1..W12; WS/00 constraints C1-C4).

Input: the sealed graph as data (CP/02's artifact, consumed as-is — C1):

    {"plan_artifact_id": str, "plan_version": int,
     "nodes": [{"node_id", "capability_id",
                "priority_band" in {"CRITICAL","REQUIRED","OPTIONAL","DEFERRED"},
                optional "group_id", optional "rank" (int, CP ranking)}],
     "requires_edges": [[producer_node_id, consumer_node_id], ...]}

Output: a frozen Workflow — 1:1 execution units (WS-W2/W3), edges carried
verbatim (WS-W4), canonical total order (deterministic Kahn, unit-id
tie-break, WS-W6), derived level views, per-unit gate markers (uniform
per-unit verification, WS/02 §10c), alternative groups carried unresolved
with CP ranking intact (WS-W8), zero provider ids (WS-W11), zero runtime
state (WS-W12). Identical sealed graph + ws_config_version -> identical
artifact and identical content hash (WS-W5).

Fail closed: any structural violation raises WorkflowRejected — a rejected
workflow is never published (WS/01 §7 "no third outcome").
"""
import hashlib
import json
from types import MappingProxyType

BANDS = ("CRITICAL", "REQUIRED", "OPTIONAL", "DEFERRED")


class WorkflowRejected(Exception):
    """Structural gate failure — the artifact is never published."""


class Workflow:
    """Immutable compiled artifact. All fields frozen at construction."""

    def __init__(self, workflow_id, provenance, units, edges, canonical_order,
                 levels, groups, content_hash):
        self.workflow_id = workflow_id
        self.provenance = MappingProxyType(dict(provenance))
        self.units = MappingProxyType({uid: MappingProxyType(dict(u))
                                       for uid, u in units.items()})
        self.edges = tuple(tuple(e) for e in edges)
        self.canonical_order = tuple(canonical_order)
        self.levels = tuple(tuple(level) for level in levels)
        self.groups = MappingProxyType({g: tuple(members)
                                        for g, members in groups.items()})
        self.content_hash = content_hash

    def predecessors(self, unit_id):
        return tuple(sorted(p for p, c in self.edges if c == unit_id))

    def successors(self, unit_id):
        return tuple(sorted(c for p, c in self.edges if p == unit_id))


def _unit_id(workflow_id, node_id):
    # deterministic derivation (WS/01 §5, CM memory_id precedent)
    return "u-" + hashlib.sha256(
        (workflow_id + ":" + node_id).encode()).hexdigest()[:16]


def compile_workflow(sealed_graph, ws_config_version):
    if not isinstance(sealed_graph, dict):
        raise WorkflowRejected("ws.graph_not_mapping")
    plan_id = sealed_graph.get("plan_artifact_id")
    plan_version = sealed_graph.get("plan_version")
    nodes = sealed_graph.get("nodes")
    edges = sealed_graph.get("requires_edges", [])
    if not isinstance(plan_id, str) or not plan_id or not isinstance(plan_version, int):
        raise WorkflowRejected("ws.bad_provenance")
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowRejected("ws.no_nodes")

    # workflow identity = pure function of the determinism tuple (WS/01 §1)
    workflow_id = "wf-" + hashlib.sha256(
        ("%s:%d:%d" % (plan_id, plan_version, ws_config_version)).encode()
    ).hexdigest()[:16]

    units = {}
    by_node = {}
    groups = {}
    for node in sorted(nodes, key=lambda n: str(n.get("node_id"))):
        node_id = node.get("node_id")
        capability_id = node.get("capability_id")
        band = node.get("priority_band")
        if not isinstance(node_id, str) or not node_id or node_id in by_node:
            raise WorkflowRejected("ws.bad_or_duplicate_node:" + repr(node_id))
        if not isinstance(capability_id, str) or not capability_id:
            raise WorkflowRejected("ws.bad_capability:" + node_id)
        if band not in BANDS:
            raise WorkflowRejected("ws.bad_band:%s:%r" % (node_id, band))
        for key in node:
            if "plugin" in key or "provider" in key:  # WS-W11 late binding
                raise WorkflowRejected("ws.provider_id_in_graph:" + node_id)
        uid = _unit_id(workflow_id, node_id)
        unit = {"unit_id": uid, "node_id": node_id,
                "capability_id": capability_id, "priority_band": band,
                "gate_required": True}  # per-unit verification default (WS/02 §10c)
        if node.get("group_id") is not None:
            unit["group_id"] = str(node["group_id"])
            rank = node.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise WorkflowRejected("ws.group_without_rank:" + node_id)
            unit["rank"] = rank
            groups.setdefault(unit["group_id"], []).append(uid)
        units[uid] = unit
        by_node[node_id] = uid

    unit_edges = []
    seen_edges = set()
    for edge in edges:
        if (not isinstance(edge, (list, tuple)) or len(edge) != 2
                or edge[0] not in by_node or edge[1] not in by_node):
            raise WorkflowRejected("ws.bad_edge:" + repr(edge))  # WS-W4
        pair = (by_node[edge[0]], by_node[edge[1]])
        if pair in seen_edges or pair[0] == pair[1]:
            raise WorkflowRejected("ws.duplicate_or_self_edge:" + repr(edge))
        seen_edges.add(pair)
        unit_edges.append(pair)
    unit_edges.sort()

    # deterministic Kahn: canonical total order + derived levels (WS-W1/W6)
    incoming = {uid: set() for uid in units}
    for producer, consumer in unit_edges:
        incoming[consumer].add(producer)
    remaining = dict(incoming)
    order, levels = [], []
    while remaining:
        frontier = sorted(uid for uid, deps in remaining.items() if not deps)
        if not frontier:
            raise WorkflowRejected("ws.cycle_detected")  # WS-W1
        levels.append(frontier)
        for uid in frontier:
            order.append(uid)
            del remaining[uid]
        for deps in remaining.values():
            deps.difference_update(frontier)

    for members in groups.values():  # CP ranking intact, sorted for determinism
        members.sort(key=lambda uid: (units[uid]["rank"], uid))

    provenance = {"plan_artifact_id": plan_id, "plan_version": plan_version,
                  "ws_config_version": ws_config_version}
    canonical = json.dumps(
        {"workflow_id": workflow_id, "provenance": provenance,
         "units": {uid: units[uid] for uid in sorted(units)},
         "edges": unit_edges, "canonical_order": order, "levels": levels,
         "groups": {g: groups[g] for g in sorted(groups)}},
        sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return Workflow(workflow_id, provenance, units, unit_edges, order,
                    levels, groups, content_hash)


if __name__ == "__main__":
    graph = {"plan_artifact_id": "plan-1", "plan_version": 1,
             "nodes": [
                 {"node_id": "n1", "capability_id": "cap.read", "priority_band": "CRITICAL"},
                 {"node_id": "n2", "capability_id": "cap.build", "priority_band": "REQUIRED"},
                 {"node_id": "n3", "capability_id": "cap.lint", "priority_band": "OPTIONAL"},
             ],
             "requires_edges": [["n1", "n2"], ["n1", "n3"]]}
    a = compile_workflow(graph, 1)
    b = compile_workflow(json.loads(json.dumps(graph)), 1)
    assert a.content_hash == b.content_hash and a.workflow_id == b.workflow_id  # WS-W5
    assert len(a.units) == 3 and len(a.edges) == 2  # WS-W2/W4
    assert len(a.levels) == 2 and len(a.levels[1]) == 2  # derived parallelism view
    assert compile_workflow(graph, 2).workflow_id != a.workflow_id  # config in tuple
    try:
        a.units[a.canonical_order[0]]["priority_band"] = "DEFERRED"
        raise SystemExit("artifact mutated")
    except TypeError:
        pass  # WS-W10 immutable
    bad = dict(graph)
    bad["requires_edges"] = [["n1", "n2"], ["n2", "n1"]]
    try:
        compile_workflow(bad, 1)
        raise SystemExit("cycle accepted")
    except WorkflowRejected:
        pass  # WS-W1
    print("compiler selftest ok")
