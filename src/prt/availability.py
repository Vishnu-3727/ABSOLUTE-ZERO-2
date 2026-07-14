"""PRT provider availability ladder — PRT/03 §6 (six rungs), PRT-B11
(availability is an eligibility predicate ONLY, never a scoring/ranking
model — Phase 4 owns scoring). Consumed by binding.py's stage 3 (PRT/03 §3)
as the eligibility filter.

`rung_for` is pure: it reads registry_view (Registry or a frozen
at_version RegistrySnapshot — both share registry.py's _ReadSurface),
policy_view (load_policy.LoadPolicyView — admin bar, load permission,
current load-lifecycle state) and health_snapshot (health_view.
HealthSnapshot, opaque here per PRT/03 §2) once, and returns exactly one
rung string. No scoring, no numeric comparison of reliability — reliability
is only ever compared in binding.py's tie-break (§4), never here.
"""

RUNGS = ("REGISTERED", "LOADABLE", "AVAILABLE", "OPERATIONAL",
         "UNAVAILABLE", "RETIRED")

# ponytail: the health snapshot's own "availability" field is Phase 4's
# opaque operational-health signal (evidence/quarantine mechanics are out
# of scope here, PRT/03 §2). Phase 3 only needs to know which string values
# permit vs. bar binding — "available" permits, "unavailable"/"quarantined"
# bar, anything else (including no entry at all) leaves the provider at
# Loadable (health hasn't affirmatively cleared it yet).
_HEALTH_BARS = frozenset({"unavailable", "quarantined"})
_HEALTH_PERMITS = "available"
_OPERATIONAL_LOAD_STATES = frozenset({"PREPARED", "LOADED"})


def rung_for(registry_view, provider_id, policy_view, health_snapshot):
    """Deterministic predicate composition, PRT/03 §6's ladder, evaluated
    top-down; the first gate that fails fixes the rung."""
    provider = registry_view.get_provider(provider_id)
    if provider is None or provider.lifecycle == "retired":
        return "RETIRED"

    # Registered: present, non-retired. Loadable: + policy permits + no admin bar.
    if policy_view.is_admin_barred(provider_id):
        return "UNAVAILABLE"  # administratively barred, still Registered underneath
    if not policy_view.permits(provider_id):
        return "REGISTERED"

    # Available: + health snapshot's availability permits binding.
    entry = health_snapshot.get(provider_id)
    health_state = entry["availability"] if entry is not None else None
    if health_state in _HEALTH_BARS:
        return "UNAVAILABLE"
    if health_state != _HEALTH_PERMITS:
        return "LOADABLE"

    # Operational: + currently prepared/loaded per load lifecycle state.
    if policy_view.load_state(provider_id) in _OPERATIONAL_LOAD_STATES:
        return "OPERATIONAL"
    return "AVAILABLE"


if __name__ == "__main__":
    from .health_view import HealthSnapshot
    from .records import build_provider
    from .registry import Registry

    class _FakePolicy:
        def __init__(self, permits=True, barred=False, load_state="NOT_LOADED"):
            self._permits = permits
            self._barred = barred
            self._load_state = load_state

        def is_admin_barred(self, provider_id):
            return self._barred

        def permits(self, provider_id):
            return self._permits

        def load_state(self, provider_id):
            return self._load_state

    reg = Registry()
    reg.apply({"kind": "add_provider", "record": build_provider("prov.avail.a", "1.0")})

    # Retired: absent entirely
    assert rung_for(reg, "prov.missing", _FakePolicy(), HealthSnapshot({})) == "RETIRED"

    # Retired: present but lifecycle retired
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": "prov.avail.a", "to_state": "active"})
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": "prov.avail.a", "to_state": "deprecated"})
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": "prov.avail.a", "to_state": "retired"})
    assert rung_for(reg, "prov.avail.a", _FakePolicy(), HealthSnapshot({})) == "RETIRED"

    reg2 = Registry()
    reg2.apply({"kind": "add_provider", "record": build_provider("prov.avail.b", "1.0")})

    # Registered only: policy doesn't permit loading
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(permits=False),
                    HealthSnapshot({})) == "REGISTERED"

    # Unavailable: admin barred (still present)
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(barred=True),
                    HealthSnapshot({})) == "UNAVAILABLE"

    # Loadable: permitted, no health data yet
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(), HealthSnapshot({})) == "LOADABLE"

    # Unavailable: health quarantined
    snap_bad = HealthSnapshot({"prov.avail.b": {"availability": "quarantined", "reliability": 0.1}})
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(), snap_bad) == "UNAVAILABLE"

    # Available: health permits, not currently loaded
    snap_ok = HealthSnapshot({"prov.avail.b": {"availability": "available", "reliability": 0.8}})
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(), snap_ok) == "AVAILABLE"

    # Operational: available + currently loaded
    assert rung_for(reg2, "prov.avail.b", _FakePolicy(load_state="LOADED"),
                    snap_ok) == "OPERATIONAL"

    print("availability selftest ok")
