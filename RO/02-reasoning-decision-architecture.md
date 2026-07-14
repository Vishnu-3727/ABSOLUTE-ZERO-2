# Reasoning Orchestrator (RO) — Phase 2: Reasoning Decision Architecture

Status: authoritative; governs the single question "should reasoning occur?"
Everything downstream of a YES — provider selection, budgeting, request
preparation, invocation — is RO/03+ territory. Architecture only — no code,
no algorithms, no gate mechanics, no thresholds, no configuration values.

---

## 1. Reasoning Necessity

Reasoning is **necessary** for a demand iff all three hold:

| # | Condition | Source |
|---|---|---|
| n1 | The demand passes the two-condition test — underdetermination + generalization | RO/01 §1 |
| n2 | The demand sits above its Information Boundary — no union of declared inputs, recorded knowledge, or registered deterministic procedures determines a sufficient output | RO/01 §2 |
| n3 | Deterministic exhaustion — every applicable rung of the Deterministic Ladder (§5) has been exhausted or deterministically ruled inapplicable | §5 below |

**Necessity ≠ invocation.** Necessity is a fact about the demand; whether
reasoning *occurs* additionally requires governance permission (§4 —
GOVERNANCE-REFUSED exists precisely because a necessary demand can still be
refused). Necessity is established mechanically from sealed evidence, never
by asking an engine — the decision itself is deterministic territory (RO-I3).
The system never reasons about whether to reason.

---

## 2. Decision Principles

Immutable; govern every ruling in this document.

| ID | Principle | Statement |
|---|---|---|
| P1 | Deterministic-first | Deterministic mechanisms are always attempted or ruled out before reasoning is considered (RO/00 §2) |
| P2 | Last resort | Reasoning is the governed exception, never a default path; a demand reaches the decision only carrying evidence of deterministic insufficiency |
| P3 | "No" is success | REJECTED-because-deterministic-sufficient is the healthiest outcome (RO/00 §4) |
| P4 | Minimum sufficient reasoning | When approved, scope (§6) and capability rung (RO/01 §6 ladder) are the smallest that suffice |
| P5 | Cheapest sufficient solution | Among sufficient paths, cost class decides; never quality beyond sufficiency (RO/00 §8.5) |
| P6 | Monotonic reduction | Every approved invocation must generate Experience material so the same demand shape trends below the Information Boundary (RO/00 §2 declining asymptote, RO-C2); a decision architecture that doesn't shrink its own future demand is defective |
| P7 | Justified always | Approval and every non-approval outcome carry recorded justification citing the evidence (RO/00 §8.4, extended to all outcomes) |
| P8 | Deterministic governance | Identical sealed inputs produce identical outcomes, byte-replayable (RO-I3) |

---

## 3. Decision Inputs

### 3.1 Valid inputs (closed set)

| # | Input | Why valid |
|---|---|---|
| 1 | The demand artifact itself (plan-mediated, RO-I6) | The thing being decided |
| 2 | Sealed Request Memory (CM-assembled) | Read-only evidence for (n2); what the system already knows |
| 3 | Execution outcome records | Sealed facts about the past; proof that deterministic attempts failed or were insufficient — the evidence for (n3) |
| 4 | Workflow unit state (sealed, from WS artifacts) | Establishes what was already decided upstream |
| 5 | Demand's required reasoning capability + declared characteristics (RO/01 §5) | OS-owned data; feeds §6 scope and later-phase capability rung |
| 6 | Versioned priors (Learning) | Historical effectiveness of reasoning vs. deterministic paths for this demand shape; one declared versioned artifact (RO/00 §10), never live mining |
| 7 | Governance policy as data (config version) | Ceilings and permissions; Storage-sourced declared data |
| 8 | Budget availability as a governance fact (remaining ceiling exists, yes/no class) | Refusing an unaffordable invocation is governance; sizing one is preparation (RO/03+) |

### 3.2 Forbidden inputs

| Input | Why forbidden |
|---|---|
| Raw user intent | CP is intent's sole interpreter (RO-I6) |
| Reasoning provider/model identity, availability, or health | Provider space is invisible to the necessity question — whether never depends on who; a demand's necessity cannot change because a cheap engine showed up |
| Any engine consultation | No reasoning about reasoning (§1) |
| Wall-clock, randomness, arrival order | Forbidden variability, mirrors PRT/05 discipline |
| Outcomes of other in-flight reasoning | RO-I7 |
| Un-versioned live state of any kind | Violates sealed-consumption discipline (RO/00 §8.6) |
| Facet values | Never load-bearing (RO-C4) |

---

## 4. Decision Outcomes

Complete, mutually exclusive, closed set of five. No sixth outcome may be
added without errata to this document.

| # | Outcome | Meaning | Terminal? |
|---|---|---|---|
| 1 | REASONING-APPROVED | Necessity established and governance permits. Carries justification, the demand's required capability id, and scope (§6). Hands off to RO/03+ — nothing else about the invocation is decided here. | No — continues into RO/03+ |
| 2 | REASONING-REJECTED | Deterministic-sufficient: evidence shows a deterministic path determines a sufficient output. The success case (P3). | Yes — demand returns to deterministic territory |
| 3 | DETERMINISTIC-CONTINUATION-REQUIRED | (n3) not yet met — unexhausted ladder rungs remain. A redirect, not a rejection; names which territory remains untried conceptually, no gate design. | No — resumes ladder descent |
| 4 | INSUFFICIENT-INFORMATION | The decision itself is underdetermined — sealed inputs are incomplete or contradictory. Loud, recorded. Resolution: obtain additional sealed inputs through governed channels, then re-decide. | No — parked pending state |
| 5 | GOVERNANCE-REFUSED | Necessity established but policy or budget forbids. Loud governed failure (RO/00 §8.7), never silent degradation, never quiet downgrade of constraints. | Yes — surfaced as failure |

**"Defer" is not a sixth outcome.** Deferral is the recorded pending
consequence of INSUFFICIENT-INFORMATION, never a distinct verdict — no
third-outcome creep, mirrors CP/02 gate discipline.

Every outcome — all five — is recorded with justification and the
sealed-input coordinates it was decided from, auditable from artifacts alone
(RO-I10).

---

## 5. Escalation Philosophy — the Deterministic Ladder

Ordered conceptual progression; each rung is exhausted or deterministically
ruled inapplicable before the next is considered. Concept only — no gates, no
algorithms.

| Rung | Name | Territory |
|---|---|---|
| D1 | Recorded answer | Memory/prior already holds the output (retrieval, Law 2) |
| D2 | Registered deterministic procedure | A declared computation produces it |
| D3 | Plugin/tool execution | A registered provider contract covers it (PRT territory) |
| D4 | Algorithmic search | Declared space + declared evaluation — deterministic at any scale (RO/01 §1) |
| D5 | Deterministic composition | Governed combination of D1–D4 mechanisms |
| R | Reasoning | Only past D5, entering at the cheapest sufficient complexity rung (RO/01 §6, RO/00 §8.5) — the ladder continues *inside* reasoning as C0→C4 escalation |

**Properties:**

- Descent is evidence-producing — each failed rung becomes an execution
  outcome record feeding (n3).
- Ladder rungs are extensible as data — a new deterministic mechanism class
  is a new rung, no redesign (mirrors RO-C4 open-set discipline).
- The ladder is the structural embodiment of P1/P2.

---

## 6. Reasoning Granularity

Scope hierarchy, coarsest to finest: entire request > workflow segment >
single unresolved demand > sub-problem of a demand.

| Ruling | Statement |
|---|---|
| Decision unit | The single unresolved demand — never the entire request, never a workflow segment; those were already decomposed by CP/WS, and re-deciding them would re-interpret sealed artifacts |
| Cardinality | One demand = one decision = at most one approved scope |
| No re-decomposition | RO never re-decomposes upstream artifacts — CP owns decomposition, WS owns compilation |
| Narrowing | RO may narrow scope to a sub-problem only where the narrowing itself is deterministic; splitting via reasoning would spend reasoning to save reasoning (forbidden) — a genuinely reasoning-requiring split is its own demand through the same gate |
| Minimization | Among sufficient scopes, the smallest is approved (P4's scope dimension) |
| Composition | Composite demands (RO/01 §7 composition relation) decide each component demand separately — composition is descriptive, never a bulk-approval vehicle |

---

## 7. Failure Philosophy

What happens when reasoning is *not* invoked — every non-approval outcome
maps to a defined system behavior.

| Outcome | System behavior |
|---|---|
| REJECTED | Continue deterministic execution — normal, success |
| DETERMINISTIC-CONTINUATION-REQUIRED | Resume ladder descent; outcome records accumulate |
| INSUFFICIENT-INFORMATION | Request additional sealed inputs via governed channels; demand parked as recorded pending state — never spinning, never polling, never guessing |
| GOVERNANCE-REFUSED | Explicit recorded failure surfaced downstream — Verification/requestor see a loud, unfulfilled-demand fact; the demand fails honestly rather than degrading silently |

**Absolute prohibitions:**

- Silent substitution of a weaker deterministic answer presented as sufficient.
- Constraint relaxation to make a refusal disappear.
- Quiet retry loops that re-ask the gate hoping for drift — identical inputs
  give identical outcomes (P8), which makes hope-retry structurally pointless,
  intentionally.
- Termination without a recorded outcome.

Deterministic behavior is preserved in every non-approval path: the system
remains fully deterministic unless and until an approval crosses the
quarantine.

---

## 8. Architectural Guarantees

| ID | Guarantee | Why it matters |
|---|---|---|
| G1 | Decision consistency — identical sealed inputs → identical outcome | Governance that drifts is not governance |
| G2 | Total auditability — all five outcomes reconstructible from recorded artifacts alone | Reasoning spend must be attributable; rejections are as informative as approvals (P6's fuel) |
| G3 | Vendor independence — the whether-question is provider-blind by construction (§3 forbidden inputs) | Provider churn must never change how often the system reasons |
| G4 | Deterministic governance — the gate itself never reasons | A nondeterministic gate would move the quarantine boundary inside RO, violating RO-I2/I3 |
| G5 | Minimal reasoning — structural downward pressure via ladder + granularity + P4–P6 | Reasoning is the OS's scarcest resource (RO/00 §8.1) |
| G6 | Extensibility — new deterministic mechanisms, new capability rows, new policy arrive as data; the five outcomes and the decision shape never change | The architecture must survive engine generations |

---

## 9. Invariants (RO-D)

| ID | Invariant |
|---|---|
| RO-D1 | Necessity = (n1) + (n2) + (n3), all three, established mechanically from sealed evidence — never by engine consultation |
| RO-D2 | The decision consumes only the §3 closed valid-input set; every input sealed and versioned |
| RO-D3 | Provider/model identity, availability, or health never influences whether reasoning occurs |
| RO-D4 | Exactly five outcomes; mutually exclusive; extension requires errata to RO/02 |
| RO-D5 | Every outcome — including every non-approval — is recorded with justification and decided-from coordinates |
| RO-D6 | Identical sealed inputs produce identical outcomes, byte-replayable |
| RO-D7 | The deterministic ladder is descended (or rungs ruled inapplicable) before any approval; failed rungs leave recorded evidence |
| RO-D8 | The decision unit is the single unresolved demand; RO never re-decomposes upstream artifacts; scope narrowing must itself be deterministic |
| RO-D9 | Among sufficient scopes and capability rungs, the smallest/cheapest is approved |
| RO-D10 | No non-approval path ever silently substitutes, degrades, relaxes constraints, or terminates unrecorded |
| RO-D11 | Every approval must yield Experience material toward monotonic reduction (P6) |
| RO-D12 | Governance policy and budget facts enter only as versioned data; the gate never sizes budgets — sizing is RO/03+ |

---

## 10. Glossary

Extends RO/00 §14 and RO/01 §10; never redefines.

| Term | Definition |
|---|---|
| Reasoning necessity | The (n1)–(n3) fact about a demand established from sealed evidence (§1) |
| Deterministic exhaustion | (n3) — every applicable ladder rung exhausted or deterministically ruled inapplicable |
| Deterministic ladder | The D1–D5 + R ordered progression a demand descends before reasoning is considered (§5) |
| Ladder rung | One named stage of the deterministic ladder; extensible as data |
| Decision inputs | The closed set of sealed, versioned artifacts the necessity decision may consume (§3.1) |
| Decided-from coordinates | The recorded sealed-input references an outcome cites, enabling audit without re-decision |
| Decision outcome | One of the five closed verdicts of §4 |
| Deferral | The recorded pending consequence of INSUFFICIENT-INFORMATION — never a distinct outcome |
| Scope / granularity unit | The single unresolved demand — the decision unit fixed by §6 |
| Scope narrowing | RO narrowing a demand to a sub-problem, permitted only when the narrowing itself is deterministic |
| Governance refusal | GOVERNANCE-REFUSED — necessity established but policy/budget forbids invocation |
| Hope-retry | The forbidden pattern of re-asking the gate on identical inputs expecting a different outcome |
| Governance permission | The policy-as-data authorization checked for outcomes 1 and 5 (§4); distinct from necessity — necessity is a fact about the demand, permission is a fact about policy |
| Capability rung | The complexity level (RO/01 §6, C0–C4) a REASONING-APPROVED outcome names as part of scope |

---

## 11. Relationship to RO/00 and RO/01

| This document | Consumes | Refines |
|---|---|---|
| §1 Necessity | RO/01 §1 admission test, RO/01 §2 Information Boundary | RO/00 §5 responsibility 2 (necessity decision) into three named conditions |
| §4 Outcomes | RO/00 §4 "no is success" tenet | The single "necessity decision" output (RO/00 §4) into five closed verdicts |
| §5 Ladder | RO/00 §8.5 escalation ladder, RO/01 §6 complexity hierarchy | Extends the ladder below reasoning (D1–D5) so RO/01's C0–C4 is rung R's internal continuation |
| §6 Granularity | RO/00 §5.5 scope discipline, RO/01 §7 composition | Fixes the decision unit CP/WS artifacts already imply, without re-deciding them |

Nothing in this document narrows RO/00's boundaries or RO/01's vocabulary;
where a ruling here reads as more specific than either, it is elaboration
within the frozen scope, not amendment.

---

Forward pointer: RO/03 consumes REASONING-APPROVED artifacts — justification,
capability id, scope — to prepare the request: context sizing, budgeting,
output contracts.
