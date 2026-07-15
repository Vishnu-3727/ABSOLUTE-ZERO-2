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
and a blob store with scriptable commit/reject write outcomes (VAE-O6 path)."""
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
