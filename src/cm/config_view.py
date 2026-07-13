"""CM policy as data (kernel I13/I14 pattern, kernel/config_view.py).

Default budgets, section weights, resolver depth caps live here as a
read-only, versioned snapshot — never as scattered constants or
judgment calls in the pipeline modules built in later phases. Structural
validate() only; no policy content is invented by CM itself (CM-I8: CM
does not compile prompts or decide policy, it applies it).
"""
from .request_memory import SECTION_NAMES

REQUIRED_KEYS = {
    "version": int,
    "default_budget_tokens": int,   # CM-I1: hard ceiling default
    "section_weights": dict,        # section name -> relative weight (int/float)
    "resolver_depth_cap": int,      # Phase 3 BFS depth cap, fixed here as policy
}


def validate(data):
    """Return (ok, reason). Pure structural check, no judgment."""
    if not isinstance(data, dict):
        return False, "config.not_mapping"
    for key, typ in REQUIRED_KEYS.items():
        if key not in data:
            return False, "config.missing:" + key
        if not isinstance(data[key], typ):
            return False, "config.bad_type:" + key
    if data["default_budget_tokens"] < 0:
        return False, "config.bad_default_budget_tokens"
    if data["resolver_depth_cap"] < 0:
        return False, "config.bad_resolver_depth_cap"
    weights = data["section_weights"]
    bad_sections = set(weights) - set(SECTION_NAMES)
    if bad_sections:
        return False, "config.unknown_section:" + ",".join(sorted(bad_sections))
    for section, weight in weights.items():
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
            return False, "config.bad_weight:" + section
    return True, ""


class ConfigView:
    """Read-only snapshot. Callers never mutate; a new version replaces it."""

    __slots__ = ("_data",)

    def __init__(self, data):
        ok, reason = validate(data)
        if not ok:
            raise ValueError(reason)
        object.__setattr__(self, "_data", data)

    def __setattr__(self, name, value):
        raise AttributeError("ConfigView is read-only (I14)")

    @property
    def version(self):
        return self._data["version"]

    @property
    def default_budget_tokens(self):
        return self._data["default_budget_tokens"]

    @property
    def section_weights(self):
        return self._data["section_weights"]

    @property
    def resolver_depth_cap(self):
        return self._data["resolver_depth_cap"]

    def weight_of(self, section):
        """Weight lookup; 0 when the section carries no configured weight."""
        return self._data["section_weights"].get(section, 0)


DEFAULT = {
    "version": 1,
    "default_budget_tokens": 8000,
    "section_weights": {
        "symbols": 3,
        "files": 3,
        "dependency_graph": 2,
        "knowledge": 1,
        "experience": 1,
    },
    "resolver_depth_cap": 3,
}


if __name__ == "__main__":
    assert validate(DEFAULT) == (True, "")
    view = ConfigView(DEFAULT)
    assert view.version == 1
    assert view.default_budget_tokens == 8000
    assert view.weight_of("symbols") == 3
    assert view.weight_of("not_a_section") == 0
    try:
        view.version = 2
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass

    bad = dict(DEFAULT)
    del bad["resolver_depth_cap"]
    assert validate(bad) == (False, "config.missing:resolver_depth_cap")

    bad2 = dict(DEFAULT, default_budget_tokens=-1)
    assert validate(bad2) == (False, "config.bad_default_budget_tokens")

    bad3 = dict(DEFAULT, section_weights={"not_a_section": 1})
    assert validate(bad3)[0] is False

    bad4 = dict(DEFAULT, section_weights={"symbols": -1})
    assert validate(bad4) == (False, "config.bad_weight:symbols")
    print("config_view selftest ok")
