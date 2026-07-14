# Public exports only.
"""Plugin Runtime (PRT) — PRT/00-architectural-foundation.md through
PRT/05-system-integration.md.

Phase 1: the capability registry model (PRT/01) — frozen capability/
provider/binding/relationship records (`records`), the single in-memory
registry authority with its one `apply()` admission entry point and
versioned historical snapshots (`registry`), the closed publish/consume
event vocabulary with dead-vocabulary rejection (`events`), policy as data
(`config_view`), and PRT's own bus/storage test doubles.
"""
from . import events  # noqa: F401
from .bus_double import BusDouble  # noqa: F401
from .config_view import ConfigView, DEFAULT as DEFAULT_CONFIG  # noqa: F401
from .storage_double import StorageDouble  # noqa: F401
from .records import (  # noqa: F401
    LIFECYCLE_STATES,
    RELATIONSHIP_KINDS,
    CapabilityRecord,
    ProviderRecord,
    BindingRecord,
    RelationshipEdge,
    build_capability,
    build_provider,
    build_binding,
    build_relationship,
    canonical as canonical_record,
    content_hash as record_content_hash,
)
from .registry import (  # noqa: F401
    Registry,
    RegistrySnapshot,
    RegistryRefusal,
    RecoverableRefusal,
    PermanentRefusal,
    DuplicateIdError,
    TombstoneReuseError,
    AliasResolutionError,
    RelationshipEndpointError,
    BindingConsistencyError,
    LifecycleTransitionError,
    MetadataIncompleteError,
    NotFoundError,
    UnknownMutationError,
)
