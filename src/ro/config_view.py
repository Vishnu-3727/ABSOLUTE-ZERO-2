"""RO policy as data (prt/config_view.py pattern). Read-only, versioned
snapshot. Band vocabularies (CATEGORIES, RELATIONSHIP_KINDS, characteristic
bands, descriptor-row classes) are architecture constants declared in
records.py, NOT config — they never belong here.

Phase 1 needs nothing beyond a version stamp: no policy question this
phase's scope (RO/01 + RO/03 §3) is config-driven. Later phases (necessity
policy, budget/timeout policy, priors versions) add their own keys the same
way prt/config_view.py's Phase 3/4 additions did, without touching this
shape.

# ponytail: thinnest possible view, one required key. Upgrade path: add
# keys to REQUIRED_KEYS/OPTIONAL_KEYS + ConfigView properties when a later
# phase has an actual reader for them.
"""

REQUIRED_KEYS = {
    "version": int,
}

OPTIONAL_KEYS = {}


def validate(data):
    """Return (ok, reason). Pure structural check, no judgment."""
    if not isinstance(data, dict):
        return False, "config.not_mapping"
    for key, typ in REQUIRED_KEYS.items():
        if key not in data:
            return False, "config.missing:" + key
        if not isinstance(data[key], typ):
            return False, "config.bad_type:" + key
    for key, typ in OPTIONAL_KEYS.items():
        if key in data and not isinstance(data[key], typ):
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
        raise AttributeError("ConfigView is read-only")

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
