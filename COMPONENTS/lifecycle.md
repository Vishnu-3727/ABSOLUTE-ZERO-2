# Lifecycle — Component Specification

## Purpose
Lifecycle owns the **state machines for the long-lived things**: the request lifecycle *definition*,
repository onboarding/offboarding, plugin lifecycle, and session wake/sleep. It owns **transition
legality** — which state may move to which, and under what preconditions (including passed
verification gates). It complements the Kernel: the Kernel *enforces* gates and *advances* request
state, while Lifecycle *defines* the legal state graph the Kernel and Scheduler enforce against.
For requests this split is strict (ERRATA C4): Lifecycle authors the legal-transition table,
delivered to the Kernel as governed config data via `config.changed`; the Kernel's Ledger is the
sole runtime authority for request lifecycle state and the sole mutator of it. For repos, plugins,
and sessions, Lifecycle both defines and advances the machines. Centralizing transition legality
prevents the V1 drift where lifecycle rules were implicit and scattered across the orchestrator.

## Responsibilities
- Define the request state machine (received → admitted → planned → verified → executing → completed) as an authored legal-transition table; the Kernel alone advances request state against it (ERRATA C4).
- Own repository onboarding/offboarding lifecycle; emit `repository.onboarded` / `repository.offboarded`.
- Own plugin lifecycle state transitions; emit `plugin.lifecycle.changed`.
- Own session wake/sleep; emit `session.wake` / `session.sleep` (ERRATA C11 — sole publisher).
- Enforce transition legality: reject illegal transitions and transitions lacking required verdicts.

## Owns
- The state-machine definitions and the legal-transition tables for requests, repos, plugins, sessions.
- Transition preconditions (including gate/verdict requirements).
- Emission of authoritative state-transition events.

## Never Owns
- **Request state advancement at runtime** — the Kernel Ledger is the sole runtime authority and sole mutator of request lifecycle state; Lifecycle authors the table the Kernel loads as config (ERRATA C4).
- **Gate enforcement at routing time** — the Kernel/Scheduler enforce; Lifecycle defines legality.
- **Durable writes** — Storage persists state-machine state.
- **Process spawning / retrieval / the bus** — Execution / Repository Memory / Communication.
- **Verdict computation** — Verification; Lifecycle only requires a passing verdict as a precondition.
- **Plugin registry contents** — Plugin Runtime; Lifecycle drives its *state*, Plugin Runtime enacts registry effects.

## Inputs
- `request.admitted` (Kernel) — observed for definition audit only; the Kernel advances request state (ERRATA C4).
- `plan.created` / `plan.rejected` (Capability Planning), `verify.passed` / `verify.failed` (Verification) — transition preconditions.
- `exec.completed` / `exec.failed` (Execution) — advance/rollback execution state.
- `plugin.loaded` / `plugin.unloaded` / `plugin.health.changed` (Plugin Runtime) — plugin-state evidence.

## Outputs
- Authoritative state for repos, plugins, and sessions (via query API). Request state authority lives in the Kernel Ledger; the system-wide request read surface is RSM (ERRATA C4).
- Legal-transition decisions (accept/reject).

## Events Published
- `repository.onboarded` — a repository entered management (triggers indexing, vault provisioning).
- `repository.offboarded` — a repository left management.
- `session.wake` — a session resumed (ERRATA C11 canonical name).
- `session.sleep` — a session suspended (ERRATA C11 canonical name).
- `plugin.lifecycle.changed` — a plugin's lifecycle state transitioned.

(`request.completed` is published by the **Kernel** — the terminal Ledger transition, per
`ARCHITECTURE.md`'s event matrix and ERRATA C4. Lifecycle never publishes it.)

## Events Consumed
- `request.admitted` (Kernel)
- `plan.created`, `plan.rejected` (Capability Planning)
- `verify.passed`, `verify.failed` (Verification)
- `exec.completed`, `exec.failed` (Execution)
- `plugin.loaded`, `plugin.unloaded`, `plugin.health.changed` (Plugin Runtime)

## Dependencies
- **Kernel** — enforces the gates Lifecycle marks as required.
- **Verification** — supplies the verdicts that gate transitions.
- **Storage** — persists all state-machine state durably.
- **Repository Memory / Plugin Runtime** — react to onboarding/offboarding and plugin transitions.
- **Communication / Observability** — transport and universal telemetry consumer.

## Failure Modes
- **Illegal transition** → rejected at the state machine; there is no "skip to done" path (reinforces Law 4).
- **Transition without a required verdict** → blocked; `request.completed` is unreachable without `verify.passed` on the gated steps.
- **State loss on restart** → rehydrated from Storage; in-flight entities resume at their last durable state, not lost.
- **Stuck/orphaned entity** → timeout/sweep policy moves stuck entities to a terminal or recoverable state rather than leaking.

## Performance Goals
- Transition decision latency bounded; legality is a table lookup, not a scan.
- State reads are O(1) against maintained state, not recomputed from history each query.
- Determinism (Law 6): identical event history → identical state and identical transition decisions.

## Testing Strategy
- Selftest: fixture event sequences → asserted state trajectories and emitted transition events.
- Illegal-transition tests: assert rejection of every out-of-graph move.
- Gate-precondition tests: `verify.failed`/absent verdict → `request.completed` unreachable.
- Restart/rehydration tests: state restored from Storage matches pre-restart.

## Future Expansion
- Richer session models (long-running agents, hibernation).
- Parallel/nested sub-request lifecycles.
- Policy-as-data transition tables editable without redeploy.

## Acceptance Criteria
- All long-lived state transitions are defined here and are legal-by-construction.
- No entity reaches a terminal "completed" state without its required passing verdicts.
- State survives restart via Storage.
- All published events consumed by Observability; all consumed events have a named publisher.
