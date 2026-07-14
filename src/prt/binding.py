"""PRT late binding — PRT/03 §3 (seven stages), §4 (determinism), §6
(availability, via availability.rung_for), §7 (Binding Contract shape),
§8 (binding-time constraint families). Restates nothing already fixed in
PRT/00 §4/§5 or PRT/01 (registry) — reads registry.py's existing read
surface only, mutates nothing.

Binding is a pure function over four closed inputs: the cited registry
view (Registry or a frozen at_version RegistrySnapshot — both are
registry.py's _ReadSurface), a capability id, a health snapshot taken once
by the caller (health_view.HealthSnapshot, opaque here), and a policy view
(load_policy.LoadPolicyView — eligibility gates + declared preference
order). No wall-clock, no randomness, no live re-reads mid-resolution
(PRT-B3).

# ponytail: PRT/03 §8 lists six binding-time constraint families (platform,
# capability restrictions, version, prerequisites, admin policy, operational
# status). This phase has live facts for exactly two of them — admin policy
# and operational status — both already folded into availability.rung_for's
# ladder. Platform/capability-restriction/version incompatibility need a
# live platform/dispatch-context fact this phase has no source for yet, and
# "missing prerequisites" is its own CHECK helper (prerequisites_bound,
# load_policy.py) rather than an automatic per-candidate gate here — a
# caller that needs it invokes it separately. Extending eligibility with
# real platform/version facts is a later-phase seam, not a Phase 3 gap.
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from . import availability


class BindingFailure:
    """PRT-B5: an empty eligible set (or an unresolvable capability id) is a
    loud, ordinary result — never an exception. Carries every per-candidate
    refusal reason recorded during stage 3 (PRT-B4/B5), so a caller can see
    exactly why nothing was eligible without re-deriving it."""

    __slots__ = ("capability_id", "registry_version", "health_snapshot_hash",
                "reasons", "unknown_capability")

    def __init__(self, capability_id, registry_version, health_snapshot_hash,
                reasons=(), unknown_capability=False):
        self.capability_id = capability_id
        self.registry_version = registry_version
        self.health_snapshot_hash = health_snapshot_hash
        self.reasons = tuple(reasons)  # ((provider_id, reason_str), ...)
        self.unknown_capability = unknown_capability

    def __repr__(self):
        return ("BindingFailure(capability_id=%r, unknown_capability=%r, reasons=%r)" %
                (self.capability_id, self.unknown_capability, self.reasons))


@dataclass(frozen=True)
class BindingContract:
    """PRT/03 §7's five elements + a deterministic contract id (PRT-B6):
    immutable once minted, carries the exact (registry_version,
    health_snapshot_hash) coordinates it was resolved under."""
    provider_id: str
    provider_version: str
    capability_id: str          # canonical form (stage 1)
    constraints: MappingProxyType
    load_policy: MappingProxyType
    registry_version: int
    health_snapshot_hash: str
    contract_id: str

    def canonical(self):
        return _canonical_bytes(
            self.provider_id, self.provider_version, self.capability_id,
            self.constraints, self.load_policy, self.registry_version,
            self.health_snapshot_hash)

    def content_hash(self):
        return hashlib.sha256(self.canonical()).hexdigest()


def _canonical_bytes(provider_id, provider_version, capability_id, constraints,
                     load_policy, registry_version, health_hash):
    payload = {
        "provider_id": provider_id, "provider_version": provider_version,
        "capability_id": capability_id, "constraints": dict(constraints),
        "load_policy": dict(load_policy), "registry_version": registry_version,
        "health_snapshot_hash": health_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _registry_version(registry):
    """Both Registry (live, `.current_version`) and RegistrySnapshot
    (`.version`) are valid resolve() targets — replay reads an at_version
    view — read whichever this one exposes."""
    if hasattr(registry, "current_version"):
        return registry.current_version
    return registry.version


def resolve(registry, capability_id, health_snapshot, policy_view):
    """PRT/03 §3's seven stages. Returns a BindingContract on success, a
    BindingFailure on an empty eligible set or an unresolvable id — never
    raises for either (PRT-B5). Reads `registry` only; never mutates it."""
    reg_version = _registry_version(registry)

    # stage 1: canonical lookup (PRT-R6)
    canonical_id = registry.resolve(capability_id)
    if canonical_id is None:
        return BindingFailure(capability_id, reg_version, health_snapshot.content_hash,
                              unknown_capability=True)

    # stage 2: candidate set at this version
    candidates = registry.bindings_for(canonical_id)

    # stage 3: eligibility filtering — every refusal recorded (PRT-B4/B5)
    eligible = []
    reasons = []
    for entry in candidates:
        rung = availability.rung_for(registry, entry.provider_id, policy_view, health_snapshot)
        if rung in ("AVAILABLE", "OPERATIONAL"):
            eligible.append(entry)
        else:
            reasons.append((entry.provider_id, "ineligible:" + rung))

    if not eligible:
        return BindingFailure(canonical_id, reg_version, health_snapshot.content_hash,
                              reasons=reasons)

    # stage 4/5: declared preference, then reliability (descending), then
    # stable provider id ascending (PRT/00 §4 fixed total order)
    preference = policy_view.preference(canonical_id)
    pref_rank = {pid: i for i, pid in enumerate(preference)}

    def sort_key(entry):
        rank = pref_rank.get(entry.provider_id, len(preference))
        reliability = health_snapshot.get(entry.provider_id)["reliability"]
        return (rank, -reliability, entry.provider_id)

    eligible.sort(key=sort_key)
    winner = eligible[0]
    provider = registry.get_provider(winner.provider_id)

    # stage 6: mint the contract
    contract_id = hashlib.sha256(_canonical_bytes(
        provider.id, provider.version, canonical_id, winner.terms,
        provider.load_policy, reg_version, health_snapshot.content_hash)).hexdigest()
    return BindingContract(
        provider_id=provider.id, provider_version=provider.version,
        capability_id=canonical_id, constraints=MappingProxyType(dict(winner.terms)),
        load_policy=MappingProxyType(dict(provider.load_policy)),
        registry_version=reg_version, health_snapshot_hash=health_snapshot.content_hash,
        contract_id=contract_id,
    )
    # stage 7 (execution preparation handoff) is the caller's — PRT's
    # involvement in this fulfillment ends at returning this contract.


def explain(contract_or_failure):
    """PRT-B12: a mechanical explanation derived only from the artifact's
    own recorded fields — never re-queries live registry/health state."""
    if isinstance(contract_or_failure, BindingContract):
        c = contract_or_failure
        return {
            "outcome": "bound", "capability_id": c.capability_id,
            "provider_id": c.provider_id, "provider_version": c.provider_version,
            "registry_version": c.registry_version,
            "health_snapshot_hash": c.health_snapshot_hash,
            "contract_id": c.contract_id,
        }
    if isinstance(contract_or_failure, BindingFailure):
        f = contract_or_failure
        return {
            "outcome": "failed", "capability_id": f.capability_id,
            "unknown_capability": f.unknown_capability,
            "registry_version": f.registry_version,
            "health_snapshot_hash": f.health_snapshot_hash,
            "reasons": dict(f.reasons),
        }
    raise TypeError("binding.explain_unknown_artifact:" + repr(type(contract_or_failure)))


if __name__ == "__main__":
    from .health_view import HealthSnapshot
    from .records import build_binding, build_capability, build_provider
    from .registry import Registry

    class _Policy:
        """Minimal LoadPolicyView-shaped stand-in for this module's own
        selftest — load_policy.py's real selftest exercises the real one."""

        def __init__(self, preferences=None):
            self._preferences = preferences or {}

        def is_admin_barred(self, provider_id):
            return False

        def permits(self, provider_id):
            return True

        def load_state(self, provider_id):
            return "NOT_LOADED"

        def preference(self, capability_id):
            return tuple(self._preferences.get(capability_id, ()))

    reg = Registry()
    cap = build_capability("cap.bind.x", "d", "nlp", lifecycle="active",
                          verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": cap})
    for pid in ("prov.bind.a", "prov.bind.b"):
        reg.apply({"kind": "add_provider", "record": build_provider(pid, "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": pid, "to_state": "active"})
        reg.apply({"kind": "add_binding", "record": build_binding("cap.bind.x", pid)})

    snap = HealthSnapshot({
        "prov.bind.a": {"availability": "available", "reliability": 0.5},
        "prov.bind.b": {"availability": "available", "reliability": 0.9},
    })
    policy = _Policy()

    # tie-break level 2: no preference -> higher reliability wins
    contract = resolve(reg, "cap.bind.x", snap, policy)
    assert isinstance(contract, BindingContract)
    assert contract.provider_id == "prov.bind.b"
    assert contract.registry_version == reg.current_version
    assert contract.health_snapshot_hash == snap.content_hash

    # tie-break level 1: declared preference beats reliability
    pref_policy = _Policy(preferences={"cap.bind.x": ("prov.bind.a",)})
    contract2 = resolve(reg, "cap.bind.x", snap, pref_policy)
    assert contract2.provider_id == "prov.bind.a"

    # determinism: identical inputs -> identical contract, including contract_id
    contract3 = resolve(reg, "cap.bind.x", snap, policy)
    assert contract3.contract_id == contract.contract_id

    # unknown capability id: loud, deterministic BindingFailure, never an exception
    failure = resolve(reg, "cap.does.not.exist", snap, policy)
    assert isinstance(failure, BindingFailure)
    assert failure.unknown_capability is True

    # empty eligible set: every refusal reason recorded
    empty_snap = HealthSnapshot({})
    failure2 = resolve(reg, "cap.bind.x", empty_snap, policy)
    assert isinstance(failure2, BindingFailure)
    assert failure2.unknown_capability is False
    assert dict(failure2.reasons) == {
        "prov.bind.a": "ineligible:LOADABLE", "prov.bind.b": "ineligible:LOADABLE"}

    # immutability: field reassignment on a minted contract raises
    try:
        contract.provider_id = "prov.bind.a"
        raise SystemExit("contract field reassignment allowed")
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError"

    # explain(): mechanical, derived only from the artifact
    exp = explain(contract)
    assert exp["provider_id"] == "prov.bind.b" and exp["outcome"] == "bound"
    exp_fail = explain(failure2)
    assert exp_fail["outcome"] == "failed"
    assert exp_fail["reasons"]["prov.bind.a"] == "ineligible:LOADABLE"

    print("binding selftest ok")
