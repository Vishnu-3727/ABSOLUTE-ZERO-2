"""RO/05 §5 Back flow (Experience -> RO) — the one versioned priors artifact
(RO-S6). Follows the records.py convention (dataclass(frozen=True),
MappingProxyType-frozen mapping fields, a `build_*` validating factory,
canonical/content_hash via sorted JSON).

`PriorsArtifact` folds provider priors (descriptor reliability healing,
RO/03 §3), routing priors (capability/provider pairings), demand-shape
priors (recurring-demand candidates for deterministic registration), and
policy evolution proposals — RECORDED DATA ONLY. `policy_proposals` is
never read by anything else in RO (Fable R4/R14 j — policy change is a
Vishnu/admin act, never an automatic RO code path); this module and
persistence.py are the only two src/ro files permitted to reference the
field name, enforced by law_enforcer.py.

`PriorsStore` is the ingest side of `prior.updated` (RO/05 §2 consume
table): append-only, monotonic-version history. A decision replays against
the priors version IT recorded, never current priors (RO-S6, RO/05 §5
"Replay safety") — `at_version(n)` is the only replay-safe read; `current()`
is for a live governance call choosing what to cite going forward."""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json


class PriorsRefusal(Exception):
    """Base for priors-artifact/store refusals."""


class MalformedPriorsPayloadError(PriorsRefusal):
    """A `prior.updated` payload missing/mistyping a required field."""


class StaleOrDuplicateVersionError(PriorsRefusal):
    """RO-S6: priors versions are strictly monotonic; a version <= the
    current one is refused loud, never silently ignored or overwritten."""


class UnknownVersionError(PriorsRefusal):
    """at_version(n) asked for a version never ingested."""


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


def _freeze_proposals(proposals):
    return tuple(_freeze_mapping(p) for p in (proposals or ()))


@dataclass(frozen=True)
class PriorsArtifact:
    priors_version: int
    provider_priors: MappingProxyType
    routing_priors: MappingProxyType
    demand_shape_priors: MappingProxyType
    policy_proposals: tuple  # tuple of MappingProxyType — recorded, never applied (RO-S6/R4)


def build_priors_artifact(priors_version, provider_priors, routing_priors,
                           demand_shape_priors, policy_proposals=()):
    if not isinstance(priors_version, int) or isinstance(priors_version, bool) or priors_version < 1:
        raise MalformedPriorsPayloadError("priors.bad_priors_version:" + repr(priors_version))
    for label, value in (("provider_priors", provider_priors), ("routing_priors", routing_priors),
                          ("demand_shape_priors", demand_shape_priors)):
        if not isinstance(value, dict) and not isinstance(value, MappingProxyType):
            raise MalformedPriorsPayloadError("priors.bad_" + label + ":" + repr(value))
    for p in (policy_proposals or ()):
        if not isinstance(p, dict) and not isinstance(p, MappingProxyType):
            raise MalformedPriorsPayloadError("priors.bad_policy_proposal:" + repr(p))
    return PriorsArtifact(
        priors_version=priors_version,
        provider_priors=_freeze_mapping(provider_priors),
        routing_priors=_freeze_mapping(routing_priors),
        demand_shape_priors=_freeze_mapping(demand_shape_priors),
        policy_proposals=_freeze_proposals(policy_proposals),
    )


class PriorsStore:
    """Append-only ingest of `prior.updated` payloads. The bus is the only
    inbound path (governed by runtime.py's handle_event dispatch, RO/05 §2
    consume table) — this class itself does no bus I/O, just the ledger."""

    def __init__(self):
        self._history = {}  # version -> PriorsArtifact
        self._current_version = 0

    def ingest(self, payload):
        """`payload` is a `prior.updated` event's payload dict (same shape
        `build_priors_artifact` accepts as kwargs). Refuses loud on a
        malformed payload or a version that is not strictly greater than
        the current one (RO-S6 monotonic — stale AND duplicate both
        refused, never silently accepted or overwritten)."""
        if not isinstance(payload, dict):
            raise MalformedPriorsPayloadError("priors.payload_not_a_mapping:" + repr(payload))
        artifact = build_priors_artifact(
            priors_version=payload.get("priors_version"),
            provider_priors=payload.get("provider_priors"),
            routing_priors=payload.get("routing_priors"),
            demand_shape_priors=payload.get("demand_shape_priors"),
            policy_proposals=payload.get("policy_proposals", ()),
        )
        if artifact.priors_version <= self._current_version:
            raise StaleOrDuplicateVersionError(
                "priors.stale_or_duplicate_version:got=" + str(artifact.priors_version) +
                ":current=" + str(self._current_version))
        self._history[artifact.priors_version] = artifact
        self._current_version = artifact.priors_version
        return artifact

    def at_version(self, n):
        """Immutable lookup for replay (RO-S6: a recorded version is
        readable forever)."""
        if n not in self._history:
            raise UnknownVersionError("priors.unknown_version:" + str(n))
        return self._history[n]

    def current(self):
        if self._current_version == 0:
            return None
        return self._history[self._current_version]


# -- canonical serialization (records.py pattern) -----------------

def to_dict(artifact):
    return {
        "priors_version": artifact.priors_version,
        "provider_priors": dict(artifact.provider_priors),
        "routing_priors": dict(artifact.routing_priors),
        "demand_shape_priors": dict(artifact.demand_shape_priors),
        "policy_proposals": [dict(p) for p in artifact.policy_proposals],
    }


def canonical(artifact):
    return json.dumps(to_dict(artifact), sort_keys=True, separators=(",", ":")).encode()


def content_hash(artifact):
    return hashlib.sha256(canonical(artifact)).hexdigest()


if __name__ == "__main__":
    a1 = build_priors_artifact(
        1, provider_priors={"ro.provider.x": {"reliability": "high"}},
        routing_priors={"ro.cap.summarize": ["ro.provider.x"]},
        demand_shape_priors={"recurring": ["shape.a"]},
        policy_proposals=({"proposal": "raise ceiling"},),
    )
    assert a1.priors_version == 1
    assert a1.policy_proposals[0]["proposal"] == "raise ceiling"

    # frozen
    try:
        a1.priors_version = 2
        raise SystemExit("field reassignment allowed")
    except AttributeError:
        pass

    # determinism
    a1b = build_priors_artifact(
        1, provider_priors={"ro.provider.x": {"reliability": "high"}},
        routing_priors={"ro.cap.summarize": ["ro.provider.x"]},
        demand_shape_priors={"recurring": ["shape.a"]},
        policy_proposals=({"proposal": "raise ceiling"},),
    )
    assert content_hash(a1) == content_hash(a1b)

    store = PriorsStore()
    assert store.current() is None
    ingested = store.ingest(to_dict(a1))
    assert store.current().priors_version == 1
    assert store.at_version(1).priors_version == 1

    # stale/duplicate refused
    try:
        store.ingest(to_dict(a1))
        raise SystemExit("duplicate version accepted")
    except StaleOrDuplicateVersionError:
        pass

    a0 = build_priors_artifact(1, {}, {}, {})  # same version, different content -> still stale
    try:
        store.ingest(to_dict(a0))
        raise SystemExit("stale version accepted")
    except StaleOrDuplicateVersionError:
        pass

    a2 = build_priors_artifact(2, {}, {}, {})
    store.ingest(to_dict(a2))
    assert store.current().priors_version == 2
    # replay pinning: version 1 still readable forever, unaffected by version 2
    assert store.at_version(1).priors_version == 1
    assert store.at_version(1).provider_priors["ro.provider.x"]["reliability"] == "high"

    try:
        store.at_version(99)
        raise SystemExit("unknown version accepted")
    except UnknownVersionError:
        pass

    # malformed payload refused
    try:
        store.ingest({"priors_version": "not an int"})
        raise SystemExit("malformed payload accepted")
    except MalformedPriorsPayloadError:
        pass

    print("priors selftest ok")
