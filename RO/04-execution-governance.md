# Reasoning Orchestrator (RO) — Phase 4: Execution Governance

Status: authoritative; begins when a (Reasoning Request, Provider Resolution)
pair exists (RO/03 §2). Ends the instant a sealed outcome record exists —
verification, metrics, events, Experience feedback, errata are RO/05's and
other components' territory. RO still performs no reasoning. Architecture
only — no code, no pseudocode, no APIs, no algorithms, no state machines, no
event names, no metrics design, no verification design, no vendor/model
names (forbidden throughout; this sentence names none, in compliance with
that rule).

---

## 1. Reasoning Invocation

The **invocation** is the single architectural transition from deterministic
governance into nondeterministic execution — the quarantine crossing (RO/00
§8.3). It is performed at most once per attempt, and entered only via a
(Request, Resolution) pair (RO-P1..P3).

**Invocation Authority Ruling.** RO is the sole INVOCATION AUTHORITY — no
other component may cause a reasoning engine to run (RO/00 §10, RO-I2). Law 3
(Execution = sole process spawner) is untouched by this: where an engine's
physical realization requires an OS process (a local engine), Execution
enacts the spawn; where it is a remote interaction, the transport is
Communication-shaped territory. RO decides and governs; physical realization
is enacted by the components that own those mechanics — the
DECIDE-LEGALIZE-ENACT pattern (PRT/05 §5) applied to invocation. RO never
spawns, never transports; equally, Execution and Communication never decide
that reasoning happens.

**Boundary mechanics (conceptual).**

| Moment | What happens |
|---|---|
| Control transfer | The RENDERED request (RO/03 §11) crosses the boundary with its budget, timeout class, and constraints attached |
| Inside quarantine | The OS holds no assumptions about what the engine does |
| Control recovery | The boundary returns exactly one of: an output, a failure class (§5), or an expiry/cancellation (§6-§7) — there is no fourth return |

Everything before the crossing and after the recovery is deterministic
territory.

---

## 2. Execution Lifecycle

Conceptual phases only — not a state machine, not an event canon.

| Phase | Content |
|---|---|
| Prepared | (Request, Resolution) pair exists (RO/03) |
| Initiated | Governance checks sealed: budget attached, constraints present, resolution valid at its recorded coordinates |
| Executing | Inside the quarantine; the only nondeterministic span in the OS |
| Recovery | Exactly one of: Returned \| Failed(class) \| Expired \| Cancelled(origin) |
| Outcome Sealed | Immutable outcome record produced, including §9 metadata |
| Handoff | To Verification and downstream; RO/04 ends here |

Rules:

- These phases are conceptual vocabulary feeding RO/05's later event canon —
  not a state machine.
- A request never re-enters Executing without a new governed attempt (§4).
- Sealing is unconditional: every attempt, however it ended, produces a
  sealed outcome record. Nothing vanishes.
- The sealed record is the only thing downstream ever sees. Verification
  judges output via the record, never talks to engines.

---

## 3. Provider Interaction

| Aspect | Ruling |
|---|---|
| Provider responsibilities | Accept a rendered request, produce output within declared classes (capacity, latency, determinism — its own descriptor row's claims); nothing else. No callbacks into the OS, no retrieval, no follow-up questions (self-containment, RO/03 §1). A provider needing more than the request is a failure class, not a dialogue. |
| Provider isolation | One invocation sees one request; no provider observes other invocations, other requests' context, or OS state. Provider-side memory/session state must never be load-bearing — a provider that only works statefully violates its descriptor claim; the OS assumes nothing survives between invocations. |
| Provider replacement | Mid-lifecycle replacement never happens silently: a failed attempt against provider A followed by an attempt against provider B is a new resolution (recorded re-preparation of the Resolution, same Request, per §4 retry-with-substitution), never an in-flight swap. |
| Provider transparency | Downstream consumers of outcomes never learn provider identity from the output path; identity lives in the Resolution + metadata, for audit only (extends RO-P2, PRT/05 identity discipline). |
| Provider independence | Nothing in execution governance depends on any provider's behavior beyond its declared descriptor classes; misbehavior is evidence against the declaration, handled as a failure class, never as special-case logic. |

---

## 4. Retry Philosophy

**The key distinction.** RO/02 forbids hope-retry at the decision gate
because the gate is deterministic — identical inputs, identical outcome,
retry pointless. The engine is the one component where retry is
conceptually valid, precisely because it is the one nondeterministic element
(RO/00 §8.3): an identical rendered request may legitimately yield a
different, possibly conforming, output. Retrying an engine is not repeating
identical work; retrying the gate is.

| Ruling | Statement |
|---|---|
| Retry | A new governed attempt of the same (Request, Resolution) pair; attempt index recorded; the Request never changes across retries — a changed request is new preparation, not a retry |
| Retry-with-substitution | Same Request, new Resolution (next eligible provider per RO/03 §5 order); valid when the failure class indicts the provider, not the request |
| Escalation ≠ retry | Escalation (capability rung up, RO/00 §8.5) is a new preparation cycle through RO/03 within the parent budget envelope (RO-P7); retries never escalate implicitly |
| Bounded always | Attempt ceilings are policy-as-data; every attempt draws from the same budget envelope (RO-P7 — retries are never fresh budget); an envelope exhausted by retries is exhausted (§5, F3) |
| Structural loop safety | Infinite loops are structurally impossible: bounded attempts × bounded envelope × recorded attempt index — governance prevents loops by construction, not by vigilance |
| Policy scope | Which failure classes are retryable vs terminal is policy-as-data over the §5 taxonomy, not architecture |

---

## 5. Failure Philosophy

Failure class taxonomy is closed at this level; sub-classes are data.

| Class | Meaning | Architectural response |
|---|---|---|
| F1 Provider unavailable | Engine unreachable/refuses connection | Indicts the provider: retry-with-substitution valid; evidence recorded against descriptor reliability (consumed by Learning later — no design here) |
| F2 Provider refusal | Engine declines the request (its own policy/safety) | Recorded verbatim; may be retryable-with-substitution; never silently rewritten to make the request acceptable (governance-lossless discipline, RO-P10 — constraint relaxation forbidden per RO-D10 lineage) |
| F3 Budget exhaustion | Envelope consumed mid-execution or by retries | Loud governed terminal outcome (RO-I10); never overdraft, never a plea for more — a fresh envelope requires a fresh governed decision upstream |
| F4 Request invalid | Provider rejects the rendered form as malformed | Indicts the renderer, not the demand: a renderer defect (RO-P10), surfaced as a preparation-defect failure, never patched inline |
| F5 Execution failure | Transport/process death mid-flight (Execution/Communication mechanics surface it) | Retryable per policy |
| F6 Policy refusal | A governance check at initiation fails (stale resolution coordinates, constraint set invalid) | Terminal for this pair, routes back to preparation |
| F7 Timeout | See §6 | Retryable per policy |
| F8 Contract-nonconforming output | Output fails mechanical conformance against the request's named schema version (unparseable, wrong shape) | Execution governance, not Verification — a nonconforming return is a failed attempt, retryable |

**F8 ruling — the mechanical/semantic line.** Parse-level conformance is
execution governance. Semantic judgment of a conforming output is
Verification's, absolutely never RO's (RO/00 §6). RO checks that the output
IS a well-formed answer-shaped object; whether it is a GOOD answer is
downstream.

Every failure is recorded with class + attempt index + coordinates. Failures
are evidence, never exceptions-in-the-dark. No failure class ever triggers
silent substitution, constraint relaxation, or unrecorded termination
(RO-D10 extended to execution).

---

## 6. Timeout Philosophy

**Ownership ruling.** This resolves a canon tension with ARCHITECTURE.md's
"process sandbox/timeout/retry state = Execution." RO owns reasoning-level
TIME POLICY — the timeout class attached to each invocation, derived from
policy-as-data + the workflow's sealed latency constraints (RO/03 §5) + the
capability's complexity rung (deeper reasoning legitimately gets a longer
class). Execution owns process-level ENFORCEMENT mechanics for local
engines; transport-level expiry for remote ones sits with the transport
machinery. Declare-vs-enforce split, same shape as PRT/00 C5 (policy = data
PRT declares, Execution enforces).

| Rule | Statement |
|---|---|
| No unbounded crossing | Every invocation carries a timeout class before crossing, without exception |
| Expiry = F7 | A first-class recovery (one of §1's closed returns), not an error-in-the-dark |
| Governance-side determinism | Expiry behavior is deterministic on the governance side — the same expiry produces the same recorded outcome and the same policy consequence, even though WHEN an engine would have answered is unknowable |
| Partial output at expiry | Recorded in metadata but is NOT an output — an expired attempt never half-succeeds |

---

## 7. Cancellation

**Origins.**

| Origin | Trigger |
|---|---|
| User | Via Kernel/Frontend authority chain |
| Kernel | System authority: shutdown, resource protection |
| Policy | Governance change invalidating in-flight work |
| Workflow | Supersession — the demand's plan was replaced (plan.revised lineage) |

RO originates none of these; RO enacts cancellation as a governed lifecycle
act (mirrors PRT-A4 enact-only discipline).

| Rule | Statement |
|---|---|
| Recorded signal | Cancellation is a recorded input signal (an artifact with origin + coordinates), so replay includes it — determinism preserved because the cancellation is data, not chance |
| Sealed like any other | Cancelled attempt → Cancelled recovery → sealed outcome record like any other; nothing vanishes |
| Budget reconciliation | Budget consumed-so-far is reconciled; remainder returns to the envelope's governing scope |
| Never retroactive | A returned output that arrived before the cancellation landed is a Returned outcome — the race is resolved by which artifact sealed first, and the resolution is recorded |
| No partial adoption | A cancelled attempt's partial output is metadata, never consumed downstream |

---

## 8. Multi-Provider Coordination

Composite reasoning is governed composition of single invocations — every
constituent is its own (Request, Resolution) pair with its own attempt
lifecycle. There is no special multi-provider invocation primitive.

**Pattern vocabulary** (patterns are data/policy, extensible without
redesign — RO/00 §13):

| Pattern | Shape |
|---|---|
| Sequential | Output-shaped artifacts of one constituent feed the PREPARATION of the next (through RO/03 machinery: each step's context is still RQM + prior sealed outputs as declared inputs — no live engine-to-engine channel) |
| Parallel | Independent constituents, no ordering; concurrency is derived, never required |
| Ensemble | Same demand, multiple providers; aggregation of outputs must be deterministic — a declared aggregation rule fixed at composition time (majority-of-conforming, first-conforming-by-stable-order, or similar declared forms); choosing/aggregating never spends reasoning unless that aggregation is itself a governed approved demand through the full RO/02 gate |
| Specialist pipeline | Sequential with per-step capability specialization (RO/01 §7 composition relation made operational) |
| Review chain | A constituent whose demand is evaluation of a prior constituent's sealed output (evaluation = ANALYTIC capability, RO/01 §4); still not Verification — Verification's judgment remains downstream and unskippable |
| Debate | Adversarial ensemble variant; same rules, nothing special |

**Iron rules:**

- One composite = one parent budget envelope; constituents draw from it
  (RO-P7).
- Every constituent output is sealed individually (auditability per RO/03
  G6).
- Composite failure semantics are declared at composition time — which
  constituent failures fail the composite is declared data, not
  improvisation.
- Engine-to-engine communication outside sealed artifacts never exists;
  providers never talk to each other, they only ever see rendered requests
  (isolation, §3).
- A review chain never substitutes for Verification.

---

## 9. Execution Metadata

No concrete schemas. The sealed outcome record carries:

| Element | Purpose |
|---|---|
| (Request, Resolution) references + preparation coordinates | Replay anchor |
| Attempt index + attempt history refs | Retry audit |
| Recovery kind + failure class where applicable | Taxonomy (§5) |
| Timing observations as recorded facts | Consumed later by metrics — no metric design here |
| Budget consumption + reconciliation | RO/03 §8 lifecycle |
| Cancellation origin where applicable | §7 |
| Provider-identity reference | Audit only, never downstream consumption (§3 transparency) |
| Verbatim output or its absence | Unjudged (RO/00 §4) |

**Ownership.** RO owns the record shape — OS-owned, versioned,
provider-independent, same discipline as RO/03 §10 schemas.

**Purpose.** Audit (reconstruct every attempt from artifacts alone); replay
(deterministic governance side replays; the engine's answer is data replay
reads back, never re-generates — mirrors PRT contract replay); downstream
fuel (Verification consumes the record now; Experience consumes it via
RO/05's integration — named, not designed here).

---

## 10. Architectural Guarantees

| ID | Guarantee | Why |
|---|---|---|
| G1 | Controlled nondeterminism | Nondeterminism exists only inside the Executing span; every boundary in/out is deterministic and recorded |
| G2 | Bounded execution | No crossing without budget + timeout class + attempt ceiling attached; unbounded reasoning is structurally impossible |
| G3 | Provider transparency | Outcomes are consumable without knowing who produced them; audit knows, consumers don't |
| G4 | Reproducibility | The governance side replays byte-identically from sealed records; the nondeterministic answer is replayed as recorded data |
| G5 | Total auditability | Every attempt, retry, substitution, expiry, cancellation, and failure reconstructs from artifacts alone |
| G6 | Graceful failure | Every failure class has a declared, recorded, loud response; no dark corners |
| G7 | Extensibility | New failure sub-classes, coordination patterns, timeout classes, retry policies arrive as data; the taxonomy shape and lifecycle vocabulary never change |

---

## 11. Invariants (RO-E)

| ID | Invariant |
|---|---|
| RO-E1 | RO is sole invocation authority; Execution/Communication enact physical realization but never decide reasoning occurs; RO never spawns or transports (Law 3 preserved) |
| RO-E2 | Every crossing enters via a (Request, Resolution) pair and carries budget, timeout class, and constraints; no unbounded or unconstrained crossing exists |
| RO-E3 | The boundary returns exactly one of: output, failure class, expiry, cancellation — closed set, extension requires errata |
| RO-E4 | Every attempt seals an immutable outcome record, regardless of how it ended; downstream consumes only sealed records, never engines |
| RO-E5 | Retry is valid only against the engine (the nondeterministic element) — never against the deterministic gate; a retry never mutates the Request |
| RO-E6 | Retries and escalations draw from the parent budget envelope; attempt ceilings are policy-as-data; unbounded retry is structurally impossible |
| RO-E7 | The failure taxonomy F1-F8 is closed at class level; sub-classes are data; every failure is recorded with class, attempt index, and coordinates |
| RO-E8 | Mechanical schema conformance is execution governance; semantic judgment is Verification's — RO never judges answer quality |
| RO-E9 | Timeout policy is RO's (declared data); enforcement mechanics belong to Execution/transport; every expiry is a first-class recorded recovery |
| RO-E10 | Cancellation is an enacted, recorded input signal with a named origin; RO originates none; races resolve by seal order, recorded |
| RO-E11 | Composite reasoning is governed composition of individually-sealed single invocations under one parent envelope; providers never communicate outside sealed artifacts; deterministic aggregation only, unless aggregation itself passes the full RO/02 gate |
| RO-E12 | Outcome records are OS-owned, versioned, provider-independent; provider identity in records serves audit only |

---

## 12. Glossary

Extends RO/00-03 glossaries; never redefines.

| Term | Definition |
|---|---|
| Invocation | The single quarantine crossing per attempt (§1) |
| Quarantine crossing | The transition from deterministic governance into nondeterministic execution (RO/00 §8.3) |
| Control transfer | Handing the rendered request across the boundary with budget, timeout class, constraints attached |
| Control recovery | The boundary's return of exactly one of the closed four (§1) |
| Attempt | One governed pass through Initiated → Executing → recovery for a (Request, Resolution) pair |
| Attempt index | The recorded ordinal of an attempt within its retry sequence |
| Retry | A new governed attempt of the same (Request, Resolution) pair (§4) |
| Retry-with-substitution | Same Request, new Resolution, next eligible provider (§4) |
| Recovery | One of the closed four: Returned, Failed(class), Expired, Cancelled(origin) |
| Sealed outcome record | The immutable, unconditional record produced at Outcome Sealed (§2, §9) |
| Failure class | One of F1-F8 (§5) |
| Timeout class | The declared time-policy category attached to an invocation before crossing (§6) |
| Expiry | The F7 recovery when an invocation's timeout class elapses (§6) |
| Cancellation origin | One of user, kernel, policy, workflow (§7) |
| Composite reasoning | Governed composition of individually-sealed single invocations (§8) |
| Constituent | One single-invocation member of a composite (§8) |
| Aggregation rule | The declared deterministic form combining ensemble outputs (§8) |
| Review chain | A constituent whose demand evaluates a prior constituent's sealed output (§8) |
| Seal order | The recorded ordering by which competing outcomes (e.g. a race with cancellation) are resolved (§7) |

---

Forward pointer: RO/05 integrates the event canon, metrics/observability
surfaces, the Experience feedback loop, Verification handoff formalization,
and hub-document errata (including the RO/00 §5.7 Prompt Compiler
supersession).
