"""PRT health manager — PRT/04 §3 (lifecycle states), §6 (publication,
determinism), §7 (quarantine + admin overrides), PRT-H1/H2/H3/H5/H7/H9/H11.

HealthManager is a fold over an injected EvidenceJournal: current state is a
pure, deterministic function of (that provider's ordered evidence entries,
threshold policy, legality callable) — PRT-H1. It holds no hidden state of
its own beyond an incremental cache that is provably equal to folding the
journal from scratch (see test_prt_phase4.py's replay test) — never a
registry reference (PRT-H2 structural: health.py imports nothing from
registry.py).

States (§3): HEALTHY, DEGRADED, UNAVAILABLE, QUARANTINED, RECOVERING,
RECOVERED. A provider with no evidence at all is HEALTHY (no adverse
evidence outstanding, §3's own table). RETIRED is a registry fact (PRT/02
§8) this module never emits (PRT-H12).

# ponytail: the fold's exact evidence->state policy is consecutive-failure/
# -success counters, not a decay curve or weighted score. Architecture
# (§10) requires graduated degradation + guaranteed healing, not any
# specific math — this is the laziest policy that satisfies both. Upgrade
# path: replace _step's counter logic with a richer scoring policy that
# still reduces to the same threshold-config shape.
"""
from . import events
from .health_view import HealthSnapshot
from .load_policy import AllowAllLegality  # noqa: F401  (re-exported: same
# generic decide-legalize-enact placeholder Phase 3 uses for load-lifecycle
# legality — Lifecycle's real transition-legality machine (PRT-A4) doesn't
# exist yet in either phase, so one double serves both callers rather than
# inventing a second identical stand-in (ponytail: reuse, don't duplicate).

STATES = ("HEALTHY", "DEGRADED", "UNAVAILABLE", "QUARANTINED", "RECOVERING", "RECOVERED")

DEFAULT_THRESHOLDS = {
    "consecutive_failures_to_degrade": 1,
    "failures_to_quarantine": 3,
    "successes_to_recover": 2,
}

_AVAILABLE_STATES = frozenset({"HEALTHY", "DEGRADED", "RECOVERED"})
_FAILURE_KINDS = frozenset({"exec.failed", "exec.timeout"})
_DEFAULT_RELIABILITY = 0.5  # ponytail: no priors entry yet -> neutral prior;
# PRT folds/stores priors, it never computes them (PRT-H10).


def _effective(carry):
    """Displayed state: the admin disable bar is independent of, and sits on
    top of, whatever the evidence-derived state underneath is (§3 table:
    "admin disable" under Unavailable)."""
    return "UNAVAILABLE" if carry["disabled"] else carry["state"]


def _initial_carry():
    return {"state": "HEALTHY", "cf": 0, "cs": 0, "disabled": False,
            "reliability": _DEFAULT_RELIABILITY, "priors_version": None}


def _step(carry, entry, thresholds, legality, provider_id):
    """Advance one carry by exactly one journal entry. Pure: same inputs ->
    same output, always — this single function is both the from-scratch
    fold's inner loop and the incremental cache's update step, so the two
    are structurally, not just coincidentally, equal (the replay test)."""
    state, cf, cs = carry["state"], carry["cf"], carry["cs"]
    disabled = carry["disabled"]
    reliability, priors_version = carry["reliability"], carry["priors_version"]

    etype = entry["type"]
    if etype == "priors":
        reliability = entry["prior"]
        priors_version = entry["priors_version"]

    elif etype == "admin":
        # Administrative acts are the operator's own authority (PRT/04 §7) —
        # they bypass the evidence-threshold legality gate entirely, the same
        # way load_policy.LoadPolicyView.is_admin_barred bypasses
        # LoadStateTracker's legality callable.
        kind = entry["kind"]
        if kind == "disable":
            disabled = True
        elif kind == "enable":
            disabled = False
        elif kind == "force_quarantine":
            state, cf, cs = "QUARANTINED", 0, 0
        elif kind == "force_release":
            state, cf, cs = "HEALTHY", 0, 0

    else:  # live evidence -> evidence-threshold policy REQUESTS a transition
        kind = entry["kind"]
        proposed = state
        if kind in _FAILURE_KINDS:
            cf, cs = cf + 1, 0
            if state in ("RECOVERING", "RECOVERED"):
                proposed = "QUARANTINED" if cf >= thresholds["failures_to_quarantine"] else "DEGRADED"
            elif cf >= thresholds["failures_to_quarantine"]:
                proposed = "QUARANTINED"
            elif cf >= thresholds["consecutive_failures_to_degrade"] and state == "HEALTHY":
                proposed = "DEGRADED"
        elif kind == "exec.completed":
            cf, cs = 0, cs + 1
            if state == "QUARANTINED":
                proposed = "RECOVERING"
            elif state == "RECOVERING" and cs >= thresholds["successes_to_recover"]:
                proposed = "RECOVERED"
            elif state == "RECOVERED":
                proposed = "HEALTHY"
            elif state == "DEGRADED":
                proposed = "HEALTHY"
        if proposed != state:
            # decide (above) -> legalize (here) -> enact (assignment) — PRT-H11.
            # Counters already reflect the observed evidence either way; only
            # the state transition itself is subject to refusal.
            if legality(provider_id, state, proposed):
                state = proposed

    return {"state": state, "cf": cf, "cs": cs, "disabled": disabled,
            "reliability": reliability, "priors_version": priors_version}


def fold_provider(entries, thresholds=None, legality=None, provider_id=None):
    """Pure, from-scratch fold over one provider's ordered entries (PRT-H1).
    No journal, no manager, no cache — exactly the function the invariant
    names."""
    thresholds = dict(DEFAULT_THRESHOLDS) if thresholds is None else thresholds
    legality = legality or AllowAllLegality()
    carry = _initial_carry()
    for entry in entries:
        carry = _step(carry, entry, thresholds, legality, provider_id)
    return carry


class HealthManager:
    """A fold over an injected EvidenceJournal. Never holds a registry
    reference (PRT-H2). Recomputable from scratch at any time via
    fold_provider(journal.entries_for(pid), ...); the cache here exists only
    to avoid re-walking the whole history on every query."""

    def __init__(self, journal, thresholds=None, legality=None, bus=None):
        self._journal = journal
        self._thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self._thresholds.update(thresholds)
        self._legality = legality or AllowAllLegality()
        self._bus = bus
        self._cache = {}
        self._folded = {}  # provider_id -> count of entries already folded in

    def _sync(self, provider_id):
        entries = self._journal.entries_for(provider_id)
        done = self._folded.get(provider_id, 0)
        carry = self._cache.get(provider_id, _initial_carry())
        for entry in entries[done:]:
            before = _effective(carry)
            carry = _step(carry, entry, self._thresholds, self._legality, provider_id)
            after = _effective(carry)
            if after != before and self._bus is not None:
                events.emit(self._bus, "plugin.health.changed", provider_id,
                            {"provider_id": provider_id, "from": before, "to": after})
        self._cache[provider_id] = carry
        self._folded[provider_id] = len(entries)
        return carry

    def state(self, provider_id):
        return _effective(self._sync(provider_id))

    def reliability(self, provider_id):
        return self._sync(provider_id)["reliability"]

    def record_outcome(self, provider_id, kind, detail=None):
        """Live observation -> journal -> re-sync (PRT/04 §2/§4)."""
        self._journal.append_live(provider_id, kind, detail)
        return self.state(provider_id)

    def force_quarantine(self, provider_id, actor, reason):
        self._journal.append_admin(provider_id, "force_quarantine", actor, reason)
        return self.state(provider_id)

    def force_release(self, provider_id, actor, reason):
        self._journal.append_admin(provider_id, "force_release", actor, reason)
        return self.state(provider_id)

    def disable(self, provider_id, actor, reason):
        self._journal.append_admin(provider_id, "disable", actor, reason)
        return self.state(provider_id)

    def enable(self, provider_id, actor, reason):
        self._journal.append_admin(provider_id, "enable", actor, reason)
        return self.state(provider_id)

    def snapshot(self, provider_ids):
        """One current HealthSnapshot (PRT/03 §2, PRT/04 §6) over exactly the
        providers the caller names — read once, frozen, deterministic:
        same journal content + thresholds -> identical content_hash."""
        data = {}
        for provider_id in provider_ids:
            carry = self._sync(provider_id)
            eff = _effective(carry)
            avail = "available" if eff in _AVAILABLE_STATES else "unavailable"
            data[provider_id] = {"availability": avail, "reliability": carry["reliability"]}
        return HealthSnapshot(data)


if __name__ == "__main__":
    from .evidence import EvidenceJournal

    # providers with no evidence at all are HEALTHY (§3)
    j = EvidenceJournal()
    mgr = HealthManager(j)
    assert mgr.state("prov.new") == "HEALTHY"
    assert mgr.reliability("prov.new") == 0.5

    # graduated degradation: 1 failure -> DEGRADED, 3rd consecutive -> QUARANTINED
    j.append_live("prov.a", "exec.failed")
    assert mgr.state("prov.a") == "DEGRADED"
    j.append_live("prov.a", "exec.failed")
    assert mgr.state("prov.a") == "DEGRADED"
    j.append_live("prov.a", "exec.timeout")
    assert mgr.state("prov.a") == "QUARANTINED"

    # recovery path: RECOVERING -> RECOVERED -> HEALTHY, never permanent (PRT-H5)
    j.append_live("prov.a", "exec.completed")
    assert mgr.state("prov.a") == "RECOVERING"
    j.append_live("prov.a", "exec.completed")
    assert mgr.state("prov.a") == "RECOVERED"
    j.append_live("prov.a", "exec.completed")
    assert mgr.state("prov.a") == "HEALTHY"

    # admin override both directions, explicit
    mgr.force_quarantine("prov.b", actor="op.1", reason="incident")
    assert mgr.state("prov.b") == "QUARANTINED"
    mgr.force_release("prov.b", actor="op.1", reason="resolved")
    assert mgr.state("prov.b") == "HEALTHY"

    # disable/enable: UNAVAILABLE bar independent of quarantine
    mgr.disable("prov.b", actor="op.1", reason="planned maintenance")
    assert mgr.state("prov.b") == "UNAVAILABLE"
    mgr.enable("prov.b", actor="op.1", reason="maintenance done")
    assert mgr.state("prov.b") == "HEALTHY"

    # legality refusal: no transition, no event
    from .bus_double import BusDouble

    def _refuse(pid, frm, to):
        return False

    bus = BusDouble()
    j2 = EvidenceJournal()
    mgr2 = HealthManager(j2, legality=_refuse, bus=bus)
    mgr2.record_outcome("prov.c", "exec.failed")
    assert mgr2.state("prov.c") == "HEALTHY"  # refused: stayed put
    assert bus.messages("plugin.health.changed") == []

    # replay: fold-from-scratch equals the incrementally-maintained cache
    bus2 = BusDouble()
    j3 = EvidenceJournal()
    mgr3 = HealthManager(j3, bus=bus2)
    for kind in ("exec.failed", "exec.failed", "exec.timeout", "exec.completed"):
        mgr3.record_outcome("prov.d", kind)
    incremental = mgr3.state("prov.d")
    scratch = _effective(fold_provider(j3.entries_for("prov.d"), provider_id="prov.d"))
    assert incremental == scratch == "RECOVERING"

    # snapshot: deterministic content_hash, availability mapped per state rules
    snap = mgr3.snapshot(["prov.d"])
    snap2 = mgr3.snapshot(["prov.d"])
    assert snap.content_hash == snap2.content_hash
    assert snap.get("prov.d")["availability"] == "unavailable"  # RECOVERING bars

    # event emitted on transition, canon name, {provider_id, from, to} payload
    changed = bus2.messages("plugin.health.changed")
    assert changed and changed[0]["payload"]["provider_id"] == "prov.d"
    assert changed[0]["payload"]["from"] == "HEALTHY"

    # health never touches registry: structural check, no import edge (PRT-H2)
    import ast
    with open(__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            imported.update(n.name.rsplit(".", 1)[-1] for n in node.names)
    assert "registry" not in imported

    print("health selftest ok")
