"""PRT health-state coordinate — PRT/03 §2 (opaque input to binding; its
computation is Phase 4's), PRT/04 §6 (snapshot stability: read once, frozen
into the Binding Contract, never re-read mid-decision).

HealthSnapshot is a frozen record: provider_id -> {"availability": <rung
string>, "reliability": <opaque orderable value>}, plus a content_hash —
the citable binding coordinate (PRT/03 §7, PRT-B6). Phase 3 only CONSUMES
these, injected by a caller; it never computes one.

# ponytail: Phase 4 will produce these from evidence/scoring, healing and
# quarantine mechanics. Until then this is a thin frozen wrapper around a
# plain dict a test or caller hands in directly — no evidence, no decay,
# no quarantine logic lives here.
"""
from types import MappingProxyType
import hashlib
import json

_REQUIRED = ("availability", "reliability")


class HealthSnapshot:
    """Frozen at construction: content_hash is derived from the canonical
    form once, never recomputed (PRT-B6's binding coordinate must never
    drift after the instant it was read)."""

    __slots__ = ("_providers", "content_hash")

    def __init__(self, data):
        providers = {}
        for provider_id, entry in dict(data or {}).items():
            if not isinstance(entry, dict) or any(k not in entry for k in _REQUIRED):
                raise ValueError("health_view.malformed_entry:" + str(provider_id))
            providers[provider_id] = MappingProxyType(
                {"availability": entry["availability"], "reliability": entry["reliability"]})
        object.__setattr__(self, "_providers", MappingProxyType(providers))
        object.__setattr__(self, "content_hash", self._compute_hash())

    def __setattr__(self, name, value):
        raise AttributeError("health_view.snapshot_is_frozen")

    def get(self, provider_id):
        """None if the snapshot carries no entry for this provider."""
        return self._providers.get(provider_id)

    def _compute_hash(self):
        payload = {pid: dict(entry) for pid, entry in self._providers.items()}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    snap = HealthSnapshot({"prov.a": {"availability": "available", "reliability": 0.9}})
    assert snap.get("prov.a")["reliability"] == 0.9
    assert snap.get("prov.missing") is None

    # identical content -> identical hash (PRT-B2 style determinism, restated
    # here for the coordinate binding cites)
    snap2 = HealthSnapshot({"prov.a": {"availability": "available", "reliability": 0.9}})
    assert snap.content_hash == snap2.content_hash

    # dict insertion order never affects the hash (PRT-B3: no order-sensitive input)
    snap3 = HealthSnapshot({"prov.b": {"availability": "loadable", "reliability": 0.2},
                            "prov.a": {"availability": "available", "reliability": 0.9}})
    snap4 = HealthSnapshot({"prov.a": {"availability": "available", "reliability": 0.9},
                            "prov.b": {"availability": "loadable", "reliability": 0.2}})
    assert snap3.content_hash == snap4.content_hash

    # frozen: neither the snapshot nor a provider's entry can be mutated
    try:
        snap.content_hash = "x"
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass
    try:
        snap.get("prov.a")["reliability"] = 1.0
        raise SystemExit("entry mutation allowed")
    except TypeError:
        pass

    # malformed entry (missing a required key) refused loudly at construction
    try:
        HealthSnapshot({"prov.bad": {"availability": "available"}})
        raise SystemExit("malformed entry accepted")
    except ValueError:
        pass

    print("health_view selftest ok")
