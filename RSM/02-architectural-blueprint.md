# Request State Manager — Phase 2: Architectural Blueprint

This document is Phase 2 of the RSM's 5-phase spec. It formalizes the
positioning `RSM/01-problem-definition.md` established — single source of
truth for runtime request state, assembled from bus events, never a second
write path — into concrete architectural decisions: the shape of the Request
State record, the event-sourced materialized-view philosophy that produces
it, three formal ADRs, a field-level ownership matrix, lifecycle and
eviction rules, component interaction diagrams, runtime boundaries, the
eight architectural principles applied to RSM specifically, fourteen
invariants, and the concurrency stance. It builds directly on Phase 1 and
introduces no scope not already declared there. No code, no APIs, no
classes — architectural decisions only.

**Revision note.** Amended in Phase 4 review (`RSM/04-validation-
integration-review.md`): ADR-RSM-4 (§3) and invariants RSM-I15/RSM-I16 (§9)
added. No prior decision in this document is reversed or weakened.

---

## 1. What Request State actually is

A Request State record is a **composite runtime record, one per request**,
made of named blocks. Every block is a *projection of events published by
the owning subsystem* — RSM materializes it, RSM does not originate it.
Content bodies (the plan itself, the context package, the verdict detail)
live with their owners; the record stores identifiers and references into
that owned data, per Phase 1 design goal 4 (reference over duplication).

| Block | Contents | Nature |
|---|---|---|
| **Identity** | request_id, declared_type, origin | Fixed at birth (`request.received`), immutable thereafter. |
| **Lifecycle** | current lifecycle state, admission outcome | Mirrors Kernel's admission/terminal decisions; RSM never computes lifecycle transitions itself. |
| **Plan** | plan id + revision refs, classification ref | Reference into Capability Planning's owned plan content. |
| **Work** | current step, step history refs, task states | Reference into Scheduling/Execution's owned work-order and dispatch content. |
| **Context** | context-package id per step | Reference into Context Management's ephemeral Optimal Context Package; RSM never stores package content (Phase 1 §7 boundary). |
| **Verification** | verdict refs per gate | Reference into Verification's owned verdict content. |
| **Budget** | aggregated cost/budget consumption view | A derived aggregation, not an accounting authority (Phase 1 §5: Observability wins on any conflict). |
| **Failure** | materialized failure entries | Assembled from `*.failed` families and `fault.recorded`; content, not just a pointer, since failure entries are themselves small and terminal. |
| **Journal metadata** | applied-event count, last event id, schema/reducer version | RSM's own bookkeeping — the one block RSM authors itself (see §9, RSM-I6). |

Every field traces to exactly one owning publisher (§4). A record with no
identifiable owning event for a field is a defect in this document, not a
license to invent one.

---

## 2. Architectural philosophy

**RSM is an event-sourced materialized view.** The Communication bus *is*
the write path. RSM defines no command surface, no mutation API, no second
channel by which a field gets set. State is the deterministic fold of
per-event-family reducers over the ordered subsequence of bus events that
carry a given request_id.

Two independent surfaces follow from this:

- **Write side — passive.** RSM is a durable subscriber, at-least-once in,
  reducers apply exactly once per event id (dedup), no acknowledgment or
  response flows back to publishers. Publishers do not know RSM exists.
- **Read side — synchronous, read-only.** Any subsystem or the Frontend
  queries RSM directly for a request's current materialized state or its
  journal. This is the query surface Phase 1 §4 declared in scope. Reads
  never touch the bus and never wait on it.

RSM publishes exactly one thing back to the bus: **its own telemetry**
(`state.updated`, `state.evicted` — §7). It never publishes a command, never
publishes on another subsystem's behalf, and a query against RSM never
triggers a bus event as a side effect.

This mirrors the Kernel's own relationship to its transition log (materialize
from an ordered event sequence, single deterministic fold) at system scope
instead of kernel-internal scope — the same shape Phase 1 §3 promised
(design goal 3: deterministic replay mirrors `KERNEL/INVARIANTS.md` #17).

---

## 3. Architecture decision records

### ADR-RSM-1 — Contribution via bus events, not a direct write API

**Context.** RSM must receive contributions from every subsystem that
touches a request: Kernel, Capability Planning, Scheduling, Execution,
Context Management, Verification, Storage, Observability. Some mechanism
must carry those contributions to RSM.

**Decision.** RSM consumes only Communication bus events. It exposes no
write API, no ingestion endpoint, no synchronous "report state" call. Every
event RSM reduces is an event the owning subsystem already publishes for its
own reasons, per `ARCHITECTURE.md`'s publish/consume matrix.

**Consequences.** Zero new obligations land on any publisher — no subsystem
changes behavior, adds a call, or accepts new coupling to adopt RSM
(Phase 1 design goal 5). Replay is free: the same event subsequence that
built the live record can be walked again to reproduce it (Phase 1 design
goal 3). At-least-once delivery is handled uniformly by event-id dedup
(RSM-I4) rather than by a bespoke idempotency scheme per API. RSM can be
introduced, removed, or rebuilt from the bus without any publisher noticing.

**Alternatives rejected.** A synchronous write API (`report_state(...)`)
was rejected: it creates N new couplings (one per publisher), stands up a
second write path parallel to the bus that must be kept in lockstep with
event publication, and introduces ordering ambiguity between API writes and
bus events with no principled resolution. It also reintroduces exactly the
private-write-surface pattern Phase 1 §1 identifies as the root cause of
runtime-state drift.

### ADR-RSM-2 — Kernel Ledger reclassified, not extracted

**Context.** The Kernel already keeps an in-memory Ledger
(`KERNEL/04-request-state.md`) tracking control-plane lifecycle state,
recorded verdicts, and replan counts, governed by kernel invariants I1
(Coordinator sole mutator), I15 (single-threaded loop), I16 (in-memory only,
transition log is the durable record). RSM's arrival raises the question of
whether the Ledger becomes redundant or must be torn out.

**Decision.** The Ledger stays exactly where it is, doing exactly what it
does. It is reclassified as a **kernel-internal control-plane projection** —
a derived decision cache the Coordinator uses to make routing and gate
decisions — not a second system-wide authority. RSM's Request State record
becomes the **system-wide authoritative read surface**; the Ledger remains
private to Kernel's transition-table logic and is never queried by any
other subsystem.

**Consequences.** Kernel invariants I1, I15, I16 are frozen as written — no
kernel-internal change accompanies RSM's introduction. There is no truth
conflict between the Ledger and the Request State record because both are
deterministic projections of the same underlying event stream; they can
diverge only if one has a reducer bug, which is a defect, not a design
tension. The system-wide rule "no subsystem maintains private runtime
state" is restated precisely: it means no *authoritative* private runtime
state. A deterministic, discardable, rebuildable-from-the-bus projection
kept purely for a subsystem's own fast decisions is permitted and expected
— the Ledger is the reference example.

**Alternatives rejected.** Extracting the Ledger into RSM (deleting it from
Kernel, having Kernel query RSM for control-plane decisions) was rejected:
it is an architecture change to a shipped, tested kernel for no behavioral
gain, it violates kernel invariant I19 (zero direct edges with components
outside its declared set) by adding a synchronous kernel-to-RSM dependency
on the decision-making hot path, and it would make Kernel's own gate
enforcement latency-dependent on a subsystem outside the kernel's
single-threaded control loop.

### ADR-RSM-3 — Journal is an index of event ids, not a copy of payloads

**Context.** RSM's per-request journal must support deterministic replay
(Phase 1 design goal 3). `ARCHITECTURE.md`'s delivery semantics table
already states that events destined for durable subscribers are persisted
via Storage before ack, and the memory hierarchy names Observability's
episodic tier as the durable, append-only body store for every event that
crosses the bus. The question is what RSM's own journal should contain
given that body store already exists.

**Decision.** RSM's per-request journal is an **ordered index**: event ids,
the applied sequence number, and the reducer version active when each was
applied. It is not a copy of event payloads. Replay means walking the
journal in applied order and fetching each event body from the episodic
store via the standard read path, then re-running the reducer fold.

**Consequences.** No duplication of the episodic memory tier — Observability
remains the one place event bodies live durably (Phase 1 §8, "RSM is not a
second Observability"). Journal storage cost is proportional to event count
per request, not event size. Replay correctness depends on the episodic
store's durability guarantee, which is already load-bearing for the rest of
the system. Single-writer discipline is preserved: Storage remains the sole
durable-write authority (`ARCHITECTURE.md` §State ownership); RSM's journal
write is a small index write through that same single path, not a
second body-persistence mechanism.

**Alternatives rejected.** Journaling full event payloads inside RSM's own
record was rejected: it duplicates the episodic memory tier verbatim,
directly violates Phase 1 design goal 4 (reference over duplication) and the
memory-hierarchy discipline that "runtime artifacts are committed but never
indexed" twice, and creates two divergence-prone copies of the same body
that must be kept consistent under replay.

### ADR-RSM-4 — Reducers bind to Communication-owned versioned schemas

**Context.** Phase 4's integration review (`RSM/04-validation-integration-
review.md`, Finding F2) found that RSM's reducers do not merely consume event
*names* — they read specific fields out of event payloads (e.g. the
budget-grant field carried in `task.scheduled`, the cost field carried in
`cost.recorded`). Nothing in this document as originally written said whose
schema a reducer is entitled to assume when reading such a field. Left
unstated, a reducer could come to depend on a specific publisher's internal
payload shape rather than on a contract anyone owns and versions — hidden
coupling to every publisher's internals, invisible until a publisher
refactored and silently broke a reducer with no contract-level signal.

**Decision.** Reducers bind only to Communication's owned, versioned message
schema — the same schema `ARCHITECTURE.md`'s state-ownership table already
assigns solely to Communication ("Event schema, topic/subscription
registry"). A reducer may read a field only if that field is part of the
published event's Communication-governed schema; it may never assume a
publisher's internal representation beyond what that schema publishes.

**Consequences.** A publisher is free to refactor its own internal plan,
task, or cost representations at will, as long as the published event is
unchanged — no coupling to internals survives the review. A schema version
bump to a payload a reducer depends on is not silently absorbed: it requires
an explicit reducer migration, paired with the existing `reducer_version`
mechanism (§9 RSM-I3, RSM-I12; Phase 3 §12). This is additive discipline, not
a new mechanism — it constrains which fields a reducer may already read, it
does not change how reducers apply (§9 RSM-I2 pure-fold contract is
unaffected).

**Alternatives rejected.** Per-publisher schema contracts (RSM negotiating a
bilateral contract with each of the eight-plus contributing subsystems) was
rejected: it creates N couplings, one per publisher, exactly the pattern
ADR-RSM-1 already rejected for the write path generally. Payload-agnostic,
refs-only reducers (RSM storing only event ids and never reading payload
fields at all) was rejected: it cannot materialize the Budget block (which
requires reading a granted-amount field) or parts of the Failure block
(which requires reading failure-family-specific fields) — Phase 2 §1 and
Phase 3 §6–§7 already require reducers to read domain fields, so a
payload-agnostic reducer cannot deliver the record shape this document
already committed to.

---

## 4. Ownership model — field-level ownership matrix

Event names below are taken verbatim from `ARCHITECTURE.md`'s publish/consume
matrix. RSM is a consumer of every event listed; it is never the publisher
of any of them.

| Block / field group | Owning subsystem(s) | Feeding events | RSM's role |
|---|---|---|---|
| Identity + Lifecycle | Kernel | `request.received`, `request.admitted`, `request.rejected`, `request.completed`, `request.failed` | Materialize identity at birth; mirror lifecycle/admission outcome. Never decides admission. |
| Plan | Capability Planning; Verification | `classify.completed`, `plan.created`, `plan.revised` (Capability Planning); `plan.validated`, `plan.rejected` (Verification) | Store plan id, revision ref, classification ref. Never stores plan content. |
| Work | Scheduling; Execution | `task.scheduled`, `task.started`, `task.preempted`, `task.completed`, `task.failed` (Scheduling); `exec.started`, `exec.completed`, `exec.timeout`, `exec.failed` (Execution) | Materialize current step and step/task history as refs. Never orders or dispatches work. |
| Context | Context Management | `context.assembled` | Store context-package id per step only. Never stores package content (ephemeral, per `ARCHITECTURE.md` memory hierarchy). |
| Verification | Verification | `verify.requested`, `verify.passed`, `verify.failed` | Store verdict refs per gate. Never computes a verdict. |
| Budget | Scheduling (budget grants carried in task events); Observability (`cost.recorded`) | `task.scheduled`/`task.started` budget fields; `cost.recorded` | Aggregate into one queryable view. Observability remains accounting authority (Phase 1 §5); RSM's number is always derived. |
| Failure | Any publisher (via `fault.recorded`); the `*.failed` families across all subsystems | `fault.recorded`; `request.failed`, `task.failed`, `exec.failed`, `verify.failed`, `plan.rejected` | Materialize into the record's failure state. Never determines fault cause. |
| Commit outcomes | Storage | `storage.committed`, `storage.rejected` | Reflect commit outcome into Work/Failure as applicable. Never performs or authorizes the write. |
| Journal metadata; record shape/schema version; reducer semantics; query semantics; retention/eviction policy | **RSM itself** | n/a — authored by RSM, not fed by any external event | The one block RSM originates. Everything else is a projection of someone else's event. |

RSM owns nothing on the left side of the table except the last row. This is
the literal reading of RSM-I6 (§9): RSM originates no domain values.

---

## 5. Lifecycle ownership

A Request State record's lifecycle is driven entirely by lifecycle events
already published by Kernel; RSM adds no lifecycle states of its own.

1. **Birth.** A record is created on `request.received`. RSM subscribes to
   this event as an *additional* consumer alongside Kernel — this is what
   gives Frontend (and anyone else) visibility into a request even if Kernel
   goes on to reject it, closing the gap Phase 1 §1 named ("Frontend has no
   real state read surface").
2. **Immediate terminal — rejection.** `request.rejected` moves the record
   directly to terminal. No intermediate materialization is expected between
   birth and rejection beyond what already arrived.
3. **Terminal — completion / failure / cancellation.** `request.completed`,
   `request.failed`, or a cancellation event moves the record to terminal.
4. **Journal persistence.** On reaching terminal, the journal index is
   persisted via Storage (ADR-RSM-3).
5. **Retention.** After terminal + journal persisted, the record is retained
   **read-only** for a configurable retention window (mirrors Phase 1 design
   goal 6 and the Kernel Ledger's own eviction discipline).
6. **Eviction.** The record is evicted once retention elapses. Eviction has
   exactly three preconditions, all required: terminal state, journal
   persisted, retention window elapsed. See RSM-I11.

**Mirror of kernel design decision D4a.** An event carrying a request_id RSM
does not recognize — unknown, already evicted, or malformed — produces
`fault.recorded`. RSM never auto-creates a record from a non-birth event.
`request.received` is the sole creation trigger, exactly as
`KERNEL/04-request-state.md` D4a makes `request.received` the Ledger's sole
creation trigger.

---

## 6. Component interactions

```
                              ┌──────────────────────────────┐
  Kernel ─────┐               │                                │
  Capability   \              │                                │
   Planning ────┤             │        Communication bus       │
  Scheduling ───┼── publish ─▶│   (per-topic FIFO, at-least-   │
  Execution ────┤             │    once to durable subscribers)│
  Context Mgmt ─┤             │                                │
  Verification ─┤             └───────────────┬────────────────┘
  Storage ──────┤                              │
  Observability ┘                              │ durable subscription
                                                │ (RSM = additional consumer)
                                                ▼
                                    ┌───────────────────────┐
                                    │          RSM           │
                                    │  reducers → record +   │
                                    │  journal index          │
                                    └──────┬─────────┬───────┘
                                           │         │
                            terminal-state │         │ read-only query
                            journal index  │         │ (synchronous)
                                           ▼         ▼
                                    ┌──────────┐   ┌──────────────────────┐
                                    │ Storage  │   │ Frontend              │
                                    │ (journal │   │ Scheduling (replan)   │
                                    │  index + │   │ Capability Planning   │
                                    │ terminal │   │   (replan strategy)   │
                                    │ snapshot)│   │ Learning (completed   │
                                    └──────────┘   │   states + journals)  │
                                                    │ any subsystem         │
                                                    └──────────────────────┘
                                           │
                                           │ telemetry: state.updated,
                                           │            state.evicted
                                           ▼
                                    ┌──────────────┐
                                    │ Observability │
                                    └──────────────┘
```

- **Bus fan-in.** Every publisher in §4's matrix already emits to
  Communication for its own reasons; RSM's durable subscription adds a
  consumer, not a new publish obligation (ADR-RSM-1).
- **Query fan-out.** Frontend, Scheduling, Capability Planning, Learning, and
  any other subsystem read RSM's synchronous query surface — Phase 1 §7's
  table of who reads RSM.
- **Storage persistence.** RSM writes only at terminal state: the journal
  index and a terminal snapshot, through Storage like every other durable
  writer (`ARCHITECTURE.md` §State ownership, single-writer law).
  Storage's outcome events are `storage.committed` / `storage.rejected`,
  which are one of RSM's own inputs when they carry a request_id.
- **Learning.** Reads completed request states and journals, read-only, to
  distill lessons/faults/priors — exactly the Phase 1 §7 relationship.
- **RSM telemetry.** RSM's own emissions (`state.updated`, `state.evicted`)
  flow to Observability like every other component's telemetry (Law 7).

---

## 7. Runtime boundaries

RSM sits inside the **Core** tier beside Kernel — it is a first-class
component with its own spec, not a Substrate service. On the read side it
*behaves* substrate-like (synchronous, broadly queried by many components),
but it is not reclassified as Substrate: it has request-scoped lifecycle
(§5) that Repository Memory, Storage, Communication, and Observability do
not have.

RSM never:

- publishes commands (§2);
- mutates any other subsystem's state;
- spawns processes;
- calls LLMs;
- retrieves repository knowledge;
- writes durably except the journal index and terminal snapshot, and only
  through Storage (ADR-RSM-3, §6).

**New telemetry event family.** RSM introduces two new events into
`ARCHITECTURE.md`'s publish/consume matrix:

| Event | Published by | Consumed by |
|---|---|---|
| `state.updated` | RSM | Observability (throttled/coalesced — mechanism deferred to Phase 3) |
| `state.evicted` | RSM | Observability |

This is a flag for a follow-up edit to `ARCHITECTURE.md`'s event catalog;
the actual edit is deferred to Phase 5.

---

## 8. Architectural principles

**Single responsibility.** RSM does exactly one thing: materialize and serve
request runtime state from the event stream. It contains zero planning,
scheduling, verification, prompt, retrieval, learning, or execution logic
(RSM-I13) — every one of those stays in its existing owning subsystem.

**Single source of truth.** For any active or recently-terminal request,
there is exactly one authoritative Request State record (RSM-I1). The
Kernel Ledger's reclassification (ADR-RSM-2) is what makes this true
system-wide rather than true-with-an-asterisk: a derived, non-authoritative
projection existing alongside RSM does not create a second source of truth,
because it never answers a cross-component query on RSM's behalf.

**Reference over duplication.** Every block in §1 except Failure and Journal
metadata stores ids and refs, never owned content — the Plan block stores a
plan id, not a plan; the Context block stores a context-package id, not a
package. ADR-RSM-3 extends the same discipline to the journal itself:
indices, not payload copies.

**Clear ownership.** §4's matrix assigns every field family to exactly one
owning publisher, and RSM-I6 makes that a hard invariant: RSM originates no
domain values. Where a field looks like it could be ambiguous (Budget), §4
and Phase 1 §5 explicitly resolve the ambiguity in the owner's favor.

**Observable execution.** Every significant runtime event affecting a
request becomes visible through the Request State record without a separate
query to the originating component (Phase 1 design goal 2) — that is the
entire content of §1 and §4. RSM's own actions are equally observable:
RSM-I14 requires telemetry on every materialization and eviction, with no
silent work exempted.

**Replayability.** ADR-RSM-1 makes replay free (same events, re-folded);
ADR-RSM-3 makes replay's storage cost cheap (index, not payload); RSM-I3 and
RSM-I12 make replay a hard correctness requirement, not a best-effort
feature — deviation on replay is defined as corruption, not drift.

**Extensibility.** A new contributing subsystem, or a new field, is added by
adding a reducer for a new event family (Phase 1 design goal 7). §4's
ownership matrix is designed to be appended to, never redesigned — nothing
about the record's shape depends on the current, closed set of publishers.

**Minimal coupling.** ADR-RSM-1 is this principle's entire justification:
RSM imposes zero new obligations on any existing publisher. The read side
(§6 query fan-out) is the only coupling RSM introduces, and it is coupling
in the cheap direction — readers depend on RSM, RSM depends on no reader.

---

## 9. Invariants

Immutable. A change that violates any line below is an architecture change,
not a patch.

1. Exactly one Request State record exists per request id.
2. Mutation happens only via reducers applied to bus events. No direct write
   surface exists. No field-level ad-hoc writes.
3. Materialization is deterministic: record = fold(reducer_version, journal
   order).
4. Delivery in is at-least-once; application is exactly-once — dedup keyed by
   event id.
5. Journal order is the applied order. Replay uses journal order, never
   re-merged topic order.
6. Every field has exactly one owning publisher. RSM originates no domain
   values.
7. References over bodies: the record stores ids owned elsewhere, never
   content copies.
8. RSM writes durably only via Storage, and only the journal index plus the
   terminal snapshot.
9. Reads never block reducers. Readers see consistent snapshots, never torn
   records.
10. An event for an unknown request id produces `fault.recorded`. No
    auto-create. `request.received` is the sole creation trigger.
11. Eviction requires all three: terminal state, journal persisted, retention
    elapsed.
12. Replay must be byte-identical given (journal, reducer version). Deviation
    is corruption; corruption halts.
13. RSM contains zero planning, scheduling, verification, prompt, retrieval,
    learning, or execution logic.
14. Every materialization and every eviction emits telemetry. No silent work.
15. `state.updated` and `state.evicted` are telemetry only. No subsystem may
    gate a control decision on them — a component that wants to act on a
    request's state queries RSM's read surface directly. (Added Phase 4,
    Finding F3.)
16. Reducers bind only to Communication-owned, versioned event schemas —
    never to a publisher's internal payload layout. A schema version bump
    requires an explicit reducer migration. (Added Phase 4, Finding F2,
    ADR-RSM-4.)

---

## 10. Concurrency stance

Single-threaded reducer loop, following the same precedent as the Kernel's
own single-threaded loop (`KERNEL/INVARIANTS.md` #15). Requests share zero
mutable state — each record's fold depends only on its own event
subsequence — so the scaling path, if a measured need ever arises, is
sharding by request id, exactly as `KERNEL/04-request-state.md` §Synchronization
reserves the same option for the Ledger. It is not built until measured.
Reads observe snapshot-consistent state (RSM-I9): a reader never sees a
record mid-fold. Full treatment of the reducer loop, dedup mechanics, and
snapshot isolation is deferred to Phase 3.

---

**Phase 3 preview:** the next phase specifies reducer semantics per event
family, the exact Request State record schema, and idempotency/ordering
guarantees against Communication's at-least-once delivery.
