# Learning & Intelligence Engine (LIE) — Phase 4: Operational Lifecycle & Runtime Semantics

Status: canonical runtime semantics. No implementation, scheduling algorithms,
concurrency mechanisms, indexing, persistence design, or optimization. Refines
within LIE/00–02; contradictions require errata there.

All Phase 1–3 concepts are canon under their existing names. This document
defines how the subsystem *behaves over time*: what triggers what, what waits
for what, what happens when parts fail, and how a decade of continuous growth
changes nothing about the semantics.

Two operational concepts are introduced (§2); everything else is lifecycle
semantics over existing canon.

---

## 1. Governing Operational Stance

Three constraints from the charter, restated as the stance every section below
enforces:

1. **Learning never blocks execution.** LIE observes completed work after the
   fact. No component of the operating system ever waits on admission,
   derivation, or curation. If LIE is slow, learning is late; execution is
   untouched.
2. **Execution correctness outranks learning completeness.** Where a failure
   forces a choice, LIE drops learning before it risks corrupting learning,
   and corrupts nothing before it disturbs execution. The severity order is:
   disturb execution (forbidden) > corrupt the ledger (forbidden) > miss an
   episode (tolerable, recorded).
3. **Advice is pulled, never pushed.** Consumers request consultations. LIE's
   published events are change *notifications* — signals that re-consultation
   may be worthwhile — and never carry advice as payload.

---

## 2. Operational Concepts

**Ledger Position.** The Experience Ledger has a total, monotonic admission
order: every admitted record occupies the next position, forever. Position is
an ordinal fact about the ledger, not a semantic input — derivation remains
order-insensitive (LIE/02 §1). Position exists so that any state of the ledger
can be named ("the ledger through position N") without timestamps, clocks, or
environment dependence.

**Derivation State.** The identity of a published intelligence layer: the
triple **(ledger position, curation overlay position, ruleset version)**. The
overlay, being append-only, has positions exactly as the ledger does. The
triple fully determines the intelligence layer (LIE/02 §1 — there is no other
input), so it serves as the layer's version, its provenance, and its
reproduction instruction all at once. Every published layer carries its
Derivation State; every advisory response stamps it (§7).

These two concepts discharge replay, freshness, audit, and recovery semantics
below without any further machinery.

---

## 3. Lifecycle of an Episode

The runtime realization of LIE/00 §5, station by station:

1. **Attestation (outside LIE).** Work closes; VAE renders a verdict;
   Observability closes the trace. LIE has done nothing and delayed nothing.
2. **Admission.** The Gate, triggered by the closed verdict-tagged trace event,
   checks provenance and normalizes. Outcome: an admissible record or a
   recorded rejection. Admission is idempotent — one attested unit yields at
   most one episode, ever, regardless of event redelivery (identity derives
   from the attested unit's identity, so replays deduplicate by construction).
3. **Durable append.** The record is appended to the Ledger via Storage and
   assigned its Ledger Position. Admission is complete only when the append is
   durable; the Gate acknowledges nothing before that.
4. **Absorption.** The Distillery, notified of the append, performs
   incremental derivation (§5): affected evidence sets are identified by
   signature; affected artifacts recompiled; grades and Contested flags
   recomputed; a new intelligence layer state is published atomically.
5. **Notification.** The Advisory Interface publishes the canonical change
   events (`lesson.recorded`, `reliability.updated`, `prior.updated`) for
   whatever actually changed.
6. **Service.** From the moment of publication, consultations reflect the new
   evidence. The episode is now citable and remains so permanently, subject
   only to curation weighting.

Stations 1–3 are the *capture path* and prioritize never losing provenance.
Stations 4–6 are the *learning path* and prioritize never blocking anything.
The decoupling point is the durable append: once a record has a Ledger
Position, learning from it can happen now, later, or after a crash — with
identical results (Equivalence Obligation).

---

## 4. Trigger Model

| Subsystem | Triggered by | Never triggered by |
|---|---|---|
| Admission Gate | Closed, verdict-tagged trace events | Polling; clocks; consumers |
| Experience Ledger | Writes from the Gate; reads from Distillery, Advisory, Curator | Anything of its own — it is passive |
| Distillery | (a) ledger append → incremental derivation; (b) new curation ruling → re-derivation of affected artifacts; (c) ruleset version change → full regeneration; (d) explicit regeneration request | Clocks or schedules — derivation happens on cause, not cadence; consultations (OPS-2) |
| Curator | Deliberate governance acts; the Contested queue the Distillery flags for ruling | Anything automatic — a triggered ruling is a contradiction in terms |
| Advisory Interface | Consultation requests; layer publications (to emit change notifications) | Its own initiative — it never pushes |

The system consequently has no background heartbeat: quiescent input produces
a quiescent LIE, and every state change is causally attributable to an event
that can be named. This is determinism's operational face — clock-driven
behavior would make system state a function of wall time, which replays cannot
reproduce.

---

## 5. Incremental Derivation Semantics

Absorption of one record is bounded, signature-local work (INV-10): the new
record's signature names the evidence sets it joins; only artifacts compiled
from those sets are recompiled. The result is published as a new layer state
with an advanced Derivation State.

The Equivalence Obligation (LIE/02 §9) governs absolutely: the incrementally
produced layer must be identical to full regeneration at the same Derivation
State. Runtime consequence: the incremental path may be *suspended, dropped,
or crashed at any moment with no semantic loss* — the ledger holds the truth,
and the next derivation (incremental catch-up or full regeneration) lands in
the same place. Incremental derivation is a latency optimization, never a
source of state.

Publication is atomic from the consumer's view: a consultation sees either the
prior complete layer or the new complete layer, never a torn intermediate.
(How atomicity is achieved is implementation; that it is achieved is canon.)

---

## 6. Full Regeneration and Ruleset Evolution

**Regeneration** compiles the intelligence layer from scratch: empty layer,
full ledger, full overlay, one ruleset version. It is triggered by ruleset
change, by suspicion (corruption, equivalence audit), or by explicit request —
never by schedule. During regeneration the previous published layer continues
serving consultations; the new layer replaces it atomically on completion.
Regeneration is the reference semantics and the recovery path; it is expected
to be rare, offline-tolerable, and linear in ledger size — acceptable because
nothing waits for it.

**Ruleset evolution** is a governance act with strict semantics:

- Ruleset changes are versioned, deliberate, and owned by the Curator's
  governance authority — changing how the system learns is a curation-class
  judgment, not an engineering convenience.
- A new ruleset version takes effect *only* through full regeneration. No
  published layer ever mixes artifacts from two ruleset versions (a mixed
  layer would have no Derivation State, hence no identity, hence no
  reproducibility).
- Old ruleset versions are never deleted; any historical layer state remains
  reconstructible from its Derivation State triple.

---

## 7. Recommendation Availability and Consumer Interaction

**Availability.** Consultations are answered from the currently published
layer — synchronously, read-only, without waiting on any in-flight
derivation. Freshness is therefore eventual and *visible*: every advisory
response stamps the Derivation State it was answered from, so a consumer
always knows "advice as of ledger position N." A consumer that has just seen
work complete and wants advice reflecting it can await the corresponding
change notification before re-consulting; the choice belongs to the consumer,
as all choices do.

**Interaction model.** A consultation presents the consumer's situation as
facets; the response is the four-part recommendation object (LIE/02 §6) —
possibly several, possibly the definite "no relevant experience." Standing
signals the component sheet canonizes (plugin reliability, planning priors)
follow the same pull semantics: LIE publishes that they changed; Plugin
Runtime and Capability Planning fetch when they choose. LIE keeps no record of
what any consumer adopted — adoption consequences return, if they return, as
new attested work through the Gate. The loop closes through VAE or not at all.

**Failure of LIE, seen from consumers.** Any LIE outage has exactly one
consumer-visible symptom: consultations fail or stale. Consumers proceed
unadvised — by INV-5 the operating system remains fully functional and exactly
as deterministic. No consumer may treat advice availability as a precondition
for anything.

---

## 8. Failure, Recovery, and Replay Semantics

Failure semantics follow the severity order of §1 and the capture/learning
split of §3:

- **Gate unavailable.** Trace events remain durable with Communication;
  admission resumes on recovery and idempotency absorbs redelivery. Episodes
  are late, never lost, never duplicated.
- **Durable append fails.** The Gate does not acknowledge; the event stays
  queued; retry follows. If an append can ultimately never succeed, the
  episode is lost as learning — recorded as a rejection with reason — and the
  ledger stays uncorrupted. A record without durable provenance must not
  exist; missed learning is the tolerable cost (§1.2).
- **Distillery crashes mid-derivation.** The published layer is untouched
  (publication is atomic, §5). Recovery = re-derive from the last published
  Derivation State; the Equivalence Obligation guarantees the same
  destination.
- **Intelligence layer lost or corrupted.** Recovery = full regeneration
  (INV-3). No consumer participates; the only symptom is stale advice while
  it runs, with the stale layer still serving if it survives, or "no advice"
  if it did not.
- **Ledger or overlay damaged.** The one genuinely serious failure. Both live
  as human-readable artifacts under version control (INV-7): recovery is
  version-control restoration, and the same property makes damage *evident* —
  history in git does not corrupt silently.

**Replay.** Replaying the admitted records of a ledger through the Distillery
under a stated overlay position and ruleset version reproduces the
intelligence layer of that Derivation State exactly — in any processing
order, since derivation is order-insensitive over contents. Replay is the
universal tool: equivalence audits (incremental vs. regenerated), migration of
accumulated experience to a new installation (clone the repository,
regenerate), forensic reconstruction ("what did the system believe when it
advised this?"), and disaster recovery are all the same operation with
different inputs. LIE needs no backup mechanism of its own beyond the
version-controlled ledger and overlay — the repository *is* the institution's
memory, exactly as the long-term vision requires.

---

## 9. Operational Invariants

Binding on all later work, alongside INV-1…10:

- **OPS-1 (Non-blocking).** No execution-path component ever waits on any LIE
  activity. LIE observes; it is never observed *for*.
- **OPS-2 (Passive consultation).** Consultations are read-only and never
  trigger derivation, curation, or any state change beyond operational
  telemetry.
- **OPS-3 (Atomic publication).** Consumers only ever see complete,
  internally consistent intelligence layers, each with a Derivation State.
- **OPS-4 (Stamped advice).** Every advisory response carries the Derivation
  State it was answered from.
- **OPS-5 (Idempotent admission).** One attested unit of work yields at most
  one ledger record, under any pattern of retries or redelivery.
- **OPS-6 (One ruleset per layer).** A published layer derives from exactly
  one ruleset version; ruleset changes take effect only via full
  regeneration.
- **OPS-7 (Causal triggers only).** Every LIE state change is attributable to
  a named triggering event; nothing runs on wall-clock schedule.
- **OPS-8 (Disposable derivations).** Any derived state may be discarded at
  any time and regenerated without consumer involvement or knowledge loss.

---

## 10. Performance Principles and Behavior at Decade Scale

Principles — not algorithms — that hold as the ledger grows for years:

- **The ledger grows without bound; the intelligence layer must not.**
  Recurrence *compresses*: a thousand episodes matching one signature are one
  pattern with a large evidence set, not a thousand artifacts. Dossiers scale
  with projects, packs with domains — both bounded by human activity, not by
  execution count. The derived layer is the compact working set; this is the
  architectural answer to "consultation over ten years of experience," and it
  must be preserved by every ruleset version.
- **Consultation cost follows the intelligence layer, not the ledger.**
  Consultations match against artifacts; the ledger is touched only to resolve
  citation chains on demand. Advisory latency therefore stays flat as history
  deepens.
- **Incremental cost follows the signature, not the corpus.** Bounded
  absorption (INV-10) is preserved because signature-locality limits
  recompilation regardless of total ledger size.
- **Regeneration is the only whole-corpus operation,** rare and never waited
  on.
- **No implicit aging.** Records never expire and no silent recency bias
  exists. If a domain's ruleset policy weights newer evidence (reasonable for
  performance learning), that weighting is declared in the versioned ruleset
  like every other rule — explicit, auditable, reproducible.

**Determinism under continuous growth** reduces to one sentence: growth only
ever adds inputs, and the Derivation State triple names them completely — so
any installation, any model, any year, holding the same repository state,
compiles the same intelligence and gives the same advice. That sentence is
the whole point of the engine.

---

## 11. Phase Boundary and Phase 5 Scope

This document fixes: the operational stance, Ledger Position and Derivation
State, the six-station episode lifecycle with its capture/learning decoupling,
the causal trigger model, incremental and regeneration semantics, ruleset
evolution semantics, pull-only consumer interaction with stamped freshness,
failure/recovery/replay semantics, OPS-1…8, and the decade-scale performance
principles.

**Phase 5 scope (accepted, canon): architecture freeze.** Phase 5 introduces
no new concepts. It consolidates: an end-to-end walkthrough from verified
execution to recommendation; verification of every invariant (INV-1…10,
OPS-1…8) against every subsystem; a responsibility-leak audit across the five
subsystem boundaries; confirmation of determinism, replayability, and
explainability; and the implementation guidance and non-negotiable contracts
handed to Sonnet. After Phase 5 the architecture is frozen — subsequent change
requires errata against the phase documents, never silent divergence.
