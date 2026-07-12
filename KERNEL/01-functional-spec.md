# Kernel — Phase 1: Functional Specification

## Component Alias Table

| User name | Spec name | Role |
|-----------|-----------|------|
| Planner | Capability Planning | Intent → plans |
| Prompt Compiler | Context Management | Optimal Context Package |
| Experience Store | Learning | Traces → lessons |
| Verification Engine | Verification | Gate verdicts |

---

## What the Kernel Is

The Kernel is the system authority and execution runtime coordinator. It admits or rejects incoming requests, routes admitted work to owning components, and enforces mandatory lifecycle gates. It owns admission authority, routing authority, and gate mediation — never owns intelligence, planning, or domain work. The Kernel is fully domain-independent: it coordinates intelligent work in any domain (software, robotics, electronics, research, simulation) identically.

## Why It Exists

V1's orchestrator became a god module: it owned classification, retrieval, execution, and verification simultaneously. Verification was skippable by convention (root cause of H3 fault). V2 Kernel: small, strict, black-box authority. Gates are structurally unskippable (not policy, not convention). All domain work is delegated to peer components. Admission and routing are singular, mechanical, auditable.

## What It Owns

Every Kernel decision is a table lookup or a boolean check — never judgment.

- **Admission enforcement:** mechanical checks only — request contract is schema-valid and the system is not halted. No worthiness, quota, or capacity judgment (capacity rejection is Scheduling backpressure; admission policy content is configuration owned by Storage).
- **Routing enforcement:** static lookup of the request's *declared* type against the routing table. Table content is configuration (owned by Storage). The Kernel never inspects request content or infers intent — that is classification (Capability Planning, V1-H1). Unknown or ambiguous type → reject.
- **Gate enforcement:** mechanically apply the gate definitions owned by Lifecycle — no transition past a gate without the required passing verdict. The Kernel never decides which gates exist or which verdicts gate which transitions.
- **Execution coordination state:** bookkeeping — which request is at which lifecycle stage, which gates are pending, which verdicts have arrived.
- **Top-level halt authority:** halt admission on enumerated deterministic conditions only (Communication unavailable, Kernel fault) — never discretionary.

## What It Never Owns

- **Durable writes** — Storage is the sole writer.
- **Process spawning** — Execution is the sole spawner.
- **Event transport** — Communication owns the bus; Kernel is a peer publisher/subscriber.
- **Repository knowledge / retrieval / similarity** — Repository Memory only.
- **Planning / classification / decomposition** — Capability Planning only.
- **Verification logic** — Verification computes verdicts; Kernel only enforces them.
- **Context/prompt assembly** — Context Management owns it.
- **Domain coupling** — zero Git, zero programming-language terms, zero business logic, zero reasoning.

## Responsibilities

- Receive `request.received` and decide admission (`request.admitted` or `request.rejected`).
- Route admitted requests to owning components via Communication, with routing authority unambiguous.
- Mediate lifecycle gates: block any transition without the required passing verdict.
- Emit `gate.enforced` for every gate decision (permit or block) so every admission and transition is auditable.
- Hold final halt authority: if Communication is unavailable or Kernel itself is faulting, halt admission rather than degrade into unmediated execution.
- Coordinate request lifecycle state: track which stage each request occupies, which gates are pending.

## Non-Responsibilities

- **Verdict computation** — Verification does this; Kernel enforces the result.
- **Gate policy definition** — Lifecycle owns which gates exist and which verdicts gate which transitions; Kernel only enforces.
- **Admission/routing policy content** — configuration owned by Storage; Kernel only applies it.
- **Request classification** — Capability Planning infers intent; Kernel reads only the declared request type.
- **Intent decomposition** — Capability Planning turns intent into plans.
- **Work scheduling** — Scheduling owns priority, backpressure, budget allocation.
- **Work execution** — Execution spawns and monitors processes.
- **Prompt assembly** — Context Management constructs the Optimal Context Package.
- **Retrieval** — Repository Memory is the sole retrieval authority.
- **Telemetry storage** — Observability collects events; Storage writes them.
- **Durable state** — Storage is the sole writer of persistent state.

## Operating Principles

- **Determinism:** identical request + identical verdict state → identical admission, routing, and gate decisions (Global Law 6).
- **Deterministic-before-probabilistic:** all deterministic operations (routing, gate enforcement) happen before any LLM call.
- **Compute-once, reuse:** never recompute what another component already knows.
- **Single responsibility:** Kernel admits and routes, never plans, never executes, never verifies.
- **Explicit interfaces only:** events and structured contracts only; no reaching into peer internals.
- **Fail loud, never silent:** absence of a required verdict = blocked, never permits; ambiguous routing = rejection, never guess-route.
- **Domain independence:** every Kernel mechanism works unchanged whether workload is code, robotics, research, or simulation.

## Success Criteria

- **Zero domain terms in Kernel contracts.** No Git, no Python, no specific LLM, no field-specific jargon in admission or routing logic.
- **Structurally unskippable gates.** No transition past a gate occurs without a passing `verify.passed` verdict; missing verdict blocks automatically.
- **Complete request lifecycle.** Every admitted request is either routed to a valid owning component or explicitly rejected; never dropped or lost.
- **Identical replay yields identical decisions.** Given the same `request.received` event and identical earlier `verify.*` verdicts, admission and routing outcomes are byte-identical.
- **Kernel contains no write / spawn / retrieval / planning / reasoning.** Zero calls to Storage write APIs, Execution spawn APIs, Repository Memory retrieval, Capability Planning, or any LLM.
- **Universal observability.** Every `request.*` and `gate.*` event is consumed by Observability; every admitted request has a `gate.enforced` event per mandatory gate.
