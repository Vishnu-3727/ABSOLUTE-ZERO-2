# Communication — Component Specification

## Purpose
Communication is the **event bus and message-schema authority** — the only inter-component channel
besides the direct query APIs it defines (Global Law 3). It owns pub/sub contracts, the shared
message schema, and delivery guarantees. It exists so components stay decoupled peers (fixing the
V1 god-module drift): no component calls another's internals; everything flows over one bus with
one versioned schema and known delivery semantics. It carries the shared dotted event vocabulary
(`request.admitted`, `plan.created`, `verify.failed`, `trace.closed`, …) that every spec references.

## Responsibilities
- Transport all events between components (publish/subscribe) with defined delivery guarantees.
- Own and version the message schema and the dotted event-name vocabulary.
- Enforce pub/sub contracts: valid topics, well-formed messages, subscriber registration.
- Provide dead-letter handling for undeliverable messages; emit `delivery.failed`.
- Define the direct query-API contract shape components use for synchronous reads.

## Owns
- The bus transport and delivery-guarantee policy (ordering, at-least-once/exactly-once semantics).
- The message schema registry and event-name vocabulary.
- Dead-letter queue and delivery-failure signaling.

## Never Owns
- **Durable writes** — Storage only (persistent event log, if any, is written via Storage).
- **Process spawning** — Execution only.
- **Domain logic** — it moves messages; it never interprets planning/verdicts/retrieval.
- **Retrieval/similarity** — Repository Memory only.
- **Telemetry semantics** — Observability; Communication carries telemetry events but does not define their schema meaning.

## Inputs
- Publish requests from every component (events to deliver).
- Subscription registrations (who consumes which topics).
- Schema/topic definitions.

## Outputs
- Delivered events to subscribers.
- Delivery-failure notifications and dead-lettered messages.

## Events Published
- `delivery.failed` — a message could not be delivered within guarantees and was dead-lettered.

## Events Consumed
- (Transport-level) all published events pass *through* Communication for routing; it does not
  domain-consume them. It observes subscription/publish control messages only.

## Dependencies
- **Storage** — persists the durable event log / dead-letter records (Communication writes nothing directly).
- **Observability** — universal consumer; also receives `delivery.failed` for reliability monitoring.
- (Every component depends on Communication; it depends only on Storage, kept near the base of the layering.)

## Failure Modes
- **Undeliverable message** → dead-lettered + `delivery.failed`; never silently dropped (a dropped
  gate/verdict event would be a correctness hole).
- **Schema violation** → malformed messages rejected at publish with a clear error; never propagated.
- **Subscriber down** → delivery guarantee (retry/at-least-once) holds the message per policy; no loss on transient outage.
- **Ordering hazard** → per-topic ordering guarantees documented so gate/verdict sequences are not reordered into incorrectness.
- **Bus outage** → fail loud; components that require the bus (e.g. Kernel admission) halt rather than act blindly.

## Performance Goals
- Delivery latency bounded and predictable for the hot path (admission, dispatch, verdicts).
- Throughput scales with subscribers without per-message full-fanout scans.
- Determinism where it matters (Law 6): per-topic ordering is stable, so identical publish sequences deliver in identical order.

## Testing Strategy
- Selftest: publish → subscribe round-trip on a fixture topic, assert delivery.
- Schema tests: malformed message rejected; valid message accepted.
- Delivery-guarantee tests: subscriber-down then up → message delivered (at-least-once), or dead-lettered per policy.
- Ordering tests: per-topic sequence preserved.

## Future Expansion
- Pluggable transports (in-proc, cross-host broker) behind one delivery contract.
- Schema evolution/versioning with compatibility checks.
- Exactly-once semantics for critical topics; partitioned topics for scale.

## Acceptance Criteria
- All inter-component events flow over Communication; no component invokes another's internals.
- No message is silently dropped; undeliverable messages are dead-lettered with `delivery.failed`.
- One versioned schema and one dotted vocabulary govern all messages.
- `delivery.failed` is consumed by Observability; Communication introduces no unpublished consumed event.
