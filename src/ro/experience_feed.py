"""RO/05 §5 Out flow (RO -> Experience) — the full decision/outcome stream
as a reference-shaped batch. Deterministic ordering = caller's input order
preserved (RO/05 §2 Ordering: "seal order within one request only").

`build_experience_batch(decision_records, sealed_records)` folds the two
record kinds §5's Out row lists RO produces: "the full decision stream —
approvals AND the four non-approvals" and "sealed outcome records; budget
reconciliations; failure classes". Reconciliation facts (recovery kind,
failure class, budget consumed/remaining) travel with each outcome ref so
Experience can compute utilization/retry-frequency metrics downstream
(RO/05 §7) without a second read of the sealed record.

Verification acceptance results travel via Verification's OWN events (§5
parenthetical) — explicitly NOT RO's job; this module never reaches for
them."""
from dataclasses import dataclass
import hashlib
import json

from .decision_gate import content_hash as decision_content_hash
from .outcome import content_hash as outcome_content_hash


@dataclass(frozen=True)
class ExperienceBatch:
    decision_refs: tuple    # tuple of {"decision_record_content_hash", "outcome"}
    outcome_refs: tuple     # tuple of reconciliation-fact dicts (see module docstring)
    batch_content_hash: str


def _decision_ref(record):
    return {
        "decision_record_content_hash": decision_content_hash(record),
        "outcome": record.outcome,
    }


def _outcome_ref(record):
    return {
        "record_content_hash": outcome_content_hash(record),
        "request_content_hash": record.request_content_hash,
        "resolution_content_hash": record.resolution_content_hash,
        "attempt_index": record.attempt_index,
        "recovery_kind": record.recovery_kind,
        "failure_class": record.failure_class,
        "cancellation_origin": record.cancellation_origin,
        "budget_consumed": record.budget_consumed,
        "budget_remaining": record.budget_remaining,
    }


def build_experience_batch(decision_records, sealed_records):
    """`decision_records`/`sealed_records`: iterables of decision_gate.
    DecisionRecord / outcome.SealedOutcomeRecord, in the order the caller
    wants them preserved (RO/05 §2 Ordering — no reordering happens here)."""
    decision_refs = tuple(_decision_ref(r) for r in decision_records)
    outcome_refs = tuple(_outcome_ref(r) for r in sealed_records)
    payload = {"decision_refs": list(decision_refs), "outcome_refs": list(outcome_refs)}
    batch_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ExperienceBatch(decision_refs=decision_refs, outcome_refs=outcome_refs,
                            batch_content_hash=batch_hash)


def to_dict(batch):
    return {
        "decision_refs": [dict(r) for r in batch.decision_refs],
        "outcome_refs": [dict(r) for r in batch.outcome_refs],
        "batch_content_hash": batch.batch_content_hash,
    }


if __name__ == "__main__":
    from types import MappingProxyType

    from .decision_gate import DecisionRecord
    from .outcome import build_sealed_outcome

    approved = DecisionRecord(
        outcome="REASONING_APPROVED", justification=MappingProxyType({}), decided_from=MappingProxyType({}),
        approved_capability_id="ro.cap.x", approved_required_rung="C1",
        approved_scope=MappingProxyType({"description": "d", "granularity": "g", "narrowing": None}),
    )
    rejected = DecisionRecord(
        outcome="REASONING_REJECTED", justification=MappingProxyType({}), decided_from=MappingProxyType({}),
        approved_capability_id=None, approved_required_rung=None, approved_scope=None,
    )
    r1 = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED", failure_class="F1",
        provider_id="p", budget_consumed=10, budget_remaining=90,
    )
    r2 = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=2, attempt_history_refs=(), recovery_kind="RETURNED",
        provider_id="p", budget_consumed=20, budget_remaining=70, output={"summary": "ok"},
    )

    batch = build_experience_batch((rejected, approved), (r1, r2))
    assert batch.decision_refs[0]["outcome"] == "REASONING_REJECTED"  # order preserved, non-approval first
    assert batch.decision_refs[1]["outcome"] == "REASONING_APPROVED"
    assert batch.outcome_refs[0]["failure_class"] == "F1"
    assert batch.outcome_refs[1]["recovery_kind"] == "RETURNED"
    assert batch.outcome_refs[1]["budget_consumed"] == 20  # reconciliation fact present
    assert "output" not in json.dumps(to_dict(batch))  # reference-shaped, no verbatim output

    # determinism: same inputs -> same batch hash
    batch2 = build_experience_batch((rejected, approved), (r1, r2))
    assert batch.batch_content_hash == batch2.batch_content_hash

    # order matters (RO/05 §2 Ordering)
    batch3 = build_experience_batch((approved, rejected), (r1, r2))
    assert batch3.batch_content_hash != batch.batch_content_hash

    print("experience_feed selftest ok")
