# Public exports only.
"""Verification & Assurance Engine (VAE) — VAE/00-06 (VAE/ARCHITECTURE.md).

Phase 1: foundation — rules-as-data, the append-only five-part evidence
record, the closed event vocabulary, and VAE's own bus/storage doubles
(VAE/06 Phase 1). Zero judgment logic yet — no verdicts, no confidence, no
derivation. Zero imports from src/kernel, src/ums, src/ro, src/cm, src/prt,
src/rsm anywhere in this package (zero-seam rule, VAE/06 "Global laws").

`rules` — immutable `RulesVersion` snapshots (artifact type -> required
check set, depth, per-check deadline) with strictly-monotonic version
ingest and loud refusal of malformed rules or absent (artifact_type,
version) lookups — never a default rule set.

`evidence` — the five-part `EvidenceRecord` (VAE/04 §7.1): artifact
binding (reference only), rules binding (version id), append-only evidence
items (including identified absences as first-class items whose
contribution kind is "missing"), and an explicitly-empty derivation-account
slot refused until Phase 3. Content-hash identity is order-sensitive.

`events` — the closed VAE/05 §2 publish/consume sets: PUBLISHED =
{verify.passed, verify.failed, plan.validated, plan.rejected,
fault.recorded}; CONSUMED = {verify.requested, plan.created, exec.completed,
reasoning.completed}. Invented names refused loud on both sides.

`bus_double`, `storage_double` — VAE's own Communication/Storage test
doubles: at-least-once per-topic FIFO with scriptable duplicate injection,
and a blob store with scriptable commit/reject write outcomes (VAE-O6 path).

Phase 2: judgment core (VAE/06 Phase 2) — demand intake, the delegation
lifecycle with Execution, VAE's own bounded static checks, and the
judgment aggregate that closes a Phase 1 EvidenceRecord into a closed
evidence body. Still no verdicts, confidence, or assurance — Phase 3's.

`intake` — dedup by event id, one judgment per gated artifact occurrence,
terminal-artifact demand answered by the existing verdict reference
(VAE/04 §2.2), reusing events.py's own closed CONSUMED-set check.

`delegation` — the four-state lifecycle Required -> Dispatched ->
(Resulted | Expired) (VAE/04 §3.2) on the injected Execution boundary,
rules-assigned deadlines as injected data, and VAE-O3's re-dispatch
refusal (a delegation that produced an outcome is never dispatched again;
an unacknowledged dispatch may be idempotently re-issued).

`execution_double` — VAE's own scripted Execution boundary double: a
dispatch/poll pair whose answers are a pure function of what was scripted
plus an injected `now` (deterministic nondeterminism).

`static_checks` — a per-instance `StaticCheckRegistry` for VAE's own
bounded, I/O-free, clock-free checks; ships one built-in
(`reference_wellformed`).

`judgment` — the aggregate tying intake + delegations + static checks into
a growing EvidenceRecord; `close()` seals it once every required check has
reached a terminal state, ready for Phase 3's derivation."""
from .rules import (  # noqa: F401
    RulesRefusal,
    MalformedRulesError,
    StaleOrDuplicateVersionError as StaleOrDuplicateRulesVersionError,
    UnknownVersionError as UnknownRulesVersionError,
    UnknownArtifactTypeError,
    ArtifactRules,
    RulesVersion,
    RulesStore,
    build_artifact_rules,
    build_rules_version,
)
from .evidence import (  # noqa: F401
    CONTRIBUTION_KINDS,
    EvidenceRefusal,
    MalformedEvidenceItemError,
    UnknownContributionKindError,
    MalformedEvidenceRecordError,
    DerivationAccountRefusedError,
    EvidenceItem,
    EvidenceRecord,
    build_evidence_item,
    build_evidence_record,
    append_item,
    canonical as canonical_evidence,
    content_hash as evidence_content_hash,
)
from .events import (  # noqa: F401
    PUBLISHED as EVENTS_PUBLISHED,
    CONSUMED as EVENTS_CONSUMED,
    EventRefusal,
    UnknownEventError,
    build_envelope,
    emit as emit_event,
    check_consumed as check_consumed_event,
)
from .bus_double import BusDouble  # noqa: F401
from .storage_double import StorageDouble  # noqa: F401
from .intake import (  # noqa: F401
    Intake,
    IntakeResult,
    DemandAlreadyTerminalConflictError,
    OPENED as INTAKE_OPENED,
    ALREADY_OPEN as INTAKE_ALREADY_OPEN,
    ANSWERED_BY_EXISTING_VERDICT as INTAKE_ANSWERED_BY_EXISTING_VERDICT,
    DEDUPED as INTAKE_DEDUPED,
)
from .delegation import (  # noqa: F401
    Delegation,
    DelegationRefusal,
    ReDispatchRefusedError,
    IllegalTransitionError as DelegationIllegalTransitionError,
    build_delegation,
    dispatch as dispatch_delegation_state,
    resolve as resolve_delegation_state,
    REQUIRED as DELEGATION_REQUIRED,
    DISPATCHED as DELEGATION_DISPATCHED,
    RESULTED as DELEGATION_RESULTED,
    EXPIRED as DELEGATION_EXPIRED,
)
from .execution_double import (  # noqa: F401
    ExecutionDouble,
    ExecutionDoubleRefusal,
    UnknownResultOutcomeError,
    RESULT_OUTCOMES as EXECUTION_RESULT_OUTCOMES,
)
from .static_checks import (  # noqa: F401
    StaticCheckRegistry,
    StaticCheckRefusal,
    DuplicateCheckNameError,
    UnknownStaticCheckError,
    MalformedCheckResultError,
)
from .judgment import (  # noqa: F401
    Judgment,
    JudgmentRefusal,
    DuplicateCheckNameAcrossKindsError,
    UnknownCheckError,
    LateResultBeforeTerminalError,
    JudgmentNotReadyError,
    open_judgment,
    dispatch_delegation,
    resolve_delegation,
    record_late_result,
    run_static_check,
    is_closed as judgment_is_closed,
    close as close_judgment,
)
