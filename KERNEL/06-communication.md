# Kernel — Phase 6: Communication Contracts

## Per-Peer Contracts

| Peer | Kernel consumes | Kernel publishes toward it | Coupling |
|------|-----------------|----------------------------|----------|
| Frontend | `request.received`, `request.cancelled` | `request.admitted`, `request.rejected`, `request.completed`, `request.failed` | Request I/O; no flow control |
| Capability Planning | `plan.created`, `plan.rejected` | routing directive (request id, type, target, config version) | Fire-and-forget routing |
| Scheduling | `task.completed`, `task.failed` | routing directive | Fire-and-forget; no polling |
| Verification | `verify.passed`, `verify.failed` | — | Verdicts requested by Scheduling |
| Lifecycle | `config.changed` (state machines, gates), `session.wake`, `session.sleep` | `request.admitted` | Admission gating; state machine defs |
| Storage | `config.changed` (config content) | transition log events | Event-driven persistence; no write API |
| Observability | — | every Kernel event (universal consumer) | One-way fan-out |
| Learning | — | — | Consumes off-bus; no direct contract |

## Explicit Non-Contracts

Kernel exchanges **zero events** with: Repository Memory, Context Management, Plugin Runtime, Execution, any LLM. Their work reaches Kernel only rolled up through Scheduling/Verification events. Direct edge = drift, reject in review.

## Envelope Contract

Every event (Event Adapter validates envelope, phase 2; Kernel never interprets payload semantics):

| Field | Meaning |
|-------|---------|
| event_id | Bus-assigned, immutable; dedup key |
| event_name | From phase-3 vocabulary only |
| request_id | Request identity; null for system events |
| timestamp | Audit/correlation only |
| config_version | Kernel-published events only; schema versioning |
| payload | Opaque to Kernel; structure validated by Communication |

## D6a — Idempotency Ownership

**Guarantee:** At-least-once delivery, per-topic FIFO; Communication never deduplicates — duplicate suppression is consumer-side, and the Kernel owns its own.  
**How:** Every consumer owns idempotent application. Kernel achieves exactly-once *effect* via:
- Transition table is `(state, event)` function — post-transition duplicates match no row
- `recorded_verdicts` map writes idempotent
- Explicit dedup: `last_applied_event_id` per RequestState (bounded; FIFO makes dups adjacent)

**Rule:** Duplicate event_id = silent drop + telemetry. Unmatched non-duplicate events (illegal state/event pair) = `fault.recorded` (refines phase-3 rule).  
**Sequences:** Outbound-only (replay verification), never inbound dedup. Recovery replay bypasses dedup — Ledger being rebuilt; byte-identical check is safety.

**Amendment:** Adds `last_applied_event_id` field to phase-4 RequestState table.

## Loose Coupling Rules

- Events + structured contracts only; never peer internals
- Unknown event name = envelope reject + `fault.recorded`
- Contract changes only via versioned schema in Config View
