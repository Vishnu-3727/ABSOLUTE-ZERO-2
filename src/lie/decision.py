"""LIE Decision (LIE/01 §4.2) -- the record of a choice: the question
faced, the options considered, the option chosen, the rationale, the
constraints in force, and the consequences expected at decision time.
Admitted like all experience, through the Gate, attested by the verified
work that enacted it (`enacts` relation, LIE/01 §6) -- this module fixes
only the record shape; enactment linkage is ordinary envelope content
(a `Relation`), not a separate mechanism.

Frozen, validated at construction: `chosen` must be one of `options` (a
decision cannot choose what it did not consider), `constraints` and
`consequences_expected` are frozen mappings (may be empty -- "no
constraints were in force" is itself a legitimate recorded fact, unlike
Episode's four parts which must be non-empty)."""
from dataclasses import dataclass
from types import MappingProxyType

from .envelope import Envelope, from_dict as envelope_from_dict, to_dict as envelope_to_dict


class DecisionRefusal(Exception):
    """Base for decision.py refusals."""


class MalformedDecisionError(DecisionRefusal):
    """A required decision field is missing or structurally invalid."""


def _require_nonempty_str(label, value):
    if not isinstance(value, str) or not value:
        raise MalformedDecisionError("decision.bad_" + label + ":" + repr(value))
    return value


def _freeze_mapping(label, value):
    if not isinstance(value, dict):
        raise MalformedDecisionError("decision.bad_" + label + ":" + repr(value))
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class Decision:
    envelope: Envelope
    question: str
    options: tuple
    chosen: str
    rationale: str
    constraints: MappingProxyType
    consequences_expected: MappingProxyType


def build_decision(envelope, question, options, chosen, rationale, constraints, consequences_expected):
    if not isinstance(envelope, Envelope):
        raise MalformedDecisionError("decision.envelope_not_built:" + repr(envelope))
    _require_nonempty_str("question", question)
    if not isinstance(options, (tuple, list)) or not options:
        raise MalformedDecisionError("decision.empty_or_bad_options:" + repr(options))
    option_tuple = tuple(options)
    for o in option_tuple:
        if not isinstance(o, str) or not o:
            raise MalformedDecisionError("decision.bad_option:" + repr(o))
    _require_nonempty_str("chosen", chosen)
    if chosen not in option_tuple:
        raise MalformedDecisionError("decision.chosen_not_among_options:" + repr(chosen))
    _require_nonempty_str("rationale", rationale)
    return Decision(envelope=envelope, question=question, options=option_tuple, chosen=chosen,
                     rationale=rationale, constraints=_freeze_mapping("constraints", constraints),
                     consequences_expected=_freeze_mapping("consequences_expected", consequences_expected))


def to_dict(decision):
    return {
        "kind": "decision",
        "envelope": envelope_to_dict(decision.envelope),
        "question": decision.question,
        "options": list(decision.options),
        "chosen": decision.chosen,
        "rationale": decision.rationale,
        "constraints": dict(decision.constraints),
        "consequences_expected": dict(decision.consequences_expected),
    }


def from_dict(data):
    if data.get("kind") != "decision":
        raise MalformedDecisionError("decision.wrong_kind_in_dict:" + repr(data.get("kind")))
    envelope = envelope_from_dict(data["envelope"])
    return build_decision(envelope, data["question"], tuple(data["options"]), data["chosen"],
                           data["rationale"], data["constraints"], data["consequences_expected"])


if __name__ == "__main__":
    from . import envelope as envelope_mod

    env = envelope_mod.build_envelope(
        "decision:d1",
        envelope_mod.build_attestation("trace:t1", True, 1),
        envelope_mod.build_origin("asunama", "isaac-sim", "vishnu", "epoch-0"),
        ("ros2",), ())

    dec = build_decision(env, question="which SLAM stack?", options=("orb-slam3", "vins-fusion"),
                          chosen="orb-slam3", rationale="better monocular robustness",
                          constraints={"gps": "denied"}, consequences_expected={"risk": "moderate"})
    assert dec.chosen == "orb-slam3"

    # frozen: top-level and inner content both immutable
    try:
        dec.chosen = "vins-fusion"
        raise SystemExit("decision field reassignment allowed")
    except AttributeError:
        pass
    try:
        dec.constraints["gps"] = "available"
        raise SystemExit("decision constraint mutation allowed")
    except TypeError:
        pass

    # chosen must be among options
    try:
        build_decision(env, "q", ("a", "b"), "c", "r", {}, {})
        raise SystemExit("chosen option outside options accepted")
    except MalformedDecisionError:
        pass

    # empty constraints/consequences ARE legitimate (unlike Episode's parts)
    dec_bare = build_decision(env, "q", ("a",), "a", "r", {}, {})
    assert dec_bare.constraints == {}

    # round-trip, deterministic serialization (INV-7)
    restored = from_dict(to_dict(dec))
    assert restored == dec

    print("decision selftest ok")
