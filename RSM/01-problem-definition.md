# Request State Manager — Phase 1: Problem Definition

The **Request State Manager (RSM)** is a new subsystem for ABSOLUTE-ZERO V2. It
is the single source of truth for the *runtime state of every active
request* — one authoritative Request State record per request, materialized
from the events subsystems already publish on the Communication bus. This
document is Phase 1 of a 5-phase spec: it defines the problem RSM solves, the
boundary of what it owns, and the terms every later phase and every
implementer must treat as fixed. It contains no code, no APIs, no classes —
architectural decisions only.

**Naming mapping.** An external design brief uses different names for some
components than this repo does. Where this document (or any future RSM
phase) says a repo name, the mapping is: "Prompt Compiler" → **Context
Management**; "Experience Engine" → **Learning**; "Capability Planner" →
**Capability Planning**; "Workflow Scheduler" → **Scheduling**; "Execution
Kernel" → **Kernel**; "Unified Memory System" → **Repository Memory (UMS)**.
The rest of this document uses repo names exclusively.

---

## 1. Why the RSM exists

ABSOLUTE-ZERO V2 has fourteen components (see `ARCHITECTURE.md` §Component
summary), each owning one slice of a request's journey: Kernel admits and
routes it, Capability Planning classifies and plans it, Scheduling orders and
budgets it, Context Management assembles context for each step, Execution
runs it, Verification gates it, Storage commits it, Observability records it.
Every one of these components knows its own slice precisely. **None of them
knows the whole.**

Today, "what is request R doing right now" has no single answer. It is
scattered: Scheduling's in-memory work-order state knows the current step and
budget; Kernel's Ledger (`KERNEL/04-request-state.md`) knows the control-plane
lifecycle phase; Capability Planning's store knows the plan; Verification's
store knows the verdicts; Observability's episodic log knows everything that
happened but only after the fact, and only as an unindexed trace, not a
current-state view. Answering "what has request R cost so far, what failed,
what step is it on" requires stitching partial answers from several
components — exactly the kind of cross-component reconstruction
`ARCHITECTURE.md` eliminates for retrieval (fix H2, six divergent retrieval
paths) and for durable writes (fix H5, lost updates from multiple writers).
Runtime request state has the same drift shape and, before RSM, no fix.

Concretely, this drift produces:

- **The Frontend has no real state read surface.** Per `ARCHITECTURE.md`'s
  component diagram, Frontend reads only through Kernel (`FE -->|admit
  request / read state| K`). Kernel is a black box that knows control-plane
  lifecycle phase (Phase 3 states: created, initialized, scheduled, ...,
  cleanup) — it does not know the current plan, the current step, what
  context was assembled, or why a gate failed. The Frontend cannot show a
  user "step 3 of 5, verifying, $0.12 spent" without a component that
  aggregates across Scheduling, Verification, and Observability.
- **Replay/audit of a finished request is archaeology.** Observability holds
  the episodic trace (every event, append-only, unindexed — see
  `ARCHITECTURE.md` §Memory hierarchy), but reconstructing "the state of the
  request after step 3" from a raw event log requires re-deriving the
  materialization logic every time, in every consumer that wants it.
- **Budget/cost tracking is duplicated.** Scheduling tracks budget
  consumption to enforce backpressure; Observability records `cost.recorded`
  for accounting. Without one place both views resolve to, they drift.
- **Private runtime state accumulates.** Each component's in-memory view of
  "the request" (Kernel's Ledger, Scheduling's work order, Verification's
  pending checks) is legitimate for its own decisions but none is a
  system-wide read surface, and nothing stops a future component from growing
  its own private partial copy to answer a question RSM should answer
  instead.

RSM exists to be the one place where "what is this request doing, what has it
cost, what has failed" has a single, current, queryable answer — assembled
the same way the request lifecycle itself is assembled: from the event
stream, not from a new parallel write path.

---

## 2. Problems solved

| Problem | Symptom today | RSM resolution |
|---|---|---|
| Fragmented status | No component holds full-request status; Frontend reads Kernel only, which knows lifecycle phase, not plan/step/context/verification detail. | One materialized record per active request, assembled from every contributing subsystem's events. |
| Duplicated budget arithmetic | Scheduling and Observability both track cost/budget for different purposes; no reconciled view. | RSM aggregates `cost.recorded` and budget-relevant events into one queryable view; it does not replace either component's own accounting authority. |
| Unobservable in-flight execution | A request's current step, context, and verdict are visible only by querying the owning component directly (if at all, mid-flight). | RSM materializes in-flight fields (current step, last verdict, plan reference) as soon as their owning events land on the bus. |
| Non-replayable runs | Reconstructing a request's state at any point requires re-deriving materialization logic from Observability's raw episodic log. | RSM persists a per-request event journal; replaying that journal deterministically reproduces the materialized record. |
| Private state drift | Nothing stops components from growing bespoke partial views of "the request" as a workaround for missing shared state. | RSM is the system-wide read surface; components keep only derived, non-authoritative projections for their own decisions (see §5, §8). |
| Post-mortem stitching | Debugging a failed request means manually correlating Kernel, Scheduling, Verification, and Observability logs by request id and timestamp. | The per-request journal is already correlated by request id and ordered; a single query answers "what happened to R and in what order." |

---

## 3. Design goals

1. **Single source of truth.** For any active or recently-completed request,
   there is exactly one authoritative Request State record, and it is RSM's.
2. **Observable execution.** Every significant runtime event affecting a
   request (admission, planning, scheduling, context assembly, execution,
   verification, commit, failure, cost) becomes visible through Request State
   without a separate query to the originating component.
3. **Deterministic replay.** A completed request's journal can be replayed to
   reproduce a byte-identical materialization, mirroring the Kernel's own
   replay guarantee (`KERNEL/INVARIANTS.md` #17) at the system-state level.
4. **Reference over duplication.** Request State stores identifiers into
   other subsystems' owned data (plan id, artifact id, trace id, context
   package id), never copies of that content. RSM is a state ledger, not a
   second memory tier.
5. **Minimal coupling.** RSM contributes nothing new for publishers to do.
   Every subsystem already emits the events RSM consumes (`ARCHITECTURE.md`
   §Communication model, publish/consume matrix). Adopting RSM imposes zero
   new obligations on any existing publisher.
6. **Bounded memory.** Active records live in memory (or an equivalent fast
   store); a record is evicted after it reaches a terminal state and its
   journal has been persisted via Storage, subject to a configurable
   retention window. RSM does not grow unbounded, mirroring the Kernel
   Ledger's own eviction discipline (`KERNEL/04-request-state.md`).
7. **Extensibility.** A new contributing subsystem, or a new field on the
   Request State record, is addable by adding a reducer for a new event
   family — never by redesigning the record's shape or the subsystems that
   already contribute to it.

---

## 4. Scope

In scope for RSM:

- **Materialized Request State record** — one per active request, holding the
  current aggregate view: lifecycle phase, current plan reference, current
  step, last verdict, cost-to-date, failure state, and reference ids into
  every subsystem's owned data.
- **Per-request event journal** — the ordered subsequence of bus events that
  affected that request, sufficient to deterministically reproduce the
  materialized record via replay.
- **Query/read surface** — the mechanism by which any subsystem or the
  Frontend obtains a request's current materialized state or its journal.
  Full request status is answerable from RSM alone.
- **Budget/cost aggregation view** — an aggregated read of cost data sourced
  from Scheduling's budget events and Observability's `cost.recorded` events.
  This is a view, not an accounting authority: Observability remains the
  owner of token/cost accounting (`ARCHITECTURE.md` §State ownership).
- **Failure representation** — `*.failed` events (e.g. `request.failed`,
  `task.failed`, `exec.failed`, `verify.failed`) and `fault.recorded` are
  materialized into the record's failure state, so "what failed and why" is
  answerable without a separate fault-log query.
- **Replay support** — reconstructing a completed request's materialized
  state from its persisted journal.

---

## 5. Non-responsibilities

RSM never mutates any other subsystem's state and never publishes commands.
It is a durable subscriber and a query surface — nothing else.

| Responsibility | Owned instead by |
|---|---|
| Repository memory, indexing, embeddings, knowledge graphs | Repository Memory |
| Semantic understanding / retrieval | Repository Memory |
| Planning, classification, capability matching | Capability Planning |
| Scheduling, budgets, preemption, work ordering | Scheduling |
| Prompt / context generation | Context Management |
| Plugin execution, isolation, loading | Plugin Runtime / Execution |
| Verification logic and verdict computation | Verification |
| Long-term learning, lessons, faults, priors | Learning |
| Durable writes (all of them) | Storage |
| Telemetry, metrics, episodic traces, audit log | Observability |
| Transition legality of long-lived state machines (repo, plugin, session) | Lifecycle |
| Admission, routing authority | Kernel |
| Cost/token accounting authority | Observability |

RSM's *aggregation view* of cost (§4) reads from Observability's
`cost.recorded` events; it does not become a second accounting authority. If
this line blurs during Phase 2 design, Observability wins — RSM's number is
always derived, never primary.

---

## 6. Success criteria

1. Any component, or the Frontend, can answer a request's full status —
   lifecycle phase, current step, plan reference, cost-to-date, last verdict,
   failure state — by querying RSM alone. No cross-component stitching.
2. A completed request can be deterministically replayed from its persisted
   journal to produce a byte-identical materialization to the one RSM held
   live.
3. Zero authoritative private runtime state exists outside RSM. Audited
   explicitly: the Kernel's internal Ledger is reclassified (§ Kernel
   relationship, §8) as a kernel-internal control-plane projection, not a
   second authority.
4. RSM contains zero logic from the exclusion table in §5 — no planning, no
   scheduling, no verification, no retrieval, no accounting authority.
5. Adding a new contributing subsystem requires only a new event-family
   reducer in RSM — never a schema redesign of the Request State record.
6. Memory is bounded: RSM holds active records only; terminal records are
   evicted after their journal is persisted via Storage, per a configurable
   retention window.

---

## 7. Relationship to every subsystem

RSM is a durable subscriber to the Communication bus (at-least-once delivery,
idempotent by event id — `ARCHITECTURE.md` §Communication model). Event names
below are taken verbatim from `ARCHITECTURE.md`'s publish/consume matrix.

| Component | Contributes (feeds Request State) | Reads (queries RSM for) | Boundary (RSM must never take) |
|---|---|---|---|
| Kernel | `request.admitted`, `request.rejected`, `request.completed`, `request.failed` | Nothing — Kernel is authoritative for admission/routing; it does not need RSM to make decisions. | Admission/routing authority, transition-table logic, the Ledger itself. |
| Repository Memory | `memory.indexed`, `memory.queried`, `memory.updated` (only where tied to a request's context assembly) | Nothing (out of request scope; repo lifecycle is not request lifecycle) | Retrieval, indexing, similarity logic. |
| Scheduling | `task.scheduled`, `task.started`, `task.preempted`, `task.completed`, `task.failed` | Full request materialization for scheduling/replan decisions where useful (read-only). | Work-order authority, budget enforcement, preemption decisions. |
| Execution | `exec.started`, `exec.completed`, `exec.timeout`, `exec.failed` | Nothing (Execution is stateless per dispatch). | Process sandbox/timeout/retry state. |
| Capability Planning | `classify.completed`, `plan.created`, `plan.revised` | Prior request state on replan to inform strategy (read-only). | Planning logic, classification, plan content itself (RSM stores plan id, not the plan). |
| Plugin Runtime | `plugin.*` events **only when tied to a specific request's steps** (e.g. a step's tool load outcome) | Nothing. | Plugin lifecycle (discovery/registration/health) — explicitly out of RSM's scope; that is Plugin Runtime's own lifecycle, not a request's. |
| Context Management | `context.assembled` | Nothing (Context Management is per-call, ephemeral). | The Optimal Context Package content — RSM stores the context-package id only. |
| Verification | `verify.requested`, `verify.passed`, `verify.failed`, `plan.validated`, `plan.rejected` | Nothing (verdicts are one-shot). | Verdict computation, check logic. |
| Learning | none | Completed request states and journals, read-only, for distilling lessons/faults/priors. | Nothing to take — Learning is read-only against RSM. |
| Storage | `storage.committed`, `storage.rejected` | Nothing directly (RSM persists journals *through* Storage, as a writer). | Durable-write authority — RSM's own journal persistence goes through Storage like every other component's durable writes. |
| Frontend | none | All materialized Request State fields, for any active or recently-terminal request — this is Frontend's primary state read surface going forward. | Nothing — Frontend is read-only against RSM as it is against everything. |
| Communication | delivery substrate | n/a | RSM is a durable subscriber; it never redefines bus semantics. |
| Lifecycle | request-scoped session/repo events only where a request's own state machine is opened/closed (out of scope otherwise — repo/plugin/session lifecycle is not request lifecycle) | Nothing. | Transition legality of long-lived state machines. |
| Observability | `cost.recorded` (feeds the budget/cost aggregation view) | RSM's live view and journal, as an additional signal alongside its own episodic store (not a replacement for it). | Telemetry schema, metrics, audit log, cost/token accounting authority. |

---

## 8. Anti-goals / explicit tensions

**RSM is not a second Kernel Ledger, and it does not replace it.** The
Kernel's internal Ledger (`KERNEL/04-request-state.md`) is Coordinator-sole-writer,
in-memory, and exists to make control-plane decisions — table lookups against
lifecycle phase, gate verdicts, replan counts (`KERNEL/INVARIANTS.md` #1, #2).
That reason to exist does not go away. What changes is its *classification*:
the Ledger is a **kernel-internal control-plane projection** — a derived
decision cache, private to Kernel's own transition-table logic — while RSM's
Request State record is the **system-wide authoritative read surface**.
Kernel invariants I1 (Coordinator sole mutator), I15 (single-threaded loop),
and I16 (Ledger is in-memory only, transition log is the durable record)
remain fully intact; RSM changes nothing about how Kernel decides, only what
external readers consult instead of reverse-engineering Kernel's black box.
This is a reclassification, not an extraction — the Ledger keeps living where
it lives and doing what it does.

The general principle this generalizes: **"no subsystem maintains private
runtime state" means no *authoritative* private runtime state.** A
deterministic projection or cache derived from the same event stream RSM
consumes — kept by a subsystem purely to make its own fast decisions — is
permitted and expected. It is not a second source of truth as long as it
never answers a cross-component query on RSM's behalf, and as long as it
could in principle be discarded and rebuilt from the bus without any
information loss.

**RSM is not a second Observability.** Observability owns the durable
episodic history — the full, permanent, replayable trace of everything that
happened, indexed for audit, telemetry, and metrics
(`ARCHITECTURE.md` §Memory hierarchy, Episodic tier). RSM owns the *live now*
view of active requests plus a bounded per-request journal, evicted after
terminal state and retention expiry. Observability is where a request's
history lives forever; RSM is where a request's current shape lives while it
matters. They read the same bus but answer different questions, and RSM's
journal being bounded (§3, §6) is precisely what keeps it from becoming a
second, competing episodic store.

---

**Phase 2 preview:** the next phase formalizes RSM's positioning as an
event-sourced materialized view (ADR-RSM-1) — reducer semantics per event
family, the exact Request State record schema, and idempotency/ordering
guarantees against Communication's at-least-once delivery.
