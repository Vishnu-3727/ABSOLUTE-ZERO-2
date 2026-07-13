# Request State Manager — Phase 3: Internal Design

This document is Phase 3 of the RSM's 5-phase spec. It builds directly on
`RSM/01-problem-definition.md` (problem, scope, non-responsibilities) and
`RSM/02-architectural-blueprint.md` (record shape, ADR-RSM-1/2/3, ownership
matrix, invariants RSM-I1..I14). Phase 2 fixed *what* RSM is; this phase
fixes *how it behaves internally*: the RSM process's own lifecycle, the
record's materialization state machine, the full transition table, the
reducer pipeline, execution-history and failure/budget representation,
observability, concurrency, and performance — all implementation-independent.
No code, no APIs, no classes — behavior only.

---

## 1. Runtime lifecycle of the RSM itself

RSM is a process (or process group) with its own startup, recovery, and
shutdown sequence, distinct from any individual record's lifecycle (§2).

**Startup.** Order is fixed and matters:

1. Subscribe (durably) to every contributing topic in the Phase 2 §4
   ownership matrix. Subscription must be live — acknowledged by
   Communication — before step 2.
2. Open the read surface.

The read surface never opens before subscription is live. Opening it first
would create a window where a query could observe "no such request" for a
request whose birth event is already in flight on the bus — a false negative
indistinguishable from an actual unknown id. Subscribing first means the
first event RSM can miss is zero; any event published after subscription
begins is guaranteed delivery (at-least-once, per `ARCHITECTURE.md`
Delivery semantics).

**Restart / recovery.** RSM holds no state that survives a crash except what
it wrote through Storage (ADR-RSM-3: journal index + terminal snapshot,
persisted only at terminal). On restart:

1. Re-subscribe durably (same as startup step 1) — durable subscription
   means Communication has already persisted every event published while
   RSM was down (`ARCHITECTURE.md`: durable-subscriber events are persisted
   via Storage before ack), so nothing is lost regardless of downtime length.
2. Identify non-terminal requests as of the crash. Two sources, either
   sufficient: the last persisted checkpoint (§11) if one exists for a
   request, or a full replay of that request's event subsequence from the
   persisted log if it does not.
3. Re-fold reducers in journal order for every non-terminal request,
   reconstructing each record exactly as ADR-RSM-1/RSM-I3 require.
4. Only after all identified non-terminal requests are re-folded does the
   read surface reopen.
5. Live events arriving during recovery are buffered by the durable
   subscription (Communication holds them; RSM does not apply them out of
   order against a half-recovered record set) and applied only after
   recovery completes, in the order they arrive.

Recovery is exclusive by construction (§9): no reads, no live-event
application, until replay is done. This is fail-loud, not fail-open — a
query during recovery gets "recovering," never a stale or partially-rebuilt
answer. This mirrors Kernel's own `recovering` state
(`KERNEL/03-execution-lifecycle.md`: `[ANY non-terminal] --crash_detected-->
recovering`), applied at RSM's own process scope rather than per-request.

**Shutdown.** Drain the in-flight reducer application (finish the event
currently being folded; do not abandon mid-fold), checkpoint (§11) if a
checkpoint boundary is due, stop accepting new reads, disconnect the
subscription cleanly. No record is left half-applied.

---

## 2. State evolution — record-level materialization states

Every Request State record moves through five materialization states.
These are RSM's own bookkeeping states (Phase 2 §1 "Journal metadata"
block) — orthogonal to the Lifecycle *block*'s content, which mirrors
Kernel's admission/terminal phases. A record can be materialization-state
`active` while its Lifecycle block says `executing`; the two are different
axes.

```
                 request.received
                  (birth event)
                        │
                        ▼
                 ┌─────────────┐
   (no record)   │   absent    │
                  └──────┬──────┘
                         │ create
                         ▼
                  ┌─────────────┐   contributing events
                  │   active    │◀──────────────────────┐
                  └──────┬──────┘   (apply, stay active) │
                         │                                │
        request.completed│failed│rejected│cancelled       │
                         ▼                                │
                  ┌─────────────┐                         │
                  │  terminal   │─────────────────────────┘
                  └──────┬──────┘   late, tolerant family
                         │           (cost.recorded — apply,
       journal index +   │            stay terminal)
       terminal snapshot │
       persisted via     │
       Storage           ▼
                  ┌─────────────┐
                  │  persisted  │
                  └──────┬──────┘
                         │ retention window opens
                         ▼
                  ┌─────────────┐   read-only queries answered
                  │  retained   │   from the retained snapshot
                  └──────┬──────┘
                         │ retention window elapses
                         ▼
                  ┌─────────────┐   query answers "evicted";
                  │   evicted   │   replay still possible from
                  └─────────────┘   persisted journal + episodic store
```

- **absent** — no record exists for this request id. Default state for
  every id RSM has never seen.
- **active** — record exists, mutable, being folded against arriving
  contributing events.
- **terminal** — a terminal Lifecycle event has been applied; no further
  ordinary contributing events are expected, but late-tolerant events
  (§3) can still apply.
- **persisted** — terminal, and the journal index + terminal snapshot are
  durably written via Storage (ADR-RSM-3). Precondition for retention.
- **retained** — persisted, read-only, inside the configurable retention
  window (Phase 1 design goal 6, Phase 2 §5.5).
- **evicted** — retention elapsed. The record itself is gone from RSM's
  active/retained set; queries answer "evicted" rather than reconstructing
  it inline. Replay from the persisted journal index plus Observability's
  episodic store (ADR-RSM-3) remains possible on demand — evicted is a
  statement about RSM's own memory footprint, not about recoverability.

---

## 3. State-transition table

Full table: (record materialization state × event family) → action + next
state. "Contributing family" means any event family in the Phase 2 §4
ownership matrix other than the terminal Lifecycle family.

| Record state | Event family | Action | Next state |
|---|---|---|---|
| absent | birth (`request.received`) | Create record: materialize Identity block, initialize all other blocks empty, journal metadata seq=0. | active |
| absent | any non-birth, recognized family | `fault.recorded` (mirrors Kernel D4a). No auto-create. | absent (unchanged) |
| active | contributing family (Plan, Work, Context, Verification, Budget, Storage-commit) | Apply matching reducer, append event id + seq to journal, coalesced `state.updated` telemetry (§8). | active |
| active | terminal family (`request.completed` / `request.failed` / `request.rejected` / cancellation) | Apply reducer (Lifecycle block → terminal outcome), append to journal, trigger persistence (§2 terminal → persisted step). | terminal |
| active | duplicate event id (any family, already in journal) | Silent drop. No reducer call, no journal append, no telemetry beyond the existing dedup counter. Dedup law RSM-I4. | active (unchanged) |
| terminal / retained | late-tolerant family (`cost.recorded`) | Apply reducer, append to journal as "late" (applied-order position, not the position it would have held if on time), coalesced telemetry. | terminal / retained (unchanged) |
| terminal / retained | any other recognized family | `fault.recorded`. Not applied, not journaled. | terminal / retained (unchanged) |
| terminal / retained | duplicate event id | Silent drop. | terminal / retained (unchanged) |
| persisted | any event | Same rules as terminal/retained above — persisted is not read-only-yet-mutable-again; late-tolerant families still apply and re-trigger a journal-index write. | persisted (unchanged) |
| evicted | any event, including birth | `fault.recorded`. No auto-create, no un-eviction. Replay is the only path back to a materialized view. | evicted (unchanged) |
| any state | unregistered event family (bus carries it, RSM has no reducer) | Not applied, not journaled, not faulted — counted in a telemetry counter (§4, §8). | unchanged |
| any state | malformed event of a registered family | `fault.recorded`, not applied, not journaled (journal holds only applied events — replay stays exact). | unchanged |

**Decision — late-tolerant families.** Only `cost.recorded` is late-tolerant.
Final cost accounting legitimately arrives after `request.completed` (an
execution's cost may finalize after the request itself is marked done), and
Phase 2 §4 already scopes Budget as a derived aggregation, not part of the
terminal decision. Every other family arriving after terminal is an anomaly
— `fault.recorded`, per the row above.

**Decision — malformed events are not journaled.** An event that fails
schema validation for its own registered family produces `fault.recorded`
and is discarded, never journaled as "rejected." This keeps ADR-RSM-1's
replay guarantee exact: `record = fold(reducer_version, journal order)`
where journal order contains only events that were actually applied. A
"rejected" journal entry would force every future replay to special-case a
no-op entry, for no correctness gain.

---

## 4. Component update flow — reducer discipline

**Reducer registry.** Exactly one reducer per contributing event family —
`request.received`, `classify.completed`, `plan.created`, `plan.revised`,
`plan.validated`, `plan.rejected`, `task.scheduled`, `task.started`,
`task.preempted`, `task.completed`, `task.failed`, `exec.started`,
`exec.completed`, `exec.timeout`, `exec.failed`, `context.assembled`,
`verify.requested`, `verify.passed`, `verify.failed`, `storage.committed`,
`storage.rejected`, `cost.recorded`, `fault.recorded` (as a payload, not
just RSM's own emission), and the terminal Lifecycle family. One family, one
reducer — this is what makes §12's additive-evolution promise literal: a new
contributing subsystem is exactly one new registry entry.

**Reducer contract.** Pure, deterministic, total over its family's schema:
`(record, event) → record'`. No I/O, no clock reads, no randomness, no
cross-record access — a reducer sees only the one record it is folding into
and the one event it was handed. This is what makes RSM-I3 (deterministic
fold) and RSM-I12 (byte-identical replay) checkable properties rather than
aspirations: given the same (record, event) pair, a reducer produces the
same record' every time, everywhere, forever.

**Pipeline per event** (single-threaded, in arrival order — §9):

```
 event arrives on durable subscription
              │
              ▼
   ┌─────────────────────┐
   │ 1. dedup check       │──── already in journal? ────▶ silent drop (RSM-I4)
   │    (event id)         │
   └──────────┬───────────┘
              │ new
              ▼
   ┌─────────────────────┐
   │ 2. request-id         │──── no request_id field? ───▶ fault.recorded
   │    extraction          │     (malformed)
   └──────────┬───────────┘
              │ extracted
              ▼
   ┌─────────────────────┐
   │ 3. record lookup      │──── unregistered family? ───▶ telemetry counter,
   │    (by request_id)     │     (RSM has no reducer)      not applied/journaled
   └──────────┬───────────┘
              │ family is registered
              ▼
   ┌─────────────────────┐
   │ 4. transition-table   │──── row says fault/drop ────▶ act per §3 row,
   │    row lookup (§3)     │                                stop
   └──────────┬───────────┘
              │ row says apply
              ▼
   ┌─────────────────────┐
   │ 5. reducer apply       │──── schema invalid? ────────▶ fault.recorded,
   │    (record, event)      │     (malformed)               not applied/journaled
   │    → record'            │
   └──────────┬───────────┘
              │ applied
              ▼
   ┌─────────────────────┐
   │ 6. journal append      │  event id + seq (+ reducer_version,
   │    (event id + seq)     │  §12), applied order = journal order
   └──────────┬───────────┘
              │
              ▼
   ┌─────────────────────┐
   │ 7. coalesced telemetry │  §8 — immediate for Lifecycle-block change,
   │                          │  coalesced for work/context/budget-block change
   └─────────────────────┘
```

**Unregistered event family.** The bus carries families no reducer claims
(e.g. `memory.indexed` with no request tie, or a future event family added
for a different consumer entirely). Not applied, not journaled, not a fault
— counted in a dedicated telemetry counter so "RSM is silently ignoring
traffic" stays visible without polluting the fault channel meant for actual
anomalies.

**Malformed event of a registered family.** The family has a reducer, but
the specific event instance fails schema validation (missing required
field, wrong type). `fault.recorded`, not applied, not journaled — decided
in §3.

---

## 5. Execution history

Two granularities, both derivable from the same journal, serving different
read patterns:

- **Coarse — Work block, current.** Ordered step history: per task, {task
  id, state (`scheduled`/`started`/`preempted`/`completed`/`failed`), exec
  outcome ref (the `exec.*` event id(s) that produced it), verification
  verdict ref, storage commit ref}. This is what a live query or the
  Frontend reads — a compact, current-as-of-now list, cheap to serve
  without walking the journal.
- **Exact — journal replay.** The full event-id index (§3 journal append),
  ordered. Replaying it reproduces every intermediate state the coarse Work
  block ever held, not just the current snapshot. This is what Learning and
  audit consumers use when the coarse view isn't enough (Phase 1 §7,
  Phase 2 §6).

The coarse Work block is a projection maintained incrementally by the
reducer pipeline (step 5 of §4); it is never computed by scanning the
journal at read time (§10, O(1) reducer discipline). The journal is the
source of truth; the Work block is a cache of "where the fold currently
stands," discardable and rebuildable from the journal exactly like every
other block.

---

## 6. Failure representation

**Failure block.** Append-only list of failure entries: {source event id,
family (`exec.failed` / `exec.timeout` / `verify.failed` / `plan.rejected`
/ `task.failed` / `fault.recorded` / `storage.rejected`), step/task ref,
sequence}. Append-only mirrors the journal's own append-only discipline —
a failure entry, once recorded, is never edited or removed; a subsequent
retry or replan produces a *new* entry, not a mutation of the old one.

**Derived counters.** `replan_count` — a count of `plan.revised` events
folded so far, exposed for read convenience (retry visibility). This is a
read-time derivation over the Failure block's own entries and the applied
event stream, not a separately-tracked authoritative counter; it can always
be recomputed by re-scanning the block.

**RSM records, never reacts.** Every failure entry is inert data. RSM never
retries, never replans, never escalates, never suppresses a downstream
consumer's own reaction — that authority stays exactly where Phase 1 §5 and
Phase 2 §4/§8 already placed it: Scheduling and Capability Planning decide
what to do about a failure; RSM only makes the fact of it, and its history,
queryable.

**Terminal failure is not inferred.** A record only reaches materialization
state `terminal` via `request.failed` (or `.completed`/`.rejected`/
cancellation) arriving from Kernel — never because RSM independently
decided "enough failures have accumulated, this must be dead." Individual
`task.failed` / `exec.failed` / `verify.failed` entries land in the Failure
block and the record stays `active`; only Kernel's own terminal Lifecycle
event moves the record to `terminal`. This is the same non-inference
discipline Phase 2 §5 already establishes for the Lifecycle block generally
— RSM mirrors Kernel's terminal decision, it does not compute one of its
own from raw failure counting.

---

## 7. Budget tracking

**Budget block.** Granted budget — read from the budget-relevant fields
carried in `task.scheduled` / `task.started` payloads (Scheduling is the
grant's owning publisher, Phase 2 §4). Consumed — the running sum of
`cost.recorded` events folded for this request id (including late-tolerant
ones, §3). Remaining — derived at read time as granted minus consumed; RSM
stores no `remaining` field, because a stored value would be a second
place that arithmetic could drift, and remaining is cheap enough to compute
on every read (O(1), §10).

**RSM does aggregation arithmetic only.** No enforcement, no backpressure
decision, no budget-exceeded action — that authority is Scheduling's
(Phase 1 §5, Phase 2 §4). No accounting authority — Observability's
`cost.recorded` remains the primary record; if RSM's derived number and
Observability's own view ever disagree, Observability wins by
Phase 1 §5's explicit rule. RSM's Budget block is a read convenience, never
a second source either component checks against for a decision.

**Late-tolerant `cost.recorded`.** Consistent with §3/§6: a `cost.recorded`
event that lands after the record has gone terminal still folds into
Consumed, because final cost accounting legitimately trails request
completion. Every other late event on a terminal record is a fault; this
one family is the sole exception, decided once in §3 and referenced here
rather than re-litigated.

---

## 8. Observability of the RSM

**Emissions.**

| Event | Trigger | Coalescing |
|---|---|---|
| `state.updated` | Any applied event that changes the record. | Lifecycle-block change: emitted immediately, one per change, no batching — lifecycle transitions are rare and high-value, callers (e.g. Frontend) need them promptly. Work/Context/Budget-block change: coalesced — at most one `state.updated` per request per coalescing interval (interval is config, per Phase 2 §7's "mechanism deferred to Phase 3" — resolved here as: immediate for Lifecycle, interval-coalesced for everything else). |
| `state.evicted` | Record crosses retained → evicted (§2). | Not coalesced — one per eviction, always. |
| `fault.recorded` | Every fault path in §3/§4 (unknown-id non-birth event, late event on non-tolerant family, malformed event, absent/evicted non-birth event). | Not coalesced — every fault is individually observable, per RSM-I14 and the kernel-mirroring principle in Phase 2 §5. |
| recovery start / end telemetry | Recovery begins (§1 step 2) / recovery completes (§1 step 4, read surface reopens). | Not coalesced — two events per recovery episode, always. |

**RSM-I14 compliance.** Every materialization (each row in §3 that says
"apply") and every eviction is observable — either via the coalesced
`state.updated` (materializations) or the uncoalesced `state.evicted`
(eviction). Coalescing changes *delivery cadence* for high-frequency,
lower-value block changes; it never changes whether a change is observable
at all — the underlying journal entry (§4 step 6) is written for every
applied event regardless of whether that event's telemetry was coalesced
into a later emission.

**No metrics beyond own counters.** RSM computes no cross-request metrics,
no aggregated system health signal, no derived KPI — that is
Observability's job (Phase 1 §5 exclusion table; Phase 2 §7 "RSM never...
retrieves repository knowledge" list extends the same way to metrics
computation). RSM's own counters (dedup drops, unregistered-family count,
fault count, coalescing-interval backlog) are for RSM's own health, mirroring
`KERNEL/08-observability.md`'s I11 spirit of "a component telemeters its own
work, not the system's."

---

## 9. Concurrency model

**Single-threaded reducer loop**, same precedent as Kernel
(`KERNEL/INVARIANTS.md` #15, restated at RSM scope in Phase 2 §10). Events
apply in arrival order, no locks, no interleaving between the pipeline steps
of §4 for different events — one event fully completes step 7 before the
next begins step 1.

**Reads — versioned immutable snapshots.** Each record mutation (§4 step 5)
produces a new immutable version of that record, not an in-place mutation of
shared state. Readers grab the current version pointer for a request id and
read that immutable snapshot — they never observe a torn record (a
partially-applied reducer output) and they never block the reducer loop
(RSM-I9), because reading a pointer-and-immutable-object requires no
coordination with the writer beyond an atomic pointer swap.

**Sharding — reserved, not built.** Requests share zero mutable state: one
record's fold depends only on its own event subsequence (same argument
Kernel's Ledger makes, `KERNEL/04-request-state.md` §Synchronization). The
scaling path, if event throughput ever measurably saturates the single
loop, is consistent-hash sharding on request id: one reducer loop and one
journal per shard, with cross-request queries (e.g. Learning's "all
completed requests this week") fanning out across shards and merging at the
read surface. This is not built until measured — house rule, same as
Kernel's own deferred sharding and Phase 2 §10's explicit statement of the
same reservation.

**Recovery is exclusive.** During recovery (§1), no reads are served and no
live event is applied against the in-progress rebuild — live events queue
in the durable subscription (Communication's own persistence, not a
RSM-side buffer) and are drained only after recovery finishes. This
prevents the exact hazard versioned snapshots exist to avoid: a reader or a
live-event reducer observing a record that is only half-rebuilt from
replay.

---

## 10. Performance

| Operation | Cost | Why |
|---|---|---|
| Record lookup | O(1) | Keyed by request id (Phase 2 §1: Identity block fixed at birth). |
| Reducer application | O(1) per event | Append refs, set fields — no scans, no cross-record reads (reducer contract, §4). |
| Record size | Bounded, small | Refs only, never payload bodies (ADR-RSM-3, Phase 2 §1 "reference over duplication"). |
| Journal append | O(1) | Append to an ordered index (event id + seq + reducer_version); no re-sort, no re-index. |
| Memory footprint | Bounded | Active records bounded by admission control upstream (Kernel's own admission gate limits concurrent non-terminal requests); retained records bounded by the configurable retention window (§2, Phase 1 design goal 6). |
| Enumerate-active (list all active requests) | O(active count) | The one legitimate scan RSM performs; bounded because active count is bounded. |

No operation in RSM's write path scans the journal or touches more than one
record. The only scan is the explicitly-bounded enumerate-active query.

---

## 11. Scalability

Three independent growth axes, each with its own bound:

1. **Events/sec.** Scaling path is the sharding reservation in §9 —
   consistent-hash on request id, not built until measured.
2. **Active requests.** Bounded upstream by admission control (Kernel
   decides how many requests are concurrently non-terminal); RSM does not
   independently cap this, it inherits the bound.
3. **Journal length per request.** Bounded by request lifetime for
   ordinary requests, but a long-running request (many steps, many
   replans) can accumulate a long journal. **Decision — periodic
   checkpoints.** Every N applied events (N from config), RSM writes a
   checkpoint via Storage: the persisted prefix of the journal index up to
   that point, plus a snapshot of the record's blocks as of that point.
   Recovery (§1) then only needs to replay from the last checkpoint
   forward, not from event 1 — bounding replay cost independent of total
   request lifetime length. A checkpoint is additive to the journal, never
   a replacement for it: the full index is still the ground truth for
   audit-depth replay (§5 exact granularity); the checkpoint is purely a
   recovery-speed optimization.

**Read load.** Snapshots (§9) make reads embarrassingly parallel — any
number of concurrent readers can hold pointers to immutable versions
without coordinating with each other or with the single reducer loop.

---

## 12. Extensibility

**Schema/reducer versioning.** Every record carries `reducer_version`
(Phase 2 §1 Journal metadata block). Replay is valid only when the reducer
set used to replay matches the version recorded in the journal at the time
each event was applied (RSM-I12) — a version bump means new reducers for
new events going forward; old journals continue to replay correctly using
the reducer version they were originally folded with, because reducer
versions themselves are retained, never deleted or overwritten in place.

**Additive evolution.** A new block, or a new event family within an
existing block, is added by registering a new reducer and bumping the
schema by a minor version — never a redesign of the record shape or a
migration of existing records (Phase 1 design goal 7, Phase 2 §8
"Extensibility" principle). This is mechanical, not just a hope: §4's "one
family, one reducer" discipline is exactly what makes it mechanical.

**New contributing subsystem.** Same shape: its event family(ies) plus a
reducer registration. Nothing about the record schema, the transition table
(§3), or the pipeline (§4) changes to accommodate a new publisher — only
the registry grows.

**Query surface extension is orthogonal to the write path.** Adding a new
way to read RSM (a new query shape, a new filter, a new fan-out consumer)
never touches reducers, the transition table, or the journal format — reads
are synchronous and read-only against whatever the write path has already
materialized (§2 of Phase 2). This orthogonality is what lets Phase 4 design
the query surface without reopening any decision made here.

---

## Invariant refinements

Phase 3 decisions sharpen two Phase 2 invariants without contradicting
either:

- **RSM-I3 (deterministic fold) and late-tolerant families.** §3's decision
  that `cost.recorded` may apply after a record goes terminal could look
  like an exception to "record = fold(reducer_version, journal order)." It
  is not: late events are journaled in **applied order**, not in the order
  they would have held had they arrived on time. Replay walks the journal
  in that same applied order and reproduces the identical record — the fold
  is still a pure function of (reducer_version, journal order), it's just
  that journal order and event-origination order are allowed to differ for
  exactly one family. RSM-I5 ("journal order is the applied order, never
  re-merged topic order") already anticipated this; §3 exercises it.
- **RSM-I10 (unknown request id → fault, no auto-create) and evicted
  records.** Phase 2 RSM-I10 was written against "unknown" broadly; §3's
  transition table makes explicit that **evicted** is a distinct case from
  never-existed, but produces the identical outcome — `fault.recorded`, no
  auto-create, no un-eviction. This closes a gap Phase 2 left implicit:
  evicted-but-replayable is not a backdoor to resurrecting a live record
  from a stray event.

No other Phase 2 invariant is altered. Everything in this document is a
refinement of behavior already promised, not a new promise.

---

**Phase 4 preview:** the next phase specifies the query/read surface — the
exact shapes callers can ask for, filtering and fan-out semantics, and how
the read surface answers for `evicted` records without violating §2's
bounded-memory guarantee.
