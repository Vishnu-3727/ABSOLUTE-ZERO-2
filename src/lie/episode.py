"""LIE Episode (LIE/01 §4.1) -- the universal experience record: one
attested, closed, verdict-tagged unit of completed engineering work.
Conceptually four parts, all required: *situation* (what was needed, under
what constraints), *approach* (what was done), *outcome* (VAE verdict,
resulting state, errors), *cost* (time, resources, retries). Content
schemas within each part are later-phase material (LIE/01 §11) -- this
phase fixes only that each part is a present, non-empty, structured mapping,
frozen the same way `rules.py`'s `deadlines` field is (`MappingProxyType`),
so an `Episode` is immutable in full, not just at its top level.

`Episode` carries a completed `Envelope` (envelope.py) -- an envelope that
cannot be completed already raised at `build_envelope` time (LIE/04 §6);
`build_episode` adds only the four content-part checks on top."""
from dataclasses import dataclass
from types import MappingProxyType

from .envelope import Attestation, Envelope, from_dict as envelope_from_dict, \
    to_dict as envelope_to_dict


class EpisodeRefusal(Exception):
    """Base for episode.py refusals."""


class MalformedEpisodeError(EpisodeRefusal):
    """A required episode part is missing or structurally invalid."""


def _freeze_part(label, value):
    if not isinstance(value, dict) or not value:
        raise MalformedEpisodeError("episode.empty_or_bad_" + label + ":" + repr(value))
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class Episode:
    envelope: Envelope
    situation: MappingProxyType
    approach: MappingProxyType
    outcome: MappingProxyType
    cost: MappingProxyType


def build_episode(envelope, situation, approach, outcome, cost):
    if not isinstance(envelope, Envelope):
        raise MalformedEpisodeError("episode.envelope_not_built:" + repr(envelope))
    if not isinstance(envelope.attestation, Attestation):
        # Experience records are VAE-attested only (INV-1); a derivation-
        # flavored attestation (Phase 2, derived.py) has no path into the
        # experience layer.
        raise MalformedEpisodeError(
            "episode.requires_vae_attestation:" + repr(type(envelope.attestation)))
    return Episode(envelope=envelope,
                    situation=_freeze_part("situation", situation),
                    approach=_freeze_part("approach", approach),
                    outcome=_freeze_part("outcome", outcome),
                    cost=_freeze_part("cost", cost))


def to_dict(episode):
    return {
        "kind": "episode",
        "envelope": envelope_to_dict(episode.envelope),
        "situation": dict(episode.situation),
        "approach": dict(episode.approach),
        "outcome": dict(episode.outcome),
        "cost": dict(episode.cost),
    }


def from_dict(data):
    if data.get("kind") != "episode":
        raise MalformedEpisodeError("episode.wrong_kind_in_dict:" + repr(data.get("kind")))
    envelope = envelope_from_dict(data["envelope"])
    return build_episode(envelope, data["situation"], data["approach"], data["outcome"], data["cost"])


if __name__ == "__main__":
    from . import envelope as envelope_mod

    env = envelope_mod.build_envelope(
        "episode:e1",
        envelope_mod.build_attestation("trace:t1", True, 1),
        envelope_mod.build_origin("asunama", "isaac-sim", "vishnu", "epoch-0"),
        ("ros2",),
        (envelope_mod.build_relation("about", "ums:repo/asunama"),))

    ep = build_episode(env, situation={"needed": "gps-denied nav"}, approach={"steps": ["orb-slam"]},
                        outcome={"verdict": "passed"}, cost={"retries": 0})
    assert ep.situation["needed"] == "gps-denied nav"

    # frozen at every level: top-level field reassignment refused
    try:
        ep.outcome = {}
        raise SystemExit("episode field reassignment allowed")
    except AttributeError:
        pass
    # inner content is a MappingProxyType -- refuses item assignment too
    try:
        ep.outcome["verdict"] = "failed"
        raise SystemExit("episode content part mutation allowed")
    except TypeError:
        pass

    # each of the four parts is required and must be a non-empty mapping
    for missing in ("situation", "approach", "outcome", "cost"):
        kwargs = {"situation": {"a": 1}, "approach": {"a": 1}, "outcome": {"a": 1}, "cost": {"a": 1}}
        kwargs[missing] = {}
        try:
            build_episode(env, **kwargs)
            raise SystemExit("empty " + missing + " accepted")
        except MalformedEpisodeError:
            pass

    # round-trip, deterministic serialization (INV-7)
    restored = from_dict(to_dict(ep))
    assert restored == ep

    print("episode selftest ok")
