"""B9 / ERRATA C10 configuration-ownership conformance.

Config decomposes into schema / defaults / authored instance + activation /
effective view (ERRATA C10). Guards:

  1. Schema namespaces are disjoint: across every component config_view,
     the only shared key is "version" — a key two components need must be
     authored once and delivered through activation, never declared twice.
  2. Validation is pure: kernel validate() never mutates its input and a
     rejected snapshot leaves the caller's last-good view untouched.
  3. Defaults are not authority: default_config.snapshot() hands out
     independent deep copies — mutating one changes no future snapshot.
"""
import copy
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

REPO = Path(__file__).resolve().parent.parent
_VIEW_MODULES = ("kernel.config_view", "cm.config_view", "prt.config_view",
                 "ro.config_view", "rsm.config_view")


def _keys_of(module_name):
    mod = importlib.import_module(module_name)
    keys = set(getattr(mod, "REQUIRED_KEYS", {}) or {})
    keys |= set(getattr(mod, "OPTIONAL_KEYS", {}) or {})
    return keys


def test_config_schema_namespaces_are_disjoint():
    seen = {}
    offenders = []
    for name in _VIEW_MODULES:
        for key in _keys_of(name):
            if key == "version":
                continue  # the one deliberately shared key
            if key in seen:
                offenders.append("%r declared by both %s and %s" % (key, seen[key], name))
            seen[key] = name
    assert offenders == [], (
        "config keys are single-schema; shared values go through activation "
        "(ERRATA C10): %s" % offenders)


def test_kernel_validation_is_pure():
    from kernel import config_view
    from kernel.default_config import snapshot

    good = snapshot()
    before = copy.deepcopy(good)
    ok, reason = config_view.validate(good)
    assert ok, reason
    assert good == before, "validate() must never mutate its input (ERRATA C10)"

    bad = snapshot()
    del bad["gates"]
    ok, _ = config_view.validate(bad)
    assert not ok, "missing required key must be rejected (fail closed)"


def test_defaults_are_not_authority():
    from kernel.default_config import snapshot

    first = snapshot()
    first["fault_policy"]["max_replans"] = 999999
    second = snapshot()
    assert second["fault_policy"]["max_replans"] != 999999, (
        "snapshot() must deep-copy; defaults can never be mutated into "
        "shared authority (ERRATA C10)")
