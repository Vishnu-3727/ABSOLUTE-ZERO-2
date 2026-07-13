# WS/00 — Workflow Scheduler: Architectural Foundation

Phase 0 of the Workflow Scheduler (WS) design. Context, boundaries, constraints, principles.
No internal design here — that begins in Phase 1.

## 1. Naming & Topology Reconciliation

- **WS = the "Scheduling" component** of [ARCHITECTURE.md](../ARCHITECTURE.md) and
  [COMPONENTS/scheduling.md](../COMPONENTS/scheduling.md). One component, two names; the frozen
  spec stays authoritative for boundaries and events.
- The linear pipeline (Kernel → RSM → UMS → CM → CP → **WS** → Plugin Runtime → …) is the
  *conceptual question order*, same reconciliation as CP/00 §1. Runtime topology remains the
  ARCHITECTURE.md event hub: WS talks to nobody directly; it consumes and publishes bus events.

## 2. Position in the Operating System

WS sits at the seam between **deciding what** and **doing it**. Upstream, the Capability Planner
answers *what abilities the request needs* and seals that answer as an immutable Capability Graph
(`plan.created`). Downstream, Execution/Plugin Runtime answer *how* each step is performed. WS
answers exactly one question:

> **In what order, with what resources, and under which gates does admitted work run?**

It transforms a sealed Capability Graph into an executable workflow — ordering, dependencies,
parallelism, synchronization points, checkpoints, retry strategy, rollback boundaries — and then
governs the release of that work over time (dispatch, preemption, backpressure, budgets).

## 3. Boundaries

| Owns | Never owns |
|---|---|
| Execution order and dependency-respecting sequencing | Executing anything (Execution spawns; WS decides *when*, never *how*) |
| Parallelism, synchronization, checkpoints, rollback boundaries | Choosing plugins/providers (late binding — Plugin Runtime binds at fulfillment) |
| Work queues, priority ordering, admission-to-queue policy | Prompt generation (Prompt Compiler) or invoking reasoning (Reasoning Engine) |
| Budget ceilings + reservations for scheduling decisions (measurements from Observability) | Computing verification verdicts (WS enforces verdicts, never produces them) |
| Retry strategy and preemption/backpressure policy | Reinterpreting intent or re-deriving dependencies (CP's sealed graph is sole truth) |
| The executable workflow artifact derived from the Capability Graph | Durable writes (Storage), the bus (Communication), repository retrieval (UMS) |

## 4. Upstream & Downstream Relationships

| Neighbor | Relationship |
|---|---|
| Kernel | Source of admitted work (`request.admitted`) and gate authority; WS never manages request lifecycle. |
| Capability Planner | Supplies the sealed Capability Graph (`plan.created`/`plan.revised`). WS consumes; on execution failure it requests replanning — it never patches a plan itself. |
| Verification | Supplies gate verdicts (`verify.passed`/`verify.failed`). Structural law: no dispatch past an unpassed gate, ever (V1-H3). Three-gate split per CP/03: CP internal gates → VE plan admissibility (`plan.validated`, pre-scheduling) → post-execution outcome verification. WS anchors to gates 2 and 3. |
| Execution / Plugin Runtime | Dispatch targets. WS releases work; completion/failure/timeout events free capacity and advance the workflow. |
| Observability | Supplies budget/cost measurements (`budget.exceeded`, `cost.recorded`); consumes all WS telemetry. |
| Storage | Persists durable queue/workflow state; recovery reads it back. WS itself holds only in-memory working state. |
| RSM | Downstream mirror of WS state transitions via events; never a control input. |
| Context Manager | No direct relationship. WS never assembles or requests execution contexts (CP/03: per-step contexts are a CM engagement, not a WS one). |

## 5. Inherited Locked Constraints

Decisions already made elsewhere that every WS design phase must respect:

| # | Constraint | Source |
|---|---|---|
| C1 | Consume the sealed graph as-is: never reinterpret intent, rediscover capabilities, or re-derive dependencies from registry metadata. Requires-edges are the sole dependency truth. | CP/02, CP/03 |
| C2 | Published graphs are immutable. Alternative-branch selection at execution time never mutates the graph; failures produce a replan request answered by `plan.revised` (a new artifact through the full CP pipeline). | CP/02, CP/03 |
| C3 | CP priority bands (CRITICAL/REQUIRED/OPTIONAL/DEFERRED) are an *input* expressing importance — never a pre-baked sequence. Ordering is WS's job alone. | CP/02, CP/03 |
| C4 | Late binding: workflows reference capability ids; Plugin Runtime binds providers at fulfillment. Provider churn never invalidates a workflow. | CP/03 |
| C5 | Verification gates are structurally unskippable: `task.dispatched` requires a matching `verify.passed`; no priority fast-tracks a held task. | Global Law 4, scheduling.md |
| C6 | Budgets (token + time) are hard ceilings with preemption, never honor-system. Budget checks O(1) against maintained counters. | scheduling.md |
| C7 | Determinism (Law 6): identical admitted set + identical verdict/budget state → identical dispatch order. Nondeterminism lives only in the Reasoning Engine. | scheduling.md, CP/03, CP/04 |
| C8 | Starvation-proof: aging guarantees eventual dispatch of low-priority admitted work. | scheduling.md |
| C9 | Ownership walls: Storage = sole writer, Communication = sole bus, Execution = sole spawner, UMS = sole retrieval. | Global laws |
| C10 | Queue/workflow state survives restart via Storage; unpersisted transient work fails loud, never silently dropped. | scheduling.md |

## 6. Event Surface (canon + known drift)

Frozen consumed set: `request.admitted`, `plan.created`, `plan.validated`, `plan.revised`,
`verify.passed`/`verify.failed`, `exec.completed`/`exec.timeout`/`exec.failed`,
`plugin.disabled`/`plugin.health.changed`, `budget.exceeded`, `cost.recorded`.
Frozen published set: `task.scheduled`, `task.started`, `task.preempted`, `task.completed`,
`task.failed`, `verify.requested`, plus backpressure signaling.

Known drift to reconcile in a later phase (same pattern as CP's `classify.completed` fix):
scheduling.md names `task.dispatched` + `backpressure.engaged`; the ARCHITECTURE.md matrix has
`task.started`/`task.completed` and no backpressure row. One canon must win before implementation.

## 7. Guiding Principles for Phases 1+

1. **One question.** WS answers ordering/resources/gates. Any design needing WS to answer a second
   question (what capability? which plugin? is it correct?) belongs to another component.
2. **Plan compiler + dispatcher, cleanly separated concerns.** Deriving the executable workflow
   from the graph is deterministic transformation; releasing work over time is reactive policy.
   Both live in WS, but later phases must keep the artifact inspectable independent of the runtime.
3. **Deterministic over heuristic.** Tie-breaks are total and stable (ids in the sort key, per CM
   precedent) — never input-order, wall-clock, or hash-order dependent.
4. **Reproducible and inspectable.** The workflow derived from a given sealed graph + config is a
   byte-stable artifact; a human can read why each step runs when it runs.
5. **Scale assumption: thousands of capabilities.** Hot-path decisions bounded and independent of
   total queue depth; no full-graph rescans per dispatch.
6. **Recoverable by construction.** Checkpoints and rollback boundaries are placed when the
   workflow is derived, not improvised at failure time.
7. **Reusable plans.** Identical sealed graphs should yield identical workflows — cacheable and
   replayable, per the OS goals of minimal reasoning cost and reusable execution plans.
