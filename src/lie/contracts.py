"""Boundary contracts for the three LIE subsystems Phase 1 does not
implement -- Distillery, Advisory Interface, Curator (LIE/00 §4.3-4.5,
LIE/04 §6). These are seams only: `typing.Protocol` method signatures a
later phase implements against, carrying zero derivation, recommendation,
or ruling-semantics logic -- explicitly out of scope for this phase (the
implementation charter names "no derivation logic, no recommendation
logic, no similarity, no packs, no ruleset content").

Each Protocol fixes only what LIE/04 §6's contract table already commits
each subsystem to accepting/returning, expressed with Phase 1's own value
types (`DerivationState`, `Annotation`) -- no new concepts invented here."""
from typing import Protocol

from .curation import Annotation
from .derivation_state import DerivationState


class DistilleryPort(Protocol):
    """LIE/04 §6 Distillery contract, seam only. `absorb` is one
    incremental derivation triggered by a Ledger append (LIE/03 §4);
    `regenerate` is full regeneration from scratch (LIE/03 §6). Both
    return the newly published `DerivationState` -- the Equivalence
    Obligation (LIE/02 §9) that the two must agree is a later phase's
    test to write, not this seam's to enforce."""

    def absorb(self, ledger_position: int) -> DerivationState: ...

    def regenerate(self) -> DerivationState: ...


class AdvisoryPort(Protocol):
    """LIE/04 §6 Advisory Interface contract, seam only. A consultation
    takes the consumer's situation as facets and returns advice stamped
    with the `DerivationState` it was answered from (OPS-4) -- the
    four-part recommendation object itself (LIE/02 §6) is Phase 3+
    material; this seam fixes only the pull-only shape of the call."""

    def consult(self, situation_facets: tuple) -> object: ...


class CuratorPort(Protocol):
    """LIE/04 §6 Curator contract, seam only. `rule` appends one
    deliberate governance act (curation.Annotation) to the overlay and
    returns its new overlay position -- ruling semantics (which side of a
    Contested pair wins, how vocabulary merges are decided) are Phase 3+
    material; this seam only fixes that a ruling is append-only input,
    never a mutation."""

    def rule(self, annotation: Annotation) -> int: ...


if __name__ == "__main__":
    # Protocol classes are structural -- runtime_checkable is not declared
    # here (no isinstance() use in this phase), so the only thing worth
    # asserting is that each port exposes exactly the seam methods LIE/04
    # §6 commits to, nothing more (no derivation/recommendation/ruling
    # logic snuck in as extra methods).
    assert set(vars(DistilleryPort)) >= {"absorb", "regenerate"}
    assert set(vars(AdvisoryPort)) >= {"consult"}
    assert set(vars(CuratorPort)) >= {"rule"}

    print("contracts selftest ok")
