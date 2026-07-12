# Kernel — Component Specification

> **BLACK BOX.** This spec defines the Kernel's *boundary* only — its responsibilities,
> what it owns and refuses, and its relationships to the other 13 components. **Internal
> design (admission algorithm, routing tables, gate-enforcement mechanics, data structures)
> is deliberately out of scope and will be produced in a dedicated Kernel-internals session.**
> Nothing downstream may depend on Kernel internals; components depend only on the events and
> contracts below.

## Purpose
The Kernel is the system authority: it admits or rejects incoming requests, routes admitted
work to the correct components, and mediates the mandatory lifecycle gates. It exists to fix
V1's root-cause drift — the orchestrator that grew into a god module owning classification,
retrieval, execution, and verification at once. In V2 the Kernel is small, strict, and
black-box: it holds authority but delegates *all* domain work to peer components. It also
enforces V1-H3: verification verdicts are honored structurally, not by convention — nothing
reaches a terminal "done" state without the gate the Kernel guards.

## Responsibilities
- Receive `request.received`, decide admission, emit `request.admitted` or `request.rejected`.
- Route admitted requests to the owning components (Scheduling, Capability Planning) via Communication.
- Mediate lifecycle gates: no request advances past a gate whose verdict is absent or failing.
- Hold final routing authority — the single point that says "this work is legitimate and goes here".
- Emit `gate.enforced` whenever a gate blocks or permits transition, so the decision is auditable.

## Owns
- Admission enforcement (mechanical: contract validity + halt state; policy content is configuration owned by Storage).
- Routing enforcement (static lookup on declared request type; never content inspection or intent inference).
- Gate enforcement (mechanically applies gate definitions owned by Lifecycle; never defines which gates exist).
- The system's top-level halt authority (enumerated deterministic triggers only).

## Never Owns
- **Durable writes** — Storage is the sole writer.
- **Process spawning** — Execution is the sole spawner.
- **The event bus / message transport** — Communication owns it; the Kernel is a peer publisher/subscriber.
- **Repository knowledge / retrieval / similarity** — Repository Memory only.
- **Planning, classification, decomposition** — Capability Planning.
- **Verification logic** — Verification computes verdicts; the Kernel only *enforces* them.
- **Context/prompt assembly, scheduling internals, telemetry storage** — respective owners.

## Inputs
- `request.received` events (from Frontend, via Communication).
- Verdict events (`verify.passed`, `verify.failed`) that gate transitions.
- Plan availability signals (`plan.created`, `plan.rejected`) for routing decisions.

## Outputs
- Admission decisions (`request.admitted` / `request.rejected`).
- Routing directives delivered as events to owning components.
- Gate decisions (`gate.enforced`).

## Events Published
- `request.admitted` — request accepted, routed.
- `request.rejected` — request refused at admission (with reason).
- `gate.enforced` — a lifecycle gate permitted or blocked a transition.

## Events Consumed
- `request.received` (Frontend)
- `plan.created`, `plan.rejected` (Capability Planning)
- `verify.passed`, `verify.failed` (Verification)

## Dependencies
- **Communication** — sole channel for receiving and routing events.
- **Lifecycle** — owns the state machines; the Kernel enforces gates *defined by* Lifecycle.
- **Verification** — supplies the verdicts the Kernel enforces.
- **Scheduling / Capability Planning** — the primary routing targets for admitted work.
- **Observability** — receives every Kernel event (universal consumer).

## Failure Modes
> Boundary obligations only; internal failure handling is deferred to the internals session.
- **Communication unavailable** → the Kernel cannot admit or route; it must fail loud and halt
  admission rather than route blindly. No silent local queue (that would re-create a god module).
- **Missing/absent verdict at a gate** → treated as *not passed*; transition is blocked. Absence
  never defaults to permit (fixes V1-H3).
- **Ambiguous routing target** → reject the request with a reason; never guess-route.
- **Kernel itself faulting** → surfaces as `alert.raised` via Observability; the system halts
  admission rather than degrade into unmediated execution.

## Performance Goals
> Boundary-level only.
- Admission decision latency is bounded and predictable (a routing/authority step, not a compute step).
- Gate mediation adds no unbounded wait: a gate either has a verdict or blocks — it never polls indefinitely.
- Determinism: identical request + identical verdict state → identical admission and routing outcome (Global Law 6).

## Testing Strategy
- Boundary contract tests: given event fixtures, assert the correct admit/reject/route/gate emissions.
- Gate-enforcement tests: assert no `verify.failed` or missing verdict can produce a past-gate transition.
- Negative routing tests: ambiguous or unauthorized requests are rejected, never routed.
- Determinism tests: replay identical inputs, assert identical outputs.
- (Internal algorithm tests are out of scope until the internals session.)

## Future Expansion
- Kernel-internals design session: admission algorithm, routing tables, gate mechanics.
- Multi-tenant admission policy; priority classes at admission time.
- Distributed Kernel authority (leader election) for multi-machine deployments.

## Acceptance Criteria
- Kernel spec describes **only** boundaries and relationships; contains no internal algorithm.
- Every admitted request is either routed to a valid owning component or rejected — never dropped.
- No transition past a gate occurs without a passing verdict; missing verdict blocks.
- Kernel performs no write, no spawn, no retrieval, no planning, no bus transport itself.
- All three published events are consumed by Observability; all consumed events have a named publisher.
