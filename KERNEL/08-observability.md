# Kernel — Phase 8: Observability

**Core thesis:** Kernel stores no telemetry (Observability collects, Storage persists — phase 1 non-responsibilities). Kernel's observability duty = emit unconditionally. Every action is already an event; observability is nearly free. This phase enumerates WHAT is emitted and guarantees completeness (Global Law 7: no action without telemetry).

---

## Emission Completeness

Every Kernel action from phases 3–7 emitted to Observability (universal consumer):

| Kernel Action | Emitted Event(s) | Triggering State(s) |
|---------------|------------------|-------------------|
| Admission decision | `request.admitted` OR `request.rejected` + `gate.enforced` | created → initialized/failed |
| Routing decision | `routing directive` + `gate.enforced` | initialized → scheduled/failed |
| Task completion (permit) | `request.completed` + `gate.enforced` (permit) | executing → completed |
| Task completion (block) | `gate.enforced` (block) | executing → verifying |
| Cancellation ack | `request.cancelled` + `gate.enforced` | any non-terminal → cancelled |
| Verdict recorded (no transition) | transition-log record | executing (verify.* arrives) |
| Verify failed → replan | `gate.enforced` (block) | verifying → scheduled |
| Task failed → replan | transition-log record (replan_count++) | executing → scheduled |
| Config snapshot accepted/rejected | transition-log record (config_version bump) / `fault.recorded` | any state |
| Duplicate event dropped | transition-log no-op record, verdict=duplicate (D8a) | any state; D6a dedup |
| Crash/fault detected, halt/degradation change | `fault.recorded` | any non-terminal → recovering/halted |

---

## Metrics Derived, Not Computed

Kernel computes NO metrics (no counters, histograms, or aggregations — that is Observability's job). Examples of derivable metrics:

| Metric | Source | Notes |
|--------|--------|-------|
| Admission rate; rejection reasons | `request.admitted` / `request.rejected` counts + gate block reasons | Zero counter state in Kernel |
| Gate block rate | `gate.enforced` (block) event frequency by gate | Observability aggregates stream |
| Replan count distribution | Ledger `replan_count` value at transitions | Cost signal; Kernel only records |
| Time-in-state per request | Transition log timestamps (sequence order, config_version) | Correlation: request_id |
| Duplicate rate | Transition log records with verdict=duplicate | Silent drop; no fault stream pollution |
| Halt frequency | `fault.recorded` event count | Determinism errors, replay deviations |

---

## Resource & Cost Accounting

Token/compute/plugin cost accounting belongs entirely to Observability, fed by Scheduling and Execution emissions. Kernel never sees work internals, never emits cost signals itself. Every Kernel-published event carries **config_version + request_id**: correlation keys enabling per-request cost rollup downstream. Kernel stateless on cost; Observability owns accounting schema and aggregation.

---

## Tracing

`request_id` = trace ID; `transition_sequence` (Phase 4 Ledger field) = span order within trace. Per-topic FIFO + single-threaded loop = total Kernel-side causality per request (no separate causal tracking needed). Observability opens trace on `request.received`, closes on terminal state (`request.completed` / `request.failed` / `request.cancelled`). Request IDs remain stable through recovery replay.

---

## Design Decision D8a — Duplicate-Drop Representation

Dropped duplicates (Phase 6 D6a: "silent drop + telemetry") surface without polluting the fault stream. **How:** No event emitted on bus; instead the drop is recorded as a transition-log no-op record (event_id, verdict: duplicate=true, state unchanged). Storage persists it; Observability derives duplicate rate from log records; fault stream stays clean; replay remains byte-identical (dup records replay as no-ops, no state mutation).

---

## What Kernel Never Does

- **No telemetry files**, no metrics endpoints, no sampling decisions, no retention policy (Storage owns durability, Observability owns retention).
- **No dashboards, no alerting** — Observability owns both.
- **Emission is unconditional**, never sampled. Law 7 completeness beats volume; volume control is Observability's problem downstream.
- **No cost measurement, no budget enforcement** — Scheduling/Execution measure and emit cost; Scheduling enforces budgets. Kernel is decoupled from both.
