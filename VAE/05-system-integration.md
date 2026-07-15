# Verification & Assurance Engine (VAE) — Phase 5: System Integration & Completion

Status: authoritative; completes the VAE architecture (VAE/00–05). Introduces
no new concepts — assembles frozen ones from VAE/00–04 into the subsystem's
integration surface: the closed event canon, the resolution recommendations for
flagged canon inconsistencies, the Learning/Experience integration, the
cross-phase invariant audit, and the implementation bridge. Architecture only —
no code, no APIs, no schemas, no algorithms, no vendor/model names. The event
canon declared in §2 is CLOSED as of this document; any future verification
event is an errata to this doc, mirroring RO/05's and PRT/05's closed-set
discipline. VAE/00–04 are immutable above this document: where this document is
silent they govern; where they speak, this document assembles and never
contradicts.

---

## 1. Subsystem Integration Surface

The complete seam table — what crosses each boundary and what never does,
assembled from VAE/00 §8 and refined by VAE/01–04. Nothing new; each row cites
where it was fixed.

| Subsystem | VAE consumes | VAE produces toward it | VAE never owns (fixed at) |
|---|---|---|---|
| Kernel | Nothing direct — verdicts reach it as bus events | `verify.passed` as decision input; evidence records fetchable by reference | Policy, enforcement, lifecycle (VAE-I1, VAE-I2, VAE-K12) |
| Scheduler | `verify.requested` demand | `verify.passed` / `verify.failed` gate inputs | Scheduling, dispatch, retry/replan decisions (VAE-K3–K5, VAE-K9) |
| Capability Planning | `plan.created` demand | `verify.failed` / `plan.rejected` replan inputs; `plan.validated` | Plan shaping, replan decisions (VAE/00 §5, VAE/03 §3.3) |
| Execution | Delegated results on the direct channel | Check dispatches on the direct channel | Process spawning, sandboxing (VAE-I3, VAE-O2) |
| Reasoning Orchestrator | `reasoning.completed` demand; sealed outcome records with carried verification expectations | Nothing — verdicts flow to enforcers, never back into sealed attempts (§4) | In-flight reasoning influence (VAE/00 §8, RO-S5) |
| Request State Manager | Nothing | Nothing direct — RSM materializes VAE's bus events into its Verification block | Request state authority (VAE-K10, K11; RSM-I15 discipline) |
| UMS (Repository Memory) | Dependency knowledge for check scoping, via UMS's retrieval query surface | Nothing | Retrieval, indexing, similarity (VAE-I11, Law 2) |
| Context Management | Nothing — zero seam, permanent (VAE/00 §8) | Nothing | Context assembly |
| Plugin Runtime | Nothing — plugin outputs arrive as sealed artifacts via Execution/Storage | Nothing | Plugin loading, execution (VAE/00 §5, VAE/01 §8) |
| Learning / Experience | Nothing live — benchmarking findings return only as versioned rules revisions via config (VAE-O8) | Verdict events, evidence records, benchmarking telemetry — the trusted-knowledge membrane's supply side (§5) | Lesson distillation, prior computation (VAE-I9, VAE/00 §5) |
| Storage | Rules versions (config path); read path for artifacts and records | Evidence records and verdict content via the single-writer path (VAE-O5–O7) | Any local durable write (VAE-I11) |
| Communication / Observability | Demand events; bus delivery guarantees | All events; all telemetry in the one schema (VAE-I12, VAE-O8) | Transport; telemetry schema |

---

## 2. Event Canon — CLOSED

The complete enumeration of VAE's bus participation. Every row below is an
exact ARCHITECTURE.md publish/consume matrix row. This set is closed: a future
verification event requires errata to this document first.

### 2.1 Published by Verification (4 events + 1 shared)

| Event | Matrix row (publisher → consumers) | Emitted when (fixed at) |
|---|---|---|
| `verify.passed` | Verification → Scheduling, Kernel, Observability | A gated artifact reaches a definite terminal pass (VAE-K1; choreography VAE/04 §5) |
| `verify.failed` | Verification → Scheduling, Capability Planning, Observability | A gated artifact reaches a definite terminal fail, with failure cause and structured reasons (VAE-K1, VAE-K8) |
| `plan.validated` | Verification → Scheduling, Observability | A plan artifact's verification concludes admissible — the plan-artifact notification of a passed verdict (see §3.2 for the publisher-attribution errata) |
| `plan.rejected` | Verification → Capability Planning, Observability | A plan artifact's verification concludes inadmissible — the plan-artifact notification of a failed verdict (see §3.2, §3.3) |
| `fault.recorded` | Any (via Communication) → Observability, Learning | VAE's own failure modes: evidence-persistence rejection (VAE-O6), malformed demand, internal fault — the loud-absence channel |

**Reconciliation of `plan.validated`/`plan.rejected` with the verdict
discipline.** These two rows exist in the matrix with Verification as
publisher; this document enumerates them because the canon contains them —
it does not mint them. Their reading, consistent with everything VAE/00–04
fixed: `verify.passed`/`verify.failed` remain the terminal verdicts and the
sole gate-openers for every artifact kind including plans (VAE-A7 verbatim);
`plan.validated`/`plan.rejected` are the plan-artifact outcome notifications
the matrix routes to the plan pipeline's specific consumers. They carry no
gate authority beyond the verdict they announce, obey the same definiteness,
determinism, and explainability disciplines (VAE-I5, VAE-I6, VAE-I8), and
introduce no third verdict state. Whether they remain distinct events or are
folded into the `verify.*` pair is a hub-doc question flagged in §3.2 — not
settled here, because settling it would edit canon VAE does not own.

**No other event is VAE's to publish.** In particular: `task.*`, `exec.*`,
`plan.created`, `plan.revised`, `verify.requested` (Scheduling's), all
`request.*`, `storage.*`, `lesson.*`, `reliability.*`, `prior.*`,
`reasoning.*` (RO-S2), `state.*` — all owned elsewhere per the matrix; VAE
publishing any of them is a defect (VAE-O2).

### 2.2 Consumed by Verification (4 events)

The demand set, fixed in VAE/04 §2.1 — the only matrix rows naming
Verification as consumer:

| Event | Publisher | Why consumed |
|---|---|---|
| `verify.requested` | Scheduling | Gate demand for a step result |
| `plan.created` | Capability Planning | Pre-scheduling plan verification demand |
| `exec.completed` | Execution | Producer artifacts newly judgable; also Execution's own emission about delegated-check completion |
| `reasoning.completed` | Reasoning Orchestrator | Sealed reasoning outcome record awaiting grading (canonized by RO/05 §2 and hub-doc errata E4) |

### 2.3 Non-Event Channels (complete)

| Channel | Canon basis | Discipline |
|---|---|---|
| VAE → Execution check dispatch (and result return) | Component diagram edge `VER → EXE` ("run checks / selftests") | Direct query/command; delegated outcomes — including timeout/failure — return here as ordinary results (VAE-O2, VAE/04 §3.1) |
| VAE → UMS scoping query | VAE/00 §7 ("Repository knowledge — Unified Memory System"); ARCHITECTURE.md's direct-query style ("chiefly Repository Memory's retrieval API") | Read-only dependency knowledge for check scoping; never similarity search by VAE (VAE-I11). Diagram edge absence noted in §7 (E-V7) |
| VAE → Storage write (evidence records, verdict content) | State-ownership row: "Verification verdicts — Verification — Storage" | Single-writer, persist-then-publish (VAE-O5) |
| VAE → Storage read (artifacts by reference, rules versions) | VAE/00 §7 (Storage-backed references; rules as versioned config) | Sealed consumption — no live re-query mid-judgment (VAE/00 §9) |

**Rules (canon-closure discipline, mirroring RO/05 §2):**

| Rule | Statement |
|---|---|
| Ownership | Publisher owns name + schema via Communication's versioned registry; `verify.*` names are Verification's alone |
| Immutability | Verdict events are facts, never retracted; the record is the truth, the event the notification |
| Replay | Every verdict event re-derives from its persisted evidence record (VAE-K2, VAE-O10) |
| Closed set | New verification events require errata to this document first |

---

## 3. Canon Inconsistency Resolutions (Recommendations Only)

Phase 5's audit surfaced the following inconsistencies. Each receives a
recommended disposition; **the hub-doc edits themselves are outside VAE's
authority** and are recorded as errata candidates for the repository owner
(§7). VAE's design is complete and consistent under the recommended readings
without any edit being applied.

### 3.1 `exec.timeout` / `exec.failed` — matrix vs. verification lifecycle diagram (VAE/04 §11)

- **Inconsistency:** the matrix routes both events only to Scheduling +
  Observability; ARCHITECTURE.md's verification lifecycle diagram transitions
  `RunningSelftests → Failed` on them, implying Verification consumes them.
- **Recommended disposition: diagram errata; matrix stands as-is.** VAE
  receives every delegated outcome — timeout and failure included, as ordinary
  results per the V1-H4 containment rule — on the direct VAE→Execution channel
  (VAE-O2, VAE/04 §3.1). No bus consumption is needed or designed. The
  diagram's transition label should read as "delegated result: timeout/failure
  (direct channel)" rather than naming bus events.

### 3.2 `plan.validated` publisher — matrix vs. request-lifecycle sequence diagram

- **Inconsistency:** the matrix assigns `plan.validated` to publisher
  Verification; the hub doc's own request-lifecycle sequence diagram shows
  Capability Planning emitting it (`CP -->> OBS: plan.validated`) after
  receiving Verification's `verify.passed` on the plan pre-check.
- **Recommended disposition: matrix is authoritative** (it is the declared
  "shared vocabulary referenced by all component specs"); sequence-diagram
  errata to move the emission to Verification — or, if the repository owner
  prefers, a considered decision to fold `plan.validated`/`plan.rejected` into
  the `verify.*` pair entirely, which would shrink the canon. Either
  resolution leaves VAE/00–05 valid; this document enumerates the canon as the
  matrix states it today (§2.1).

### 3.3 `plan.rejected` publisher — matrix vs. KERNEL/09

- **Inconsistency:** KERNEL/09's inbound contract lists `plan.created,
  plan.rejected` with publisher Capability Planning; the matrix assigns
  `plan.rejected` to Verification.
- **Recommended disposition: KERNEL/09 errata** to re-attribute
  `plan.rejected`'s publisher to Verification per the matrix. The Kernel's
  consumption ("plan bookkeeping") is unaffected — Kernel invariants are
  untouched by a publisher-attribution correction.

### 3.4 Learning's declared inputs vs. matrix rows

- **Inconsistency (a):** COMPONENTS/learning.md declares consuming
  `verify.failed`, but the matrix's `verify.failed` row does not list Learning
  as consumer.
- **Inconsistency (b):** COMPONENTS/learning.md consumes `trace.closed`,
  `process.failed`, `process.timeout` and publishes `lesson.recorded` — none
  of which are matrix rows (the matrix has `exec.failed`/`exec.timeout` and
  `lesson.learned`).
- **Recommended disposition:** for (a), add Learning to the `verify.failed`
  consumer list (smallest fix; matches the component sheet and the
  fault-ledger design). For (b), these are naming-era drift in the Learning
  component sheet (`process.*` → `exec.*`, `lesson.recorded` →
  `lesson.learned`, `trace.closed` → episodic-trace availability via
  Observability); recommend a Learning-sheet errata note. Neither affects any
  VAE row; both affect the membrane's supply side and are therefore flagged
  here (§5).

### 3.5 Stale event names in VAE/00 §7

- **Inconsistency:** VAE/00 §7 cites "`process.*`, `write.committed`" as
  already-canonized events; the matrix names are `exec.*` and
  `storage.committed`.
- **Recommended disposition:** errata note in VAE/00 per its own errata
  clause ("contradictions of this document require errata here"). Purely
  nomenclature; every later VAE phase already uses the matrix names.

---

## 4. Reasoning Orchestrator Handoff — Compatibility Confirmation

RO/05 §4 built RO's side of the handoff; this section confirms VAE's side is
shape-compatible, point by point. Nothing new is designed — both sides were
already fixed independently; Phase 5's job is demonstrating they meet.

| RO/05 §4 term | RO's side | VAE's side | Compatible because |
|---|---|---|---|
| Sealed outcome record crosses | Verbatim output, schema version reference, verification expectations metadata, constraint set, decision justification chain | VAE judges the sealed record against the output contract RO declared before invocation (VAE/00 §4 resp. 2, VAE/01 §4 "Reasoning artifacts") | The carried verification expectations are exactly the declared contract VAE's semantic level judges against |
| Demand signal | `reasoning.completed` → Verification (RO/05 §2) | Canonical demand source (VAE/04 §2.1, §2.2 here) | Same matrix row, both sides |
| Provider identity never a judgment input (RO-E12: audit-only) | Excluded from the handoff as judgment input | Provenance is evidence *about* an artifact, never a substitute for verifying it (VAE/00 §2); engine self-assessment carries no authority (VAE/00 §8) | Both sides independently rule identity out of the verdict function; it may sit in the record as audit data (VAE-S7 formalizes) |
| RO's opinion of answer quality never crosses (RO-E8) | RO transports, never judges | VAE accepts no producer self-score (VAE-I7) | Mutual: the judge takes no producer opinion; the producer offers none |
| Verdict never flows back into a sealed attempt (RO-S5) | No verdict-accepting path exists in RO | `verify.failed` routes to Scheduling/Capability Planning replan only (VAE-K4); no VAE emission targets RO | Failure is downstream workflow territory through the full gate on both sides' rulings |
| Mechanical/semantic line | Parse-level conformance is RO's execution governance | Semantic judgment of a conforming output is VAE's | The line lands identically in RO-E8 and VAE/01 §5 (Semantic level) |

**Verdict: shape-compatible with zero adjustments.** The handoff was designed
twice, independently, against the same laws — and meets in the middle without
an erratum on either side.

---

## 5. Learning / Experience Integration

The trusted-knowledge membrane (VAE/00 §3, VAE-I9) made operational at the
integration surface. VAE's role is entirely supply-side: it certifies, it
never learns.

### 5.1 What VAE Supplies

| Supply | Path | Feeds |
|---|---|---|
| Verdict events (`verify.passed`/`verify.failed`, with failure cause and assurance level) | Bus; persisted into the episodic record like all events | The verdict tags that make a closed trace admissible to Learning's distillation (Learning's own rule: "lessons... distilled only from closed, verdict-tagged traces") |
| Evidence records | Storage, fetchable by reference (VAE/04 §7.3) | Learning's grounding for *why* something failed — the fault ledger's substance beyond the bare event |
| Benchmarking telemetry (six signal families, VAE/04 §8) | Observability's one schema | Experience's analysis of verification itself: calibration, coverage honesty, check effectiveness, independence-agreement (VAE/02 §9) |

### 5.2 The Membrane, Operationally

- **Trusted path:** Learning distills lessons, faults, priors, and reliability
  only from closed, verdict-tagged material. An unverified outcome may exist
  in the episodic record (raw history is retained, VAE/00 §3) but carries no
  verdict tag and therefore never becomes a lesson, a prior, or a reliability
  signal. The membrane is enforced by Learning's own admission rule; VAE's
  obligation — met by VAE-K1 and VAE-O5 — is that every gated artifact carries
  a definite, durable, explainable verdict for Learning to key on.
- **A fail verdict is verified material.** Learning from `verify.failed` (the
  fault ledger) does not breach VAE-I9: a definite negative verdict *is*
  verification — the membrane excludes *unjudged* execution, not negative
  judgments. This reading was already forced by VAE/00 §8's Experience row
  ("Experience may learn *about* verification... from VAE's telemetry and
  evidence records") and is recorded here so no later reader mistakes the
  fault ledger for a membrane leak.
- **Matrix gap:** Learning's declared `verify.failed` consumption is missing
  from the matrix row — flagged in §3.4, recommendation: add Learning to the
  row.

### 5.3 What Flows Back — and How

Mirroring RO/05 §5's loop-closure discipline exactly:

| Flow back | Path | VAE's consumption discipline |
|---|---|---|
| Planning priors (`prior.updated` → Capability Planning, RO) | Learning's event | Not VAE's to consume — priors inform planning and reasoning governance, never verdicts. Priors as verdict input outside the versioned rules discipline is already forbidden (VAE/00 §8, Experience row) |
| Plugin reliability (`reliability.updated` → Plugin Runtime, CP) | Learning's event | Not VAE's to consume — reliability shapes capability matching, never judgment. VAE judges plugin output on evidence, not on the plugin's reputation (VAE/00 §2) |
| Verification-rules revision proposals | Experience proposes from benchmarking findings; a governance act enacts them as a **new rules version** via the config/Storage path | The only door into VAE (VAE-O8): findings enter as versioned rules-as-data, never as live adjustment. Every judgment records the rules version it used (VAE-K2), so past verdicts replay against past rules forever — the same no-rewrite discipline as RO-S6's priors versioning |

**The loop, complete:** VAE verdicts tag traces → Learning distills lessons,
faults, priors, reliability → planning and reasoning improve → producers
produce better artifacts → VAE's benchmarking telemetry meanwhile audits
verification itself → Experience proposes rules revisions → governance
versions them → VAE judges better. Two independent improvement circuits, both
crossing VAE only through versioned, replayable inputs — never through a live
edge.

---

## 6. Cross-Phase Invariant Audit

Sweep of VAE-I1–12, VAE-M1–7, VAE-A1–10, VAE-K1–12, VAE-O1–10 (51 invariants)
against each other, KERNEL/INVARIANTS.md (22), and ARCHITECTURE.md's laws.
Method: every pair where tension was plausible was examined; pairs with no
conceivable interaction are not tabulated. **Result: zero contradictions.**
Findings:

| # | Pair examined | Plausible tension | Verdict |
|---|---|---|---|
| 1 | VAE-I5 (every gated item gets a definite terminal verdict) vs VAE-O6 (persistence rejection → loud absence, no verdict published) | O6 appears to permit a gated item with no verdict | **Consistent.** VAE/00 §9 defines the failure-mode contract both descend from: "definite fail *or a loud absence the enforcers treat as fail*." I5's second clause (absence treated system-wide as not-passed) is exactly the state O6 produces; the item still terminates — via the enforcers' absence-as-fail machinery (VAE-K5) rather than via an unexplainable recordless verdict. |
| 2 | VAE/01 §9 "never retries" vs VAE-O3 (idempotent re-issue of unacknowledged dispatch) | Re-issue looks like retry | **Consistent.** Reconciled at design time (VAE/04 §3.4): retry re-runs against an existing outcome; delivery redundancy re-issues where no outcome exists. Duplicate results count once (VAE-A4/VAE/02 §5 Redundant). |
| 3 | VAE-A7 (gates open on `verify.passed` alone) vs `plan.validated` consumed by Scheduling | A second event opening the plan gate would bypass A7 | **Consistent under the §2.1 reading.** `verify.passed` remains the sole gate-opener; `plan.validated` is the plan-pipeline notification of that verdict, carrying no independent gate authority. Publisher-attribution errata flagged (§3.2) but no invariant conflict under either resolution. |
| 4 | VAE-K12 (Kernel records verdicts read-only) vs Kernel invariant 1 (Coordinator is sole mutator of the Ledger) | K12 says "read-only," Kernel mutates its Ledger to record verdicts | **Consistent.** K12 constrains verdict *content authority* (Kernel never authors or alters a verdict); Kernel invariant 1 governs Ledger *bookkeeping mechanics*. Recording a received verdict is mutation of the Ledger, not of the verdict. |
| 5 | VAE-I2 (enforcement lives in Kernel/Scheduler edges) vs Kernel invariants 2, 5, 12 (decisions are table lookups; missing verdict = blocked; Kernel never verifies) | Enforcement might require the Kernel to judge | **Consistent — mutually reinforcing.** Kernel invariant 5 is VAE-I5/K5 stated from the Kernel's side; enforcement is a boolean check on a received verdict (invariant 2), never judgment (invariant 12). |
| 6 | VAE-I9 (Experience never learns from unverified execution) vs Learning's fault ledger consuming `verify.failed` | Learning from failures might look like learning from unverified work | **Consistent.** A fail verdict is verified (judged) material; the membrane excludes unjudged execution, not negative judgments (§5.2). |
| 7 | VAE-I10 (reasoning-assisted checks cross RO's gate) vs RO-S5 (no verdict path back into sealed attempts) + VAE/00 §8 (no VAE influence on in-flight reasoning) | VAE requesting a reasoning-assisted check might constitute VAE↔RO circularity | **Consistent.** The check-invocation is an ordinary governed demand through RO's gate producing a sealed record consumed as weighed evidence; the verdict it feeds never flows back into that or any attempt. The circle never closes. |
| 8 | VAE-O4 (deadlines fixed pre-dispatch, never extended) vs Kernel invariant 10 (Kernel owns no timers; timeouts arrive as events) | Timer ownership | **Consistent.** Invariant 10 binds the Kernel only. VAE's delegation deadlines are VAE-internal bounded-self-work machinery (VAE/04 §3.3); nothing arrives at the Kernel as a VAE timer. |
| 9 | VAE-O5 (persist-then-publish) vs Kernel invariant 7 (log before publish) | None — pattern reuse | **Consistent by construction**; O5 explicitly adopts the Kernel's discipline at VAE's boundary. |
| 10 | VAE-O8 (findings only as versioned rules revisions) vs RO-S6/RO-S7 (priors only as versions; metrics never live inputs) | None — parallel structures | **Consistent** — the same loop-closure discipline independently derived on both subsystems; §5.3 aligns them explicitly. |
| 11 | VAE-K5 vs VAE-I5; VAE-K7 vs VAE-A7 | Near-duplicates within the register | **Intentional refinement, not conflict.** K5 restates I5's absence-as-fail at the enforcement seam; K7 restates A7 at the consumption seam. Each K-form binds a party the earlier form could not name (the enforcers, the consumers). No pair can be satisfied while the other is violated — the duplication is harmless and the seam-specific statements earn their place. Noted for the implementation's invariant checklist so both forms map to one check each. |
| 12 | VAE-M2/VAE-A6/VAE-O7 (evidence never degraded/pruned) vs Learning's compaction policy ("compaction/summarization keeps lessons compact") | Compaction might touch evidence | **Consistent.** Compaction operates on Learning's own lessons ledger; VAE's evidence records are a different owner's state (Verification via Storage) and no Learning process writes them. Ownership separation (Law 1) settles it. |
| 13 | VAE-I3/VAE-O2 (no spawning; dispatch only via direct channel) vs Law 3 (Execution sole spawner) and the containment rule (exec failures are ordinary results) | None | **Consistent by construction** — the V1-H4 fix, held across all five phases. |

**Duplicates found:** none that conflict (finding 11 documents the two
intentional seam-restatements). **Contradictions found: zero.** No STOP
condition reached.

---

## 7. Repository Errata Candidates

Recommendations only; every edit is the hub-doc/component-doc owner's act,
never VAE's (mirrors RO/05 §9's two-kind discipline — here all items are
candidates, none applied).

| ID | Location | Recommended edit | Basis |
|---|---|---|---|
| E-V1 | ARCHITECTURE.md verification lifecycle diagram | Relabel `RunningSelftests → Failed` transition from `exec.timeout / exec.failed` to "delegated result: timeout/failure (direct channel)"; matrix rows stand unchanged | §3.1; VAE-O2 |
| E-V2 | ARCHITECTURE.md request-lifecycle sequence diagram | Move `plan.validated` emission from CP to Verification (matrix is authoritative) — or fold `plan.validated`/`plan.rejected` into `verify.*` (owner's call) | §3.2 |
| E-V3 | KERNEL/09-interfaces.md inbound contract | Re-attribute `plan.rejected` publisher: Capability Planning → Verification, per matrix | §3.3 |
| E-V4 | ARCHITECTURE.md matrix, `verify.failed` row | Add Learning to consumers (COMPONENTS/learning.md already declares the consumption) | §3.4(a) |
| E-V5 | COMPONENTS/learning.md | Errata note: `process.*` → `exec.*`; `lesson.recorded` → `lesson.learned`; `trace.closed` → episodic-trace availability via Observability (no such matrix row exists) | §3.4(b) |
| E-V6 | VAE/00 §7 | Errata note per VAE/00's own clause: "`process.*`, `write.committed`" → "`exec.*`, `storage.committed`" | §3.5 |
| E-V7 | ARCHITECTURE.md component diagram (low priority) | Optionally add a `VER → MEM` query edge ("scope checks") — the seam is already canonized textually (VAE/00 §7; the direct-query style naming Repository Memory's retrieval API) but has no drawn edge | §2.3 |

---

## 8. Implementation Bridge

VAE design phases 0–5 are complete; implementation follows as a future
blueprint (analogous to UMS/00 and RO/05 §10). What that blueprint will need
**beyond** these design documents — the concrete decisions the design
deliberately left as data or mechanics:

| Needed by the blueprint | Why the design left it open |
|---|---|
| Concrete rules-as-data format: the artifact-type → checks/depth/deadline mapping's representation, versioning mechanics, and validation | Rules are versioned data by design (VAE/00 §9); their format is implementation, not architecture |
| Check-module packaging: how bounded static-check modules are declared, loaded, and kept out of producer fate-sharing | "Modular checks" fixed architecturally (VAE/00 §9); packaging is code structure |
| Evidence-record serialization for the five-part shape (VAE/04 §7.1) and the reference scheme into Storage | No-schema rule bound all five phases |
| Confidence/assurance derivation expression: the deterministic mapping from evidence body to dimensions, uncertainty, and level (VAE/02 §3, §7) as rules-as-data | Semantics fixed; expression explicitly deferred to rules-as-data (VAE/02 §3) |
| Dedup store for demand event ids and the pending-projection's in-memory shape (VAE/04 §2.2, §6) | Operational state classified, not designed |
| Deadline mechanics for delegations (clock source, expiry detection) | Bounded-self-work fixed; timing machinery is implementation |
| Direct-channel contract with Execution (dispatch/result carrier) | The channel is canonized (VAE-O2); its transport is Execution-side integration work |
| Test doubles: Execution, Storage, Communication, UMS as doubles until real; scripted delegated-check results as deterministic nondeterminism (RO/05 §10's engine-double pattern reused) | Established repo practice |
| Golden-artifact test suite: committed fixture artifacts + rules versions → byte-identical expected verdicts, evidence records, assurance readouts; determinism rate is a gate (100%), not a metric | CP/04 and RO/05 precedent |
| Invariant enforcement checks: the 59-invariant register (I/M/A/K/O/S) as a review gate plus, where scannable, law-enforcer-style static checks; finding-11 note — K5/I5 and K7/A7 map to one check each | Mirrors the kernel process mandate and RO-S10 |
| Replay tests: any verdict reconstructs byte-identically from artifact reference + rules version + recorded results, zero live reads (VAE/00 §10 criterion 4) | Success criterion fixed; harness is implementation |

**Completion criterion (RO/05 §10's standard adopted):** an implementer can
build VAE from VAE/00–05 with zero further *architectural* decisions; anything
discovered to need one is errata first, code second.

---

## 9. Final Subsystem Invariants (VAE-S)

New Phase 5 register, extending VAE-I1–12, M1–7, A1–10, K1–12, O1–10 without
duplication. These close the subsystem.

1. **VAE-S1** — VAE's architecture is complete in VAE/00–05; behavior not
   derivable from these documents does not exist; extensions are errata to the
   phase that owns the question, never silent divergence.
2. **VAE-S2** — The published event set (§2.1) is closed: `verify.passed`,
   `verify.failed`, `plan.validated`, `plan.rejected`, plus `fault.recorded`
   on the shared any-component row. `verify.*` names are Verification's alone;
   no other component publishes them, and VAE publishes nothing else.
3. **VAE-S3** — The consumed demand set (§2.2) is closed to the four matrix
   rows naming Verification; VAE reacts to no other event, and new demand
   requires errata here plus a matrix row, in that order.
4. **VAE-S4** — VAE's contribution to the trusted-knowledge membrane is
   supply-side only: verdicts, evidence records, and telemetry. VAE never
   distills, never writes a lesson, prior, or reliability signal, and a
   definite fail verdict is verified material — the membrane excludes unjudged
   execution, never negative judgments.
5. **VAE-S5** — Experience/benchmarking influence enters VAE only as a new
   versioned rules revision through the config/Storage path; every judgment
   records the rules version it used, and past verdicts replay against past
   rules forever. No live edge from any learning, metric, or telemetry stream
   into a judgment exists.
6. **VAE-S6** — No verdict flows backward into any sealed producer artifact,
   attempt, or record (mutual with RO-S5): failure routes forward through the
   enforcers' replan gates only, and no VAE emission targets a producer.
7. **VAE-S7** — Producer and provider identity within a judged record is
   audit-only data: it never enters the verdict function as a judgment input
   (formalizing the RO-E12–compatible reading of VAE/00 §2 provenance
   discipline at the integration surface).
8. **VAE-S8** — The implementation is verified against the invariant registers
   (VAE-I/M/A/K/O/S) only; phase-document prose is rationale, invariants are
   law (mirrors RO-S10 and the kernel process mandate).

---

## 10. Completion Summary

**VAE design phases 0–5 are COMPLETE.**

The six documents compose a single arc. VAE/00 fixed identity: evidence, never
decision — the judge that neither produced the artifact nor profits from its
acceptance. VAE/01 fixed the model: what is verifiable, the five question
levels, evidence as attributable accumulation, the five-way failure taxonomy.
VAE/02 fixed the measure: confidence as evidence strength in five dimensions,
uncertainty explicit and separate, five assurance levels that summarize and
never decide. VAE/03 fixed the enforcement seam: verdicts as first-class
events, structurally unskippable gates, limbo made impossible, retry and
rollback left wholly to the enforcers. VAE/04 fixed the operation: demand
intake, the delegation lifecycle, persist-then-publish, crash-safe pending
state, telemetry that makes assurance itself auditable. VAE/05, this document,
closes the surface: a closed event canon, a shape-compatible RO handoff
confirmed on both sides, the trusted-knowledge membrane wired to Learning
through versioned inputs only, fifty-one prior invariants audited clean, and
eight closing invariants.

**Settled by this document:** the complete integration surface (§1); the
closed published/consumed event canon and the complete non-event channel list
(§2); recommended dispositions for all five flagged canon inconsistencies
(§3); RO-handoff compatibility, confirmed point-by-point with zero adjustments
(§4); the Learning/Experience integration — membrane supply, fail-verdicts-
are-verified-material, and the versioned-revisions-only return path (§5); the
cross-phase invariant audit — thirteen examined tensions, zero contradictions
(§6); seven repository errata candidates (§7); the implementation bridge (§8);
and VAE-S1–S8 (§9).

**Deferred beyond the design:** nothing architectural. What remains is the
implementation blueprint (§8) and the hub-doc errata dispositions (§7), both
outside VAE's authority to enact. The evolution test stands as VAE/00 §11
wrote it: any future question outside "is this artifact trustworthy, with what
evidence, at what confidence, explained how" is a new component, not a VAE
extension.

Assurance is manufactured, not assumed — and the factory is now fully
designed: every gate structurally unskippable, every verdict definite and
replayable, every confidence traceable to evidence, every failure loud, and
every improvement to the judge itself arriving only as a versioned, auditable
revision.

---

## 11. Glossary (Phase 5 additions)

| Term | Definition |
|---|---|
| **Event canon (VAE)** | The closed set of bus events VAE publishes (§2.1) and consumes (§2.2); extension requires errata to this document. |
| **Errata candidate** | A recommended correction to a document outside VAE's authority (hub doc, kernel doc, component sheet), recorded in §7 for the owner's disposition — never applied by VAE. |
| **Membrane supply side** | VAE's role toward Learning: providing the verdicts, evidence records, and telemetry that make traces admissible to the trusted-knowledge path — certifying, never distilling. |
| **Rules revision** | The only inbound door for learning about verification: a new versioned rules-as-data snapshot enacted through the config/Storage path; never a live adjustment. |
| **Seam restatement** | An invariant that re-binds an earlier invariant's rule at a specific integration seam (e.g., VAE-K5 restating VAE-I5 for enforcers); intentional, non-conflicting, and mapped to a single implementation check (§6, finding 11). |
| **Shape compatibility** | The demonstrated property that two independently designed sides of a handoff (here RO/05 §4 and VAE's consumption of sealed outcome records) meet without adjustment on either side. |
