# Public exports only.
"""System Governance & Policy Engine (SGPE) — SGPE/00-05 (SGPE/05 §8
implementation contract).

Phase 1: the Policy Store (SGPE/01) — the passive, deterministic
repository of authored governance data. Zero evaluation, zero compilation,
zero conflict detection, zero enforcement (PS-1) — Phase 1 fixes
structure, identity, versioning, and the catalog only.

`vocabulary` — `Vocabulary`: versioned, additive-only domain/operation/
fact-name registry (SGPE/00 §9's initial thirteen-domain set via
`default_v1()`); `evolve()` is the only path to a new version and refuses
any proposed term set that is not a strict superset, per axis, of the
current one.

`condition` — the closed declarative condition grammar (SGPE/01 §2):
`Comparison`, `SetMembership`, `BooleanComposition` — data structures
only, never executable code.

`rule` — `Rule`: `rule_id` + `Target` (domain/operation/resource
selector) + `Effect` (ALLOW/DENY/REQUIRE_APPROVAL/LIMIT(value)) + optional
`condition` + optional `final` flag, recorded structurally regardless of
scope (final's scope-legality is the Compiler's semantic check, PS-6).

`document` — `PolicyDocument`: `Header` (identity, scope, domain refs,
provenance, vocabulary/schema versions) + ordered `Rule` tuple; duplicate
rule ids refused at construction; `doc_id()` gives the stable (scope,
name) identity; `content_hash()` is the canonical-serialization hash
(SGPE/01 §3).

`manifest` — `SnapshotManifest` (snapshot version, catalog position,
document-version refs) and `ActivationFact` — data ABOUT a compile/
activation; the compiled index itself is never stored (PS-10).

`catalog` — `Catalog`: the append-only, monotonic-position index every
Store append advances; `as_of(position, kind)` gives deterministic,
position-stamped reads (PS-9).

`store` — `PolicyStore`: append documents/vocabulary/deprecation markers/
manifests/activation facts; structural gate only (PS-6) — rejects
unparseable documents, duplicate rule ids, non-monotonic/duplicate
versions, identity collisions, unknown schema versions, and references to
nonexistent vocabulary versions; accepts everything semantic (unknown
vocabulary terms, conflicting rules, `final` scope-legality) by design,
proving PS-6's boundary structurally. `documents_as_of()` /
`vocabulary_as_of()` are deterministic position-stamped reads.
`export_log()` / `rebuild_from_log()` make PS-5 ("entire state is a pure
function of the append sequence") literal and testable.

`events` — the closed five-name event canon shared by Store and Compiler
(`policy.authored`, `policy.deprecated`, `policy.compiled`,
`policy.rejected`, `policy.activated`); nothing is consumed (PS-7/AC-10).

`bus_double`, `storage_double` — SGPE's own Communication/Storage test
doubles (zero-seam rule beats DRY, mirroring every sibling component's own
copies).

Phase 2: the Admission Compiler (SGPE/02) — the gate between "authored"
and "in force." Zero runtime evaluation, zero enforcement (AC-1) — turns a
position-stamped policy set into a validated, totally-decided, immutable
candidate snapshot, or a rejection that changes nothing (AC-3).

Phase 3: the Evaluator (SGPE/03) — runtime policy evaluation as a pure
function: Decision = f(snapshot version, grant-slice position, evaluation
ruleset version, canonical Question). Retrieval, not reasoning (EV-3);
never reads the Store, never compiles, never fetches grants (EV-2).

`evaluator` — `evaluate(snapshot_version, snapshot,
grant_slice_position, grant_slice, question, evaluation_ruleset_version,
bus=None, memo=None)`: the 7-step lifecycle (well-formedness, memo probe,
index match, final check, exact-signature grant overlay, binding-
constraint attachment, Decision + trace); returns a `Decision` (one
effect + binding ceilings + byte-stable citation-triple explanation +
replay stamps, EV-4) or an `IllPosedVerdict` (protocol-error class,
never a DENY, EV-6); `build_question()` is the canonical Question
constructor; `ask_signature()` is what REQUIRE_APPROVAL emits and grants
are keyed to (EV-5); the caller-owned memo dict is keyed by every
answer-changing input and semantically invisible (EV-7/EV-8).

Phase 4: the Grant Ledger and Effective Policy Resolver (SGPE/04 +
ERRATA C3) — the runtime policy context of a request.

`ledger` — `GrantLedger`: the append-only, monotonic-position record of
approval outcomes, a SIBLING record to the Store (own storage namespace,
same discipline). Two record kinds only (GL-3): `append_grant()` and
`append_revocation()` (a new record naming a grant id, inheriting its
signature and scope binding — no supersession or edit semantics).
Stores, never judges (GL-2/GL-5): signatures opaque, bounds stored as
condition.py data, validity is the Evaluator's evaluation-time call.
`slice()` gives deterministic position-stamped reads (GL-6);
`export_log()`/`rebuild_from_log()` make replay literal (GL-1). Every
append is a `grant.recorded`/`grant.revoked` event (GL-7).

`resolver` — stateless module functions (EPR-6): `admit(read_active_
snapshot_version, ledger, request_id, principal, project)` performs the
two atomic admission reads and emits the immutable `EffectivePolicy`
binding (EPR-1), failing closed on a missing snapshot or unreachable
Ledger (EPR-5); `consultation_slice(ledger, ep, position)` implements
ERRATA C3's closed growth rule (standing world frozen at P₀, only
request-scoped appends enter, EPR-2/EPR-4) and projects to the
Evaluator's `GrantRecord` shape; `effective_policy_from_dict()` is the
replay entry point (EPR-7).

`compiler` — `compile_snapshot(store, position, compiler_ruleset_version,
bus=None)`: the 8-stage pipeline (assembly, vocabulary, scope & modifier
legality, dependency, totality, conflict detection, construction,
readiness), pure in `(catalog position, vocabulary version, compiler
ruleset version)` (AC-2/R1); `activate()` performs the atomic activation
act (manifest + activation fact appends via the Phase 1 Store, snapshot
version assigned at activation, AC-7/AC-8); `rollback()` recompiles an old
manifest's own recorded inputs and activates forward; `regenerate()` is
the R5 standing equivalence oracle (recompiling a manifest must reproduce
its recorded content hash, AC-9). `Finding`/`CompileReport` carry
`error_class` (`"corruption"` vs. `"authoring"`) and, for conflicts, a
concrete overlap witness (AC-5)."""
from .vocabulary import (  # noqa: F401
    INITIAL_DOMAINS,
    VocabularyRefusal,
    MalformedVocabularyError,
    VocabularyNotAdditiveError,
    VocabularyNoNewTermsError,
    Vocabulary,
    build_vocabulary,
    default_v1 as default_vocabulary_v1,
    evolve as evolve_vocabulary,
    to_dict as vocabulary_to_dict,
    from_dict as vocabulary_from_dict,
)
from .condition import (  # noqa: F401
    COMPARISON_OPS,
    SET_OPS,
    BOOL_OPS,
    ConditionRefusal,
    MalformedConditionError,
    Comparison,
    SetMembership,
    BooleanComposition,
    build_comparison,
    build_set_membership,
    build_boolean,
    to_dict as condition_to_dict,
    from_dict as condition_from_dict,
)
from .rule import (  # noqa: F401
    EFFECT_KINDS,
    RuleRefusal,
    MalformedEffectError,
    MalformedTargetError,
    MalformedRuleError,
    Effect,
    Target,
    Rule,
    build_effect,
    build_target,
    build_rule,
    to_dict as rule_to_dict,
    from_dict as rule_from_dict,
)
from .document import (  # noqa: F401
    SCOPES,
    SUPPORTED_SCHEMA_VERSIONS,
    DocumentRefusal,
    MalformedProvenanceError,
    MalformedHeaderError,
    DuplicateRuleIdError,
    MalformedDocumentError,
    Provenance,
    Header,
    PolicyDocument,
    build_provenance,
    build_header,
    build_document,
    doc_id,
    to_dict as document_to_dict,
    from_dict as document_from_dict,
    canonical as document_canonical,
    content_hash as document_content_hash,
)
from .manifest import (  # noqa: F401
    ManifestRefusal,
    MalformedManifestError,
    MalformedActivationFactError,
    SnapshotManifest,
    ActivationFact,
    build_manifest,
    build_activation,
    manifest_to_dict,
    manifest_from_dict,
    activation_to_dict,
    activation_from_dict,
)
from .catalog import (  # noqa: F401
    ENTRY_KINDS,
    CatalogRefusal,
    UnknownEntryKindError,
    CatalogAppendRejectedError,
    CatalogEntry,
    Catalog,
)
from .events import (  # noqa: F401
    PUBLISHED as EVENTS_PUBLISHED,
    CONSUMED as EVENTS_CONSUMED,
    EventRefusal,
    UnknownEventError,
    build_envelope as build_event_envelope,
    emit as emit_event,
    check_consumed as check_consumed_event,
)
from .bus_double import BusDouble  # noqa: F401
from .storage_double import StorageDouble  # noqa: F401
from .store import (  # noqa: F401
    StoreRefusal,
    MalformedAppendError,
    IdentityCollisionError,
    NonMonotonicVersionError,
    UnknownVocabularyVersionError,
    VocabularyNotAdditiveError as StoreVocabularyNotAdditiveError,
    UnknownDocumentVersionError,
    DeprecationMarker,
    PolicyStore,
)
from .compiler import (  # noqa: F401
    CURRENT_COMPILER_RULESET_VERSION,
    SUPPORTED_COMPILER_RULESET_VERSIONS,
    SCOPE_RANK,
    EFFECT_PRIORITY,
    ERROR as FINDING_ERROR,
    WARNING as FINDING_WARNING,
    CORRUPTION as ERROR_CLASS_CORRUPTION,
    AUTHORING as ERROR_CLASS_AUTHORING,
    VOCAB_DOMAIN_UNRESOLVED,
    VOCAB_OPERATION_UNRESOLVED,
    VOCAB_FACT_UNRESOLVED,
    FINAL_ILLEGAL_SCOPE,
    FINAL_CONTRADICTED,
    VOCAB_VERSION_AHEAD,
    TOTALITY_GAP,
    UNDECIDABLE_CONFLICT,
    SHADOWED,
    STALE_VOCABULARY,
    DECIDED_BY_SCOPE,
    DECIDED_BY_DENY_OVERRIDES,
    DECIDED_BY_MIN_LIMIT,
    CompilerRefusal,
    MalformedCompileInputError,
    UnsupportedCompilerRulesetVersionError,
    ActivationRefusedError,
    RegenerationMismatchError,
    Finding,
    CompileReport,
    IndexEntry,
    CompiledSnapshot,
    CompileResult,
    compile_snapshot,
    activate,
    rollback,
    regenerate,
    finding_to_dict,
    report_to_dict,
    snapshot_to_dict,
)
from .evaluator import (  # noqa: F401
    CURRENT_EVALUATION_RULESET_VERSION,
    SUPPORTED_EVALUATION_RULESET_VERSIONS,
    GRANT,
    REVOCATION,
    ILLPOSED_NOT_A_QUESTION,
    ILLPOSED_NON_CANONICAL,
    ILLPOSED_UNKNOWN_ACTION,
    ILLPOSED_MISSING_FACTS,
    ILLPOSED_UNDECLARED_FACTS,
    ILLPOSED_INCOMPARABLE,
    EvaluatorRefusal,
    MalformedEvaluationInputError,
    UnsupportedEvaluationRulesetVersionError,
    SnapshotIntegrityError,
    MalformedGrantRecordError,
    MalformedQuestionError,
    Question,
    GrantRecord,
    Decision,
    IllPosedVerdict,
    build_question,
    build_grant_record,
    question_to_dict,
    question_from_dict,
    question_hash,
    ask_signature,
    decision_to_dict,
    decision_bytes,
    illposed_to_dict,
    evaluate,
)
from .ledger import (  # noqa: F401
    SCOPE_KINDS,
    LedgerRefusal,
    MalformedGrantAppendError,
    UnknownGrantIdError,
    LedgerAppendRejectedError,
    ScopeBinding,
    GrantProvenance,
    LedgerRecord,
    GrantLedger,
    build_scope_binding,
    build_grant_provenance,
    record_to_dict as ledger_record_to_dict,
    record_from_dict as ledger_record_from_dict,
)
from .resolver import (  # noqa: F401
    REFUSED_NO_ACTIVE_SNAPSHOT,
    REFUSED_SNAPSHOT_FACT_UNREADABLE,
    REFUSED_LEDGER_UNREACHABLE,
    ResolverRefusal,
    MalformedAdmissionInputError,
    AdmissionRefusedError,
    EffectivePolicy,
    admit,
    consultation_slice,
    effective_policy_to_dict,
    effective_policy_from_dict,
)
