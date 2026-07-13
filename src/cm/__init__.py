# Public exports only.
"""Context Manager (CM) — COMPONENTS/context-management.md, CM/00-implementation-blueprint.md.

Phases 1-3: the frozen Request Memory artifact, Assembly Spec intake/
hashing, the closed context.* event set, policy as data, a test bus
double (Phase 1); source adapters gathering raw candidates from UMS/RSM/
references (Phase 2); dependency-aware expansion, dedup, and deterministic
prioritization turning that raw set into an ordered, unique, dependency-
complete candidate selection (Phase 3).

Phase 4: per-section budget envelopes + global hard ceiling with fidelity-
tier degradation (`budgeter`), the pipeline orchestrator that populates the
frozen Request Memory and emits `context.assembled`/`context.overflow`
(`assembler`), and the structural validation gates that block emit on any
bad artifact (`validator`) -- first end-to-end, byte-identical Request
Memory.

Phase 5 (final): the ephemeral `(request_id, spec_hash)` Request-Memory
registry (`cache`); `index.updated` path-overlap invalidation + section-
scoped incremental rebuild that is byte-identical to a full rebuild
(`freshness`); automated scan-based invariant checks -- no similarity/
retrieval in src/cm/, ums import confined to sources.py, exactly one
assembler, closed event set (`law_enforcer`). Also closes the Phase-4
seam: `assembler.py` now disambiguates dedup.py's contradiction pairs
(same id, both kept, both flagged) with a deterministic content-hash id
suffix so they survive validator's zero-duplicate-ids gate. CM is
complete: 15/15 blueprint modules.
"""
from .request_memory import RequestMemory, SECTION_NAMES, build as build_request_memory  # noqa: F401
from .request_memory import canonical as canonical_request_memory  # noqa: F401
from .request_memory import content_hash as request_memory_hash  # noqa: F401
from .spec import build as build_spec, canonical as canonical_spec, spec_hash  # noqa: F401
from . import events  # noqa: F401
from .config_view import ConfigView, DEFAULT as DEFAULT_CONFIG  # noqa: F401
from .bus_double import BusDouble  # noqa: F401
from . import sources  # noqa: F401
from .resolver import expand as resolve_dependencies  # noqa: F401
from .dedup import dedup as dedup_candidates  # noqa: F401
from .prioritizer import prioritize as prioritize_candidates  # noqa: F401
from . import budgeter  # noqa: F401
from .budgeter import fit as fit_budget  # noqa: F401
from . import validator  # noqa: F401
from .validator import validate as validate_request_memory  # noqa: F401
from .assembler import Assembler  # noqa: F401
from .cache import Cache, key as cache_key  # noqa: F401
from . import freshness  # noqa: F401
from .freshness import (  # noqa: F401
    on_index_updated,
    get_or_assemble,
    rebuild as incremental_rebuild,
    affected_sections,
)
from . import law_enforcer  # noqa: F401
