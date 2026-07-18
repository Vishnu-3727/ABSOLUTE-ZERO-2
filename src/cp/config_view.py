"""CP policy as data (kernel I13/I14 pattern; ERRATA C10 — CP owns its own
disjoint config namespace). Read-only, versioned; validate() is pure.
"""
REQUIRED_KEYS = {
    "version": int,
    "confidence_bands": dict,       # band name -> [low, high)
    "disposition_thresholds": dict, # publish / publish_with_fallbacks / reject
    "expansion_depth_cap": int,     # CP/02 §5 fixpoint bound
    "gate_names": list,             # the 10 validation gates, CP/02 §10
}
OPTIONAL_KEYS = {}


def validate(data):
    if not isinstance(data, dict):
        return False, "cp.config.not_mapping"
    for key, kind in REQUIRED_KEYS.items():
        if key not in data:
            return False, "cp.config.missing:" + key
        if not isinstance(data[key], kind):
            return False, "cp.config.bad_type:" + key
    if data["expansion_depth_cap"] <= 0:
        return False, "cp.config.bad_depth_cap"
    return True, ""


class ConfigView:
    def __init__(self, data):
        ok, reason = validate(data)
        if not ok:
            raise ValueError(reason)
        self.version = data["version"]
        self.confidence_bands = dict(data["confidence_bands"])
        self.disposition_thresholds = dict(data["disposition_thresholds"])
        self.expansion_depth_cap = data["expansion_depth_cap"]
        self.gate_names = tuple(data["gate_names"])


def default_config():
    return {"version": 1,
            "confidence_bands": {"high": [0.8, 1.01], "medium": [0.5, 0.8],
                                 "low": [0.0, 0.5]},
            "disposition_thresholds": {"publish": 0.8,
                                       "publish_with_fallbacks": 0.5,
                                       "reject_for_clarification": 0.0},
            "expansion_depth_cap": 16,
            "gate_names": ["acyclicity", "coverage", "dedup", "edge_fidelity",
                           "constraint_integrity", "band_assignment",
                           "gap_typing", "confidence_traceability",
                           "lineage", "immutability"]}


if __name__ == "__main__":
    import copy
    data = default_config()
    before = copy.deepcopy(data)
    view = ConfigView(data)
    assert data == before and view.expansion_depth_cap == 16  # validate pure
    bad = default_config()
    del bad["gate_names"]
    assert validate(bad) == (False, "cp.config.missing:gate_names")
    print("config_view selftest ok")
