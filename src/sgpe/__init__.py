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

`events` — the closed Store event canon (`policy.authored`,
`policy.deprecated`) — never `policy.activated` (that's the Compiler's
activation act, Phase 2); the Store consumes nothing (PS-7).

`bus_double`, `storage_double` — SGPE's own Communication/Storage test
doubles (zero-seam rule beats DRY, mirroring every sibling component's own
copies)."""
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
