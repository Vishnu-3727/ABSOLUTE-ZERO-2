# Public exports only.
"""Reasoning Orchestrator (RO) — RO/00-05 (RO/ARCHITECTURE.md).

Phase 1: capability & descriptor space (RO/01 + RO/03 §3) — frozen
capability/relationship/descriptor-row records with closed-set validation
(`records`), the single in-memory versioned space authority with its one
`apply()` admission entry point and immutable historical snapshots
(`descriptor_space`), and policy as data (`config_view`). Zero imports from
src/prt anywhere in this package — RO's descriptor space is its own
authority, disjoint from PRT's registry (RO-I9).

Phase 2: the necessity gate (RO/02) — sealed decision inputs (`demand`),
governance policy as data (`policy_view`), and the pure `decide()` gate
producing one of five closed outcomes (`decision_gate`). Never imports
DescriptorRow (RO-D3) — provider identity/availability is structurally
invisible to the gate.

Phase 3: request preparation + resolution/rendering (RO/03, blueprint
groups G3+G4) — OS-owned output schemas (`schemas`), governance token
budgets with parent-envelope inheritance (`budget`), sealed-RQM context
selection/reduction (`context_prep`), capability matching + deterministic
provider selection (`matching_selection`), and the `prepare()` entry point
assembling the two-artifact pair — provider-independent `ReasoningRequest`
+ `ProviderResolution` (`request`) — plus the governance-lossless renderer
mapping a request into one provider-consumable form (`renderer`). Provider
identity lives only in `ProviderResolution`, never in `ReasoningRequest` or
any rendering (RO-P2/P3).

Phase 4: execution governance (RO/04, blueprint group G5) — the sealed
outcome record shape (`outcome`), injected cancellation signals (
`cancellation`), execution policy as data including timeout-class
derivation (`execution_policy`), the injected engine boundary port +
`ScriptedEngineDouble` (`engine_boundary`), the invocation governor driving
Initiated -> Executing -> Recovery -> Sealed for every attempt plus retry-
with-substitution and escalation directives (`invocation`), governed
composition of individually-sealed constituents (`composite`), and
governance-side replay from sealed records alone (`execution_replay`). RO
is the sole invocation authority (RO-E1); nondeterminism exists only inside
the injected boundary call, never in RO's own code (zero time/random/
datetime imports, AST-enforced).
"""
from .config_view import ConfigView, DEFAULT as DEFAULT_CONFIG  # noqa: F401
from .records import (  # noqa: F401
    CATEGORIES,
    CHARACTERISTIC_BANDS,
    COMPLEXITY_RUNGS,
    LIFECYCLE_STATES,
    RELATIONSHIP_KINDS,
    CONTEXT_CAPACITY_CLASSES,
    COST_CLASSES,
    LATENCY_CLASSES,
    DETERMINISM_CLASSES,
    DEPLOYMENT_LOCALITY_CLASSES,
    PRIVACY_DOMAINS,
    RELIABILITY_BASELINE_CLASSES,
    REQUEST_FORMS,
    CapabilityRecord,
    RelationshipRecord,
    DescriptorRow,
    build_capability,
    build_relationship,
    build_descriptor_row,
    canonical as canonical_record,
    content_hash as record_content_hash,
)
from .descriptor_space import (  # noqa: F401
    DescriptorSpace,
    DescriptorSpaceSnapshot,
    DescriptorSpaceRefusal,
    RecoverableRefusal,
    PermanentRefusal,
    DuplicateIdError,
    TombstoneReuseError,
    LifecycleTransitionError,
    CategoryFrozenError,
    RelationshipEndpointError,
    DependencyCycleError,
    DescriptorClaimError,
    ClaimedCapabilityRetirementError,
    NotFoundError,
    UnknownMutationError,
)
from .demand import (  # noqa: F401
    RUNGS as LADDER_RUNGS,
    LADDER_STATUSES,
    DemandArtifact,
    LadderEvidence,
    SealedInputs,
    build_demand,
    build_ladder_evidence,
    build_sealed_inputs,
    canonical as canonical_demand,
    content_hash as demand_content_hash,
    ladder_evidence_hash,
)
from .policy_view import PolicyView, build_policy_view  # noqa: F401
from .decision_gate import (  # noqa: F401
    OUTCOMES,
    DecisionRecord,
    decide,
    canonical as canonical_decision,
    content_hash as decision_content_hash,
)
from .schemas import (  # noqa: F401
    SchemaRefusal,
    DuplicateSchemaVersionError,
    UnknownSchemaError,
    SchemaRecord,
    SchemaRegistry,
)
from .budget import (  # noqa: F401
    BudgetRefusal,
    BudgetInvalidError,
    BudgetExhaustedError,
    BudgetInfeasibleError,
    BudgetEnvelope,
    allocate_budget,
    require_fits,
)
from .context_prep import (  # noqa: F401
    ContextRefusal,
    MalformedRQMError,
    StaleRQMError,
    EmptyContextError,
    select_and_reduce,
    validate_rqm,
    rqm_content_hash,
    check_freshness,
)
from .matching_selection import (  # noqa: F401
    MatchingRefusal,
    EmptyCandidateSetError,
    EmptyEligibleSetError,
    build_candidate_set,
    select_provider,
    derive_size_class,
)
from .request import (  # noqa: F401
    PreparationRefusal,
    UnapprovedDecisionError,
    UnconstrainedRequestError,
    ReasoningRequest,
    ProviderResolution,
    prepare,
    canonical as canonical_request,
    content_hash as request_content_hash,
)
from .renderer import (  # noqa: F401
    RenderRefusal,
    UnknownRequestFormError,
    render,
    assert_lossless,
)
from .outcome import (  # noqa: F401
    RECORD_VERSION,
    RECOVERY_KINDS,
    FAILURE_CLASSES,
    CANCELLATION_ORIGINS,
    OutcomeRefusal,
    InconsistentOutcomeError,
    SealedOutcomeRecord,
    build_sealed_outcome,
    canonical as canonical_outcome,
    content_hash as outcome_content_hash,
)
from .cancellation import (  # noqa: F401
    # ORIGINS not re-imported here: identical closed tuple already exported
    # as CANCELLATION_ORIGINS above (outcome.py owns it; cancellation.py
    # imports the same object).
    CancellationRefusal,
    UnknownOriginError,
    CancellationSignal,
    build_cancellation_signal,
    canonical as canonical_cancellation,
    content_hash as cancellation_content_hash,
)
from .execution_policy import (  # noqa: F401
    TIMEOUT_CLASSES,
    ExecutionPolicyRefusal,
    UnknownTimeoutInputError,
    ExecutionPolicyView,
    build_execution_policy_view,
    derive_timeout_class,
)
from .engine_boundary import (  # noqa: F401
    CROSSING_KINDS,
    BoundaryRefusal,
    ScriptExhaustedError,
    MalformedBoundaryReturnError,
    CrossingPayload,
    ScriptedEngineDouble,
)
from .invocation import (  # noqa: F401
    InvocationRefusal,
    SubstitutionRefusedError,
    EscalationDirective,
    run_attempts,
    retry_with_substitution,
    escalation_directive,
    canonical as canonical_escalation_directive,
    content_hash as escalation_directive_content_hash,
)
from .composite import (  # noqa: F401
    PATTERNS,
    AGGREGATION_RULES,
    FAILURE_SEMANTICS,
    CompositeRefusal,
    UnknownPatternError,
    MissingAggregationRuleError,
    UnknownFailureSemanticsError,
    EmptyConstituentsError,
    ConstituentSpec,
    CompositePlan,
    CompositeOutcome,
    build_composite_plan,
    run_composite,
    canonical as canonical_composite,
    content_hash as composite_content_hash,
)
from .execution_replay import (  # noqa: F401
    ReplayRefusal,
    replay_attempts,
)
