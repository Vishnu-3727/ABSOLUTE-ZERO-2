# Public exports only.
"""Context Manager (CM) — COMPONENTS/context-management.md, CM/00-implementation-blueprint.md.

Phases 1-3: the frozen Request Memory artifact, Assembly Spec intake/
hashing, the closed context.* event set, policy as data, a test bus
double (Phase 1); source adapters gathering raw candidates from UMS/RSM/
references (Phase 2); dependency-aware expansion, dedup, and deterministic
prioritization turning that raw set into an ordered, unique, dependency-
complete candidate selection (Phase 3). No budget/assemble/validate/
cache/freshness yet — those are Phases 4-5.
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
