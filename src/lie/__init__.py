# Public exports only.
"""Learning & Intelligence Engine (LIE) — LIE/00-04 (LIE/04 §6 implementation
contract).

Phase 1: architectural foundation — the provenance envelope, the two
experience-layer record kinds (Episode, Decision), the closed relation set,
the controlled facet vocabulary, the curation annotation record, the
Experience Ledger, the curation overlay, the Derivation State value type,
the closed event vocabulary, the Admission Gate, and boundary-contract
stubs for the three subsystems this phase does not implement (Distillery,
Advisory Interface, Curator). Zero derivation logic, zero recommendation
logic, zero ruleset content (LIE/02-03 material) — Phase 1 fixes structure
and invariants only.

`vocabulary` — versioned, additive-only `FacetVocabulary`; `evolve()` is
the only path to a new version and refuses any proposed term set that is
not a strict superset of the current one (removal/renaming refused loud).

`envelope` — the five-section provenance envelope (identity, attestation
incl. facet-vocabulary version per R2, origin, facets, relations); the
closed seven-relation set (`enacts`, `recovers`, `follows`,
`evidenced-by`, `instead-of`, `supersedes`, `about`); every `build_*`
factory refuses an incomplete envelope loud (LIE/04 §6: "rejection, not
partial admit").

`episode`, `decision` — the two experience-layer record kinds (LIE/01
§4): Episode (situation/approach/outcome/cost) and Decision
(question/options/chosen/rationale/constraints/consequences_expected),
both frozen and validated at construction, both round-trippable to a
human-readable dict (INV-7).

`curation` — the curation overlay's one record kind, `Annotation`
(deprecation / supersession / contradiction_resolution), append-only,
always carrying `reason` and `cited_evidence`.

`derivation_state` — the (ledger position, overlay position, ruleset
version) triple (LIE/03 §2) that names a published intelligence layer.

`admission_receipt` — `AdmissionReceipt`, the structural INV-1
enforcement: minted only by `AdmissionGate.admit()`, required by
`ExperienceLedger.append()`.

`ledger` — `ExperienceLedger`: append-only, monotonic Ledger Position,
durable-append-then-position via the Storage double, no update/delete API
at all (INV-2 structural), identity uniqueness enforced.

`overlay` — `CurationOverlay`: the append-only overlay store for
`Annotation` records, monotonic overlay position, same no-mutator
discipline as the Ledger.

`events` — the closed LIE/00 §4.4 publish set (`lesson.recorded`,
`reliability.updated`, `prior.updated`) and the one consumed event
(`trace.closed`) — never `lesson.learned`.

`bus_double`, `storage_double`, `telemetry_double` — LIE's own
Communication/Storage/Observability test doubles (zero-seam rule beats
DRY, mirroring every sibling component's own copies).

`gate` — `AdmissionGate`: the single entry point for experience —
provenance check, vocabulary normalization, OPS-5 idempotent admission
keyed on attested-unit identity, durable-append-then-acknowledge ordering,
rejection records to Observability, never the Ledger (R1).

`contracts` — `DistilleryPort`, `AdvisoryPort`, `CuratorPort`: minimal
`typing.Protocol` boundary seams for the three subsystems this phase does
not implement."""
from .vocabulary import (  # noqa: F401
    VocabularyRefusal,
    MalformedVocabularyError,
    VocabularyNotAdditiveError,
    VocabularyNoNewTermsError,
    FacetVocabulary,
    build_vocabulary,
    evolve as evolve_vocabulary,
)
from .envelope import (  # noqa: F401
    RELATION_TYPES,
    EnvelopeRefusal,
    EnvelopeIncompleteError,
    UnknownRelationTypeError,
    Attestation,
    Origin,
    Relation,
    Envelope,
    build_attestation,
    build_origin,
    build_relation,
    build_envelope,
    to_dict as envelope_to_dict,
    from_dict as envelope_from_dict,
    canonical as envelope_canonical,
)
from .episode import (  # noqa: F401
    EpisodeRefusal,
    MalformedEpisodeError,
    Episode,
    build_episode,
    to_dict as episode_to_dict,
    from_dict as episode_from_dict,
)
from .decision import (  # noqa: F401
    DecisionRefusal,
    MalformedDecisionError,
    Decision,
    build_decision,
    to_dict as decision_to_dict,
    from_dict as decision_from_dict,
)
from .curation import (  # noqa: F401
    ANNOTATION_KINDS,
    CurationRefusal,
    UnknownAnnotationKindError,
    MalformedAnnotationError,
    Annotation,
    build_annotation,
    to_dict as annotation_to_dict,
    from_dict as annotation_from_dict,
)
from .derivation_state import (  # noqa: F401
    DerivationStateRefusal,
    MalformedDerivationStateError,
    DerivationState,
    build_derivation_state,
    to_dict as derivation_state_to_dict,
    from_dict as derivation_state_from_dict,
)
from .admission_receipt import AdmissionReceipt  # noqa: F401
from .ledger import (  # noqa: F401
    LedgerRefusal,
    UnauthorizedAppendError,
    DuplicateIdentityError,
    LedgerAppendRejectedError,
    UnknownRecordKindError as LedgerUnknownRecordKindError,
    LedgerEntry,
    ExperienceLedger,
)
from .overlay import (  # noqa: F401
    OverlayRefusal,
    OverlayAppendRejectedError,
    MalformedOverlayAppendError,
    OverlayEntry,
    CurationOverlay,
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
from .telemetry_double import ObservabilityDouble  # noqa: F401
from .gate import (  # noqa: F401
    ADMITTED,
    REJECTED,
    DEDUPED,
    OUTCOMES as GATE_OUTCOMES,
    GateRefusal,
    UnknownRecordKindError as GateUnknownRecordKindError,
    AdmissionResult,
    AdmissionGate,
)
from .contracts import DistilleryPort, AdvisoryPort, CuratorPort  # noqa: F401
