"""CP — the Capability Planner (CP/00-05; ERRATA C16).

Phase 1 (Foundation & vocabulary door) per the frozen blueprint's
one-phase-per-session law:

  plan_artifact.py   frozen Capability Graph artifact + determinism tuple
                     + lineage + content hash + the WS-facing
                     `to_sealed_graph()` projection
  spec.py            intake normalization — all inputs injected, hashed
                     order-independently
  events.py          closed 4-name set (`intent.classified` per C16)
  config_view.py     CP policy as data (C10 disjoint namespace)
  registry_view.py   the one vocabulary door: aliases, lifecycle
                     semantics, version stamping, read-only
  bus_double.py / registry_double.py  test doubles (tests/selftests only)

Phases 2-5 (discovery, graph core, judgment/publication, persistence +
law enforcement) follow per blueprint — strictly linear, fresh sessions.
"""
from .config_view import ConfigView, default_config  # noqa: F401
from .events import EVENT_NAMES, emit  # noqa: F401
from .plan_artifact import (ArtifactRefusal, BANDS, EDGE_TYPES,  # noqa: F401
                            GAP_TYPES, ORIGINS, PlanArtifact, build_artifact)
from .registry_view import RegistryView, RegistryViewRefusal  # noqa: F401
from .spec import PlanningSpec, SpecRefusal, build_spec  # noqa: F401
