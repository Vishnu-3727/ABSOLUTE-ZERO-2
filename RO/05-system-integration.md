# Reasoning Orchestrator (RO) — Phase 5: System Integration & Completion

Status: authoritative; completes the RO architecture (RO/00-05). Introduces no
new concepts — assembles frozen ones from RO/00-04 into the subsystem's
integration surface. The event canon declared in §2 is CLOSED as of this
document; any future reasoning event is an errata to this doc, mirroring
PRT/05's closed-set discipline. Architecture only — no code, no pseudocode,
no APIs, no algorithms, no modules/files/classes, no vendor/model names.

---

## 1. Subsystem Integration

| Subsystem | RO consumes | RO produces toward it | RO never owns |
|---|---|---|---|
| Kernel | Nothing direct beyond shared bus + config discipline | Nothing direct | Kernel admission/routing authority; kernel lifecycle (RO/00 §6) |
| RSM | Nothing | Mirrored decision/attempt/outcome records, telemetry-only (§3) | Request state authority; RSM-I15 — mirrored events never control edges back |
| UMS | Nothing — zero seam, ever (RO-I5, Law 2, PRT-S9 pattern) | Nothing | Repository understanding, retrieval, similarity; RO's knowledge arrives only inside sealed Request Memory |
| CM | Request Memory as sealed input (RO/03 §6) | Nothing | Context assembly; stale-RQM discovery is a preparation failure routed back (RO-P12), never a retrieval request |
| CP | Nothing directly — demands arrive plan-mediated via WS dispatch (RO-I6, RO/00 §10); CP is fully upstream | Nothing live — influence only via the Experience → priors loop (§5) | Intent interpretation, decomposition; CP never names reasoning methods (CP/03 §9) |
| WS / Execution | Demand via sealed workflow-unit dispatch | Sealed outcome records the workflow's downstream consumes | Scheduling, ordering, dispatch, process spawning (Law 3); Execution enacts local-engine physical realization only (RO-E1) |
| PRT | Nothing — zero seam (RO-I9, PRT-S9) | Nothing | Reasoning-provider descriptor space is RO's own; tool-provider identity never enters reasoning requests |
| Verification | Nothing | Sealed outcome records (§4) + carried verification expectations (RO-P8) | Judgment of any kind — RO transports, never judges (RO-E8) |
| Experience / Learning (+ Observability path) | Versioned priors (`prior.updated`) | Full decision/outcome event stream + records (§5) | Priors computation, lesson distillation |
| Storage | Config/policy versions | Durable artifacts: descriptor-space versions, schemas, decision records, sealed outcome records | Any RO-local durable write path — single-writer law holds |

---

## 2. Event Participation

The canonical RO event set — CLOSED.

**Published by RO (4 events):**

| Event | Emitted when | Consumers |
|---|---|---|
| `reasoning.decided` | A necessity decision seals — all five RO/02 outcomes use this one event; outcome class carried in payload. One event, not five: all outcomes share the same consumer set, unlike CP's `plan.created`/`plan.rejected` split which had different control consumers. | Scheduling, Learning, Observability |
| `reasoning.invoked` | A quarantine crossing begins (an attempt enters Executing, RO/04 §2) | Observability |
| `reasoning.completed` | An attempt seals with Returned recovery | Verification, Scheduling, Observability |
| `reasoning.failed` | An attempt seals with Failed / Expired / Cancelled recovery | Scheduling, Learning, Observability |

**Consumed by RO:**

| Event | Publisher | Why RO consumes it |
|---|---|---|
| `context.assembled` | CM | Request Memory availability signal for preparation (RO/03 §6) |
| `prior.updated` | Learning | Versioned priors input (RO/00 §10). This row is missing from the ARCHITECTURE.md matrix even though CP/00 already declared consuming it — errata E5 (§9) adds it |
| Config/policy versions | Storage | Via Storage discipline, not an event-consumption novelty |

**Rules:**

| Rule | Statement |
|---|---|
| Ownership | Publisher owns name + schema via Communication's versioned registry (established canon) |
| Ordering | Seal order within one request only (RO-E10); no cross-request ordering promise |
| Immutability | Events are facts, never retracted; corrections are new events |
| Replay | Events are re-derivable from sealed records — records are the truth, events the notification (mirrors RSM journal philosophy) |
| Closed set | New reasoning events require errata to this document |

---

## 3. Request State Integration

RO's records mirror into RSM: decision records (all five RO/02 outcomes),
attempt/outcome summaries (RO/04 §9).

| Property | Statement |
|---|---|
| Ownership | RO owns record content; RSM owns the materialized view; the bus is the only write path (RSM canon — no direct write surface) |
| Immutability | Records are append-only, versioned with the artifacts they cite |
| Auditability | RSM's view answers "what is this request's reasoning state" without touching RO internals |
| Lifecycle | Records follow request lifecycle (evicted per RSM policy); durable truth stays in Storage per §1 |
| Control | Telemetry only, never control (RSM-I15) |

---

## 4. Verification Handoff

The absolute boundary between RO and Verification:

| RO ends at | Verification begins at |
|---|---|
| Sealed outcome record exists (RO/04 §2) | Judging the conforming output against carried verification expectations |

**Crosses the boundary:** the sealed outcome record — verbatim output, schema
version reference, verification expectations metadata, constraint set,
decision justification chain.

**Never crosses:**

| What | Why |
|---|---|
| Engine access | Verification never talks to engines (RO-E4) |
| Provider identity as a judgment input | Audit-only (RO-E12) |
| RO's opinion of answer quality | RO has none (RO-E8) |
| Verification's verdict as a live control into the same attempt | A failed verification is downstream workflow territory — replan/re-demand through the full gate (CP/03 three-gate split); it never rewinds a sealed record |

**Mechanical/semantic line (restated, RO-E8):** parse-level conformance is
execution governance; semantic judgment of a conforming output is
Verification's, always.

---

## 5. Experience Feedback

Closing the loop without breaking replay.

| Flow | Content |
|---|---|
| Out (RO → Experience) | The full decision stream — approvals AND the four non-approvals (rejections are P6's fuel); sealed outcome records; budget reconciliations; failure classes (F1-F8); verification acceptance results (via Verification's own events) |
| Back (Experience → RO) | ONE versioned priors artifact (`prior.updated`), folding: provider priors (descriptor reliability healing, RO/03 §3); routing priors (which capability/provider pairings historically sufficed); demand-shape priors (recurring demands that reasoning answered → candidates for deterministic registration, driving the Information Boundary DOWN — RO-C2, the declining asymptote made operational); policy evolution proposals (Experience proposes; governance policy changes are Vishnu/admin acts — Experience never edits policy directly) |

**Replay safety.** Priors enter every determinism tuple as a VERSION (RO/03
§12); a decision replays against the priors version it recorded, never
current priors — future governance changes never rewrite past decisions
(CP/04 no-pinning-for-new/pinned-for-replay discipline).

---

## 6. Observability

| Observed aspect | Why it exists |
|---|---|
| Decisions (all five outcomes + justifications) | The governance story; approval rate is meaningless without the rejection denominator |
| Preparation (context selection sizes, reduction records, inclusion justifications) | Payload minimization is measurable or it is fiction |
| Selection (candidate/eligible sets, refusal reasons) | Provider-market health + policy-filter effects visible |
| Invocations (attempts, retries, substitutions) | The quarantine crossing count IS the scarcity metric |
| Failures (F1-F8 distribution) | Taxonomy only earns its keep if observed |
| Budgets (allocation, consumption, reconciliation) | Hard ceilings need visible pressure gauges |

One schema, one sink: Observability (established canon); RO emits, never
aggregates.

---

## 7. Architectural Metrics

Conceptual, RO-owned, NO calculations.

| Metric | What it tells |
|---|---|
| Reasoning approval rate | Governance permissiveness in practice |
| Deterministic avoidance rate (demands resolved below rung R) | THE headline metric — must trend up (RO/00 §11.1) |
| Provider utilization | Per descriptor row |
| Budget utilization | Allocated vs. consumed |
| Retry frequency | Per failure class |
| Context reduction ratio | RQM offered vs. sent |
| First-pass success | Returned + verification-accepted on attempt 1 |
| Verification acceptance rate | Consumed from Verification events, attributed per capability/provider |
| Reasoning latency class distribution | Cost-shape visibility |
| Cost class distribution | Spend-shape visibility |

**Rule.** Metrics are derived downstream from RO's records/events by
Observability — RO owns the DEFINITIONS, never the computation (mirrors
CP/04: benchmarks ≠ architecture).

---

## 8. Architectural Evolution

| GROWS AS DATA | NEVER CHANGES |
|---|---|
| Providers / descriptor rows | The two-condition reasoning test (RO/01 §1) |
| Capability rows + facets | The five decision outcomes (RO/02 §4) |
| Renderers / serialization forms | The two-artifact split (RO/03 §2) |
| Schemas (versions) | The closed four recoveries (RO/04 §1) |
| Failure sub-classes | F1-F8 class level (RO/04 §5) |
| Coordination patterns | The event set (sans errata, §2) |
| Timeout/retry/budget policy | The quarantine's single gate |
| Priors | — |

**Why stable.** Every volatile axis was pushed into declared data; every
stable axis is a closed set with an errata-only extension path.

**Evolution test (RO/00 §13, restated).** If a future development requires
RO to answer a question outside "should we reason, with what, at what cost,
prepared how, measured how" — that is a new component, not an RO extension.

---

## 9. Repository Errata

The corrections this completed architecture requires elsewhere. Two kinds.

**(a) Edits applied now** (live hub docs — see RO Phase 5 companion edits):

| ID | Edit |
|---|---|
| E1 | ARCHITECTURE.md non-duplication bullet (~line 411): Prompt Compiler entry superseded — request preparation + rendering exist in exactly one place: RO (RO/00 §5.7) |
| E2 | ARCHITECTURE.md component summary CM row (~line 540): drop "deferred to future Prompt Compiler service", point to RO |
| E3 | ARCHITECTURE.md context-assembly diagram (~line 497): LLM-call node relabeled through RO |
| E4 | ARCHITECTURE.md event matrix: +4 `reasoning.*` rows |
| E5 | ARCHITECTURE.md event matrix: +`prior.updated` row (Learning → Capability Planning, Reasoning Orchestrator, Observability) — CP/00 already declared consuming it, row was always missing |
| E6 | ARCHITECTURE.md component summary: +Reasoning Orchestrator row |
| E7 | COMPONENTS/context-management.md: errata note (its three Prompt-Compiler references superseded) |

**(b) Interpretation rules for frozen docs** (no edits — recorded here as the
global reading): every "Prompt Compiler" reference in frozen docs (PRT/05
§2/§8/PRT-S9, CP/00 §2/§8, CP/03 §8/§10, WS/00 §3, KERNEL/01 mapping table,
RSM/01 mapping note, CM/00 blueprint scope ruling, ROADMAP.md CM bullet) now
reads as "RO's request-preparation/rendering boundary (RO/00 §5.7)"; every
constraint attached to that line (provider identity never crosses it; never
sees raw intent) transfers intact and is already re-encoded as
RO-P2/RO-I6/RO-I8. PRT-S9's zero-seam with "Prompt Compiler" = zero-seam with
RO's preparation boundary — confirmed, RO-I9. Terminology: "Reasoning
Engine(s)" in older docs = RO's reasoning providers/engines (RO/00 §14).

---

## 10. Implementation Blueprint

Architectural bridge; NO modules/files/classes.

**Conceptual component groups, dependency-ordered:**

| Group | Content (RO doc) |
|---|---|
| G1 Capability & Descriptor Space | RO/01 + RO/03 §3 — capability rows, characteristics, relationships, descriptor rows, versioning |
| G2 Decision Gate | RO/02 — necessity evidence evaluation, five outcomes, ladder bookkeeping, decision records |
| G3 Preparation | RO/03 — context selection/reduction from RQM, budgeting, constraints, schema binding, request artifact |
| G4 Resolution & Rendering | RO/03 §4-5, §11 — matching, selection, Provider Resolution, renderers |
| G5 Execution Governance | RO/04 — attempts, retries, failure taxonomy, timeouts, cancellation, composites, sealed records |
| G6 Integration Surface | RO/05 — events, RSM mirroring, observability emission, persistence wiring, law enforcement |

**Implementation sequencing.** Five phases mirroring G1→G6 (G3+G4 together as
one phase — they share the preparation determinism tuple), strictly linear,
each phase's tests green before the next; engines = injected test doubles
producing SCRIPTED nondeterminism (the double is deterministic; the
architecture treats its output as data — exactly how replay works);
Storage/Communication/Verification = doubles until real (established repo
practice).

**Testing philosophy.** Golden-artifact style (CP/04 precedent) — committed
expected Reasoning Requests/Resolutions/records for fixture inputs,
byte-equality asserted; determinism rate = gate (100%), not metric; every
RO-* invariant list = review gate +, where scannable, a law-enforcer-style
static check; replay tests: full governance-side replay from sealed records
must reproduce every decision byte-identically with zero live reads.

**Verification philosophy (of the implementation).** Behavior verified
against RO/01-05 invariant lists ONLY (RO-I/C/D/P/E + RO-S from this doc);
phase docs' prose = rationale, invariants = law (mirrors kernel process
mandate).

**Completion criterion.** An implementation model can build from
RO/ARCHITECTURE.md + the six docs with zero further architectural decisions;
anything discovered to need one = errata first, code second.

---

## 11. Final Subsystem Invariants (RO-S)

| ID | Invariant |
|---|---|
| RO-S1 | RO's architecture is complete in RO/00-05; behavior not derivable from these documents does not exist; extensions = errata |
| RO-S2 | The event set (§2) is closed; `reasoning.*` names are RO's alone; no other component publishes them |
| RO-S3 | All determinism-tuple coordinates (descriptor-space versions, schema versions, priors versions, policy versions, decision/outcome records) are durable via Storage — a replay coordinate that can vanish is a defect |
| RO-S4 | RSM mirroring is telemetry-only; nothing RO does is ever gated on RSM state |
| RO-S5 | Verification consumes sealed records only; no path from a verification verdict back into a sealed attempt exists |
| RO-S6 | Experience influence enters ONLY as versioned priors; decisions replay against recorded priors versions forever |
| RO-S7 | Metrics are defined by RO, computed by Observability, and never feed back as live inputs to any RO decision (metrics-as-control would be an unversioned input, violating RO-D2) |
| RO-S8 | Zero seams: RO×UMS, RO×PRT — permanent (RO-I5, RO-I9); any future design proposing one is a violation, not an integration |
| RO-S9 | Every "Prompt Compiler" reference repo-wide resolves to RO's request-preparation boundary; no separate prompt-compilation component may ever be created (RO-I8) |
| RO-S10 | The implementation is verified against invariant lists (RO-I/C/D/P/E/S), not phase-doc prose |

---

## 12. Completion Summary

The six RO documents compose a single arc. RO/00 fixes identity and
boundaries — what RO governs and what it never touches. RO/01 fixes the
language of reasoning itself: the two-condition test, the Information
Boundary, capabilities as OS-owned, vendor-blind classes. RO/02 is the gate —
the single deterministic question of whether a demand's reasoning need is
real, resolved into five closed outcomes where "no" is the healthy case.
RO/03 is the artifact — how an approved demand becomes a provider-independent
Reasoning Request plus a separately-recorded Provider Resolution, minimally
sized, budgeted, constrained, and schema-bound. RO/04 is the crossing — the
one governed quarantine transition, its closed four recoveries, its retry and
failure taxonomy, its sealed outcome record. RO/05, this document, is the
weave — how RO's events, records, and priors interlock with every neighboring
subsystem without ever growing a second seam.

Nothing here decides a new question; every decision was already made in
RO/00-04. What closes is the surface: a closed event set, a closed
integration table, a closed invariant list, and a repository-wide erratum
that finally retires the "future Prompt Compiler Execution Service" in favor
of the boundary that actually absorbed it.

The philosophy that started this subsystem closes it too: the OS reasons
less every month, and can prove it — every crossing justified, budgeted,
measured, sealed; determinism everywhere except one governed door.
