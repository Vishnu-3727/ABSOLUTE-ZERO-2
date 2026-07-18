# Scheduling — Component Specification

## Purpose
Scheduling orders and admits work — tasks, agents, and background jobs — and enforces priorities,
budgets (token *and* time), preemption, and backpressure. Critically, it enforces that
**verification gates cannot be scheduled around** (Global Law 4, fixing V1-H3): a task whose gate
has not passed is never dispatched, no matter its priority. It turns the Kernel's admitted requests
into an ordered, budget-bounded flow of dispatchable work.

Gate layering (ERRATA C5, per `VAE/03` §3.1/§3.2): Scheduling's gate guards **task dispatch**;
the Kernel's gate guards **request lifecycle transitions** (completion). Two gates, two objects,
composed fail-closed — a permit requires both layers. The Kernel is the gate *authority*: it owns
gate definitions (governed config) and is the sole emitter of `gate.enforced` audit records.
Scheduling's refusal is a scheduling hold, never a gate verdict.

## Responsibilities
- Consume `request.admitted` and place resulting work into priority-ordered, budget-bounded queues.
- Enforce token + time budgets as ceilings (a V1 strength kept: budget-as-ceiling, not honor-system).
- Dispatch work to Execution / Capability Planning only when all preceding gates are satisfied.
- Preempt and apply backpressure when budgets exhaust or downstream saturates.
- Refuse to dispatch any task past a gate lacking a `verify.passed` verdict.

## Owns
- Work queues, priority ordering, and admission-to-queue policy.
- Budget accounting *for scheduling decisions* (ceilings, reservations) — sourced from Observability's measurements.
- Preemption and backpressure policy.

## Never Owns
- **Durable writes** — Storage only (queue state persisted via Storage).
- **Process spawning** — Execution only; Scheduling decides *when*, Execution decides *how*.
- **The bus** — Communication only.
- **Verification logic** — it enforces verdicts, never computes them.
- **Gate authority** — gate definitions and `gate.enforced` audit records are the Kernel's (ERRATA C5); Scheduling holds ungated work, it never rules on gates.
- **Repository retrieval** — Repository Memory only.

## Inputs
- `request.admitted` (routed work from Kernel).
- `verify.passed` / `verify.failed` (gate verdicts).
- `exec.completed` / `exec.failed` (to free capacity and advance queues).
- `budget.exceeded` (from Observability's token/cost accounting).

## Outputs
- Dispatch directives (as events) to Execution and Capability Planning.
- Backpressure signals to upstream producers.

## Events Published
- `workflow.created` — a compiled Execution Workflow reached Published (ERRATA C15).
- `task.scheduled` — work enqueued with priority and budget reservation.
- `task.started` — work released downstream, the dispatch announcement (ERRATA C15; `task.dispatched` is a dead draft name and is never published).
- `task.completed` / `task.failed` — a unit reached its terminal outcome.
- `verify.requested` — WS asking Verification for a unit's verdict.
- `task.preempted` — running/queued work paused or evicted.
- `backpressure.engaged` — intake throttled; deferred until the dispatcher-policy phase (ERRATA C15 — chartered, not yet registered or published).

## Events Consumed
- `request.admitted` (Kernel)
- `verify.passed`, `verify.failed` (Verification)
- `exec.completed`, `exec.failed`, `exec.timeout` (Execution)
- `budget.exceeded` (Observability)

## Dependencies
- **Kernel** — source of admitted work and gate authority.
- **Verification** — supplies gate verdicts.
- **Execution** — the dispatch target for external work.
- **Observability** — supplies budget/cost measurements; universal consumer of Scheduling events.
- **Storage** — persists durable queue state.
- **Communication** — carries all dispatch/backpressure events.

## Failure Modes
- **Gate bypass attempt** (V1-H3) → structurally impossible: `task.started` requires a matching
  `verify.passed` (ERRATA C15); a high-priority task with a failing/absent gate is held, never fast-tracked.
- **Budget exhaustion** → preempt and emit `task.preempted` + `backpressure.engaged`; never overspend silently.
- **Downstream saturation / timeout storm** → backpressure upstream; do not keep dispatching into a failing Execution.
- **Queue-state loss** → recover from Storage-persisted state; unpersisted transient work fails loud, not silently dropped.
- **Priority inversion / starvation** → aging policy guarantees eventual dispatch of low-priority admitted work.

## Performance Goals
- Dispatch decision latency bounded and independent of total queue depth for the hot path.
- Budget checks are O(1) against maintained counters, not recomputed scans.
- Determinism (Law 6): identical admitted set + identical verdict/budget state → identical dispatch order.

## Testing Strategy
- Selftest: fixture queue + verdict states, assert dispatch order and that no ungated task dispatches.
- Budget-ceiling tests: inject `budget.exceeded`, assert preemption/backpressure.
- Starvation tests: assert aging eventually dispatches low-priority work.
- Determinism replay tests.

## Future Expansion
- Deadline-aware and fair-share scheduling classes.
- Cross-machine distributed scheduling with global budget reservations.
- Predictive backpressure using Learning's throughput priors.

## Acceptance Criteria
- No task is dispatched past an unpassed gate under any priority.
- Token and time budgets are enforced as hard ceilings with preemption.
- Queue state survives restart via Storage.
- All published events consumed by Observability; all consumed events have a named publisher.
