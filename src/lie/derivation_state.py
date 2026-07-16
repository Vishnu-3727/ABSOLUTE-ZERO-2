"""LIE Derivation State (LIE/03 §2). The identity of a published
intelligence layer: the triple (ledger position, curation overlay
position, ruleset version). Fixed here as a plain, human-readable value
type -- no publication, no layer, no ruleset content; those are Phase 3+
material. This phase needs the triple only as the value OPS-4 requires
every advisory response to stamp, and as the seam `DistilleryPort.absorb`/
`regenerate` (contracts.py) return."""
from dataclasses import dataclass


class DerivationStateRefusal(Exception):
    """Base for derivation_state.py refusals."""


class MalformedDerivationStateError(DerivationStateRefusal):
    """A derivation state component failed structural validation."""


def _nonneg_int(label, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MalformedDerivationStateError("derivation_state.bad_" + label + ":" + repr(value))
    return value


@dataclass(frozen=True)
class DerivationState:
    ledger_position: int
    overlay_position: int
    ruleset_version: int


def build_derivation_state(ledger_position, overlay_position, ruleset_version):
    return DerivationState(
        ledger_position=_nonneg_int("ledger_position", ledger_position),
        overlay_position=_nonneg_int("overlay_position", overlay_position),
        ruleset_version=_nonneg_int("ruleset_version", ruleset_version))


def to_dict(state):
    return {"ledger_position": state.ledger_position, "overlay_position": state.overlay_position,
            "ruleset_version": state.ruleset_version}


def from_dict(data):
    return build_derivation_state(data["ledger_position"], data["overlay_position"],
                                   data["ruleset_version"])


if __name__ == "__main__":
    s1 = build_derivation_state(3, 1, 1)
    s2 = build_derivation_state(3, 1, 1)
    assert s1 == s2  # value equality, no identity gimmicks

    try:
        s1.ledger_position = 4
        raise SystemExit("derivation state field reassignment allowed")
    except AttributeError:
        pass

    for bad in (-1, "x", 1.5, True):
        try:
            build_derivation_state(bad, 0, 1)
            raise SystemExit("bad ledger_position accepted: " + repr(bad))
        except MalformedDerivationStateError:
            pass

    assert from_dict(to_dict(s1)) == s1

    print("derivation_state selftest ok")
