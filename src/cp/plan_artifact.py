"""CP plan artifact — the frozen Capability Graph (CP/05 foundation;
CP/02 artifact inventory; CP/04 §1 determinism tuple; CP-IMPL 2/9).

Nodes: id-or-gap, capability id, origin provenance (explicit/implicit/
derived), situational constraints, priority band, node confidence.
Typed edges: requires / composes / alternative-of / conflicts-with /
serves-goal. Alternative groups with ranks, typed gaps, whole-plan
confidence, the five-part determinism tuple, lineage (predecessor ref),
canonical serialization + content hash. Frozen at construction — revision
is a NEW artifact with lineage, never an edit (CP/02 inv; WS C2).

`to_sealed_graph()` is the WS-facing projection (CP/03: WS consumes the
sealed graph unchanged): requirement nodes + requires-edges only, in
exactly the shape `ws.compiler.compile_workflow` consumes. A projection,
not a second authority — everything in it is derived from this artifact.
"""
import hashlib
import json
from types import MappingProxyType

EDGE_TYPES = ("requires", "composes", "alternative-of", "conflicts-with",
              "serves-goal")
ORIGINS = ("explicit", "implicit", "derived")
BANDS = ("CRITICAL", "REQUIRED", "OPTIONAL", "DEFERRED")
GAP_TYPES = ("unknown-ability", "missing-capability",
             "unsatisfiable-constraint", "ambiguous-mapping")
TUPLE_KEYS = ("request_id", "registry_version", "priors_version",
              "request_memory_hash", "config_version")


class ArtifactRefusal(Exception):
    """Malformed artifact input — nothing partial is ever constructed."""


class PlanArtifact:
    def __init__(self, plan_id, plan_version, determinism, nodes, edges,
                 groups, gaps, confidence, predecessor, content_hash):
        self.plan_id = plan_id
        self.plan_version = plan_version
        self.determinism = MappingProxyType(dict(determinism))
        self.nodes = MappingProxyType({nid: MappingProxyType(dict(n))
                                       for nid, n in nodes.items()})
        self.edges = tuple(tuple(e) for e in edges)
        self.groups = MappingProxyType({g: tuple(m) for g, m in groups.items()})
        self.gaps = tuple(MappingProxyType(dict(g)) for g in gaps)
        self.confidence = confidence
        self.predecessor = predecessor  # (plan_id, plan_version) | None
        self.content_hash = content_hash

    def to_sealed_graph(self):
        """WS-consumed projection: nodes + requires-edges, verbatim ids."""
        nodes = []
        for nid in sorted(self.nodes):
            node = self.nodes[nid]
            out = {"node_id": nid, "capability_id": node["capability_id"],
                   "priority_band": node["priority_band"]}
            if node.get("group_id") is not None:
                out["group_id"] = node["group_id"]
                out["rank"] = node["rank"]
            nodes.append(out)
        return {"plan_artifact_id": self.plan_id,
                "plan_version": self.plan_version,
                "nodes": nodes,
                "requires_edges": [[p, c] for kind, p, c in self.edges
                                   if kind == "requires"]}


def build_artifact(determinism, nodes, edges, groups=None, gaps=(),
                   confidence=None, predecessor=None):
    if (not isinstance(determinism, dict)
            or sorted(determinism) != sorted(TUPLE_KEYS)):
        raise ArtifactRefusal("cp.bad_determinism_tuple:" + repr(determinism))
    if not isinstance(nodes, dict) or not nodes:
        raise ArtifactRefusal("cp.no_nodes")
    clean_nodes = {}
    for nid in sorted(nodes):
        node = nodes[nid]
        if not isinstance(nid, str) or not nid:
            raise ArtifactRefusal("cp.bad_node_id:" + repr(nid))
        if node.get("origin") not in ORIGINS:
            raise ArtifactRefusal("cp.bad_origin:%s:%r" % (nid, node.get("origin")))
        if node.get("priority_band") not in BANDS:
            raise ArtifactRefusal("cp.bad_band:" + nid)
        if not isinstance(node.get("capability_id"), str) or not node["capability_id"]:
            raise ArtifactRefusal("cp.bad_capability:" + nid)
        conf = node.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
            raise ArtifactRefusal("cp.bad_node_confidence:" + nid)
        for key in node:
            if "plugin" in key or "provider" in key:  # CP-IMPL 7
                raise ArtifactRefusal("cp.provider_awareness:" + nid)
        entry = {"capability_id": node["capability_id"], "origin": node["origin"],
                 "priority_band": node["priority_band"], "confidence": conf,
                 "constraints": tuple(node.get("constraints", ()))}
        if node.get("group_id") is not None:
            rank = node.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise ArtifactRefusal("cp.group_without_rank:" + nid)
            entry["group_id"] = str(node["group_id"])
            entry["rank"] = rank
        clean_nodes[nid] = entry
    clean_edges = []
    for edge in edges:
        if (not isinstance(edge, (list, tuple)) or len(edge) != 3
                or edge[0] not in EDGE_TYPES):
            raise ArtifactRefusal("cp.bad_edge:" + repr(edge))
        if edge[1] not in clean_nodes or edge[2] not in clean_nodes:
            raise ArtifactRefusal("cp.dangling_edge:" + repr(edge))
        clean_edges.append((edge[0], edge[1], edge[2]))
    clean_edges.sort()
    groups = groups or {}
    for group_id, members in groups.items():
        for member in members:
            if member not in clean_nodes:
                raise ArtifactRefusal("cp.bad_group_member:%s:%s" % (group_id, member))
    for gap in gaps:
        if not isinstance(gap, dict) or gap.get("gap_type") not in GAP_TYPES:
            raise ArtifactRefusal("cp.bad_gap:" + repr(gap))
    if confidence is None or not isinstance(confidence, (int, float)) \
            or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ArtifactRefusal("cp.bad_plan_confidence:" + repr(confidence))
    plan_version = 1
    pred = None
    if predecessor is not None:
        pred = (str(predecessor[0]), int(predecessor[1]))
        plan_version = pred[1] + 1
    canonical = json.dumps(
        {"determinism": {k: determinism[k] for k in sorted(determinism)},
         "nodes": clean_nodes, "edges": clean_edges,
         "groups": {g: sorted(groups[g]) for g in sorted(groups)},
         "gaps": sorted(json.dumps(dict(g), sort_keys=True) for g in gaps),
         "confidence": confidence, "predecessor": pred,
         "plan_version": plan_version},
        sort_keys=True, separators=(",", ":"), default=tuple)
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    plan_id = "plan-" + content_hash[:16]
    return PlanArtifact(plan_id, plan_version, determinism, clean_nodes,
                        clean_edges, {g: sorted(m) for g, m in groups.items()},
                        [dict(g) for g in gaps], confidence, pred, content_hash)


if __name__ == "__main__":
    det = {"request_id": "r1", "registry_version": 3, "priors_version": 1,
           "request_memory_hash": "abc", "config_version": 1}
    nodes = {"n1": {"capability_id": "cap.read", "origin": "explicit",
                    "priority_band": "CRITICAL", "confidence": 0.9},
             "n2": {"capability_id": "cap.build", "origin": "derived",
                    "priority_band": "REQUIRED", "confidence": 0.8}}
    a = build_artifact(det, nodes, [("requires", "n1", "n2")], confidence=0.85)
    b = build_artifact(dict(det), json.loads(json.dumps(nodes)),
                       [["requires", "n1", "n2"]], confidence=0.85)
    assert a.content_hash == b.content_hash and a.plan_id == b.plan_id
    try:
        a.nodes["n1"]["priority_band"] = "DEFERRED"
        raise SystemExit("artifact mutated")
    except TypeError:
        pass
    revised = build_artifact(det, nodes, [("requires", "n1", "n2")],
                             confidence=0.9, predecessor=(a.plan_id, a.plan_version))
    assert revised.plan_version == 2 and revised.predecessor == (a.plan_id, 1)
    sealed = a.to_sealed_graph()
    assert sealed["requires_edges"] == [["n1", "n2"]]
    assert sealed["plan_artifact_id"] == a.plan_id
    for bad in (lambda: build_artifact({}, nodes, [], confidence=0.5),
                lambda: build_artifact(det, {}, [], confidence=0.5),
                lambda: build_artifact(det, nodes, [("requires", "n1", "nX")],
                                       confidence=0.5),
                lambda: build_artifact(det, {"n1": dict(nodes["n1"],
                                                        provider_id="p")},
                                       [], confidence=0.5)):
        try:
            bad()
            raise SystemExit("bad artifact accepted")
        except ArtifactRefusal:
            pass
    print("plan_artifact selftest ok")
