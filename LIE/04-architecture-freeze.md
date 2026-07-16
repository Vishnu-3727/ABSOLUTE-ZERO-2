# Learning & Intelligence Engine (LIE) — Phase 5: Architecture Freeze & Implementation Contract

Status: final. This document validates, consolidates, and **freezes** the LIE
architecture defined in LIE/00–03. It introduces no new concepts. Where review
found friction, it is resolved here using existing concepts only, and the
resolution is canon. After this document the architecture is
implementation-ready; subsequent change requires errata against the phase
documents, never silent divergence.

Canon under freeze: the five subsystems (Admission Gate, Experience Ledger,
Distillery, Advisory Interface, Curator); three knowledge classes (Experience,
Intelligence, Curation); record kinds (Episode, Decision) and derived kinds
(Lesson, Pattern, Anti-Pattern, Recipe, Project Dossier, Domain Knowledge
Pack); the provenance envelope, facets, and relations; Evidence Set, Maturity
Grade, Contested, Project Signature; the Derivation Ruleset; Ledger Position
and Derivation State; the Equivalence Obligation; invariants INV-1…10 and
OPS-1…8.

---

## 1. End-to-End Walkthrough

One experience, followed through every subsystem. Scenario: a Jetson
deployment fails, is recovered, and the experience later advises another
project.

**Verified execution.** A deployment workflow runs (Workflow Scheduler,
Plugin Runtime, Reasoning Orchestrator under Kernel governance). It fails; a
recovery attempt succeeds. VAE attests both outcomes — a verified failure and
a verified success. Observability closes both traces. *LIE has not yet acted,
and nothing waited for it (OPS-1).*

**Admission.** The Gate receives each closed verdict-tagged trace event via
Communication. Provenance checks pass; each unit is normalized into an
Episode — situation, approach, outcome, cost — with facets assigned from the
controlled vocabulary and the envelope completed (identity, attestation
reference, origin, relations: the recovery episode links `recovers` to the
failure episode; both link `about` to UMS identifiers and `enacts` to the
Decision that chose this deployment approach, admitted alongside them under
the same attested closure). Admission is idempotent (OPS-5): event redelivery
cannot duplicate either episode.

**Ledger.** Each record is appended via Storage, becomes durable, and receives
its Ledger Position. Capture is complete; the records are immutable forever
(INV-2).

**Derivation.** The Distillery, notified of the appends, performs incremental
derivation: the failure episode joins the negative evidence set for its
signature; the recovery joins the positive one. Under the current Derivation
Ruleset the negative set has now recurred — an Anti-Pattern is compiled, with
an `instead-of` link to the recovery-backed approach, grade Provisional (one
project). The new layer is published atomically with an advanced Derivation
State (OPS-3); equivalence with full regeneration holds by obligation.

**Curation.** Nothing requires ruling in this pass — the Curator is not in the
per-episode path and acts only deliberately (OPS-7). Had this artifact
conflicted with an existing one at the same signature, the Distillery would
have set Contested and queued it for ruling; advice would meanwhile present
both sides.

**Recommendation.** The Advisory Interface publishes `lesson.recorded`. Months
later a different project with an overlapping Project Signature consults
before deploying: its situation facets match the anti-pattern's signature. The
response is the four-part object — the warning, the scope in which it holds,
grade and standing, and the citation chain ending at both VAE verdicts —
stamped with the Derivation State it was answered from (OPS-4).

**Future request.** The consumer (Capability Planner, say) decides for itself
(INV-5), plans the alternative approach, work executes, VAE attests, and the
resulting episode enters the Gate — strengthening the evidence set, promoting
the artifact toward Established as project span grows. The loop closed through
VAE, not around it.

Every subsystem appeared exactly once in its own role; infrastructure
(Storage, Communication, Observability) carried everything and owned nothing
of LIE's.

---

## 2. Responsibility Audit

| Subsystem | Single responsibility | Leak check |
|---|---|---|
| Admission Gate | Decide what may become experience, and normalize it | Does not derive, store durably (Storage does), or judge quality beyond provenance. Clean. |
| Experience Ledger | Be the immutable system of record | Passive; no logic beyond append/serve. Clean. |
| Distillery | Compile intelligence from experience per the ruleset | Does not admit, rule, or advise. Detecting Contested is compilation (signature comparison), not judgment — the *ruling* stays with the Curator. Clean. |
| Advisory Interface | Answer consultations with cited advice; notify change | Read-only both directions; stores nothing. Clean. |
| Curator | Judge standing: rulings, vocabulary, ruleset governance | Does not admit, compile, or advise. Clean. |

Three frictions found in review, resolved with existing concepts:

- **R1 — Where do Gate rejections live?** LIE/00 requires recorded
  rejections; INV-1 bars non-attested content from the ledger. Resolution:
  rejection records are operational telemetry, owned by Observability like
  all runtime records — never ledger content. The audit trail exists; INV-1
  is untouched.
- **R2 — Facet assignment vs. vocabulary evolution.** The Gate assigns facets
  from the Curator-owned vocabulary, which evolves. Immutable episodes must
  stay interpretable. Resolution: the envelope's attestation section already
  records admission provenance — the vocabulary version in force at admission
  is part of that provenance. Old records read under old terms; rulings map
  terms forward (LIE/01 §7). No mutation, no new concept.
- **R3 — Reliability signals and planning priors** (component-sheet
  obligations) have no named artifact kind. Resolution: they are **Lessons in
  statistical form** — "in scope S, plugin X succeeds at rate r" is exactly a
  Lesson: a statement, a facet scope, an evidence set of episodes. Compiled
  by the ruleset, published in the layer, pulled by Plugin Runtime and
  Capability Planning like any advice. No sixth-and-a-half artifact kind
  needed.

---

## 3. Invariant Audit

Each invariant, its enforcement point, verified against the walkthrough:

| Invariant | Enforced by | Holds because |
|---|---|---|
| INV-1 single door | Gate | Only Gate writes experience; rejections live outside the ledger (R1) |
| INV-2 immutable experience | Ledger + Curator discipline | Append-only store; curation annotates by reference |
| INV-3 reproducible intelligence | Distillery + Derivation State | Layer = f(ledger, overlay, ruleset); triple names all inputs |
| INV-4 citation or silence | Advisory + envelope graph | Chain constructed from `evidenced-by`; unmatchable situation → definite absence |
| INV-5 advisory boundary | Advisory + consumer contracts | Pull-only, read-only; LIE outage degrades advice only |
| INV-6 model independence | Knowledge model | Records are structured engineering text; nothing model-shaped exists to lose |
| INV-7 human-readable, version-controlled | Ledger + overlay as repo artifacts | Recovery and portability are git operations (§4) |
| INV-8 deterministic processing | All subsystems | Versioned ruleset, causal triggers, no clocks, order-insensitive compilation |
| INV-9 UMS separation | Gate + envelope rules | `about` carries identifiers only; no repo semantics stored |
| INV-10 bounded incremental cost | Distillery | Signature-locality; Equivalence Obligation keeps the shortcut honest |
| OPS-1…8 | Verified §1 | Non-blocking capture, passive consultation, atomic publication, stamped advice, idempotent admission, one ruleset per layer, causal triggers, disposable derivations — each appeared in the walkthrough at its station |

Determinism, replayability, explainability, advisory-only: determinism is
INV-3/INV-8/OPS-6/OPS-7 jointly; replayability is Derivation State plus
order-insensitivity (LIE/03 §8); explainability is INV-4's constructed chain
plus the readable ruleset; advisory behavior is INV-5/OPS-1/OPS-2 jointly. All
four are properties of the structure, not of implementation diligence — which
is what makes them freezable.

---

## 4. Operational Audit

- **Crash recovery.** Capture path: unacknowledged events redeliver;
  idempotency deduplicates. Learning path: published layer survives or is
  regenerated (OPS-8). No cross-subsystem recovery protocol exists because no
  subsystem holds another's state.
- **Repository cloning.** Clone carries ledger, overlay, ruleset versions,
  and vocabulary — the complete Derivation State inputs. Regeneration on the
  clone reproduces the layer exactly. Migration of a decade of experience is
  `git clone` plus one regeneration.
- **Model replacement.** No stored artifact references any model (INV-6). The
  new model consults the same layer and receives the same advice. Nothing to
  audit beyond confirming nothing model-shaped leaked in — forbidden at the
  Gate by envelope rules.
- **Ruleset evolution.** New version → full regeneration → atomic swap
  (OPS-6). Historical layers remain reconstructible; old artifacts remain
  explainable under the versions that produced them.
- **Curator rulings.** Append-only overlay advances its position; Distillery
  re-derives affected artifacts; history unchanged. "What did we believe
  before the ruling" stays answerable via the prior Derivation State.
- **Replay.** One operation serves audit, migration, forensics, and disaster
  recovery (LIE/03 §8). The Equivalence Obligation gives implementation a
  standing oracle: incremental and regenerated layers must match exactly.
- **Long-term growth.** Ledger unbounded, layer compressed by recurrence,
  consultation cost tracks the layer, absorption cost tracks the signature.
  No clocks, no decay, no scheduled maintenance — the ten-year system is the
  one-year system with a longer ledger.

---

## 5. Integration Audit

- **Execution Kernel.** Consumer and sovereign. Consults; decides; enforces
  nothing for LIE. LIE asks nothing of it. Clean.
- **VAE.** Sole admission authority upstream. One-way flow; LIE never
  re-verifies, VAE never learns. LIE's quality is bounded by VAE's rigor —
  accepted coupling, one standard of truth. Clean.
- **UMS.** Peer, strict separation. Identifiers cross; content never does
  (INV-9). UMS answers "what is here"; LIE answers "what has verified work
  taught us." Clean.
- **Capability Planner.** Consumer: pulls planning priors (Lessons in
  statistical form, R3) and situation advice. Owns its plans and its
  adoption decisions. Clean.
- **Workflow Scheduler.** Not a consumer in the direct sense — schedules per
  Kernel decisions; its executed workflows become episode content. No
  contract with LIE beyond the general one: never wait for it. Clean.
- **Plugin Runtime.** Consumer: pulls reliability signals (R3). Owns the
  registry and all plugin state; LIE derives numbers, never touches state.
  Clean.
- **Reasoning Orchestrator.** Producer-side only: its outcomes reach LIE
  exclusively through VAE attestation — reasoning output has no direct path
  into the ledger, which is INV-1 doing exactly what it was designed for.
  May consult like any component. Clean.
- **Infrastructure** (Storage, Communication, Observability). All durable
  writes via Storage (Law 3); all events via Communication; closed traces in,
  telemetry and rejections out via Observability. LIE spawns no processes and
  holds no private persistence. Clean.

No responsibility crosses a boundary in either direction. The component sheet
(`COMPONENTS/learning.md`) remains fully satisfied: its events, its
reliability/prior obligations, its noise-rejection and determinism acceptance
criteria all have owners above.

---

## 6. Implementation Contract for Sonnet

Non-negotiable. An implementation violating any line below is wrong regardless
of how well it works.

### Global contracts

- Determinism everywhere: identical inputs and versions → identical outputs,
  bit-comparable. No wall-clock inputs, no environment-dependent behavior, no
  unordered iteration leaking into outputs.
- The Equivalence Obligation is the standing test oracle: incremental
  absorption and full regeneration must produce identical layers. Ship the
  comparison as a first-class check.
- All experience, overlay, ruleset, and vocabulary artifacts: human-readable,
  diffable, version-controlled. If a contributor cannot read it in a text
  editor, it is out of contract.
- Nothing model-shaped in any stored artifact. No embeddings-as-truth, no
  opaque scores without recorded derivation.
- All durable writes through Storage; all events through Communication; no
  private persistence; no spawned processes.
- Every stored record carries the full provenance envelope. An envelope that
  cannot be completed is a rejection, not a partial admit.

### Admission Gate

- **Required:** single entry point; provenance verification against VAE
  attestation; normalization onto the current vocabulary (version recorded in
  the envelope, R2); idempotent admission keyed on attested-unit identity;
  durable-append-then-acknowledge ordering; rejection records with reasons to
  Observability (R1).
- **Forbidden:** admitting anything unattested (no bulk import, no manual
  insertion — INV-1 has no exceptions); deriving; mutating the vocabulary;
  acknowledging before durability.
- **Guarantees:** one attested unit → at most one ledger record; no admitted
  record lacks a complete envelope.
- **Assumptions to preserve:** VAE verdicts are trustworthy and final; trace
  events are durable and redeliverable.

### Experience Ledger

- **Required:** append-only record store with monotonic Ledger Position;
  serve reads to Distillery, Advisory (chain resolution), Curator.
- **Forbidden:** update or delete of any record; any content transformation;
  any logic beyond append and serve.
- **Guarantees:** any historical ledger state is nameable by position and
  reconstructible via version control.
- **Assumptions to preserve:** the ledger is the sole source of experience
  truth; losing everything else loses nothing permanent.

### Distillery

- **Required:** execute the current Derivation Ruleset version exactly;
  evidence-set grouping by signature; compile all six artifact kinds; compute
  Maturity Grades and Contested flags; read the curation overlay as weighting
  input; incremental absorption with signature-local cost; full regeneration;
  atomic publication stamped with Derivation State.
- **Forbidden:** editing anything it reads; resolving Contested conflicts
  itself (no automatic tie-breaks — recency, count, or otherwise); mixing
  ruleset versions in one layer; deriving from anything outside (ledger,
  overlay, ruleset); clock- or schedule-driven runs.
- **Guarantees:** layer = pure function of the Derivation State triple;
  order-insensitive over ledger contents; publication atomic; crash-safe by
  disposability.
- **Assumptions to preserve:** regeneration is reference semantics; the
  ruleset is data, versioned and readable.

### Advisory Interface

- **Required:** pull-only consultations taking situation facets; four-part
  recommendation objects (advice, scope statement, maturity and standing,
  walkable citation chain); definite "no relevant experience"; Derivation
  State stamp on every response; publish `lesson.recorded`,
  `reliability.updated`, `prior.updated` as notifications without advice
  payloads.
- **Forbidden:** pushing advice; writing any consumer state; triggering
  derivation; storing recommendations; answering from a partially published
  layer; emitting any recommendation whose chain cannot be walked to VAE
  verdicts.
- **Guarantees:** same question at same Derivation State → same answer,
  forever; consultation is read-only and never blocks on derivation.
- **Assumptions to preserve:** consumers decide; absence of advice is a valid,
  expected operating condition for the whole OS.

### Curator

- **Required:** append-only rulings (deprecation, supersession, contradiction
  resolution) with reasons and cited evidence; vocabulary ownership (additive
  evolution, merges by ruling); ruleset version governance; process the
  Contested queue deliberately.
- **Forbidden:** mutating or deleting any record anywhere; automatic or
  event-triggered rulings; admitting experience; compiling intelligence.
- **Guarantees:** every ruling is itself a citable, versioned record; overlay
  position advances monotonically.
- **Assumptions to preserve:** judgment is deliberate and human-accountable;
  the Distillery follows rulings mechanically.

---

## 7. Freeze Declaration

The Learning & Intelligence Engine architecture — LIE/00 foundation, LIE/01
knowledge model, LIE/02 derivation, LIE/03 operational lifecycle, and this
review — is **frozen and declared implementation-ready**.

All review findings (R1–R3) are resolved within existing concepts. All
invariants verify against all subsystems. All integration boundaries are
clean. No open architectural questions remain; everything left unspecified
(thresholds, formats, mechanics) is deliberately implementation-phase material
and is bounded by the contracts of §6.

Implementation proceeds under LIE/04 §6. Architectural change from this point
requires errata against the phase documents.
