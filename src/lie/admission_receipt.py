"""LIE admission receipt -- the structural enforcement of INV-1 ("only the
Gate writes experience"). `AdmissionReceipt` is minted exactly once per
admitted record, only by `AdmissionGate.admit()` (gate.py) once provenance
and vocabulary checks have both passed. `ExperienceLedger.append()`
(ledger.py) requires one and refuses anything else -- a caller that wants
to append to the Ledger without going through the Gate has to reimplement
the Gate's own checks to construct a receipt, which is the same
"one door" property `intake.py`'s `mark_terminal` seam gives VAE's
choreography, applied here to the write path itself.

Lives in its own module (not gate.py or ledger.py) purely to avoid a
circular import between the two -- both need the type, neither should
import the other."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AdmissionReceipt:
    record: object  # an Episode or Decision whose envelope already passed the Gate's checks
