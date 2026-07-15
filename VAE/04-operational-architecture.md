# Verification & Assurance Engine (VAE) — Phase 4: Operational Architecture

Status: authoritative for VAE's operational architecture — event choreography
around verdict emission, the delegation lifecycle with Execution, pending-
verdict state management, evidence persistence mechanics, telemetry shape, and
the performance envelope stated structurally. Architecture only: no code, no
APIs, no schemas, no numeric thresholds, latencies, or capacity figures. The
full event canon, Learning/Experience integration detail, and the cross-phase
invariant audit are VAE/05 territory (VAE/00 §11). VAE/00, VAE/01, VAE/02, and
VAE/03 are immutable above this document: where this document is silent they
govern; where they speak, this document refines and never contradicts.

---

## 1. Operational Position

Phases 0–3 fixed what VAE is (evidence producer, never decider), what it judges
(the artifact taxonomy and verification levels), what it derives (confidence,
uncertainty, assurance levels), and how its products reach enforcers (verdict
events, gate topology, the limbo-prevention contract). Phase 4 fixes how VAE
*operates* between demand arriving and a verdict leaving:

- The choreography from verification demand to verdict emission (§2, §5)
- The delegation lifecycle with Execution: dispatch, pending tracking,
  deadlines, and the reconciliation with "never retries" (§3, §4)
- Pending-verdict state: what VAE holds in flight, its authority status, and
  its recovery discipline (§6)
- Evidence persistence mechanics through the Storage single-writer path (§7)
- The telemetry that makes VAE/02 §9's benchmarking possible (§8)
- The performance envelope, stated structurally, never numerically (§9)

Nothing in this phase adds authority. VAE remains event-driven, control-loop-
free, and policy-free (VAE/00 §9); this document describes the mechanics of a
component that already may not decide anything.

---

## 2. Verification Demand Intake

### 2.1 Demand Sources

VAE reacts to bus events; it polls nothing (VAE/00 §9). Its demand arrives
exclusively through rows already canonized in ARCHITECTURE.md's
publish/consume matrix where Verification is a listed consumer:

| Demand event | Publisher | What it signals to VAE |
|---|---|---|
| `verify.requested` | Scheduling | A gated step result awaits judgment (the Scheduler's "require gate"). |
| `plan.created` | Capability Planning | A plan artifact awaits pre-scheduling verification. |
| `exec.completed` | Execution | An execution result is available — either a producer artifact newly judgable, or a delegated check result VAE itself is awaiting (§3). |
| `reasoning.completed` | Reasoning Orchestrator | A sealed reasoning outcome record awaits grading against its declared output contract (VAE/00 §3, §8). |

No other event obligates VAE to act, and VAE consumes no event the matrix does
not route to Verification. Demand not on this list is not demand.

### 2.2 Intake Discipline

- **Dedup by event id.** The bus is at-least-once (ARCHITECTURE.md
  §Communication model); VAE applies each demand event exactly once, keyed by
  event id — the same discipline the Kernel (KERNEL/INVARIANTS.md #8) and RSM
  (RSM-I4) already use. A redelivered demand event never opens a second
  judgment of the same artifact.
- **Per-artifact ordering.** Demand for a given artifact is processed in
  arrival order. No total ordering across artifacts is required or assumed
  (per-topic FIFO is the bus's only ordering guarantee); VAE/01 §5 already
  fixed that level ordering is per-artifact, never system-wide (VAE-M6).
- **Buffering, not dropping.** Demand that arrives faster than VAE judges is
  queued, bounded by the bus's backpressure mechanism — the bus "signals
  backpressure rather than dropping" (ARCHITECTURE.md delivery semantics), and
  VAE inherits that behavior rather than inventing its own shedding policy.
  Silently dropped demand would be a limbo factory: an artifact whose demand
  vanished would wait forever for a verdict that was never opened. Under
  backpressure, demand slows upstream; it never disappears.
- **One judgment per gated occurrence.** Intake opens exactly one judgment per
  gated artifact instance (VAE/03 §4.1: one verdict per gated occurrence,
  immutable once emitted). Demand referencing an artifact that already holds a
  terminal verdict is answered by the existing verdict record, not by a
  re-judgment.

---

## 3. Delegation Lifecycle with Execution

### 3.1 The Dispatch Channel

Delegated checks travel on the direct query/command edge ARCHITECTURE.md's
component diagram already draws: `VER → EXE` ("run checks / selftests"). This
is a synchronous request/response relationship in the hub doc's two-style
model ("direct queries: reads that need an answer now"), not a bus event. VAE
therefore publishes no Execution-owned or Scheduling-owned event to get a
check run — `task.scheduled` belongs to Scheduling and `exec.*` belongs to
Execution, and VAE authors neither.

What crosses the channel:

| Direction | Content | Nature |
|---|---|---|
| VAE → Execution | A check request: check identity, artifact reference, the rules-version-declared scope (changed + dependent units, VAE/00 §4 resp. 6), and the deadline the rules assign | A request to run, never a command about policy — Execution owns sandboxing, isolation, and process mechanics entirely (Law 3) |
| Execution → VAE | The check result: outcome, captured output reference, or timeout/failure as an ordinary result (V1-H4 containment) | Sealed evidence (VAE/01 §5, Execution level); admissible whatever its content |

Execution additionally emits its own `exec.started` / `exec.completed` /
`exec.timeout` / `exec.failed` events for its own consumers per the matrix;
those are Execution's emissions about its own work, not VAE's channel. VAE's
authoritative receipt of a delegated result is the direct-channel response
(see the matrix note in §11).

### 3.2 Delegation States

Each dispatched check occupies exactly one state in VAE's pending-state
projection (§6):

| State | Meaning | Exits |
|---|---|---|
| **Required** | The rules version for this artifact type names this check as required; not yet dispatched | → Dispatched |
| **Dispatched** | Sent to Execution; deadline running | → Resulted (result arrives) / → Expired (deadline passes) |
| **Resulted** | Execution returned an outcome — success, failure, timeout, or crash, all equally ordinary results | Terminal for the delegation; result becomes an evidence item (VAE/01 §6) |
| **Expired** | The deadline passed with no result received | Terminal; recorded as execution-failure evidence (VAE/01 §11), never silence |

No delegation state is ever "abandoned" or "forgotten": every dispatched check
terminates in Resulted or Expired, which is the delegation-level expression of
VAE-I5's no-limbo rule applied to VAE's own inputs.

### 3.3 Deadlines

- Every dispatch carries a deadline drawn from the versioned rules-as-data
  (VAE/00 §4 resp. 1) — never negotiated at dispatch time, never extended
  mid-flight (sealed consumption, VAE/00 §9).
- Deadline expiry converts the delegation to execution-failure evidence
  (VAE/01 §11, "Execution failure") and the judgment proceeds to a definite
  verdict on the evidence that exists. A late result arriving after expiry is
  recorded (evidence is never discarded, VAE-M2) but the expired delegation's
  evidentiary status stands for the verdict already reached — verdicts are
  immutable (VAE/03 §4.1); late evidence can move future assurance readouts,
  never past verdicts.
- Deadline bookkeeping is VAE-internal operational state. The Kernel owns no
  timers (KERNEL/INVARIANTS.md #10) and none of this touches the Kernel; VAE's
  deadlines discharge its own bounded-self-work constraint (VAE/00 §9) and
  create no timer obligation anywhere else.

### 3.4 Reconciling Deadlines with "Never Retries"

VAE/01 §9 is binding: VAE never re-runs a check "to see if it passes this
time." The operational layer draws the line precisely:

| Situation | Permitted? | Why |
|---|---|---|
| Check returned a result (any result) and VAE re-dispatches it hoping for a different outcome | **Never** | This is outcome-shopping — "run it again until it passes," the exact failure VAE/01 §9 and Law 6 forbid. A Resulted delegation is terminal. |
| Dispatch was never received by Execution (delivery failure on the direct channel, no acknowledgment) and VAE re-issues the identical request | Permitted | This is delivery redundancy, not retry: no outcome exists to shop against. The re-issue is idempotent (same check, same artifact, same rules version, same deadline), and if both dispatches somehow produce results, the duplicate is Redundant evidence — recorded, counted once (VAE/02 §5). |
| Deadline expired and VAE re-dispatches to "give it another chance" | **Never** | Expiry is a terminal delegation state (§3.2) producing definite evidence. Re-dispatching after expiry is retry wearing a deadline costume. |
| The rules version itself declares a check family as multi-sample (independent runs as independent evidence sources) | Permitted, as N distinct Required delegations from the outset | This is corroboration by design, declared before judgment in rules-as-data — not a reaction to an outcome. Each run is a separate delegation with its own lifecycle; their agreement or conflict is weighed per VAE/02 §5. |

The invariant form: **a delegation that has produced an outcome — result or
expiry — is never dispatched again within the same judgment** (VAE-O3, §10).

---

## 4. In-Flight Artifact State

Between demand intake and verdict emission, an artifact under judgment is
**pending** — a state visible to VAE alone. Operationally:

- **Pending is not a verdict state.** Enforcers already treat verdict absence
  as not-passed (VAE-I5, VAE-K5); "pending inside VAE" and "no verdict exists"
  are indistinguishable from outside, by design. VAE exposes no "almost done"
  signal that an enforcer could be tempted to treat as a soft pass.
- **Pending is bounded.** An artifact's pending duration is bounded by its
  delegations' deadlines plus VAE's fixed evaluation overhead (VAE/00 §9,
  bounded self-work). Because every delegation terminates (§3.2) and static
  checks are VAE's own bounded work, every pending artifact structurally
  reaches a terminal verdict — pendency cannot be indefinite.
- **Pending holds references, not bodies.** In-flight state is artifact
  references, rules version, delegation states, and accumulated evidence item
  references — the same reference-over-duplication discipline RSM/02 ADR-RSM-3
  applies. VAE is not a cache of artifact content.

---

## 5. Verdict Emission Choreography

### 5.1 Ordering: Persist, Then Publish

VAE/03 §2.2 ruled that evidence is persisted before or atomically with verdict
emission. Phase 4 fixes the operational sequence:

1. **Evidence complete.** All required checks for the artifact's rules version
   have reached Resulted or Expired; static-check findings are recorded;
   the evidence body for this judgment is closed (sealed consumption — no
   re-querying mid-judgment, VAE/00 §9).
2. **Derive.** Verdict, confidence, uncertainty, and assurance level are
   derived deterministically from the closed evidence body and rules version
   (VAE-I6, VAE-A1).
3. **Persist.** The evidence record — evidence items, rules version, derivation
   account, verdict, assurance level — is written via Storage (single writer).
   Storage's confirmation (its `storage.committed` emission and the direct
   write-path acknowledgment) establishes durability.
4. **Publish.** Only after durable confirmation does VAE publish
   `verify.passed` / `verify.failed` on the bus, carrying the evidence record
   reference per VAE-K1.

This is the Kernel's own "log before publish" discipline
(KERNEL/INVARIANTS.md #7) applied at VAE's boundary: no consumer ever holds a
verdict whose evidence record cannot be fetched. A verdict event referencing
an unpersisted record would break VAE-I8 (explainable from the immutable
record alone) at the first moment anyone tried to use it.

### 5.2 Persistence Rejection

If Storage rejects the evidence-record write (`storage.rejected` routes to the
requesting component per the matrix):

- **No verdict is published.** A verdict without a durable record is
  forbidden (§5.1); publishing one would manufacture unexplainable authority.
- **The failure is loud.** VAE emits `fault.recorded` (any component may, per
  the matrix) so Observability and Learning see the persistence failure.
- **The artifact resolves as absence.** With no verdict published, the
  enforcers' absence-as-fail machinery (VAE-K5, VAE-K6) governs: the gate
  stays closed, the Scheduler's deadline routing treats the step as failed.
  This is exactly the "loud absence the enforcers treat as fail" that VAE/00
  §9 names as the acceptable degradation — never an implicit pass, never a
  recordless verdict.

### 5.3 Emission Is Unconditional and Single

- One terminal verdict event per gated artifact occurrence (VAE/03 §4.1);
  emission is never sampled, suppressed, or batched away — every judgment
  that completes produces its event (Law 7 discipline; no silent work).
- At-least-once delivery downstream is the bus's concern; consumers dedup by
  event id (ARCHITECTURE.md delivery semantics, KERNEL/09 guarantees). VAE
  does not re-emit to "make sure."

---

## 6. Pending-Verdict State Management

### 6.1 Authority Status

VAE's pending state — open judgments, delegation states, deadlines,
accumulated evidence references — is a **non-authoritative, rebuildable
operational projection**, the same classification RSM/02 ADR-RSM-2 gives the
Kernel Ledger: "a deterministic, discardable, rebuildable-from-the-bus
projection kept purely for a subsystem's own fast decisions is permitted and
expected."

The authoritative records are elsewhere, all already owned:

| Authoritative record | Owner |
|---|---|
| Evidence records and verdicts (once persisted) | Verification's owned content, written via Storage |
| The demand events that opened each judgment | Episodic store (Observability, via Storage) |
| The rules versions | Config via Storage (rules-as-data) |
| Request-level verification status | RSM's Verification block (VAE-K10) |

### 6.2 Loss and Recovery

If VAE crashes and its pending state is lost:

- **Nothing passes.** Every open judgment's artifact simply has no verdict;
  enforcers treat absence as not-passed (VAE-I5, VAE-K5). Crash cannot mint a
  pass — the fail-safe direction is structural, not aspirational.
- **Recovery is re-derivation, not resurrection.** A restarted VAE rebuilds
  its view from what is durable: demand events (redelivered by the durable-
  subscriber bus contract or replayed from the episodic store), persisted
  evidence records, and the current rules version. Judgments whose verdicts
  were already persisted and published are recognized as terminal (intake
  dedup, §2.2) and not reopened.
- **In-flight delegations at crash time** resolve through the existing
  machinery: their deadlines were rules-assigned, and a delegation whose
  result cannot be attributed to a live judgment expires into execution-
  failure evidence when the judgment is rebuilt. No special crash-recovery
  verdict semantics exist — recovery reuses §3's states, because a recovered
  judgment reaching a different verdict than the original would have violated
  determinism (VAE-I6) anyway.
- **No warm-standby, no replicated pending store** is prescribed. Pending
  state is cheap to lose precisely because it is a projection; engineering
  redundancy for it would add operational surface to protect something whose
  loss is already safe.

---

## 7. Evidence Persistence Mechanics

### 7.1 The Record, Architecturally

VAE/00 §12 and VAE/01 §6 fix what evidence *is*; this section fixes the
operational shape of the persisted record — as named parts, not a schema:

| Part | Content | Constraint |
|---|---|---|
| Artifact binding | The Storage-backed reference to the judged artifact | The record binds to a sealed reference, never embedded artifact content (reference over duplication) |
| Rules binding | The rules version used | Required for deterministic replay (VAE-K2) |
| Evidence items | Each recorded observation: the rule addressed, artifact reference, source (own check or delegated result reference), result, contribution kind (VAE/02 §5), and level/kind attribution (VAE-M7) | Append-only; items are never edited, reweighted in place, or pruned (VAE-M2, VAE-A6) |
| Identified absences | Evidence the rules named obtainable but which is missing (VAE/02 §5, "Missing") | Absences are first-class parts of the record — coverage honesty depends on them |
| Derivation account | The verdict, per-dimension confidence, uncertainty, assurance level, and the trace from each to its supporting items and absences (VAE-A10) | Re-derivable by any party from the items alone (VAE-A1); the stored account is a convenience copy of a deterministic function's output, never a second authority |

### 7.2 Write Discipline

- **Single writer.** Every durable byte goes through Storage
  (ARCHITECTURE.md, State ownership: "Verification verdicts | Verification |
  Storage"). VAE holds no local durable path, no file it writes itself, no
  side database (VAE-I11 restated operationally).
- **Append-only growth.** A judgment's record grows by appending items as
  results arrive; post-verdict evidence (late results, dependent-artifact
  findings per VAE/01 §7) appends to the same artifact's evidence body without
  touching the closed judgment's derivation account. History is
  reconstructible at any past point (VAE-A10) because nothing is ever
  rewritten.
- **Atomicity expectation on Storage.** VAE requires of Storage exactly what
  Storage already guarantees every writer (ARCHITECTURE.md, write path):
  atomic, locked, transactional writes with `storage.committed` /
  `storage.rejected` outcomes. VAE layers no transaction machinery of its own
  on top; the persist-then-publish ordering (§5.1) is VAE's only added
  discipline.

### 7.3 Access Patterns

The record is read far more often than written, by parties VAE does not know
about in advance. The operational shape supports exactly three lookups, all by
reference — never by search:

| Access | Reader | Path |
|---|---|---|
| By evidence record reference | Kernel, Scheduler, Frontend, auditors following a verdict event's `evidence_record_ref` (VAE-K1) | Direct fetch via the standard Storage read path |
| By artifact reference | Consumers asking "what is the full evidence body for artifact X," including post-verdict accumulation | Fetch of the artifact's append-only evidence body |
| By request, via RSM | Anyone asking "what was verified in request R" | RSM's Verification block holds the verdict references (VAE-K10); bodies are fetched by reference from Storage |

No similarity search, no scanning, no indexing by VAE (Law 2, VAE-I11):
evidence records are looked up by identity, and any future need to *search*
them is Repository Memory's authority to serve, not VAE's to build.

---

## 8. Telemetry Shape

VAE-I12 requires all VAE activity observable in Observability's one schema.
Phase 4 fixes *what families of signals exist* — their expression in the
telemetry schema is Observability's, and no metric definitions or math appear
here (VAE/00 §9; Observability owns the schema).

| Signal family | What it reports | Which VAE/02 §9 benchmarking concern it feeds |
|---|---|---|
| Judgment outcomes | Every verdict: artifact kind, rules version, verdict, failure cause (VAE/01 §11), assurance level | Calibration (do stronger-assured artifacts exhibit fewer downstream defects) |
| Check activity | Every delegation and static check: which check, dispatched/resulted/expired, result category | Historical verification effectiveness (which checks catch defects; which never fail anything) |
| Coverage readouts | Per judgment: identified absences and the coverage dimension's state | Evidence coverage honesty (does formally-complete coverage still miss defect classes) |
| Agreement records | Per corroborated or conflicting claim: which independent sources agreed or conflicted (substrate preserved per VAE-M4) | Agreement between independent verification activities (is corroboration earning its extra trust) |
| Derivation consistency | Re-derivation events: evidence body identity, rules version, derived outputs | Consistency across repeated executions (determinism demonstrated, not asserted) |
| Latency and demand | Judgment durations, delegation durations, queue depth under backpressure | Performance envelope observation (§9) — and the operational health of assurance itself |

Discipline, restated from VAE/02 §9 because the telemetry path is where it
would erode: benchmarking findings re-enter VAE **only as versioned rules
revisions**, never as live adjustment mid-judgment. Telemetry is emitted
unconditionally — no sampling that could hide the signals benchmarking needs
(Law 7; the Kernel's "emission unconditional, never sampled" discipline
adopted at VAE's boundary). Telemetry is never a control edge back into VAE or
out of it (RSM-I15 discipline).

---

## 9. Performance Envelope

Structural statements only; no numbers, budgets, or thresholds (those are
rules-as-data and deployment configuration, not architecture).

| Property | Structural bound | Source |
|---|---|---|
| Verdict latency | Bounded by the slowest required delegation's rules-assigned deadline plus VAE's fixed evaluation overhead. Nothing in a judgment waits on anything unbounded. | VAE/00 §9 ("Bounded self-work"), §3.3 |
| Throughput | Proportional to demand: VAE does work only when demand events arrive (event-driven, no polling, no background loops), and per-judgment work is proportional to the rules-required check set, not to request size or system state. | VAE/00 §9; VAE/01 §3 ("workload proportional to what actually happened") |
| Backpressure behavior | Under overload, intake slows via the bus's backpressure signal (§2.2); judgments already open continue to their deadlines. Degradation lengthens time-to-verdict; it never skips checks, thins evidence, or relaxes rules — depth is fixed by rules version, not by load. | ARCHITECTURE.md delivery semantics; VAE/00 §2 (proportionality by rules, not exception) |
| Enforcement path cost | Enforcers act on the verdict event alone; the evidence record fetch is off the gate's hot path (reference, not payload — VAE-K1). Gate decisions never wait on a Storage read. | VAE/03 §2.2 |
| Failure cost | VAE crash costs at most the re-derivation of open judgments (§6.2); it never costs a wrong verdict, a lost persisted record, or an open gate. | §6; VAE-I6 |
| Scaling shape | Judgments are independent per artifact (no cross-artifact ordering, VAE-M6); nothing in this phase's design serializes unrelated judgments through a shared bottleneck other than the bus and Storage, which are already the system's shared substrate. | VAE/01 §5; VAE-M6 |

The envelope's defining asymmetry, stated once: **VAE trades latency for
integrity in every conflict between them.** A slow definite verdict is an
operational cost; a fast wrong or thin one is an architectural failure.

---

## 10. Operational Invariants (VAE-O)

New Phase 4 register, extending VAE-I1–I12, VAE-M1–M7, VAE-A1–A10, and
VAE-K1–K12 without duplication; binding on all later VAE phases.

1. **VAE-O1** — VAE's pending-judgment state is a non-authoritative,
   rebuildable projection; its loss can delay verdicts but can never open a
   gate, alter a persisted record, or change what verdict a rebuilt judgment
   reaches. *Prevents:* operational state becoming a second authority, and
   crash becoming a pass.
2. **VAE-O2** — Delegated checks travel only on the direct VAE→Execution
   channel; VAE publishes no Scheduling-owned or Execution-owned event to
   cause execution, and consumes demand only from matrix rows that name
   Verification. *Prevents:* VAE minting other components' events; topology
   drift beyond the canon.
3. **VAE-O3** — A delegation that has produced an outcome — result or expiry —
   is never dispatched again within the same judgment. Re-issue is permitted
   only for a dispatch with no outcome and no acknowledgment, identically and
   idempotently; duplicate results count once (Redundant, VAE/02 §5).
   *Prevents:* outcome-shopping — "run it again until it passes" — at the
   delegation layer.
4. **VAE-O4** — Every dispatch carries a rules-assigned deadline fixed before
   dispatch; expiry converts deterministically to execution-failure evidence
   and the judgment proceeds to a definite verdict. No deadline is extended,
   negotiated, or waived mid-flight. *Prevents:* indefinite pendency (limbo at
   the input side) and load-sensitive judgment depth.
5. **VAE-O5** — No verdict event is published before its evidence record is
   durably persisted via Storage. Persist, then publish, always. *Prevents:*
   verdicts in circulation whose evidence cannot be fetched — VAE-I8 broken at
   the moment of use.
6. **VAE-O6** — A rejected evidence-record write yields a loud absence
   (`fault.recorded`, no verdict event), resolved by the enforcers'
   absence-as-fail machinery; VAE never publishes a recordless verdict and
   never converts persistence failure into an implicit pass. *Prevents:* the
   persistence path becoming a silent bypass of explainability or of the gate.
7. **VAE-O7** — Persisted evidence bodies grow append-only; post-verdict
   evidence appends to the artifact's body without modifying any closed
   judgment's derivation account, and no operational process rewrites,
   reweights, or prunes persisted items. *Prevents:* the operational layer
   eroding VAE-M2/VAE-A6 under storage-hygiene or performance pressure.
8. **VAE-O8** — All telemetry flows through Observability's one schema,
   emitted unconditionally, and is never a control edge: nothing reads VAE
   telemetry to adjust a judgment in flight, and benchmarking findings enter
   VAE only as versioned rules revisions. *Prevents:* sampling holes in the
   benchmarking substrate and feedback loops that bend live judgments.
9. **VAE-O9** — Under load, VAE degrades only by slowing intake through the
   bus's backpressure mechanism; it never drops demand, skips required checks,
   thins evidence, or shortens deadlines in response to load. *Prevents:*
   throughput pressure becoming assurance erosion — the operational form of
   independence (VAE/00 Principle 2) against the system's own busyness.
10. **VAE-O10** — Recovery after VAE failure re-derives open judgments from
    durable sources (demand events, persisted records, rules versions) and
    reaches verdicts identical to those an uninterrupted VAE would have
    reached from the same evidence (VAE-I6 across restarts). Already-terminal
    judgments are never reopened. *Prevents:* crash-recovery becoming a
    re-judgment lottery or a second chance for failed artifacts.

---

## 11. Matrix Note (Flagged, Not Resolved)

ARCHITECTURE.md's publish/consume matrix lists Verification as a consumer of
`exec.completed` but **not** of `exec.timeout` or `exec.failed` (those rows
route only to Scheduling and Observability). The hub doc's own verification
lifecycle diagram, however, transitions `RunningSelftests → Failed` on
`exec.timeout / exec.failed` — implying Verification consumes them.

This document does not need the missing rows: the delegation design (§3.1)
receives all delegated outcomes — including timeout and failure as ordinary
results — on the direct VAE→Execution channel the component diagram canonizes,
so no bus consumption of `exec.timeout`/`exec.failed` by VAE is required.
The inconsistency between the matrix and the lifecycle diagram is flagged
here for Phase 5's cross-phase audit and possible hub-doc errata (VAE/00 §11,
Phase 5 scope); it is not silently repaired by inventing matrix rows.

---

## 12. Phase Summary

**Now fully defined by this document:**

- The four canonical demand sources (`verify.requested`, `plan.created`,
  `exec.completed`, `reasoning.completed`) and the intake discipline: dedup by
  event id, per-artifact ordering, backpressure-bounded buffering, one
  judgment per gated occurrence (§2).
- The delegation lifecycle with Execution: the direct dispatch channel, the
  four delegation states (Required, Dispatched, Resulted, Expired), rules-
  assigned deadlines, and the precise reconciliation of deadlines and delivery
  redundancy with "never retries" (§3).
- In-flight artifact state: pending as an externally invisible, bounded,
  reference-only condition (§4).
- Verdict emission choreography: evidence closure → deterministic derivation →
  persist via Storage → publish; persistence rejection as loud absence, never
  recordless verdict (§5).
- Pending-verdict state as a non-authoritative rebuildable projection, and the
  crash-recovery discipline in which nothing passes by crashing (§6).
- Evidence persistence mechanics: the five-part record shape, single-writer
  append-only discipline, Storage's existing transactional guarantees as the
  only transaction machinery, and the three reference-based access patterns
  (§7).
- The six telemetry signal families and their mapping to VAE/02 §9's
  benchmarking concerns, with the rules-revisions-only feedback discipline
  (§8).
- The performance envelope, structurally: bounded verdict latency,
  demand-proportional work, integrity-preserving degradation, off-hot-path
  evidence fetches, and the latency-for-integrity trade stated as policy (§9).
- Ten new Phase 4 invariants (VAE-O1–O10) binding all later phases (§10).
- One flagged canon inconsistency for Phase 5's audit (§11).

**Intentionally deferred**, per the VAE/00 §11 roadmap:

- The full event canon — any additional VAE-adjacent event families beyond
  the already-canonized rows, and resolution of the §11 matrix inconsistency —
  **Phase 5 (System Integration)**.
- Learning/Experience integration detail: how verdicts, evidence records, and
  benchmarking telemetry feed the trusted-knowledge path, planning priors,
  plugin reliability, and rules-as-data revision proposals — **Phase 5**.
- The cross-phase invariant audit over VAE-I/M/A/K/O and all consuming
  systems, and any resulting hub-doc errata — **Phase 5**.

This document introduces no code, schema, formula, numeric threshold, or new
event name, and settles no question VAE/00–03 already settled. Every
operational rule traces to an invariant, principle, law, or canon row it
refines.

---

## 13. Glossary (Phase 4 additions)

| Term | Definition |
|---|---|
| **Demand event** | A bus event from a matrix row naming Verification as consumer, signaling that an artifact awaits judgment (`verify.requested`, `plan.created`, `exec.completed`, `reasoning.completed`). |
| **Judgment** | The operational unit from demand intake to terminal verdict for one gated artifact occurrence; exactly one per occurrence. |
| **Delegation** | One dispatched check's lifecycle on the direct VAE→Execution channel: Required → Dispatched → Resulted / Expired. |
| **Pending state** | VAE's non-authoritative, rebuildable in-memory projection of open judgments and delegations; invisible to enforcers, safe to lose. |
| **Persist-then-publish** | The mandatory ordering in which an evidence record is durably written via Storage before its verdict event is published (VAE-O5). |
| **Loud absence** | The failure degradation in which no verdict is published, `fault.recorded` is emitted, and enforcers' absence-as-fail machinery resolves the artifact — the only permitted alternative to a definite verdict. |
| **Delivery redundancy** | Idempotent re-issue of a dispatch that produced no outcome and no acknowledgment; distinct from retry, which re-runs against an existing outcome and is forbidden. |
| **Signal family** | A named category of VAE telemetry (judgment outcomes, check activity, coverage readouts, agreement records, derivation consistency, latency/demand) feeding a VAE/02 §9 benchmarking concern. |
