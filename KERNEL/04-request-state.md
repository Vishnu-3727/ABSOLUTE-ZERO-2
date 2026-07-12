# Kernel — Phase 4: Request State

## RequestState Entry (in-memory Ledger)

| Field | Type | Meaning | Mutator |
|-------|------|---------|---------|
| request_id | UUID | Identifier (from request.received) | Coordinator |
| declared_type | string | Request type | Coordinator |
| lifecycle_state | enum | Current phase (Phase 3 states: created, initialized, scheduled, ..., cleanup) | Coordinator |
| config_version | int | Config snapshot version used for this state's decisions | Coordinator |
| recorded_verdicts | map<gate, bool> | Arrived verdicts (verify.passed → true, verify.failed → false) | Coordinator |
| pending_gates | set<gate> | Gates blocking current transition | Coordinator |
| routing_target | string\|null | Owning component name (from routing table) | Coordinator |
| cancellation_flag | bool | True if request.cancelled was consumed | Coordinator |
| transition_sequence | int | Monotonic counter, increments per state change | Coordinator |
| last_applied_event_id | id | Inbound dedup key — duplicate delivery dropped silently (Phase 6 D6a) | Coordinator |
| replan_count | int | task.failed → scheduled loop count, compared to Config View max_replans (Phase 7) | Coordinator |

In-memory only. Created on request.received (state `created`, so the admission decision itself is recorded and replayable), evicted after cleanup. Coordinator is sole writer; all others read-only via query (Phase 2 Gate Enforcer usage).

---

## Ownership and Mutability

**Coordinator sole writer** (Phase 2 law). All other modules (Admission, Router, Gate Enforcer) and external components are readers only. External components never touch Ledger directly — state flows via published events. Mutations happen **exclusively via Phase 3 transition-table rows** applied by Coordinator; no field-level ad-hoc writes. Config snapshots arrive as config.changed events; Coordinator updates config_version before applying decisions.

---

## Synchronization

Single-threaded loop (Phase 2 D1). No locks. Sequential event processing is the sync mechanism: each event atomically mutates Ledger + emits outbound events. Next event pulled only after prior completes. Determinism: a request's decisions depend only on (its event subsequence, config snapshot version). Requests share zero mutable state; sharding by request-id preserves guarantees if loop saturates (not built until measured).

---

## Durability

Ledger is in-memory current state only. Every state transition emitted as immutable event; Storage persists the log (Phase 2 D2, sole durable writer). Crash recovery: replay transition log through Communication (event-based read path; Kernel calls no retrieval API). Full in-Kernel history rejected: violates Storage monopoly and makes Kernel a database.

---

## Versioning

Each entry carries **transition_sequence** (monotonic per request) and **config_version** (Config View snapshot at decision time). Enables byte-identical replay verification (Phase 3 D3b).

Log record schema (one immutable record per transition):

| Field | Type | Meaning |
|-------|------|---------|
| request_id | UUID | Request identifier |
| sequence | int | Transition sequence number for this request |
| prior_state | enum | State before transition |
| event | string | Event name (Phase 3 vocabulary only: request.received, verify.passed, task.completed, ...) |
| guard_result | bool | Guard check outcome (true = proceed, false = block) |
| next_state | enum | State after transition (unchanged if guard blocked) |
| config_version | int | Config snapshot at decision time |
| emitted_events | list<string> | Events published (request.admitted, gate.enforced, ...) |

---

## Concurrency

Many interleaved requests, zero shared state between Ledger entries (Phase 2 D1 sharding argument). Once terminal state + cleanup executed, entry evicted; Ledger never grows unbounded.

---

## Design Decision

**D4a — Verdict for unknown or evicted request ID:** A verify.passed or verify.failed event for a request_id not in the Ledger (unknown, already evicted, or malformed) produces fault.recorded. No entry is auto-created. Ledger entries exist only via admitted request.received. Verdict anomalies are faults, never creation triggers.
