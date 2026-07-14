# Public exports only.
"""Plugin Runtime (PRT) — PRT/00-architectural-foundation.md through
PRT/05-system-integration.md.

Phase 1: the capability registry model (PRT/01) — frozen capability/
provider/binding/relationship records (`records`), the single in-memory
registry authority with its one `apply()` admission entry point and
versioned historical snapshots (`registry`), the closed publish/consume
event vocabulary with dead-vocabulary rejection (`events`), policy as data
(`config_view`), and PRT's own bus/storage test doubles.

Phase 2: discovery & admission (PRT/02) — the immutable Declaration bundle
(`declarations`), discovery sources that produce Declarations without ever
touching the registry (`discovery`, PRT-A1), the Candidacy pipeline-state
tracker (`candidacy`, PRT/02 §2), the nine-stage admission pipeline over
registry.py's `admit_bundle`/`dry_run` extensions (`admission`, PRT/02 §3,
§7 persist-before-commit), and Lifecycle-enacted retirement (`retirement`,
PRT-A4/PRT-A11).
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
    AliasTargetRetirementError,
    RelationshipEndpointError,
    BindingConsistencyError,
    LifecycleTransitionError,
    MetadataIncompleteError,
    NotFoundError,
    UnknownMutationError,
)
from .declarations import (  # noqa: F401
    SOURCE_CLASSES,
    Declaration,
    build_declaration,
)
from .discovery import FixtureSource, discover  # noqa: F401
from .candidacy import STATES as CANDIDACY_STATES, Candidacy, CandidacyError  # noqa: F401
from .admission import (  # noqa: F401
    IdentityMalformedError,
    SemanticHijackError,
    CapabilityReferenceError,
    ConstraintIncoherenceError,
    CompatibilityConflictError,
    admit,
)
from .retirement import enact_lifecycle_event  # noqa: F401
