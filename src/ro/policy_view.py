"""RO/02 §3.1 input 7 — governance policy as data. Read-only versioned view,
mirrors config_view.py's ConfigView shape. Holds only declared permissions
and ceilings (RO-D12): no numeric scoring or threshold ever lives here —
RO/02 forbids scores/thresholds in this architecture entirely.

`permitted_categories` and `permitted_rungs` are declared SUBSETS of
records.py's closed CATEGORIES / COMPLEXITY_RUNGS vocabularies — reused,
never duplicated (RO-C4/RO-C7 stay records.py's authority)."""
from types import MappingProxyType

from .records import CATEGORIES, COMPLEXITY_RUNGS


class PolicyView:
    """Read-only snapshot. Callers never mutate; a new policy_version
    replaces it wholesale."""

    __slots__ = ("_reasoning_permitted", "_permitted_categories", "_permitted_rungs",
                 "_policy_version")

    def __init__(self, reasoning_permitted, permitted_categories, permitted_rungs,
                 policy_version):
        if not isinstance(reasoning_permitted, bool):
            raise ValueError("policy_view.bad_reasoning_permitted:" + repr(reasoning_permitted))
        permitted_categories = tuple(permitted_categories or ())
        for cat in permitted_categories:
            if cat not in CATEGORIES:
                raise ValueError("policy_view.unknown_category:" + str(cat))
        permitted_rungs = tuple(permitted_rungs or ())
        for rung in permitted_rungs:
            if rung not in COMPLEXITY_RUNGS:
                raise ValueError("policy_view.unknown_rung:" + str(rung))
        if not isinstance(policy_version, int):
            raise ValueError("policy_view.bad_policy_version:" + repr(policy_version))
        object.__setattr__(self, "_reasoning_permitted", reasoning_permitted)
        object.__setattr__(self, "_permitted_categories", permitted_categories)
        object.__setattr__(self, "_permitted_rungs", permitted_rungs)
        object.__setattr__(self, "_policy_version", policy_version)

    def __setattr__(self, name, value):
        raise AttributeError("PolicyView is read-only")

    @property
    def reasoning_permitted(self):
        return self._reasoning_permitted

    @property
    def permitted_categories(self):
        return self._permitted_categories

    @property
    def permitted_rungs(self):
        return self._permitted_rungs

    @property
    def policy_version(self):
        return self._policy_version


def build_policy_view(reasoning_permitted, permitted_categories, permitted_rungs,
                       policy_version):
    return PolicyView(reasoning_permitted, permitted_categories, permitted_rungs, policy_version)


if __name__ == "__main__":
    view = build_policy_view(True, ("INTERPRETIVE", "ANALYTIC"), ("C0", "C1", "C2"), 1)
    assert view.reasoning_permitted is True
    assert view.permitted_categories == ("INTERPRETIVE", "ANALYTIC")
    assert view.policy_version == 1

    try:
        view.policy_version = 2
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass

    try:
        build_policy_view(True, ("MADEUP",), ("C0",), 1)
        raise SystemExit("unknown category accepted")
    except ValueError:
        pass

    try:
        build_policy_view(True, (), ("C9",), 1)
        raise SystemExit("unknown rung accepted")
    except ValueError:
        pass

    print("policy_view selftest ok")
