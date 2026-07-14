"""PRT policy as data (kernel I13/I14 pattern; cm/config_view.py,
ums equivalents). Read-only, versioned snapshot.

Phase 1 needed nothing beyond a version stamp. Phase 3 (PRT/03 §5-§6) adds
exactly one optional key: `admin_barred` — the administrative load-bar list
availability.py's ladder and load_policy.LoadPolicyView read (an
administrative act, config-data this phase; the real operator-act mechanics
are PRT/04 §7 territory). Quarantine thresholds and other Phase 4 config
remain un-invented here — still no reader for them.

# ponytail: thinnest possible view — one required key (`version`), one
# optional key (`admin_barred`). Upgrade path: Phase 4 adds its own keys to
# OPTIONAL_KEYS + ConfigView properties when it has an actual reader,
# following this same validate()/ConfigView shape.
"""

REQUIRED_KEYS = {
    "version": int,
}

OPTIONAL_KEYS = {
    "admin_barred": tuple,
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
        raise AttributeError("ConfigView is read-only (I14)")

    @property
    def version(self):
        return self._data["version"]

    @property
    def admin_barred(self):
        return self._data.get("admin_barred", ())


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

    # admin_barred: optional, additive (PRT/03 §5-§6)
    barred = ConfigView({"version": 1, "admin_barred": ("prov.bad",)})
    assert barred.admin_barred == ("prov.bad",)
    assert ConfigView(DEFAULT).admin_barred == ()  # absent key -> empty, not an error
    bad3 = {"version": 1, "admin_barred": ["not", "a", "tuple"]}
    assert validate(bad3) == (False, "config.bad_type:admin_barred")

    print("config_view selftest ok")
