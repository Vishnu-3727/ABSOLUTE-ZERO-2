# Public exports only.
"""Context Manager (CM) — COMPONENTS/context-management.md, CM/00-implementation-blueprint.md.

Phase 1 (Foundation & artifact) only: the frozen Request Memory artifact,
Assembly Spec intake/hashing, the closed context.* event set, policy as
data, and a test bus double. No gather/resolve/dedup/prioritize/budget/
assemble/validate/cache/freshness yet — those are Phases 2-5.
"""
from .request_memory import RequestMemory, SECTION_NAMES, build as build_request_memory  # noqa: F401
from .request_memory import canonical as canonical_request_memory  # noqa: F401
from .request_memory import content_hash as request_memory_hash  # noqa: F401
from .spec import build as build_spec, canonical as canonical_spec, spec_hash  # noqa: F401
from . import events  # noqa: F401
from .config_view import ConfigView, DEFAULT as DEFAULT_CONFIG  # noqa: F401
from .bus_double import BusDouble  # noqa: F401
