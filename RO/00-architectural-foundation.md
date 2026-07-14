# Reasoning Orchestrator (RO) — Phase 0: Architectural Foundation

Status: authoritative foundation for all RO design phases. Architecture only — no
algorithms, no interfaces, no modules, no event names. Later RO phases refine
within these boundaries; contradictions of this document require errata here, not
silent divergence.

---

## 1. Mission

The Reasoning Orchestrator governs reasoning as a scarce, metered computational
resource. It decides **whether** reasoning is required, **which** reasoning
capability the demand needs, **which** provider supplies it, **how much** context
and token budget the invocation may consume, **what** constraints and expected
output contract govern it, and **how** the invocation is measured. It never
reasons. Every unit of nondeterministic computation in the operating system
passes through RO's gate or does not happen.

**Flow reconciliation.** The linear pipeline (Kernel → … → Plugin Runtime → RO →
Reasoning Engines → Verification → Experience) is the conceptual question order,
not topology. ARCHITECTURE.md's hub/event topology stays authoritative, as ruled
for CP/00 §1 and WS/00.

---

## 2. Philosophy

| Tenet | Meaning |
|---|---|
| Deterministic-first | The OS exhausts deterministic execution before RO permits reasoning. RO's first answer to any demand is "can this be answered without an engine?" — and "yes" is the success case. |
| Reasoning is scarce | Invocation frequency, context size, and token spend are costs to be driven down, never conveniences. A cheaper sufficient answer always wins. |
| Declining asymptote | As Experience accumulates, reasoning frequency trends toward zero for recurring demand shapes. A healthy system reasons less this month than last. |
| Escalation, not default | Reasoning capability classes form a cost ladder; RO starts at the cheapest sufficient rung and escalates only on demonstrated insufficiency, never preemptively. |
| Prompt-independence | A prompt is one possible materialization of a prepared reasoning request. The architecture holds unchanged for engines that consume structured artifacts, programs, or modalities that do not exist yet. Nothing in RO's design may assume prompt-based interaction. |
| Orchestration is deterministic | Everything RO decides — necessity, selection, sizing, budgeting, preparation, retry — is a deterministic function of declared inputs. Nondeterminism exists only inside the engine call itself (CP/03 §9 quarantine, restated in §8). |

---

## 3. Architectural Position

RO sits fully downstream of all planning and compilation authority. By the time
a demand reaches RO, intent has been interpreted (CP), the plan sealed (CP/02),
the workflow compiled (WS/01), and deterministic fulfillment attempted or ruled
out. RO is the **gatekeeper of the nondeterminism quarantine**: deterministic
territory on one side, reasoning engines on the other, and RO the only door.

| Relative to | RO is |
|---|---|
| Kernel, CP, WS, PRT | Strictly downstream — receives sealed artifacts, influences none of them live |
| CM | A consumer of Request Memory — never an assembler, never a retriever |
| Reasoning Engines | The sole invoker and sole authority over their use |
| Verification | Strictly upstream — RO's outputs are verifiable objects like any other |
| Experience/Learning | A telemetry producer and a versioned-priors consumer, nothing more |

---

## 4. System Boundaries

**Inputs (all sealed, versioned, declared):**

| Input | Origin |
|---|---|
| Reasoning demand (a workflow unit or system need that deterministic execution cannot satisfy) | Downstream execution flow |
| Request Memory (ranked, deduped, budget-fitted context) | Context Manager — sole source of context, ever |
| Reasoning provider descriptors (declared capabilities, cost/latency/determinism attributes) | RO's own descriptor space (§10, PRT-S9) |
| Budgets and governance policy as data | Config (Storage-sourced) |
| Priors (historical reasoning effectiveness) | Learning, as a versioned declared artifact |

**Outputs:**

| Output | Nature |
|---|---|
| Necessity decision | Deterministic, recorded — including the "no reasoning needed" outcome, which is itself a first-class result |
| Prepared reasoning request artifact | Immutable; carries selected context subset, constraints, output contract, budget, and its own decision coordinates |
| Governed invocation | The one bridge across the quarantine |
| Reasoning outcome record | Raw engine output + metadata + measurements, handed downstream (Verification, Experience) unjudged |

**Never crosses the boundary:** raw user intent (CP is intent's sole interpreter,
CP/03 §8); provider identity flowing upstream into plans or prompts of any other
component; live signals from reasoning outcomes back into any in-flight plan
(CP/03 §9 — influence travels only through the Experience → priors loop).

---

## 5. Responsibilities

| # | Responsibility | Boundary note |
|---|---|---|
| 1 | Reasoning governance | Policy-as-data: when reasoning is permitted at all, under what ceilings |
| 2 | Necessity decision | Deterministic; "no" is success; every "yes" carries a recorded justification |
| 3 | Capability-class selection | Which *kind* of reasoning the demand needs — never which vendor |
| 4 | Provider selection | Deterministic resolution over declared descriptors; vendor-blind by construction |
| 5 | Context sizing | Selecting the minimal sufficient **subset of Request Memory** — never assembling, retrieving, or augmenting context |
| 6 | Token budgeting | Hard ceilings allocated per invocation from governed budgets; ceilings, not quotas |
| 7 | Request preparation | Transforming demand + context subset + constraints into the form a provider consumes. **Binding ruling: RO absorbs prompt compilation.** Prompt compilation is one possible materialization inside this responsibility; the "future Prompt Compiler Execution Service" (ARCHITECTURE.md non-duplication list, CM Phase-0 ruling) is superseded — hub-doc errata land in RO's final phase. All constraints previously attached to the Prompt Compiler line (never sees raw intent; provider identity never enters a prepared request) transfer intact to this boundary. |
| 8 | Output contract preparation | Declaring the expected shape/schema of the engine's answer before invocation |
| 9 | Retry policy | Deterministic policy-as-data: what counts as engine failure, how many attempts, when to escalate the capability ladder, when to fail loud |
| 10 | Multi-engine coordination | Governing composite invocations (ensembles, decomposed sub-questions) as one metered decision |
| 11 | Reasoning metadata + metrics | Every invocation stamped, measured (tokens, latency, cost, outcome class), and emitted as telemetry |

---

## 6. Non-Responsibilities

| Never RO's | Owner |
|---|---|
| Performing reasoning | Reasoning Engines |
| Repository understanding, retrieval, similarity | UMS (Law 2) |
| Context assembly / Request Memory construction | Context Manager (Law: one assembler) |
| Intent interpretation, planning, capability semantics | CP |
| Scheduling, ordering, dispatch | WS |
| Provider registry, tool binding, plugin health | PRT (tool providers; reasoning providers are RO's own space, §10) |
| Process spawning, sandboxing | Execution (Law 3) |
| Judging outcome correctness | Verification (RO records outcomes; it never grades them) |
| Distilling lessons/priors from outcomes | Learning |
| Durable writes | Storage |
| Kernel lifecycle, user interaction | Kernel / Frontend |

---

## 7. Design Goals

1. **Orchestration determinism** — identical declared inputs produce identical decisions and identical prepared request artifacts, byte-for-byte.
2. **Vendor independence** — no artifact, policy, or decision references a vendor or model name; providers are interchangeable rows of descriptor data.
3. **Minimization** — downward pressure, by construction, on reasoning frequency, context size, request size, token usage, latency, and cost — with correctness never traded away.
4. **Auditability** — every invocation (and every declined invocation) reconstructible from recorded artifacts alone.
5. **Measurability** — reasoning spend is first-class telemetry with one schema, feeding both Observability and Learning.
6. **Extensibility without redesign** — new capability classes, providers, engine modalities, and coordination patterns arrive as data and bounded extensions, never as architectural change.

---

## 8. Core Principles

1. **Scarcity principle.** Reasoning is the most expensive operation in the OS; every invocation must be cheaper than not having it.
2. **Capability-not-vendor.** RO depends on declared reasoning capabilities (analysis depth, synthesis, structured-output fidelity, context tolerance, cost class) exactly as CP depends on execution capabilities — abstract, verifiable, provider-blind. Selection is mechanical resolution over descriptors, never judgment about brands.
3. **Total quarantine.** Deterministic before the call, deterministic after the call, nondeterministic only inside it. The engine's answer is data to be verified, never authority. No reasoning outcome touches an in-flight plan; influence on the future flows only through Experience → priors (CP/03 §9).
4. **Justified invocation.** No engine call without a recorded necessity decision citing why deterministic execution was insufficient. Unjustified reasoning is a structural violation, not a style issue.
5. **Escalation ladder.** Cheapest sufficient capability first; escalation is a recorded decision triggered by demonstrated insufficiency, subject to the same budgets.
6. **Sealed consumption.** RO consumes only sealed, versioned artifacts (demand, Request Memory, descriptors, priors, config) and re-queries no live world during a decision — the same replay discipline as PRT binding (PRT/05 §7) and CP determinism tuples (CP/04 §1). The concrete RO decision tuple is a later-phase design item; the discipline is fixed now.
7. **Fail loud.** No sufficient capability within budget, provider refusal, contract-violating output past retry policy — all surface as explicit recorded failures. RO never silently substitutes, pads budgets, or degrades constraints.

---

## 9. Architectural Constraints

| Constraint | Consequence |
|---|---|
| No model/vendor assumption | Nothing may encode Claude/GPT/Gemini/Qwen or any provider's behavior; descriptors carry all differentiation as data |
| No prompt-format assumption | Request preparation targets an abstract provider-consumable form; prompt text is one renderer among possible renderers |
| Implementation/language independence | This document and all RO phase docs describe behavior and boundaries only |
| Deterministic whenever possible | Only the engine call is exempt; a nondeterministic orchestration decision is a defect |
| Observable + measurable | Every decision and invocation emits telemetry in Observability's one schema |
| Auditable + replayable | Decisions replay from recorded coordinates without re-querying anything live |
| Budget ceilings are hard | Exhaustion is a loud governed outcome, never an overdraft |
| Plugin independence | RO neither loads nor executes plugins; deterministic fulfillment attempts happen before demands reach RO |

---

## 10. Interaction with Other Subsystems

| Subsystem | Direction | What crosses | What NEVER crosses |
|---|---|---|---|
| Kernel | — | Nothing direct beyond shared bus + config discipline | Kernel never gates on reasoning specifics |
| CP | upstream only | Sealed plans reach RO's territory via WS/Execution artifacts | CP never names reasoning methods in plans (CP/03 §9); RO never sees raw intent (CP/03 §8) |
| WS / Execution | demand → RO | Reasoning demand from workflow units whose fulfillment requires reasoning | RO never schedules, reorders, or spawns |
| PRT | — | **Nothing — zero seam (PRT-S9).** Reasoning providers are NOT PRT registry entries; RO owns its own reasoning-provider descriptor space, governed by admission/versioning discipline *analogous* to PRT's but architecturally separate. PRT/05's "Prompt Compiler" row now maps to RO's request-preparation boundary; its constraint (provider identity never crosses that line) holds identically | Tool-provider identity into reasoning requests; reasoning influence into binding |
| CM | CM → RO | Request Memory, consumed as sealed input | RO never assembles context, never queries UMS, never adds to RQM (Law 2, CM-I) |
| Reasoning Engines | RO → engines | Prepared request artifacts; RO is sole invoker | Direct engine access by any other component |
| Verification | RO → downstream | Reasoning outcome records as verifiable objects | RO never grades outcomes; Verification never edits RO artifacts |
| Learning / Experience | bidirectional, versioned | Out: invocation records, necessity decisions, effectiveness signals. In: priors as one versioned declared artifact | Live prior injection mid-decision; RO mining episodic history itself |
| RSM / Observability | RO → | Telemetry mirror of all decisions and spend | Telemetry as a control edge back (RSM-I15) |
| Storage | RO → | Durable persistence of request/outcome artifacts — extent is a later-phase decision; single-writer law holds regardless | Any RO-local durable write path |

---

## 11. Success Criteria

1. Reasoning-invocation rate for recurring demand shapes declines over system lifetime (measured, not asserted).
2. 100% of invocations carry a recorded justification, budget, and measurement; 0% escape the quarantine gate.
3. Zero vendor or model references in any RO artifact, policy, or decision record.
4. Orchestration decisions replay byte-identically from recorded coordinates.
5. A new reasoning provider — or a new engine modality with no prompt concept — onboards as descriptor data plus a bounded renderer, with zero redesign.
6. Reasoning spend (tokens, cost, latency) is fully attributable per request, per capability class, per provider.

---

## 12. High-Level Reasoning Lifecycle

Conceptual stages only; states, events, and mechanics are later-phase design.

| Stage | Question answered |
|---|---|
| Demand arrival | What could not be done deterministically? |
| Necessity decision | Is reasoning actually required — or is a deterministic/cached/prior answer sufficient? ("No" terminates the lifecycle successfully) |
| Capability selection | What class of reasoning does this demand need, at the cheapest sufficient rung? |
| Provider selection | Which descriptor row deterministically satisfies that class within budget? |
| Preparation | What minimal context subset, constraints, output contract, and budget define the request artifact? |
| Governed invocation | The single quarantine crossing, metered and stamped |
| Outcome capture | Record output + measurements verbatim; no judgment |
| Feedback emission | Telemetry to Observability; effectiveness material toward Learning's future priors |

Retry/escalation loops within these stages are policy-governed and recorded;
they never bypass a stage.

---

## 13. Long-Term Evolution Goals

| Goal | Mechanism |
|---|---|
| Reasoning frequency → 0 asymptote | Priors and accumulated deterministic capability answer recurring shapes before the necessity gate says yes |
| Non-prompt engine modalities | Prompt-independence (§2) means new modalities are new renderers + descriptor rows, not redesign |
| Multi-engine ensembles | Coordination (§5.10) generalizes as governed composition — an extension, never a rewrite |
| Richer capability taxonomy | New classes/facets arrive as descriptor data, mirroring CP/01's rows-not-branches evolution |
| Cheaper-first economics | The escalation ladder absorbs future cheap engines automatically — they slot in as lower rungs |

Evolution test (CP/04 precedent): if a future development requires RO to answer a
question outside "should we reason, with what, at what cost, prepared how,
measured how" — that is a new component, not an RO extension.

---

## 14. Glossary

| Term | Definition |
|---|---|
| Reasoning demand | A sealed statement of need that deterministic execution could not satisfy; RO's unit of work |
| Necessity decision | RO's recorded deterministic verdict on whether a demand requires an engine at all |
| Reasoning capability | An abstract, provider-blind class of reasoning ability with declared attributes. **Distinct from a CP/01 capability** (a verifiable contract of *execution* ability in PRT's registry); the two vocabularies never mix |
| Reasoning provider | An interchangeable supplier of one or more reasoning capabilities, described entirely by descriptor data in RO's own space |
| Reasoning engine | The running provider instance that performs the nondeterministic computation |
| Provider descriptor | The declared data row (capabilities, cost class, latency class, context tolerance, determinism attributes) selection resolves over |
| Prepared reasoning request | The immutable artifact crossing the quarantine: context subset, constraints, output contract, budget, decision coordinates |
| Materialization / renderer | The transformation of a prepared request into a specific provider-consumable form; a prompt is one renderer |
| Escalation | The recorded move to a costlier capability rung after demonstrated insufficiency |
| Budget | A hard token/cost ceiling attached to an invocation; exhaustion is a loud outcome |
| Quarantine | The system-wide containment of nondeterminism inside engine calls (CP/03 §9); RO is its only gate |
| Outcome record | Verbatim engine output plus measurements, handed downstream unjudged |

---

## 15. Foundation Invariants (RO-I)

1. **RO-I1** — RO never performs reasoning; it governs it. No inference, judgment, or generation happens inside RO.
2. **RO-I2** — Every reasoning invocation in the OS passes through RO's necessity gate; there is no second door into the quarantine.
3. **RO-I3** — Every orchestration decision is a deterministic function of sealed, versioned, declared inputs; nondeterminism exists only inside the engine call.
4. **RO-I4** — No RO artifact, policy, or decision names or assumes a vendor or model; providers are descriptor data only.
5. **RO-I5** — RO consumes Request Memory as sealed input and never assembles, retrieves, augments, or re-ranks context (Law 2 preserved).
6. **RO-I6** — RO never sees raw user intent; demands arrive plan-mediated (CP/03 §8).
7. **RO-I7** — No reasoning outcome influences an in-flight plan or any live decision elsewhere; influence flows solely via Experience → versioned priors (CP/03 §9).
8. **RO-I8** — Prompt compilation, where it exists at all, exists only inside RO's request-preparation boundary; nothing else in the OS compiles prompts, and nothing in RO requires prompts to exist.
9. **RO-I9** — Reasoning providers are not PRT registry entries; RO's descriptor space and PRT's registry are disjoint authorities (PRT-S9 preserved).
10. **RO-I10** — Budgets are hard ceilings; every invocation and every declined invocation is measured, stamped, and auditable from artifacts alone.

---

## 16. Phase Outline

| Phase | Scope (content set by future prompts) |
|---|---|
| 1 | Reasoning capability model + provider descriptor space |
| 2 | Necessity decision + governance model (the gate) |
| 3 | Request preparation + budgeting + output contracts |
| 4 | Invocation lifecycle, retry/escalation, multi-engine coordination, metrics |
| 5 | System integration, event canon, hub-doc errata (Prompt Compiler supersession lands here) |
