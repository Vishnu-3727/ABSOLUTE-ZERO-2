# Observability — Component Specification

## Purpose
Observability owns **unified telemetry**: traces, metrics, token accounting, cost, and the audit
log — one schema, one sink. It fixes V1-M8 (telemetry scattered across five artifact directories,
un-joinable) and upholds Global Law 7 (everything observable). It is the **universal consumer**:
every component's events flow to it, giving one coherent, queryable record of system behavior.
Dashboards read from here, Learning harvests closed traces from here, and Scheduling gets its
budget/cost measurements from here. It preserves V1's fail-loud, self-documenting posture by making
faults and budget breaches first-class, auditable events.

## Responsibilities
- Ingest the entire event stream; correlate events into per-request traces (open → close).
- Maintain metrics, token accounting, and cost accounting under one schema.
- Own the append-only audit log of system actions and decisions.
- Emit `trace.opened` / `trace.closed`, `budget.exceeded`, and `alert.raised` for downstream reaction.
- Be the single read source for dashboards and analytics (no component keeps a private telemetry store).

## Owns
- The unified telemetry schema and the single telemetry sink (logical).
- Trace correlation, metrics, token/cost accounting, and the audit log content model.
- Budget-measurement and alerting thresholds.

## Never Owns
- **Durable-write mechanics** — Storage persists the telemetry bytes; Observability owns the schema/meaning.
- **Budget *enforcement*** — it *measures* and emits `budget.exceeded`; Scheduling *acts* (preempts).
- **Process spawning / the bus / retrieval** — Execution / Communication / Repository Memory.
- **Deriving lessons** — Learning consumes `trace.closed`; Observability just closes and stores traces.

## Inputs
- The full event stream from every component (universal subscription).
- Token/cost measurements emitted during LLM calls and process runs.
- Read queries from Frontend, Learning, and Scheduling.

## Outputs
- Correlated traces, metrics, token/cost records, and the audit log (via Storage-backed persistence + query API).
- Budget and alert signals.

## Events Published
- `trace.opened` — a new request trace began.
- `trace.closed` — a request trace reached its end (raw material for Learning).
- `budget.exceeded` — measured token/time/cost crossed a budget threshold.
- `alert.raised` — a fault/anomaly warranting attention (fail-loud).

## Events Consumed
- **All events** — Observability subscribes to the entire published vocabulary (universal consumer),
  which is what closes the cross-file event loop: every event any component publishes is consumed
  here at minimum. Notable correlators: `request.received`/`request.admitted` (open traces),
  `request.completed` (close traces), `verify.failed` / `process.failed` / `delivery.failed`
  (raise alerts), token/cost measurements (budget accounting).

## Dependencies
- **Communication** — the source of the universal event stream.
- **Storage** — persists telemetry, traces, and the audit log durably.
- **Frontend / Learning / Scheduling** — primary read consumers of telemetry.

## Failure Modes
- **Scattered/unjoinable telemetry** (V1-M8) → eliminated by one schema + one sink; all events share
  trace correlation IDs, so behavior is reconstructable end-to-end.
- **Telemetry loss** → persisted via Storage's durable path; buffering with backpressure rather than silent drop.
- **Alert storm** → deduplication/rate-limiting on `alert.raised`; signal not drowned in noise.
- **Accounting drift** → token/cost accounting is authoritative and reconciled; Scheduling and Context Management measure against this single source (Law 5).

## Performance Goals
- Ingest keeps up with the event stream without dropping; bounded buffering with backpressure.
- Trace correlation is incremental per event, not periodic full re-joins.
- Query latency for dashboards bounded over indexed telemetry.
- Determinism (Law 6): identical event stream → identical traces, metrics, and accounting.

## Testing Strategy
- Selftest: fixture event stream → asserted trace open/close, metric totals, token/cost accounting.
- Correlation test: interleaved multi-request events correlate into correct per-request traces.
- Alerting test: injected `verify.failed`/`process.failed`/`delivery.failed` → `alert.raised` (deduped).
- Budget-accounting test: token/cost measurements cross threshold → `budget.exceeded`.

## Future Expansion
- Distributed tracing across machines; sampling policies for high volume.
- Anomaly detection feeding Learning and predictive alerting.
- Rich cost attribution (per-plugin, per-model) for the "out-orchestrate, don't out-model" economics.

## Acceptance Criteria
- One telemetry schema and one sink; no component keeps a private telemetry store.
- Every published event in the system is consumed here (universal consumer) — closing the event loop.
- Budget breaches and faults surface as `budget.exceeded` / `alert.raised`; Observability enforces nothing itself.
- All published events (`trace.opened`, `trace.closed`, `budget.exceeded`, `alert.raised`) have named downstream consumers.
