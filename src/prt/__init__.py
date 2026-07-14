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

Phase 3: binding & load policy (PRT/03) — the opaque health-state
coordinate binding consumes (`health_view`, PRT/03 §2), the availability
ladder as an eligibility predicate only (`availability`, PRT/03 §6,
PRT-B11), deterministic late binding and the immutable Binding Contract
(`binding`, PRT/03 §3/§7, PRT-B1..B7/B12), and declared load policy plus
the runtime-only load lifecycle (`load_policy`, PRT/03 §5/§9, PRT-B8/B9).

Phase 4: health & reliability (PRT/04) — the append-only evidence journal
of closed input classes (`evidence`, PRT/04 §4/§8, PRT-H6/H9), the
deterministic HealthManager fold that now PRODUCES the HealthSnapshot
Phase 3 only consumed (`health`, PRT/04 §3/§6/§7, PRT-H1/H2/H5/H7/H11),
and the one-directional Learning->PRT reliability seam
(`reliability_bridge`, PRT/04 §4/§9, PRT-H10).
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
from .health_view import HealthSnapshot  # noqa: F401
from . import availability  # noqa: F401
from .binding import (  # noqa: F401
    BindingContract,
    BindingFailure,
    resolve as resolve_binding,
    explain as explain_binding,
)
from .load_policy import (  # noqa: F401
    LOAD_STATES,
    LoadPolicyView,
    LoadStateTracker,
    AllowAllLegality,
    prerequisites_bound,
)
from .evidence import EvidenceJournal  # noqa: F401
from .health import (  # noqa: F401
    STATES as HEALTH_STATES,
    DEFAULT_THRESHOLDS as HEALTH_DEFAULT_THRESHOLDS,
    HealthManager,
    fold_provider as fold_health,
)
from .reliability_bridge import (  # noqa: F401
    consume_reliability_update,
    drain_reliability_updates,
)
