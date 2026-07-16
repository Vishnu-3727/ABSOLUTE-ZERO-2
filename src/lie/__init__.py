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
not implement.

Phase 2: engineering knowledge model (LIE/01) — the intelligence layer's
six derived artifact kinds as immutable record MODELS only; zero
compilation/derivation logic (Distillery is Phase 3+).

`derived` — Lesson, Pattern, AntiPattern (+ observed consequence,
optional `instead-of` relation), Recipe (ordered steps), ProjectDossier
(per-project refs + `ProjectRelationship` statements citing shared
facets), DomainKnowledgePack (declared facet scope + member refs). Every
derived record requires a `DerivationAttestation` envelope and at least
one `evidenced-by` relation (INV-4 at construction time).
`knowledge_class()` derives experience/intelligence/curation purely from
record type.

`envelope` (extended) — `DerivationAttestation`: the derived-record
attestation flavor (LIE/01 §3), wrapping the `DerivationState` triple;
experience records structurally refuse it (episode/decision builders) and
derived records structurally require it.

`decision` (extended) — `ARCHITECTURE_FACET` + `is_architecture_record()`:
Architecture Records are Decisions with architectural scope, a facet, not
a subclass (LIE/01 §4.2).

Phase 3: the Distillery (LIE/02) — the deterministic intelligence
compiler.

`ruleset` — `DerivationRuleset`: versioned, declarative rules-as-data;
every threshold (pattern/recipe recurrence, maturity rungs) and every
declared pack scope is validated data, none baked into the compiler.

`distillery` — `regenerate(ledger, overlay, ruleset) -> Layer`: full
regeneration as the only compiler (reference semantics, LIE/03 §6);
`Signature` + `evidence_sets` (grouping by facet profile, partitioned by
verdict polarity); all six artifact kinds compiled per LIE/02 §3 with
Maturity Grades as a pure function of evidence + ruleset thresholds;
Contested set on same-signature/same-approach opposite-valence pairs with
NO automatic resolution ever (contradiction_resolution rulings direct
which side fresh derivation follows); deprecation/supersession rulings
exclude records from fresh evidence sets; `instead-of` links compiled,
never authored; `citation_chain` walks artifact → evidence → attestation
refs, loud on any unresolvable link; `layer_canonical` is the Equivalence
Obligation seam (byte-identical layer comparison, LIE/02 §9).

`derived` (extended) — the real LIE/02 §4 Maturity ladder
(`MATURITY_GRADES`, closed three, computed at derivation) replacing the
Phase 2 pinned placeholder, plus the `contested` flag on
Pattern/AntiPattern.

Phase 4: operational lifecycle (LIE/03).

`advisory` — `AdvisoryInterface`: atomic layer publication (OPS-3) with
`lesson.recorded` change notifications (never carrying advice, LIE/03
§7); pull-only `consult()` returning four-part `Recommendation` objects
or the definite `NoRelevantExperience`, every response stamped with its
Derivation State (OPS-4).

`runtime` — `LieRuntime`: the causal-trigger orchestrator (OPS-7, no
clocks) — `on_ledger_appended`, `on_curation_ruling`,
`on_ruleset_changed` (OPS-6: effect only via full regeneration),
`regenerate` (explicit request / recovery); every trigger is full
regeneration + atomic publication (OPS-8 by construction).

Phase 5: the Curator (LIE/00 §4.5, LIE/04 §6) — implementation complete.

`curator` — `Curator`: deliberate governance only — `rule()` appends
citable, versioned rulings to the overlay (implements CuratorPort);
vocabulary ownership via additive `evolve_vocabulary()`; monotonic
ruleset version governance via `adopt_ruleset()` with every historical
version retained; `contested_queue()` reads the Distillery-flagged
conflicts from a published layer for deliberate ruling. No admission, no
compilation, no mutation surface anywhere.

`gate` (extended) — `adopt_vocabulary()`: forward-only adoption of a
Curator-issued newer vocabulary version, keeping admission normalized
onto the CURRENT vocabulary."""
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
    DerivationAttestation,
    Origin,
    Relation,
    Envelope,
    build_attestation,
    build_derivation_attestation,
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
    ARCHITECTURE_FACET,
    DecisionRefusal,
    MalformedDecisionError,
    Decision,
    build_decision,
    is_architecture_record,
    to_dict as decision_to_dict,
    from_dict as decision_from_dict,
)
from .derived import (  # noqa: F401
    EXPERIENCE,
    INTELLIGENCE,
    CURATION,
    KNOWLEDGE_CLASSES,
    MATURITY_PROVISIONAL,
    MATURITY_CORROBORATED,
    MATURITY_ESTABLISHED,
    MATURITY_GRADES,
    DERIVED_KINDS,
    DerivedRefusal,
    MalformedDerivedRecordError,
    MissingEvidenceCitationError,
    MaturityNotAvailableError,
    UnknownKnowledgeRecordError,
    Lesson,
    Pattern,
    AntiPattern,
    Recipe,
    ProjectRelationship,
    ProjectDossier,
    DomainKnowledgePack,
    build_lesson,
    build_pattern,
    build_anti_pattern,
    build_recipe,
    build_project_relationship,
    build_project_dossier,
    build_domain_knowledge_pack,
    knowledge_class,
    to_dict as derived_to_dict,
    from_dict as derived_from_dict,
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
from .ruleset import (  # noqa: F401
    RulesetRefusal,
    MalformedRulesetError,
    DerivationRuleset,
    build_ruleset,
    default_ruleset,
    to_dict as ruleset_to_dict,
    from_dict as ruleset_from_dict,
)
from .distillery import (  # noqa: F401
    POSITIVE,
    NEGATIVE,
    POLARITIES,
    DistilleryRefusal,
    UnknownVerdictError,
    UnwalkableChainError,
    MalformedCompilerInputError,
    Signature,
    Layer,
    signature_of,
    polarity_of,
    evidence_sets,
    regenerate,
    layer_to_dict,
    layer_canonical,
    citation_chain,
)
from .advisory import (  # noqa: F401
    AdvisoryRefusal,
    NoLayerPublishedError,
    MalformedConsultationError,
    Recommendation,
    NoRelevantExperience,
    AdvisoryInterface,
)
from .runtime import (  # noqa: F401
    RuntimeRefusal,
    MalformedRuntimeInputError,
    LieRuntime,
)
from .curator import (  # noqa: F401
    CuratorRefusal,
    MalformedCuratorInputError,
    RulesetVersionNotAdvancingError,
    Curator,
)
