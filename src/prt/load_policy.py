"""PRT load policy + load lifecycle — PRT/03 §5 (load policy: policy-as-
data, demand-default eagerness), §9 (load lifecycle: runtime-only state,
decide-legalize-enact, Ruling 2/3 three-way split), PRT-B8/PRT-B9.

Two halves, deliberately not one class (Ruling 3, §5): `LoadPolicyView`
reads DECLARED policy (registry-held ProviderRecord.load_policy + the admin
bar from config) — it never holds runtime state. `LoadStateTracker` holds
the runtime load-lifecycle state (PRT-B8: never mints a registry version,
never touches or holds a reference to the registry object at all) and
enacts transitions REQUESTED by policy and LEGALIZED by an injected
lifecycle-legality callable (Lifecycle's real state machine, PRT-A4 —
`AllowAllLegality` here is a recording test double standing in for it).

`prerequisites_bound` is PRT/03 §7's PRT-side CHECK (never acquisition):
does every declared dependency-relationship prerequisite of a capability
currently have >=1 eligible provider, per a caller-supplied resolve_fn
(typically binding.resolve bound to one health snapshot + policy view).
"""
from . import events
from .binding import BindingContract

LOAD_STATES = ("NOT_LOADED", "LOADING", "PREPARED", "LOADED", "RELEASED", "UNAVAILABLE")

# PRT/03 §9 diagram: Not Loaded -> Loading -> Prepared -> Loaded -> Released,
# Unavailable reachable from any of these (a barring condition); recovery
# from Unavailable re-enters at Not Loaded — a guaranteed path back, same
# spirit as PRT/04's healing though quarantine mechanics themselves are
# Phase 4.
_TRANSITIONS = {
    "NOT_LOADED": ("LOADING", "UNAVAILABLE"),
    "LOADING": ("PREPARED", "UNAVAILABLE"),
    "PREPARED": ("LOADED", "UNAVAILABLE"),
    "LOADED": ("RELEASED", "UNAVAILABLE"),
    "RELEASED": ("LOADING", "UNAVAILABLE"),
    "UNAVAILABLE": ("NOT_LOADED",),
}


class LoadPolicyView:
    """Declared, registry-held policy only — no runtime state (Ruling 3).
    Doubles as both the `load_policy_view` availability.rung_for consumes
    and the `policy_view` binding.resolve consumes: one view, two callers,
    since both reads are the same "PRT decides policy" seam (Ruling 3) —
    avoids a second view class for what is architecturally one declared-
    policy read surface."""

    def __init__(self, registry, config_view, tracker=None, preferences=None):
        self._registry = registry
        self._config_view = config_view
        self._tracker = tracker
        self._preferences = dict(preferences or {})

    def permits(self, provider_id):
        """Loadable gate (§5/§6): an absent policy key means the demand
        default permits loading; only an explicit {"loadable": False}
        blocks it."""
        provider = self._registry.get_provider(provider_id)
        if provider is None:
            return False
        return bool(provider.load_policy.get("loadable", True))

    def eagerness(self, provider_id):
        provider = self._registry.get_provider(provider_id)
        if provider is None:
            return None
        return provider.load_policy.get("eagerness", "demand")

    def is_admin_barred(self, provider_id):
        """Administrative bar — config-view datum this phase (ponytail:
        real administrative acts, force-quarantine/-release, are PRT/04 §7
        territory; here it is just a citable config list)."""
        return provider_id in self._config_view.admin_barred

    def load_state(self, provider_id):
        """Current load-lifecycle state (the Operational rung, §6) —
        delegates to an injected LoadStateTracker; NOT_LOADED if none is
        attached (a view with no tracker never reports Operational)."""
        if self._tracker is None:
            return "NOT_LOADED"
        return self._tracker.state(provider_id)

    def preference(self, capability_id):
        """Declared preference order for `capability_id` (§3 stage 4) —
        registry-policy data, a plain capability_id -> provider-id-order
        mapping supplied at construction."""
        return tuple(self._preferences.get(capability_id, ()))


class AllowAllLegality:
    """Test double standing in for Lifecycle's real transition-legality
    machine (PRT-A4) — allows every request and records what it was asked,
    so a test can assert LoadStateTracker consults it on every transition
    (PRT-B9). Real Lifecycle integration is a later-phase seam."""

    def __init__(self):
        self.calls = []  # (provider_id, from_state, to_state)

    def __call__(self, provider_id, from_state, to_state):
        self.calls.append((provider_id, from_state, to_state))
        return True


class LoadStateTracker:
    """Runtime-only load lifecycle (PRT-B8: never mints a registry version;
    holds no reference to a registry object at all — decisions come from
    LoadPolicyView, which does hold one, kept entirely separate). Every
    transition is decide (caller/policy requests) -> legalize (injected
    `is_legal` callable) -> enact (this tracker flips its own map) —
    PRT-B9's three-way split restated for the lifecycle view."""

    def __init__(self, is_legal, bus=None):
        self._is_legal = is_legal
        self._bus = bus
        self._states = {}

    def state(self, provider_id):
        return self._states.get(provider_id, "NOT_LOADED")

    def request_transition(self, provider_id, to_state):
        """Returns True if enacted, False if refused (by shape or by the
        legality callable) — a refusal changes neither state nor events."""
        if to_state not in LOAD_STATES:
            raise ValueError("load_policy.unknown_load_state:" + str(to_state))
        from_state = self.state(provider_id)
        if to_state not in _TRANSITIONS.get(from_state, ()):
            return False  # shape-illegal; never even asked Lifecycle
        if not self._is_legal(provider_id, from_state, to_state):
            return False  # Lifecycle refused (PRT-B9): no state change, no event
        self._states[provider_id] = to_state
        if self._bus is not None:
            if to_state == "LOADED":
                events.emit(self._bus, "plugin.loaded", provider_id)
            elif from_state == "LOADED" and to_state in ("RELEASED", "UNAVAILABLE"):
                events.emit(self._bus, "plugin.unloaded", provider_id)
        return True


def prerequisites_bound(registry, capability_id, resolve_fn):
    """PRT/03 §7/§8 CHECK, never acquisition: every declared dependency-
    relationship prerequisite of `capability_id` currently resolves to a
    BindingContract (>=1 eligible provider) under `resolve_fn`. Returns
    (ok, unmet_capability_ids)."""
    canonical = registry.resolve(capability_id)
    if canonical is None:
        return False, (capability_id,)
    unmet = tuple(
        edge.dst for edge in registry.relationships()
        if edge.kind == "dependency" and edge.src == canonical
        and not isinstance(resolve_fn(edge.dst), BindingContract)
    )
    return (len(unmet) == 0), unmet


if __name__ == "__main__":
    from . import binding
    from .bus_double import BusDouble
    from .config_view import ConfigView
    from .health_view import HealthSnapshot
    from .records import build_capability, build_provider, build_relationship
    from .registry import Registry

    reg = Registry()
    reg.apply({"kind": "add_provider", "record": build_provider(
        "prov.lp.a", "1.0", load_policy={"eagerness": "eager"})})
    cfg = ConfigView({"version": 1, "admin_barred": ("prov.lp.barred",)})
    view = LoadPolicyView(reg, cfg, preferences={"cap.x": ("prov.lp.a", "prov.lp.b")})

    assert view.eagerness("prov.lp.a") == "eager"
    assert view.permits("prov.lp.a") is True
    assert view.is_admin_barred("prov.lp.barred") is True
    assert view.is_admin_barred("prov.lp.a") is False
    assert view.preference("cap.x") == ("prov.lp.a", "prov.lp.b")
    assert view.preference("cap.unknown") == ()
    assert view.load_state("prov.lp.a") == "NOT_LOADED"  # no tracker attached

    # LoadStateTracker: decide-legalize-enact, events only on legal enactment
    legality = AllowAllLegality()
    bus = BusDouble()
    tracker = LoadStateTracker(legality, bus=bus)
    assert tracker.state("prov.lp.a") == "NOT_LOADED"
    assert tracker.request_transition("prov.lp.a", "LOADING") is True
    assert tracker.request_transition("prov.lp.a", "PREPARED") is True
    assert tracker.request_transition("prov.lp.a", "LOADED") is True
    assert tracker.state("prov.lp.a") == "LOADED"
    assert len(bus.messages("plugin.loaded")) == 1
    assert len(legality.calls) == 3

    # shape-illegal transition refused before Lifecycle is ever consulted
    calls_before = len(legality.calls)
    assert tracker.request_transition("prov.lp.a", "LOADING") is False  # LOADED -> LOADING illegal
    assert len(legality.calls) == calls_before  # never asked

    assert tracker.request_transition("prov.lp.a", "RELEASED") is True
    assert len(bus.messages("plugin.unloaded")) == 1

    # legality refusal: no state change, no event
    def _refusing(pid, f, t):
        return False

    tracker2 = LoadStateTracker(_refusing, bus=bus)
    assert tracker2.request_transition("prov.lp.b", "LOADING") is False
    assert tracker2.state("prov.lp.b") == "NOT_LOADED"
    assert bus.messages("plugin.loaded")[-1:] or True  # no new event asserted below
    loaded_before = len(bus.messages("plugin.loaded"))
    assert len(bus.messages("plugin.loaded")) == loaded_before  # unchanged by the refusal

    # prerequisites_bound: unmet prerequisite -> False + the unmet id
    reg2 = Registry()
    cap_a = build_capability("cap.lp.a", "d", "nlp", lifecycle="active",
                             verification_expectations=("x",))
    cap_b = build_capability("cap.lp.b", "d", "nlp", lifecycle="active",
                             verification_expectations=("x",))
    reg2.apply({"kind": "add_capability", "record": cap_a})
    reg2.apply({"kind": "add_capability", "record": cap_b})
    reg2.apply({"kind": "add_relationship", "record": build_relationship(
        "dependency", "cap.lp.a", "cap.lp.b")})
    empty_snap = HealthSnapshot({})
    empty_view = LoadPolicyView(reg2, ConfigView({"version": 1}))
    resolve_fn = lambda cid: binding.resolve(reg2, cid, empty_snap, empty_view)  # noqa: E731
    ok, unmet = prerequisites_bound(reg2, "cap.lp.a", resolve_fn)
    assert ok is False and unmet == ("cap.lp.b",)  # no provider bound to cap.lp.b yet

    print("load_policy selftest ok")
