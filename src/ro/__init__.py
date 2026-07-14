# Public exports only.
"""Reasoning Orchestrator (RO) — RO/00-05 (RO/ARCHITECTURE.md).

Phase 1: capability & descriptor space (RO/01 + RO/03 §3) — frozen
capability/relationship/descriptor-row records with closed-set validation
(`records`), the single in-memory versioned space authority with its one
`apply()` admission entry point and immutable historical snapshots
(`descriptor_space`), and policy as data (`config_view`). Zero imports from
src/prt anywhere in this package — RO's descriptor space is its own
authority, disjoint from PRT's registry (RO-I9).
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
