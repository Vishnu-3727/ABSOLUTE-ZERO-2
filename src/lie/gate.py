"""LIE Admission Gate (LIE/00 §4.1, LIE/03 §3 stations 2-3, LIE/04 §6
Admission Gate contract). The single entry point for all experience:

- **Provenance check** -- is there a VAE attestation reference, is the
  trace closed, is the origin identifiable (LIE/00 §4.1).
- **Normalization onto the current vocabulary** -- every facet the
  candidate's envelope carries must already be a member of the current
  `FacetVocabulary`; the vocabulary version recorded in the envelope's
  attestation must not name a version ahead of the current one (R2).
- **Idempotent admission keyed on attested-unit identity (OPS-5)** -- one
  attestation reference yields at most one Ledger record, redelivery-safe,
  via an in-memory attestation-ref index checked before any write is
  attempted, and again via the Ledger's own identity-uniqueness check
  (ledger.py's `DuplicateIdentityError`) as a second line of defense.
- **Durable-append-then-acknowledge ordering** -- `admit()` only reports
  ADMITTED once `ExperienceLedger.append()` has confirmed a durable
  Storage commit; a Storage rejection is acknowledged as a REJECTED
  outcome, never partially admitted.
- **Rejection records with reasons to Observability, never the Ledger**
  (R1) -- every REJECTED outcome is also recorded on the injected
  telemetry double before `admit()` returns.

`admit()` takes an already-built `Episode` or `Decision` (episode.py /
decision.py already refused an incomplete envelope loud at construction
time, one layer below the Gate -- LIE/04 §6's "an envelope that cannot be
completed is a rejection, not a partial admit" is therefore satisfied
before this module ever sees the candidate; this module adds the
Gate-specific provenance/vocabulary/idempotency checks on top)."""
from dataclasses import dataclass

from .admission_receipt import AdmissionReceipt
from .decision import Decision
from .episode import Episode
from .ledger import DuplicateIdentityError, ExperienceLedger, LedgerAppendRejectedError
from .vocabulary import FacetVocabulary

ADMITTED = "admitted"
REJECTED = "rejected"
DEDUPED = "deduped"

OUTCOMES = (ADMITTED, REJECTED, DEDUPED)


class GateRefusal(Exception):
    """Base for gate.py refusals."""


class UnknownRecordKindError(GateRefusal):
    """admit() was handed something that is neither a built Episode nor a
    built Decision -- the Gate admits only LIE/01 §2's two experience-layer
    record kinds."""


@dataclass(frozen=True)
class AdmissionResult:
    outcome: str              # one of OUTCOMES
    identity: str
    ledger_position: object    # int on ADMITTED/DEDUPED, None on REJECTED
    reason: object              # str reason on REJECTED, None otherwise


class AdmissionGate:
    def __init__(self, ledger, vocabulary, telemetry):
        if not isinstance(ledger, ExperienceLedger):
            raise GateRefusal("gate.ledger_not_an_experience_ledger:" + repr(ledger))
        if not isinstance(vocabulary, FacetVocabulary):
            raise GateRefusal("gate.vocabulary_not_built:" + repr(vocabulary))
        self._ledger = ledger
        self._vocabulary = vocabulary
        self._telemetry = telemetry
        self._admitted_by_attestation = {}  # attestation_ref -> ledger position

    def admit(self, record):
        if not isinstance(record, (Episode, Decision)):
            raise UnknownRecordKindError("gate.unknown_record_kind:" + repr(type(record)))

        envelope = record.envelope
        attestation_ref = envelope.attestation.attestation_ref

        # OPS-5: one attested unit -> at most one Ledger record, ever,
        # regardless of redelivery. Checked before any write is attempted.
        if attestation_ref in self._admitted_by_attestation:
            return AdmissionResult(DEDUPED, envelope.identity,
                                    self._admitted_by_attestation[attestation_ref], None)

        reason = self._check_provenance(envelope) or self._check_vocabulary(envelope)
        if reason is not None:
            self._reject(envelope, attestation_ref, reason)
            return AdmissionResult(REJECTED, envelope.identity, None, reason)

        try:
            entry = self._ledger.append(AdmissionReceipt(record))
        except DuplicateIdentityError:
            # Second line of defense for OPS-5: the envelope identity is
            # already durable (e.g. a prior admission whose attestation-ref
            # index update was lost) -- answer from the existing entry,
            # never retry the write, never a fresh rejection.
            existing = self._ledger.by_identity(envelope.identity)
            self._admitted_by_attestation[attestation_ref] = existing.position
            return AdmissionResult(DEDUPED, envelope.identity, existing.position, None)
        except LedgerAppendRejectedError:
            self._reject(envelope, attestation_ref, "storage_rejected")
            return AdmissionResult(REJECTED, envelope.identity, None, "storage_rejected")

        self._admitted_by_attestation[attestation_ref] = entry.position
        return AdmissionResult(ADMITTED, envelope.identity, entry.position, None)

    def adopt_vocabulary(self, vocabulary):
        """Adopt a newer Curator-issued vocabulary version -- LIE/04 §6
        Gate "normalization onto the CURRENT vocabulary" once vocabulary
        evolution (Curator-owned, curator.py) exists. Forward-only: the
        vocabulary is versioned and additive (LIE/01 §7), so the Gate can
        only ever move to a strictly newer version; anything else is
        refused loud. This is NOT the Gate "mutating the vocabulary"
        (forbidden) -- the Curator minted the new version; the Gate merely
        checks candidates against it from now on."""
        if not isinstance(vocabulary, FacetVocabulary):
            raise GateRefusal("gate.vocabulary_not_built:" + repr(vocabulary))
        if vocabulary.version <= self._vocabulary.version:
            raise GateRefusal("gate.vocabulary_version_not_advancing:current=" +
                               str(self._vocabulary.version) + ":proposed=" +
                               str(vocabulary.version))
        self._vocabulary = vocabulary

    def _reject(self, envelope, attestation_ref, reason):
        self._telemetry.record("admission_rejected", {
            "identity": envelope.identity, "attestation_ref": attestation_ref, "reason": reason,
        })

    def _check_provenance(self, envelope):
        if not envelope.attestation.attestation_ref:
            return "missing_attestation_ref"
        if not envelope.attestation.trace_closed:
            return "trace_not_closed"
        if not envelope.origin.project:
            return "origin_not_identifiable"
        return None

    def _check_vocabulary(self, envelope):
        if envelope.attestation.vocabulary_version > self._vocabulary.version:
            return "vocabulary_version_ahead_of_current"
        for facet in envelope.facets:
            if facet not in self._vocabulary.terms:
                return "unknown_facet:" + facet
        return None


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .ledger import ExperienceLedger
    from .storage_double import StorageDouble
    from .telemetry_double import ObservabilityDouble
    from .vocabulary import build_vocabulary

    def _episode(identity, attestation_ref="trace:t1", trace_closed=True, project="asunama",
                 facets=("ros2",), vocabulary_version=1):
        env = envelope_mod.build_envelope(
            identity,
            envelope_mod.build_attestation(attestation_ref, trace_closed, vocabulary_version),
            envelope_mod.build_origin(project, "isaac-sim", None, "epoch-0"),
            facets, ())
        return episode_mod.build_episode(env, situation={"a": 1}, approach={"b": 1},
                                          outcome={"c": 1}, cost={"d": 1})

    from . import episode as episode_mod

    def _new_gate():
        return AdmissionGate(ExperienceLedger(StorageDouble()), build_vocabulary(1, {"ros2", "cuda"}),
                              ObservabilityDouble())

    # -- ordinary admission --------------------------------------------------
    gate = _new_gate()
    result = gate.admit(_episode("episode:e1"))
    assert result.outcome == ADMITTED
    assert result.ledger_position == 1
    assert gate._ledger.by_position(1).record.envelope.identity == "episode:e1"

    # -- OPS-5 idempotency: redelivery of the SAME attestation, even with a
    # different envelope identity, dedupes rather than admitting twice -----
    dup = gate.admit(_episode("episode:e1-retry", attestation_ref="trace:t1"))
    assert dup.outcome == DEDUPED
    assert dup.ledger_position == 1
    assert gate._ledger.current_position() == 1  # no second ledger record

    # -- provenance rejections: reasons recorded to telemetry, NEVER the ledger (R1) --
    gate2 = _new_gate()
    rejected = gate2.admit(_episode("episode:e2", attestation_ref="trace:t2", trace_closed=False))
    assert rejected.outcome == REJECTED and rejected.reason == "trace_not_closed"
    assert gate2._ledger.current_position() == 0
    assert gate2._telemetry.by_kind("admission_rejected")[0]["reason"] == "trace_not_closed"

    # origin_not_identifiable is a defense-in-depth check: build_origin()
    # already refuses an empty project at envelope-construction time, so
    # exercising the Gate's own check requires bypassing that factory (an
    # Origin built directly, skipping validation) -- the realistic bypass
    # a hand-rolled caller could still produce.
    gate3 = _new_gate()
    bad_origin_env = envelope_mod.build_envelope(
        "episode:e3", envelope_mod.build_attestation("trace:t3", True, 1),
        envelope_mod.Origin(project="", environment="isaac-sim", contributor=None, occurred_at="epoch-0"),
        ("ros2",), ())
    bad_origin_episode = episode_mod.build_episode(bad_origin_env, situation={"a": 1}, approach={"b": 1},
                                                     outcome={"c": 1}, cost={"d": 1})
    rejected2 = gate3.admit(bad_origin_episode)
    assert rejected2.reason == "origin_not_identifiable"

    gate4 = _new_gate()
    rejected3 = gate4.admit(_episode("episode:e4", attestation_ref="trace:t4", facets=("ros2", "unknown_x")))
    assert rejected3.reason == "unknown_facet:unknown_x"

    gate5 = _new_gate()
    rejected4 = gate5.admit(_episode("episode:e5", attestation_ref="trace:t5", vocabulary_version=99))
    assert rejected4.reason == "vocabulary_version_ahead_of_current"

    # -- durable-append-then-acknowledge: a Storage rejection is a REJECTED
    # admission outcome, never partial, and never durable -------------------
    storage6 = StorageDouble()
    storage6.script_reject("lie/ledger/episode:e6")
    gate6 = AdmissionGate(ExperienceLedger(storage6), build_vocabulary(1, {"ros2"}), ObservabilityDouble())
    rejected5 = gate6.admit(_episode("episode:e6", attestation_ref="trace:t6"))
    assert rejected5.outcome == REJECTED and rejected5.reason == "storage_rejected"
    assert gate6._telemetry.by_kind("admission_rejected")[0]["reason"] == "storage_rejected"

    # -- a rejection never touches the ledger's next attempt: the SAME
    # attestation, resubmitted after fixing the problem, admits fresh ------
    fixed = gate2.admit(_episode("episode:e2-fixed", attestation_ref="trace:t2", trace_closed=True))
    assert fixed.outcome == ADMITTED

    # unknown record kind refused loud
    try:
        gate.admit("not a record")
        raise SystemExit("non-record admitted")
    except UnknownRecordKindError:
        pass

    print("gate selftest ok")
