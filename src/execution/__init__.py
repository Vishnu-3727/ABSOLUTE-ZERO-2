"""Execution — the sole process spawner (COMPONENTS/execution.md; Global
Law 3; V1-H4 containment; ERRATA C14).

engine.py: Engine + ExecutionHandle — deterministic PENDING → RUNNING →
terminal state machine; bounded retries; unconditional timeouts;
child-process containment (a tool's failure is a returned result, never a
caller crash); append-only execution journal through a Storage namespace
handle; `exec.*` lifecycle events through the Communication bus.

Execution owns execution state only: no planning, no routing, no policy,
no output persistence (callers own their outputs), no authorization.
"""
from .engine import (BadSpecError, CANCELLED, CapsUnsupportedError,  # noqa: F401
                     COMPLETED, Engine, ExecutionHandle, ExecutionRefusal,
                     FAILED, IllegalTransitionError, PENDING, RUNNING,
                     TERMINAL, TIMEOUT)
