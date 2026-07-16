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
reached a terminal state, ready for Phase 3's derivation.

Phase 3: derivation (VAE/06 Phase 3) — a pure function from a closed
evidence body + a versioned `DerivationPolicy` to a verdict, VAE/02 §3's
five confidence dimensions, explicit uncertainty (§6), a VAE/02 §7 assurance
level, and (on fail) one of VAE/01 §11's five failure causes. No events, no
persistence, no choreography — those are Phase 4/5.

`derivation` — `derive()` (pure) and `attach_derivation()` (fills
evidence.py's Phase 1 derivation-account slot via `evidence.with_derivation_account`,
never mutating the original record).

Phase 4: choreography (VAE/06 Phase 4) — persist-then-publish verdict
emission (VAE-O5), storage-rejection loud absence (VAE-O6), and the
pending-judgment projection as a rebuildable non-authority (VAE-O1, O10).
No export commit landed for Phase 4 at the time; its two modules are
exported here alongside Phase 5's.

`emission` — `emit_verdict()`: derive -> persist via Storage -> publish
exactly one verdict (or, on rejection, `fault.recorded` and no verdict).
`build_verdict_envelope()` (Phase 5 addition): the pure name/id/payload
construction, factored out so replay can reconstruct it without a second
persist.

`pending` — `PendingProjection` (open judgments, keyed by artifact ref)
and `rebuild()`, reconstructing the projection from demand events +
persisted records + the rules store alone — never resurrecting in-flight
delegation state (VAE-O1).

Phase 5: integration (VAE/06 Phase 5) — the composition root, six
telemetry signal families (VAE/04 §8), and the static law enforcer
(VAE-S7, VAE-S8).

`telemetry` — six `emit_*` functions, one per VAE/04 §8 signal family,
each reshaping already-computed facts into a reference-shaped payload for
an injected sink (VAE-O8: unconditional, never sampled). Ships its own
`TelemetrySinkDouble`.

`runtime` — `Verification`, VAE's composition root: `handle_demand` ->
per-check operations -> `try_close_and_emit` (VAE/04 §2/§5, wiring
intake/judgment/derivation/emission/telemetry) and `replay()`, the
byte-identical golden-artifact reconstruction VAE/05 §8 requires.

`law_enforcer` — seven static AST/text scans (event canon, zero-seam,
no time/random imports, append-only surface, persist-before-publish
order, no producer identity in the verdict functions, dead vocabulary
absence); `run()` raises loud on the first violated law."""
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
    DerivationAccountMalformedError,
    EvidenceItem,
    EvidenceRecord,
    build_evidence_item,
    build_evidence_record,
    append_item,
    with_derivation_account,
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
from .derivation import (  # noqa: F401
    CONFIDENCE_LEVELS,
    DIMENSIONS as CONFIDENCE_DIMENSIONS,
    CANONICAL_LEVELS as VERIFICATION_LEVELS,
    FAILURE_CAUSES,
    ASSURANCE_LEVELS,
    EXECUTION_FAILURE,
    VERIFICATION_FAILURE,
    EVIDENCE_INSUFFICIENCY,
    INCONCLUSIVE_VERIFICATION,
    CONTRADICTORY_EVIDENCE,
    VERIFIED_HIGH,
    VERIFIED_MODERATE,
    VERIFIED_LOW,
    UNVERIFIED,
    VERIFICATION_FAILED,
    VERDICT_PASSED,
    VERDICT_FAILED,
    DerivationRefusal,
    UnknownVerificationLevelError,
    MalformedDerivationPolicyError,
    DerivationPolicy,
    build_derivation_policy,
    derive,
    attach_derivation,
)
from .emission import (  # noqa: F401
    EMITTED,
    REJECTED,
    EmissionRefusal,
    JudgmentNotClosedError,
    AlreadyEmittedError,
    EmissionResult,
    build_verdict_envelope,
    emit_verdict,
)
from .pending import (  # noqa: F401
    PendingRefusal,
    PendingEntry,
    PendingProjection,
    snapshot as pending_snapshot,
    rebuild as pending_rebuild,
)
from .telemetry import (  # noqa: F401
    SIGNAL_FAMILIES,
    CHECK_PHASES as TELEMETRY_CHECK_PHASES,
    TelemetryRefusal,
    UnknownSignalFamilyError,
    UnknownCheckPhaseError,
    TelemetrySinkDouble,
    emit_judgment_outcome,
    emit_check_activity,
    emit_coverage_readout,
    emit_agreement_records,
    emit_derivation_consistency,
    emit_latency_demand,
)
from .runtime import (  # noqa: F401
    RuntimeRefusal,
    NoOpenJudgmentError,
    ReplayMismatchError,
    Verification,
)
from . import law_enforcer  # noqa: F401
