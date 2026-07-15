"""RO/04 §9 — the Sealed Outcome Record (RO/05 §10 blueprint group G5).

Sealing is unconditional (RO/04 §2 "Nothing vanishes"): every attempt,
however it ended, produces exactly one `SealedOutcomeRecord`. This module
owns the record SHAPE only — OS-owned, versioned, provider-independent
(RO-E12) — never the governance decisions that fill it in (that is
invocation.py's job).

Recovery/failure-class legality is enforced here, structurally, at
construction (`build_sealed_outcome`), so no caller can seal an
inconsistent combination:

  - RETURNED  -> failure_class None, cancellation_origin None, output may
    be present (the only recovery kind ever carrying a verbatim output;
    RO/04 §6 "an expired attempt never half-succeeds" extends to every
    other kind too).
  - FAILED    -> failure_class one of F1-F8 EXCEPT F7 (F7 is reserved for
    EXPIRED — the boundary's "expired" return is architecturally distinct
    from its "failed" return, RO/04 §1 closed four); cancellation_origin
    None; output None (metadata only).
  - EXPIRED   -> failure_class exactly "F7" (RO/04 §5 "Expired = F7 recovery
    kind EXPIRED (failure_class F7 recorded)"); cancellation_origin None;
    output None — partial output belongs in metadata (RO/04 §6).
  - CANCELLED -> failure_class None; cancellation_origin one of the closed
    four origins (RO/04 §7); output None — partial output belongs in
    metadata (RO/04 §7 "no partial adoption").

record_version=1 is OS-owned (RO-E12); every record instance carries it so
future shape changes are versioned, never silent.
"""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

RECORD_VERSION = 1

RECOVERY_KINDS = ("RETURNED", "FAILED", "EXPIRED", "CANCELLED")

# RO/04 §5 — closed at class level; sub-classes are data (RO-E7).
FAILURE_CLASSES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")

# RO/04 §7 — closed at four (RO-E10). Owned here (not cancellation.py) so
# this module's own construction-time validation never depends on a module
# that, per the implementation's dependency order, comes after it;
# cancellation.py imports this tuple rather than redeclaring it.
CANCELLATION_ORIGINS = ("user", "kernel", "policy", "workflow")


class OutcomeRefusal(Exception):
    """Base for sealed-outcome construction refusals."""


class InconsistentOutcomeError(OutcomeRefusal):
    """A recovery-kind / failure-class / origin / output combination that
    RO/04 §9 forbids (see module docstring table)."""


def _freeze_mapping(d):
    return MappingProxyType(dict(d or {}))


def build_sealed_outcome(
    *, request_content_hash, resolution_content_hash, preparation_coordinates,
    attempt_index, attempt_history_refs, recovery_kind, provider_id,
    budget_consumed, budget_remaining,
    failure_class=None, cancellation_origin=None, timing=None, output=None,
    metadata=None,
):
    """Construct one immutable `SealedOutcomeRecord`. Fails loud (
    InconsistentOutcomeError / ValueError) on any RO/04 §9 shape violation —
    never seals a defective record silently."""
    if recovery_kind not in RECOVERY_KINDS:
        raise ValueError("outcome.unknown_recovery_kind:" + str(recovery_kind))
    if not isinstance(attempt_index, int) or isinstance(attempt_index, bool) or attempt_index < 1:
        raise ValueError("outcome.bad_attempt_index:" + repr(attempt_index))
    attempt_history_refs = tuple(attempt_history_refs or ())
    if not all(isinstance(r, str) for r in attempt_history_refs):
        raise ValueError("outcome.bad_attempt_history_refs:" + repr(attempt_history_refs))
    for label, value in (("budget_consumed", budget_consumed), ("budget_remaining", budget_remaining)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("outcome.bad_" + label + ":" + repr(value))

    if recovery_kind == "RETURNED":
        if failure_class is not None:
            raise InconsistentOutcomeError("outcome.returned_with_failure_class:" + str(failure_class))
        if cancellation_origin is not None:
            raise InconsistentOutcomeError("outcome.returned_with_cancellation_origin")
    elif recovery_kind == "FAILED":
        if failure_class not in FAILURE_CLASSES or failure_class == "F7":
            raise InconsistentOutcomeError("outcome.failed_without_valid_failure_class:" + str(failure_class))
        if cancellation_origin is not None:
            raise InconsistentOutcomeError("outcome.failed_with_cancellation_origin")
        if output is not None:
            raise InconsistentOutcomeError("outcome.failed_with_output")
    elif recovery_kind == "EXPIRED":
        if failure_class != "F7":
            raise InconsistentOutcomeError("outcome.expired_without_f7:" + str(failure_class))
        if cancellation_origin is not None:
            raise InconsistentOutcomeError("outcome.expired_with_cancellation_origin")
        if output is not None:
            raise InconsistentOutcomeError("outcome.expired_with_output")
    else:  # CANCELLED
        if failure_class is not None:
            raise InconsistentOutcomeError("outcome.cancelled_with_failure_class:" + str(failure_class))
        if cancellation_origin not in CANCELLATION_ORIGINS:
            raise InconsistentOutcomeError("outcome.cancelled_without_origin:" + str(cancellation_origin))
        if output is not None:
            raise InconsistentOutcomeError("outcome.cancelled_with_output")

    return SealedOutcomeRecord(
        record_version=RECORD_VERSION,
        request_content_hash=request_content_hash,
        resolution_content_hash=resolution_content_hash,
        preparation_coordinates=_freeze_mapping(preparation_coordinates),
        attempt_index=attempt_index,
        attempt_history_refs=attempt_history_refs,
        recovery_kind=recovery_kind,
        failure_class=failure_class,
        timing=_freeze_mapping(timing),
        budget_consumed=budget_consumed,
        budget_remaining=budget_remaining,
        cancellation_origin=cancellation_origin,
        provider_id=provider_id,
        output=output,
        metadata=_freeze_mapping(metadata),
    )


@dataclass(frozen=True)
class SealedOutcomeRecord:
    record_version: int
    request_content_hash: str
    resolution_content_hash: str
    preparation_coordinates: MappingProxyType
    attempt_index: int
    attempt_history_refs: tuple
    recovery_kind: str
    failure_class: object          # str | None
    timing: MappingProxyType       # verbatim recorded facts (RO/04 §9) — never a clock read here
    budget_consumed: int
    budget_remaining: int
    cancellation_origin: object    # str | None
    provider_id: object            # str | None — audit only (RO/04 §3, RO-E12)
    output: object                 # dict | None — verbatim, unjudged (RO-E8)
    metadata: MappingProxyType     # extra recorded facts (partial output, race resolution, ...)


def _unfreeze(value):
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _unfreeze(v) for k, v in dict(value).items()}
    if isinstance(value, (tuple, list)):
        return [_unfreeze(v) for v in value]
    return value


def to_dict(record):
    return {
        "record_version": record.record_version,
        "request_content_hash": record.request_content_hash,
        "resolution_content_hash": record.resolution_content_hash,
        "preparation_coordinates": _unfreeze(record.preparation_coordinates),
        "attempt_index": record.attempt_index,
        "attempt_history_refs": list(record.attempt_history_refs),
        "recovery_kind": record.recovery_kind,
        "failure_class": record.failure_class,
        "timing": _unfreeze(record.timing),
        "budget_consumed": record.budget_consumed,
        "budget_remaining": record.budget_remaining,
        "cancellation_origin": record.cancellation_origin,
        "provider_id": record.provider_id,
        "output": _unfreeze(record.output),
        "metadata": _unfreeze(record.metadata),
    }


def canonical(record):
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


if __name__ == "__main__":
    rec = build_sealed_outcome(
        request_content_hash="reqhash", resolution_content_hash="reshash",
        preparation_coordinates={"a": 1}, attempt_index=1, attempt_history_refs=(),
        recovery_kind="RETURNED", provider_id="ro.provider.x",
        budget_consumed=10, budget_remaining=90, output={"summary": "ok"},
    )
    assert rec.record_version == 1
    assert rec.output == {"summary": "ok"}

    # frozen
    try:
        rec.attempt_index = 2
        raise SystemExit("frozen record mutation allowed")
    except AttributeError:
        pass

    # RETURNED + failure_class refused
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="RETURNED",
            provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F1",
        )
        raise SystemExit("RETURNED with failure_class accepted")
    except InconsistentOutcomeError:
        pass

    # FAILED without failure_class refused
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED",
            provider_id="p", budget_consumed=0, budget_remaining=1,
        )
        raise SystemExit("FAILED without failure_class accepted")
    except InconsistentOutcomeError:
        pass

    # FAILED with F7 refused (F7 reserved for EXPIRED)
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED",
            provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F7",
        )
        raise SystemExit("FAILED with F7 accepted")
    except InconsistentOutcomeError:
        pass

    # EXPIRED must carry exactly F7
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="EXPIRED",
            provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F1",
        )
        raise SystemExit("EXPIRED without F7 accepted")
    except InconsistentOutcomeError:
        pass
    expired = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="EXPIRED",
        provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F7",
    )
    assert expired.failure_class == "F7"

    # CANCELLED without origin refused
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="CANCELLED",
            provider_id="p", budget_consumed=0, budget_remaining=1,
        )
        raise SystemExit("CANCELLED without origin accepted")
    except InconsistentOutcomeError:
        pass
    cancelled = build_sealed_outcome(
        request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
        attempt_index=1, attempt_history_refs=(), recovery_kind="CANCELLED",
        provider_id="p", budget_consumed=0, budget_remaining=1, cancellation_origin="user",
    )
    assert cancelled.cancellation_origin == "user"

    # non-RETURNED with output refused
    try:
        build_sealed_outcome(
            request_content_hash="r", resolution_content_hash="s", preparation_coordinates={},
            attempt_index=1, attempt_history_refs=(), recovery_kind="FAILED",
            provider_id="p", budget_consumed=0, budget_remaining=1, failure_class="F1",
            output={"leak": True},
        )
        raise SystemExit("FAILED with output accepted")
    except InconsistentOutcomeError:
        pass

    # determinism: identical inputs -> identical canonical bytes / hash
    rec2 = build_sealed_outcome(
        request_content_hash="reqhash", resolution_content_hash="reshash",
        preparation_coordinates={"a": 1}, attempt_index=1, attempt_history_refs=(),
        recovery_kind="RETURNED", provider_id="ro.provider.x",
        budget_consumed=10, budget_remaining=90, output={"summary": "ok"},
    )
    assert canonical(rec) == canonical(rec2)
    assert content_hash(rec) == content_hash(rec2)

    print("outcome selftest ok")
