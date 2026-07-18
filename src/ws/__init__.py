"""WS — the Workflow Scheduler (COMPONENTS/scheduling.md; WS/00-02;
ERRATA C5 dispatch gate, C6 budget layering, C15 event canon).

compiler.py  sealed Capability Graph -> immutable Execution Workflow
             (WS-W1..W12): 1:1 units, verbatim edges, canonical total
             order, derived levels, unresolved alternative groups,
             content-hashed determinism tuple
runtime.py   WorkflowRun — all runtime state, outside the artifact
             (WS-E1..E10): readiness, canonical-order dispatch through
             the injected binder seam to Execution, per-unit
             verified-success completion, journaled + replayable

Deferred by their own specs, refused not improvised (ERRATA C15 §3):
priority/budget/aging/backpressure policy, workflow-level retry,
checkpoints/rollback.
"""
from .compiler import BANDS, Workflow, WorkflowRejected, compile_workflow  # noqa: F401
from .runtime import (ACTIVE, CANCELLED, COMPLETED, EXECUTING, FAILED,  # noqa: F401
                      NOT_EXECUTED, PENDING, STALLED, SUCCEEDED,
                      SchedulerRefusal, WorkflowRun)
