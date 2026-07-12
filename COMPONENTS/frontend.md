# Frontend — Component Specification

## Purpose
Frontend owns the user surfaces — CLI commands and the dashboard — and is where requests enter and
system state is presented. Its governing rule: it **presents state, never owns it.** It preserves
V1's proven model-agnostic CLI surface (every capability reachable as a stdlib CLI with JSON out,
portable and testable) while ensuring the UI is a pure projection of authoritative state held by
other components. It has no private truth, so the display can never diverge from reality the way a
stateful UI would.

## Responsibilities
- Accept user input (CLI invocations, dashboard actions) and emit `request.received`.
- Render system state: request status, plans, verdicts, traces, budgets, alerts — read from owners.
- Provide the model-agnostic CLI surface with structured (JSON) output for scripting/testing.
- Surface Observability data (dashboards read from Observability, never a private store).
- Never mutate authoritative state directly; all effects flow through events/APIs of owners.

## Owns
- Presentation/rendering logic and CLI command surface (input parsing, output formatting).
- Local view/session UI state (ephemeral display state only).

## Never Owns
- **Any authoritative/domain state** — it reads from owners; it holds no source of truth.
- **Durable writes** — Storage only (user edits become write requests to Storage).
- **Process spawning / retrieval / the bus** — Execution / Repository Memory / Communication.
- **Planning, verdicts, scheduling** — respective owners; Frontend only displays them.

## Inputs
- User CLI invocations and dashboard interactions.
- State/telemetry reads from Observability, Lifecycle, and other owners' query APIs.
- Status events for live updates (`request.admitted`, `verify.*`, `trace.closed`, `alert.raised`, etc.).

## Outputs
- `request.received` events representing user intent.
- Rendered CLI/dashboard views (projections of authoritative state).

## Events Published
- `request.received` — a user submitted a request/command.

## Events Consumed
- `request.admitted`, `request.rejected` (Kernel)
- `verify.passed`, `verify.failed` (Verification)
- `trace.opened`, `trace.closed`, `alert.raised`, `budget.exceeded` (Observability)
- `request.completed` (Lifecycle)

## Dependencies
- **Communication** — submits `request.received`, subscribes to status events.
- **Observability** — the read source for dashboards/metrics/traces.
- **Lifecycle** — read source for request/repo/session state.
- **Storage** — user-initiated persistence flows through Storage (never direct writes).

## Failure Modes
- **UI/state divergence** → structurally avoided: Frontend has no private truth; a stale view is a
  read lag, corrected on next read/event, never a conflicting source of record.
- **Backend unavailable** → degrade to read-only/last-known with a clear staleness indicator; never fabricate state.
- **Malformed user input** → validated at this trust boundary; rejected with a clear message, never forwarded as a malformed request.
- **Event backlog** → show liveness/lag indicators rather than freezing or showing stale data as current.

## Performance Goals
- CLI command dispatch latency bounded; JSON output stable and machine-parseable.
- Dashboard render reflects new events within a bounded, stated freshness window.
- Determinism at the surface: identical authoritative state → identical rendered projection.

## Testing Strategy
- CLI selftest: fixture invocations → asserted JSON output shape and `request.received` emission.
- Projection tests: given fixture state/events, assert rendered view matches (no invented fields).
- Input-validation tests at the trust boundary (malformed input rejected).
- Degradation test: backend unavailable → read-only staleness indicator, no fabricated state.

## Future Expansion
- Additional surfaces (web UI, IDE integration, chat) as thin projections over the same owners.
- Role-based views and access control at the presentation layer.
- Live collaborative dashboards driven by the shared event stream.

## Acceptance Criteria
- Frontend holds no authoritative state; every displayed value traces to an owner.
- All user intent enters as `request.received`; all persistence routes through Storage.
- Input is validated at the boundary; the CLI emits structured, testable output.
- All published events consumed by Observability; all consumed events have a named publisher.
