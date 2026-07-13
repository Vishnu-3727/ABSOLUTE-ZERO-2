# Request State Manager — Phase 5: Implementation Specification

This document is Phase 5, the final phase, of the RSM's 5-phase spec. It
does not design anything new. RSM's architecture is **frozen as of the
Phase 4 review** (`RSM/04-validation-integration-review.md`): the record
shape and ownership matrix (`RSM/02-architectural-blueprint.md`), the
runtime lifecycle, transition table, and reducer pipeline
(`RSM/03-internal-design.md`), and invariants RSM-I1 through RSM-I16
(`RSM/02-architectural-blueprint.md` §9, as amended by Phase 4) are all
closed. This document translates that closed architecture into an
executable build plan for a Sonnet-class implementer in a later session —
module boundaries, milestone order, testing strategy, validation checklist,
migration notes, and the two small `ARCHITECTURE.md` registration edits
Phase 2 §7 and Phase 4 Part A deferred to here. No code, no APIs, no
classes — this is a build plan, not a build.

Target: Python 3.12+, stdlib-only (house law, same as UMS —
`UMS/00-implementation-blueprint.md` "Global laws"). Package: `src/rsm/`,
beside `src/kernel/` and `src/ums/`. Tests: `tests/test_rsm_phase1.py`
through `tests/test_rsm_phase5.py`, following the existing
`tests/test_ums_phase1..5.py` / `tests/test_kernel_spec.py` naming
convention.

---

## 1. Internal modules

Twelve conceptual modules. No signatures below — module boundaries and
invariant coverage only. "Key invariants it carries" names the invariant(s)
whose correctness depends primarily on that module, not every invariant
that happens to touch it.

| Module | Responsibility | Key invariants it carries |
|---|---|---|
| `record` | The Request State record: Identity, Lifecycle, Plan, Work, Context, Verification, Budget, Failure, Journal-metadata blocks (Phase 2 §1). Records are immutable versioned snapshots — a mutation produces a new version, never an in-place edit. | RSM-I9 (snapshot isolation, no torn reads) |
| `store` | Request-id-keyed maps: active records, retained (terminal, persisted, inside retention window) records. Owns the `absent → active → terminal → persisted → retained → evicted` bookkeeping (Phase 3 §2) and the eviction gate. | RSM-I1 (exactly one record per id), RSM-I11 (eviction requires terminal + persisted + retention elapsed) |
| `transitions` | The record-state × event-family table from `RSM/03-internal-design.md` §3, verbatim: birth-only creation, late-tolerant `cost.recorded` on terminal/retained/persisted, unregistered-family counting, malformed-event faulting, evicted-state fault-no-resurrect. | RSM-I10 (unknown/evicted id → fault, no auto-create, `request.received` sole creation trigger) |
| `reducers` | Registry of exactly one pure reducer per contributing event family (Phase 3 §4's full family list). Each reducer is `(record, event) → record'`: no I/O, no clock, no randomness, no cross-record access. Reducers read only fields Communication's versioned schema publishes for that event. | RSM-I2 (mutation only via reducers, no ad-hoc write surface), RSM-I3 (deterministic fold), RSM-I6 (RSM originates no domain values), RSM-I16 (reducers bind to Communication-owned versioned schemas, ADR-RSM-4) |
| `journal` | Per-request applied-event-id index: event id, applied sequence number, reducer version active at apply time. Periodic checkpoints (persisted prefix + block snapshot) every N applied events, N from `config_view`. | RSM-I5 (journal order is applied order, never re-merged topic order) |
| `dedup` | Event-id membership check against a request's journal. An event id already present is a silent drop: no reducer call, no journal append, no telemetry beyond a dedup counter. | RSM-I4 (delivery at-least-once in, application exactly-once) |
| `ingest` | The pipeline (Phase 3 §4): dedup → request-id extraction/record lookup → transition-table row lookup → reducer apply → journal append → coalesced telemetry. Single-threaded loop, one event fully completes before the next begins. This is the **sole caller** of `reducers` and the sole mutator of `store`. | RSM-I2 (sole mutator discipline — enforced structurally, see §4 structural test) |
| `query` | The read surface: snapshot-by-request-id, block sub-reads, budget aggregation (`remaining = granted - consumed`, derived at read time, never stored), failure-entry listing, enumerate-active. Answers for `evicted` ids per Phase 3 §2/§3 (`fault.recorded`-equivalent read response, not an exception). Reads never call a reducer and never touch the bus. | RSM-I9 (reads never torn, never block reducers) |
| `persistence` | Hands `journal` and `record` data to Storage: journal-index document, terminal-snapshot document, checkpoint document (ADR-RSM-3, RSM-I8). Uses a Storage double (`storage_double`-equivalent, see §3) until real Storage exists — precedent `src/ums/storage_double.py`. | RSM-I8 (durable writes only via Storage: journal index + terminal snapshot + checkpoints, nothing else) |
| `recovery` | Startup/restart replay fold: re-subscribe, identify non-terminal requests from the last checkpoint or a full journal replay, re-fold in journal order, only then reopen `query`. Byte-identical verification against a live-held record where one exists; halts loudly on mismatch. | RSM-I12 (byte-identical replay, deviation = corruption, halts) |
| `telemetry` | Emits `state.updated` (immediate for Lifecycle-block changes, coalesced per `config_view`'s interval for Work/Context/Budget-block changes), `state.evicted` (always immediate, one per eviction), `fault.recorded`, RSM's own health counters (dedup drops, unregistered-family count, fault count, coalescing backlog). Never gates any decision — telemetry only. | RSM-I14 (every materialization and eviction observable), RSM-I15 (telemetry-only, no subsystem gates control on it) |
| `config_view` | Read-only view of: retention window, coalescing interval, checkpoint N. Mirrors the kernel Config View precedent (`KERNEL/02-internal-architecture.md`) — RSM never writes config, only reads a resolved snapshot of it. | (supports RSM-I11, RSM-I14 indirectly; no invariant of its own) |
| `bus_double` | Test double for the Communication subscription (durable, per-topic FIFO, at-least-once) until the real bus exists. Publishes events into `ingest`'s pipeline in a controllable, test-scriptable order; supports simulated redelivery for dedup tests and simulated cross-topic skew for property tests. Precedent: kernel's own `bus.py` double pattern, referenced by `UMS/00-implementation-blueprint.md` ("in-memory test doubles acceptable, kernel bus pattern"). | (test infrastructure; no invariant of its own — see ADR-RSM-4 risk table §8) |

Thirteen modules total (twelve conceptual responsibilities plus the two
doubles counted as one row each — `persistence` uses a Storage double,
`ingest`'s input uses a bus double). `record` and `store` are the only
modules holding mutable process state; every other module is either pure
(`reducers`, `transitions`), a thin coordinator (`ingest`), or read-only
(`query`, `config_view`).

---

## 2. Implementation order — 5 milestones

Same build pattern as UMS: one phase per session, each milestone ends with
a test-suite commit (`UMS/00-implementation-blueprint.md` "Build order").
Milestones are strictly ordered — M2 needs M1's record/store/transitions,
M3 needs M2's reducers to have something to query, M4 needs M3's query
surface to verify persisted state is still readable, M5 needs M4's
persistence to have something to recover from.

### M1 — Skeleton

`record` + `store` + `transitions`. Birth and terminal paths only — no
reducers yet beyond the two that create/terminate a record. The
record-state machine from `RSM/03-internal-design.md` §2 (`absent → active
→ terminal → persisted → retained → evicted`).

**Tests.** Transition-table exhaustive: every (record state, event family)
row from §3's table exercised at least once, including the "unchanged" rows
(unregistered family, malformed event, evicted-state fault). Duplicate
`request.received` for an already-active id (must not re-create).
Unknown-id fault: any non-birth event against `absent` produces
`fault.recorded`, no record created.

### M2 — Reducers + journal

`reducers` (full registry — every contributing family from
`RSM/02-architectural-blueprint.md` §4's ownership matrix, one reducer
each) + `journal` + `dedup`, wired through a minimal `ingest`.

**Tests.** Per-reducer determinism/purity: same `(record, event)` in →
same `record'` out, every time; a reducer given a second, unrelated record
in the same process must not have touched it (cross-record isolation
check). Duplicate delivery (same event id redelivered) is dropped, not
re-applied — journal length unchanged, record unchanged. An event whose
family has no registered reducer is counted (telemetry counter), not
faulted, not journaled. A malformed event of a *registered* family is
faulted, not journaled — journal must contain zero entries for it.

### M3 — Query surface

`query` fully implemented: snapshots, block reads, budget aggregation +
`remaining` derivation, failure listing, enumerate-active.

**Tests.** Reads never torn: interleave `ingest` applies with concurrent
`query` reads (simulated interleaving, single-threaded loop still holds —
the test asserts a reader never observes a half-applied reducer output, per
RSM-I9) via versioned-snapshot pointer swaps. Budget arithmetic:
`remaining = granted - consumed` matches hand-computed values across
scripted `task.scheduled`/`cost.recorded` sequences, including the
late-tolerant `cost.recorded`-after-terminal case. D4a-mirror query
answers: querying an `evicted` request id returns the defined
"evicted, not found live" answer, never a stale reconstruction and never a
crash.

### M4 — Persistence + eviction

`persistence` (Storage-double writes: journal index, terminal snapshot,
checkpoints every N applied events) + `config_view` (retention window,
checkpoint N) + the eviction gate in `store`.

**Tests.** Eviction ordering: eviction never fires unless all three
preconditions hold (terminal, persisted, retention elapsed) — property test
covering all 2^3 - 1 partial-precondition combinations, each must NOT
evict. Checkpoint prefix correctness: a checkpoint's persisted prefix,
replayed alone, reproduces the same block state the live record held at
that checkpoint's sequence number. Late-tolerant `cost.recorded` arriving
after terminal (and even after persisted, per §3's "persisted is not
read-only-yet-mutable-again" row): applies, re-triggers a journal-index
write, does not block or reverse eviction eligibility for the other two
preconditions.

### M5 — Recovery + replay + telemetry

`recovery` (replay fold, byte-identical verification, reads-closed-until-done)
+ `telemetry` (coalesced `state.updated`, `state.evicted`, `fault.recorded`,
counters) + `bus_double` finalized for end-to-end scripting.

**Tests.** Coalesced `state.updated`: Lifecycle-block changes emit
immediately (one per change, no batching); Work/Context/Budget-block
changes coalesce to at most one emission per request per configured
interval. End-to-end lifecycle test: drive the full `ARCHITECTURE.md`
request-lifecycle event sequence (admission → plan → steps → verify →
commit → completed) through `bus_double`, asserting the final record, the
final journal, and a full replay of that journal are all identical —
this is the single test that exercises every module in one pass and is the
closest thing RSM has to an acceptance demo.

---

## 3. Conceptual interfaces

Prose only — exact signatures are the implementer's freedom; the semantics
and invariants below are not.

**What `ingest` consumes.** A bus envelope carrying: event id (dedup key),
topic (which reducer family it belongs to), schema version (which reducer
version applies, per ADR-RSM-4/RSM-I16), and payload (the
Communication-owned versioned fields a reducer is entitled to read — never
more). One envelope per `ingest` pipeline pass (§1 `ingest`'s
single-threaded loop, `RSM/03-internal-design.md` §4).

**What `query` exposes.** A record snapshot by request id (current
materialized view, or the retained/evicted-appropriate answer per §2's
M3 tests); block sub-reads (one block — Identity, Lifecycle, Plan, Work,
Context, Verification, Budget, Failure, Journal-metadata — without
serializing the whole record); active-request enumeration (bounded by
admission control upstream, `RSM/03-internal-design.md` §10); journal read
for a completed (terminal or later) request, used by recovery and by
Learning's own read path (`RSM/01-problem-definition.md` §7).

**What `persistence` hands Storage.** Three document kinds, each format
versioned so a future real-Storage swap or a schema evolution can detect
mismatch rather than silently misreading: a journal-index document (ordered
event-id + sequence + reducer-version tuples for one request); a
terminal-snapshot document (the record's block state at the moment it
reached `terminal`); a checkpoint document (persisted journal prefix +
block-state snapshot as of a checkpoint sequence number, per
`RSM/03-internal-design.md` §11). All three are opaque documents from
Storage's point of view — Storage stores bytes keyed by an id, per the
`storage_double` precedent (`src/ums/storage_double.py`: `write(key,
data)`/`read(key)`/`exists(key)`, blob semantics only).

**What `telemetry` emits.** `state.updated` (coalesced per §1), `state.
evicted` (always immediate), `fault.recorded` (every fault path in the
`RSM/03-internal-design.md` §3/§4 transition table and pipeline, never
coalesced), recovery start/end signals, and RSM's own internal health
counters (dedup-drop count, unregistered-family count, fault count,
coalescing backlog depth) exposed for RSM's own observability, not as bus
events (`RSM/03-internal-design.md` §8, "no metrics beyond own counters").

---

## 4. Testing strategy

**Unit.** `reducers` (purity/determinism, one test per registered family
minimum), `transitions` (exhaustive table coverage, §2 M1), `dedup`
(redelivery drop, §2 M2).

**Property-style.** Random event interleavings across families, generated
against `bus_double`'s simulated cross-topic skew (Phase 4 Finding F4 —
the design already proves no reducer depends on cross-topic order, so this
suite is the executable check of that proof, not a search for a
counterexample). Property under test: block correctness (each block's
value matches a hand-computed fold over the same event set, regardless of
arrival interleaving) and replay identity (any interleaving that produced a
given journal, replayed in that journal's own applied order, reproduces the
same record every run).

**Golden fixtures.** Scripted event streams (fixed request, fixed event
sequence) → golden final records + golden journals, checked in under
`tests/fixtures/`, following the UMS golden-query precedent
(`UMS/00-implementation-blueprint.md` Phase 4 "Golden-query fixture suite
passes"). A golden fixture catches an accidental reducer or transition-table
regression that a property test's randomization might not hit on a given
run.

**Structural test.** Source-scan test, kernel `IT-7` precedent
(`KERNEL/10-test-spec.md`: "code audit/trace — Coordinator is sole Ledger
mutator"). RSM's version: scan `src/rsm/` and assert that only `ingest`
imports and calls into `reducers`, and only `ingest` (via `store`) performs
a record mutation — no other module constructs or calls a reducer, no other
module writes to `store`'s active/retained maps directly. This is the
executable form of RSM-I2 ("mutation happens only via reducers applied to
bus events... no field-level ad-hoc writes").

**End-to-end.** The M5 full-lifecycle test (§2).

**Invariant coverage table.** All sixteen invariants, RSM-I1 through
RSM-I16, each mapped to at least one test. No gaps.

| Invariant | Statement (abbreviated) | Verifying test |
|---|---|---|
| RSM-I1 | Exactly one record per request id | M1 duplicate-create test |
| RSM-I2 | Mutation only via reducers; no ad-hoc write surface | Structural test (source scan) |
| RSM-I3 | Deterministic fold: `record = fold(reducer_version, journal order)` | M2 per-reducer determinism test; property-style replay-identity test |
| RSM-I4 | At-least-once in, exactly-once applied (event-id dedup) | M2 duplicate-delivery-dropped test |
| RSM-I5 | Journal order is applied order, never re-merged topic order | Property-style cross-topic-skew test |
| RSM-I6 | RSM originates no domain values (every field has one owning publisher) | M2 per-reducer test (asserts reducer reads only its family's payload fields); golden fixtures |
| RSM-I7 | References over bodies: record stores ids, never content copies | Golden fixtures (assert record fields are ids/refs, never nested content) |
| RSM-I8 | Durable writes only via Storage: journal index + terminal snapshot + checkpoints | M4 persistence tests (checkpoint prefix correctness, terminal-snapshot write) |
| RSM-I9 | Reads never block reducers; readers see consistent, never-torn snapshots | M3 interleaved-apply/read test |
| RSM-I10 | Unknown/evicted request id → `fault.recorded`, no auto-create, `request.received` sole creation trigger | M1 unknown-id-fault test; M3/M4 evicted-id query test |
| RSM-I11 | Eviction requires all three: terminal, journal persisted, retention elapsed | M4 eviction-ordering property test (2^3-1 partial-precondition combinations) |
| RSM-I12 | Replay must be byte-identical given (journal, reducer version); deviation halts | M5 recovery byte-identical-verification test; end-to-end lifecycle test |
| RSM-I13 | Zero planning/scheduling/verification/prompt/retrieval/learning logic in RSM | Validation audit grep (§5) — not a unit test, a build-time check |
| RSM-I14 | Every materialization and eviction emits telemetry; no silent work | M5 telemetry-coverage test (every applied-event row from the transition table produces either coalesced `state.updated` or a counted-and-deferred coalescing entry; every eviction produces `state.evicted`) |
| RSM-I15 | `state.*` is telemetry only; no subsystem gates a control decision on it | Structural test extension (source scan: no module outside `telemetry`'s emit path reads `state.updated`/`state.evicted` as a trigger for a store mutation) |
| RSM-I16 | Reducers bind only to Communication-owned versioned schemas | M2 per-reducer test (asserts a reducer accesses only fields present in the schema-version fixture handed to it, not a superset) |

---

## 5. Validation strategy

Post-build audit checklist, run once all five milestones are green:

1. **Exclusion-table grep.** `grep`-style scan of `src/rsm/` for planning,
   scheduling, verification, prompt-construction, retrieval, or learning
   logic (`RSM/01-problem-definition.md` §5 exclusion table; RSM-I13). Any
   hit is a defect, not a style note.
2. **No internals imports.** `src/rsm/` imports nothing from `src/ums/` or
   `src/kernel/` internals — only the doubles (`bus_double`,
   `persistence`'s Storage double) stand in for those subsystems until they
   exist for real. A structural check, same shape as the sole-mutator scan
   in §4.
3. **Replay determinism demo.** Run the M5 end-to-end fixture twice from
   the same journal; diff the two resulting records byte-for-byte. Zero
   diff is the pass condition.
4. **Invariant table green.** All sixteen rows in §4's table have a passing
   test. This document's table is the audit checklist itself — no separate
   tracking artifact needed.

---

## 6. Migration strategy

**No migration of `src/kernel/ledger.py`.** The Kernel Ledger stays
kernel-internal, exactly as ADR-RSM-2 (`RSM/02-architectural-blueprint.md`
§3) decided and Phase 4's Kernel-subsection review re-confirmed
(`RSM/04-validation-integration-review.md` Part A). RSM is purely
additive — it introduces a new subsystem, it does not touch, wrap, extract
from, or deprecate anything already shipped in `src/kernel/`.

**Integration follow-ups, when real subsystems land** (none of these are
part of this build; they are the recognized next steps once the
dependencies they need actually exist):

- Swap `bus_double` for a real Communication subscription once Communication
  is built. `ingest`'s consumption contract (§3) does not change — only
  what fills the envelope changes.
- Swap `persistence`'s Storage double for real Storage once Storage is
  built. The three document kinds (§3) and their versioned formats do not
  change — only the write/read implementation underneath does.
- Frontend adopts RSM's read surface (`query`) as its primary state-read
  path, replacing today's Kernel-only status reads
  (`RSM/01-problem-definition.md` §1, `RSM/04-validation-integration-
  review.md` Part A "Frontend — SOUND WITH FOLLOW-UP").
- `ARCHITECTURE.md` component-diagram edge `FE → RSM` — a documented
  follow-up (Part A, Frontend subsection), deferred doc edit, listed here
  rather than made now. §10 below makes the two edits that Phase 4 and
  Phase 2 §7 authorized for this phase; the diagram edge itself is
  explicitly **not** one of them and stays deferred until Frontend actually
  wires the read.

---

## 7. Acceptance criteria

(a) All five milestone suites (§2) green.
(b) Invariant coverage table (§4) complete, 16/16, no gaps.
(c) Byte-identical replay demonstrated end-to-end (§2 M5, §5 item 3).
(d) Structural test enforces sole-mutator discipline (§4, RSM-I2; §5 item 1
    extends the same technique to RSM-I15).
(e) Zero forbidden-ownership logic — exclusion-table grep clean (§5 item 1).
(f) stdlib-only verified (no third-party import anywhere in `src/rsm/`).
(g) Doubles (`bus_double`, `persistence`'s Storage double) fully isolate
    RSM from Communication and Storage, both unbuilt as of this phase — no
    hidden dependency on either's real implementation.

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Payload-schema drift before real Communication exists — a reducer implicitly depends on a payload shape that isn't actually stable yet | Medium | ADR-RSM-4 (`RSM/02-architectural-blueprint.md` §3) — reducers bind to explicit, versioned schema fixtures from day one, encoded in `bus_double`'s envelope shape; a schema-version bump is an explicit reducer migration, never a silent absorption. |
| Event volume exceeds what the single-threaded `ingest` loop can sustain | Low, unmeasured | Sharding path reserved on request id (`RSM/03-internal-design.md` §9, §11) — not built until a measured saturation exists. Measure first. |
| Recovery time grows unbounded on long journals | Medium for long-running requests | Checkpoints every N applied events (config `N`, `config_view`) bound replay cost to "since last checkpoint," not "since request birth" (`RSM/03-internal-design.md` §11). |
| `persistence`'s Storage double diverges semantically from real Storage once it lands | Medium | Keep the double's contract minimal and already-proven: opaque document `put`/`get` by key, mirroring `src/ums/storage_double.py`'s `write`/`read`/`exists` blob shape exactly — nothing double-specific for a future Storage swap to unlearn. |
| Coalescing hides state changes from Frontend for longer than acceptable | Low | Lifecycle-block changes are never coalesced — immediate, one per change, always (`RSM/03-internal-design.md` §8). Only Work/Context/Budget-block changes coalesce, and only up to the configured interval; Frontend's most decision-relevant signal (did the request finish, fail, or get rejected) is never delayed. |

---

## 9. Future extensibility

A new contributing subsystem is a schema fixture plus one reducer plus one
row in the §1 `reducers` registry — never a record redesign
(`RSM/01-problem-definition.md` §3 design goal 7, `RSM/03-internal-design.md`
§12). A new block is an additive schema minor bump, following the same
`reducer_version` discipline already specified for individual reducers. The
sharding path (§8) is a future scaling seam, reserved, not built.
Cross-request analytical queries — "all completed requests this week,"
lesson distillation over many journals — stay explicitly **out** of RSM:
that is Learning's job. Learning reads individual records and journals
through `query` and aggregates on its own side
(`RSM/01-problem-definition.md` §7, `RSM/04-validation-integration-review.md`
Part A "Learning — SOUND"); RSM never grows a cross-request query surface
of its own, because doing so would be exactly the kind of scope creep
`RSM/01-problem-definition.md` §5's exclusion table exists to prevent.

---

## 10. ARCHITECTURE.md additions (this commit)

Two minimal edits to `ARCHITECTURE.md`, both flagged as deferred by earlier
phases (`RSM/02-architectural-blueprint.md` §7, `RSM/04-validation-
integration-review.md` Part C) and closed out here:

1. **Component summary table** — one new row, registering RSM alongside the
   other fourteen components.
2. **Publish/consume matrix** — two new rows, for `state.updated` and
   `state.evicted` (`RSM/02-architectural-blueprint.md` §7's "New telemetry
   event family" table, now promoted into the canonical matrix).

The mermaid component diagrams are **not** touched in this commit. The
`FE → RSM` read edge is a real, documented architectural fact (Phase 4 Part
A, Frontend subsection) but drawing it now, before RSM has a single line of
code, would make the diagram describe a wire that does not yet exist. It
stays a `§6` follow-up until Frontend actually adopts the read.

---

## 11. Project execution guide (for the implementing model)

Same shape as `UMS/00-implementation-blueprint.md`'s own execution guide —
this table is the fast-reference version of everything above.

| Topic | Directive |
|---|---|
| Sources of truth | `RSM/01..04` (architecture, frozen) + this document (build plan). If a build-time question isn't answered by either, the closed Phase 1–4 documents win over any inference; do not re-litigate a settled ADR or invariant. |
| Never modify | `src/kernel/`, `src/ums/`, `RSM/01-problem-definition.md` through `RSM/04-validation-integration-review.md`, `ARCHITECTURE.md` (beyond the two rows already added in this commit), event names/payload contracts owned by Communication. |
| Fixed assumptions | Python 3.12+, stdlib only, no third-party import without owner approval (mirrors `UMS/00-implementation-blueprint.md` "Global laws"). `bus_double` and `persistence`'s Storage double stand in for Communication and Storage until both exist. Single-threaded reducer loop; sharding reserved, not built (§8). |
| Coding priorities | 1. Invariant correctness (the 16-row table in §4 is non-negotiable). 2. Determinism (RSM-I3, RSM-I12). 3. Reducer purity (RSM-I2, RSM-I16). 4. Read-path latency (RSM-I9 — cheap, non-blocking). One module per commit with a self-test, kernel Phase-10 pattern. `ponytail:` comments on any deliberate ceiling (e.g. the checkpoint interval's default, the coalescing interval's default). |
| Testing priorities | Golden fixtures + property-style interleaving tests + the structural sole-mutator scan, per milestone as listed in §2 and §4. No test frameworks beyond stdlib `unittest`-style asserts, matching the UMS and Kernel precedent. |
| Process | Build milestones in order (§2); do not start M*n+1* until M*n*'s suite is green and committed. Push to origin only after all five milestones are complete and the §5 validation checklist is green. |

---

RSM architecture complete — ready for implementation session.
