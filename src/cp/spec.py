"""CP planning spec — intake normalization (CP/05 foundation; CP-IMPL 12).

Everything influencing a plan arrives HERE, injected by the caller —
request identity, intent text, goals, request-level constraints, the
Request Memory hash + content, an RSM state snapshot, and the three
versions (registry/priors/config). The spec canonicalizes and hashes them
order-independently; nothing in CP ever fetches (knowledge gateway,
CP/03 §4). Malformed input raises at intake — nothing enters the pipeline.
"""
import hashlib
import json
from types import MappingProxyType


class SpecRefusal(Exception):
    """Malformed planning inputs — refused at intake."""


class PlanningSpec:
    def __init__(self, fields, spec_hash):
        self._fields = MappingProxyType(dict(fields))
        self.spec_hash = spec_hash

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name)

    def determinism_tuple(self):
        return {"request_id": self.request_id,
                "registry_version": self.registry_version,
                "priors_version": self.priors_version,
                "request_memory_hash": self.request_memory_hash,
                "config_version": self.config_version}


def build_spec(request_id, intent, goals, constraints, request_memory_hash,
               request_memory, rsm_snapshot, registry_version, priors_version,
               config_version):
    if not isinstance(request_id, str) or not request_id:
        raise SpecRefusal("cp.spec.bad_request_id:" + repr(request_id))
    if not isinstance(intent, str) or not intent.strip():
        raise SpecRefusal("cp.spec.bad_intent")
    for label, seq in (("goals", goals), ("constraints", constraints)):
        if not isinstance(seq, (list, tuple)) \
                or not all(isinstance(x, str) and x for x in seq):
            raise SpecRefusal("cp.spec.bad_" + label)
    if not isinstance(request_memory_hash, str) or not request_memory_hash:
        raise SpecRefusal("cp.spec.bad_request_memory_hash")
    for label, version in (("registry", registry_version),
                           ("priors", priors_version),
                           ("config", config_version)):
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise SpecRefusal("cp.spec.bad_%s_version:%r" % (label, version))
    fields = {"request_id": request_id, "intent": intent.strip(),
              "goals": tuple(sorted(goals)),          # order-independence
              "constraints": tuple(sorted(constraints)),
              "request_memory_hash": request_memory_hash,
              "request_memory": request_memory,
              "rsm_snapshot": rsm_snapshot,
              "registry_version": registry_version,
              "priors_version": priors_version,
              "config_version": config_version}
    hashable = {k: v for k, v in fields.items()
                if k not in ("request_memory", "rsm_snapshot")}
    hashable["request_memory"] = request_memory_hash  # content by hash only
    spec_hash = hashlib.sha256(
        json.dumps(hashable, sort_keys=True, separators=(",", ":"),
                   default=list).encode()).hexdigest()
    return PlanningSpec(fields, spec_hash)


if __name__ == "__main__":
    a = build_spec("r1", "fix the bug", ["repair"], ["no-network", "fast"],
                   "rmh", {"hits": []}, {"state": "planned"}, 3, 1, 1)
    b = build_spec("r1", "  fix the bug ", ["repair"], ["fast", "no-network"],
                   "rmh", {"hits": ["different content, same hash"]},
                   {"state": "other"}, 3, 1, 1)
    assert a.spec_hash == b.spec_hash  # order-independent, content-by-hash
    assert a.determinism_tuple()["registry_version"] == 3
    for bad in (lambda: build_spec("", "x", [], [], "h", {}, {}, 1, 1, 1),
                lambda: build_spec("r", " ", [], [], "h", {}, {}, 1, 1, 1),
                lambda: build_spec("r", "x", [1], [], "h", {}, {}, 1, 1, 1),
                lambda: build_spec("r", "x", [], [], "h", {}, {}, -1, 1, 1)):
        try:
            bad()
            raise SystemExit("bad spec accepted")
        except SpecRefusal:
            pass
    print("spec selftest ok")
