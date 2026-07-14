"""PRT policy as data (kernel I13/I14 pattern; cm/config_view.py,
ums equivalents). Read-only, versioned snapshot.

Phase 1 needs nothing beyond a version stamp: the registry model (PRT/01)
has no tunable policy knob yet — no budgets, no thresholds, no weights.
Binding tie-break policy (PRT/00 §4), quarantine thresholds (PRT/04), and
load/isolation policy defaults are later-phase config; inventing keys for
them now would be speculative content this module has no reader for.

# ponytail: thinnest possible view — one required key (`version`) and
# nothing else. Upgrade path: Phase 3/4 add their own keys to
# REQUIRED_KEYS + ConfigView properties when they have an actual reader,
# following this same validate()/ConfigView shape.
"""

REQUIRED_KEYS = {
    "version": int,
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


DEFAULT = {"version": 1}


if __name__ == "__main__":
    assert validate(DEFAULT) == (True, "")
    view = ConfigView(DEFAULT)
    assert view.version == 1
    try:
        view.version = 2
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass

    bad = dict(DEFAULT)
    del bad["version"]
    assert validate(bad) == (False, "config.missing:version")

    bad2 = {"version": "not an int"}
    assert validate(bad2) == (False, "config.bad_type:version")

    print("config_view selftest ok")
