"""RO/04 §7 — Cancellation (RO/05 §10 blueprint group G5).

RO originates none of the four cancellation origins (RO-E10): a
`CancellationSignal` is always injected input — a recorded artifact with a
named origin, built by whatever component observed the trigger (Kernel,
policy, workflow supersession, or the user-authority chain) and handed to
`invocation.run_attempts` as data. No constructor path in invocation.py (or
anywhere else in RO) creates one; that is this module's sole authority.
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

from .outcome import CANCELLATION_ORIGINS as ORIGINS  # re-export — single source of truth


class CancellationRefusal(Exception):
    """Base for cancellation-signal construction refusals."""


class UnknownOriginError(CancellationRefusal):
    """RO/04 §7: origin outside the closed four."""


@dataclass(frozen=True)
class CancellationSignal:
    origin: str
    coordinates: MappingProxyType
    signal_id: str


def build_cancellation_signal(origin, coordinates, signal_id):
    """RO/04 §7 Recorded-signal rule: origin must be one of the closed four;
    `coordinates` is whatever recorded-artifact reference makes this signal
    replayable (RO-E10 "so replay includes it")."""
    if origin not in ORIGINS:
        raise UnknownOriginError("cancellation.unknown_origin:" + str(origin))
    if not signal_id:
        raise CancellationRefusal("cancellation.missing_signal_id")
    return CancellationSignal(
        origin=origin, coordinates=MappingProxyType(dict(coordinates or {})), signal_id=signal_id,
    )


def to_dict(signal):
    return {"origin": signal.origin, "coordinates": dict(signal.coordinates),
            "signal_id": signal.signal_id}


def canonical(signal):
    return json.dumps(to_dict(signal), sort_keys=True, separators=(",", ":")).encode()


def content_hash(signal):
    return hashlib.sha256(canonical(signal)).hexdigest()


if __name__ == "__main__":
    sig = build_cancellation_signal("user", {"request_id": "r1"}, "sig-1")
    assert sig.origin == "user"
    assert sig.coordinates["request_id"] == "r1"

    for origin in ORIGINS:
        build_cancellation_signal(origin, {}, "sig-" + origin)

    try:
        build_cancellation_signal("aliens", {}, "sig-x")
        raise SystemExit("unknown origin accepted")
    except UnknownOriginError:
        pass

    try:
        build_cancellation_signal("user", {}, "")
        raise SystemExit("missing signal_id accepted")
    except CancellationRefusal:
        pass

    # frozen
    try:
        sig.origin = "kernel"
        raise SystemExit("frozen signal mutation allowed")
    except AttributeError:
        pass

    # determinism
    sig2 = build_cancellation_signal("user", {"request_id": "r1"}, "sig-1")
    assert canonical(sig) == canonical(sig2)
    assert content_hash(sig) == content_hash(sig2)

    print("cancellation selftest ok")
