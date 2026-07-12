# Kernel — Phase 9: Public Interface

The Kernel's entire public surface is events published and consumed via Communication; all coupling is purely via event contracts.

## Inbound Contract

| Event | Publisher | Effect |
|-------|-----------|--------|
| request.received | Frontend | Admission decision |
| request.cancelled | Frontend, System | Cancellation |
| plan.created, plan.rejected | Capability Planning | Plan bookkeeping |
| task.completed, task.failed | Scheduling | Completion gate, replan |
| verify.passed, verify.failed | Verification | Verdict recording |
| config.changed | Storage, Lifecycle | Config snapshot swap |
| session.wake, session.sleep | Lifecycle | Session boundary |

## Outbound Contract

| Event | Consumed By |
|-------|------------|
| request.admitted | Scheduling, Lifecycle, Observability |
| request.rejected | Frontend, Observability |
| request.completed | Frontend, Learning, Observability |
| request.failed | Frontend, Learning, Observability |
| request.cancelled (ack) | Frontend, Scheduling, Execution, Observability |
| gate.enforced | Observability |
| fault.recorded | Observability, Learning |
| routing directive | Capability Planning, Scheduling |
| transition-log records | Storage |

## Envelope

Every event uses phase-6 envelope (event_id, event_name, request_id, timestamp, config_version, payload); malformed rejected with fault.recorded.

## Config Data Contract

Configuration must include: request envelope schemas, routing table, gate definitions, optional timeout/retry policy. Delivered via config.changed; invalid snapshot ignored (last-good retained).

## Guarantees to Consumers

- Per-request FIFO processing
- Deterministic decisions (same events + config version = same output)
- Every decision auditable via gate.enforced + log
- At-least-once emission; dedup by event_id on consumer side
- No request dropped silently

Anything not listed here is not public. See INVARIANTS.md.
