# Reasoning Orchestrator (RO) — Phase 3: Request Preparation

Status: authoritative; begins only after a REASONING-APPROVED outcome exists
(RO/02 §4). Transforms an approved demand into a provider-independent
Reasoning Request. Architecture only — no code, no pseudocode, no APIs, no
algorithms, no vendor/model names (forbidden throughout, including this
sentence which names Claude/GPT/Gemini/Qwen only to forbid them), no event
names, no numeric allocations, no thresholds, no metrics. Invocation
lifecycle, retries, and measurement are RO/04. Integration and event canon
are RO/05.

---

## 1. The Reasoning Request

The **Reasoning Request** is the immutable, provider-independent artifact RO
produces from a REASONING-APPROVED outcome — the only object that ever
crosses the quarantine (refines RO/00 §14 "prepared reasoning request").

| Aspect | Statement |
|---|---|
| Represents | The complete, self-contained, governed statement of what reasoning must produce: context subset, constraints, output contract, budget, preparation coordinates |
| Why it exists (a) | The auditable unit of reasoning spend |
| Why it exists (b) | Decouples every upstream artifact from every engine modality |
| Why it exists (c) | Makes preparation replayable |
| Consumed by | RO/04's invocation lifecycle |
| Judged by | Verification, against the request's declared output contract |
| Learned from | Experience, from the request's recorded effectiveness |

**Self-containment rule.** An engine needs nothing outside the rendered
request — no follow-up retrieval, no live system access. Quarantine is total
(RO/00 §8.3).

---

## 2. Two-Artifact Ruling

Preparation yields two distinct artifacts, never merged:

| Artifact | Nature |
|---|---|
| Reasoning Request | Provider-independent, canonical, contains zero provider identity |
| Provider Resolution | The selection record binding the request to one descriptor row, carrying resolution coordinates (descriptor-space version, policy version) |

**Rationale.** "Request must remain provider-independent" and "provider
selection is in scope" are co-satisfiable only by separation. The Provider
Resolution deliberately mirrors PRT/03's Binding Contract pattern: pure
resolution + immutable record + replay-from-coordinates.

Serialization (§11) consumes both — request for content, resolution for
target form. Provider identity lives only in the Provider Resolution; it
never leaks into request content, context, constraints, or schema (extends
PRT/05's provider-identity-never-crosses discipline to RO's own artifacts).

---

## 3. Provider Abstraction

A **reasoning provider** is an interchangeable implementation of one or more
OS-owned reasoning capabilities (RO/01 §3). It exists for RO only as a
descriptor row — RO's own descriptor space, disjoint from PRT's registry
(RO/00 §10, RO-I9).

Descriptor row declared fields (categorical classes, never numerics):

| Field | Declares |
|---|---|
| Capabilities claimed | RO/01 capability ids |
| Capability strength per claim | Which complexity rungs C0–C4 it can serve |
| Context capacity class | How much context it admits |
| Cost class | Categorical spend tier |
| Latency class | Categorical response-time tier |
| Determinism class | Output variance behavior |
| Deployment locality | Local / remote |
| Privacy domain | Which data classes may be sent to it |
| Compliance tags | Regulatory/policy markers |
| Reliability characteristics | Declared baseline + Learning-updated versioned priors (mirrors PRT/04's live-evidence/healed-priors split; actual health tracking is RO/04+ territory — only the declared shape is fixed here) |

Providers borrow capabilities; capabilities exist with zero providers
(RO-C3, RO/01 §8). Vendor names are forbidden in every descriptor field.

---

## 4. Capability Matching

The approved demand arrives already naming its required capability id and
complexity rung (RO/02 §4 outcome 1 carries both).

| Property | Statement |
|---|---|
| Definition | Demand's required capability + rung → the set of descriptor rows claiming that capability at sufficient strength |
| Nature | Set-construction, not choice — produces the **candidate set** |
| Inputs | Declared data only: descriptor claims + declared characteristics |
| Empty result | Loud preparation failure — no silent capability substitution; a weaker capability is never quietly matched (mirrors PRT no-cross-id-substitution) |
| Scope | Never re-asks necessity — RO-D territory is closed |

---

## 5. Provider Selection

Deterministic resolution over the candidate set. No algorithm — factors and
order only.

**Factor table:**

| Factor | Legitimacy |
|---|---|
| Supported capabilities + strength | Sufficiency |
| Context capacity class | Request must fit |
| Privacy domain | Data governance — a request carrying private context resolves only to providers whose privacy domain admits it; hard eligibility, never a preference |
| Deployment locality | Policy may require local |
| Cost class | Cheapest-sufficient (P5, RO/02) |
| Latency class | Workflow constraints from sealed upstream artifacts |
| Reliability characteristics | Declared + priors |
| Compliance constraints | Policy-as-data |
| User policy | Declared constraints, retained ownership |

**Order of application:**

| Stage | What happens |
|---|---|
| 1. Eligibility filters | Privacy, compliance, capacity, locality — binary; every excluded candidate's refusal is recorded |
| 2. Preference resolution | Among eligible candidates: cheapest-sufficient first (P5), then declared preference, then stable-id tie-break (mirrors PRT/03 resolution discipline) |

**The two-questions principle.** Provider identity never influences
necessity but may influence execution, because the two are different
questions: necessity is a fact about the **demand** (RO-D3, "whether never
depends on who") and must survive provider churn; selection is a fact about
**fulfillment** — once approved, the question changes from "must we reason?"
to "who serves this request best under governance?", a question that exists
only because providers are plural.

Empty eligible set after filters = loud failure (RO/00 §8.7) — never
constraint relaxation (extends RO-D10).

---

## 6. Context Architecture

| Principle | Statement |
|---|---|
| Minimum sufficient context | Smallest subset whose absence would change the output class (P4's context dimension); every element justified |
| Sealed RQM consumption | Context selected exclusively from CM-assembled Request Memory (RO-I5, Law 2); RO never retrieves, augments, re-ranks, or freshens content |
| Context isolation | One request's context never leaks into another's; no shared mutable context |
| Relevance | Inclusion justified by the demand's required capability characteristics (knowledge dependency + context sensitivity, RO/01 §5) — a low-knowledge-dependency demand gets minimal knowledge context by class, not ad-hoc judgment |
| Deterministic selection | Identical inputs → identical context subset, byte-identical |
| Boundaries | Context carries what the engine may see, nothing more — bounded information exposure is a security property, not just a cost property; interacts with §5's privacy domain |
| Freshness | RQM carries CM's freshness guarantees; RO trusts them and never re-validates — freshness is CM's authority; a stale-RQM discovery is a preparation failure routed back, never silent re-retrieval |
| Provenance | Every context element retains its RQM provenance so the request is auditable element-by-element |

**Justification rule.** Every included element carries a recorded inclusion
reason; unjustified context is a defect. The cheapest token is the one never
sent.

---

## 7. Context Reduction

Continuous shrink philosophy. Reduction mechanisms (conceptual):

| Mechanism | What it removes |
|---|---|
| Deduplication | Identical/equivalent content, kept once |
| Resolved-work removal | Outcomes already achieved deterministically |
| Unused-memory elimination | Elements whose class the capability characteristics rule irrelevant |
| Deterministic summarization | Only recorded, hash-keyed, deterministic summaries already in RQM (e.g. UMS-style tier artifacts) — RO never generates new summaries and never uses reasoning to shrink reasoning input; that would spend the resource to save it (mirrors RO-D8 narrowing discipline) |
| Reference substitution | Stable identifiers replace bodies where the output contract lets output cite rather than restate |

**Reduction floor.** Reduction never removes what sufficiency requires;
reduction below sufficiency is an INSUFFICIENT-INFORMATION-shaped preparation
failure, not a smaller request. Reduction is deterministic and recorded —
what was dropped and why, auditable.

---

## 8. Token Budget Architecture

| Property | Statement |
|---|---|
| Ownership | Budgets are governance property, allocated by RO from policy-as-data ceilings (RO/00 §5.6); no component grants itself budget |
| Lifecycle | Allocated at preparation → attached immutably to the request → consumed at invocation (RO/04) → reconciled after outcome (actual vs. allocated recorded) → feeds Experience |
| Constraints | Budget never exceeds any applicable governance ceiling (request-level, demand-class-level, system-level); ceilings are hard (RO-I10) — exhaustion is a loud governed outcome, never overdraft, never silent truncation to fit |
| Inheritance | Composite/escalation flows inherit the original allocation envelope — a C0→C1 escalation (RO/00 §8.5) or a composed demand's components draw from the parent's remaining ceiling, never a fresh grant; prevents escalation from becoming a budget laundering path |
| Exhaustion | Within-preparation exhaustion (context can't fit minimum sufficient content under ceiling) is a loud preparation failure; RO never quietly degrades context below sufficiency to fit budget (mirrors §7's floor) |
| Visibility | Every allocation, consumption, and reconciliation is recorded and attributable per request, capability, provider (RO/00 §11.6) |

---

## 9. Reasoning Constraints

Every request carries explicit governance data.

| Category | Content |
|---|---|
| Allowed reasoning scope | The RO/02-approved scope, restated as a hard boundary — the engine may not answer a bigger question |
| Required output form | The §10 output contract binding |
| Forbidden behaviors | Policy-as-data: classes of content/action the output must not contain — declared, not enumerated here |
| Determinism expectations | The capability's determinism tolerance class (RO/01 §5.3) — what variance downstream will accept |
| Policy constraints | Compliance, privacy, user policy carried with retained ownership; origin recorded |
| Verification expectations | What Verification will judge the output against, carried as metadata exactly like CP nodes carry them (CP/01 §7 discipline) — RO transports, never judges (RO/00 §6) |

**Rule.** Constraints are data on the request, never behavior in RO; an
unconstrained request is structurally invalid and never leaves preparation.

---

## 10. Output Schema Architecture

Unverifiable free-form output defeats the OS's verification gates;
structure is what makes reasoning output a verifiable object (RO/00 §11,
RO/01 §5.8 output-structure characteristic).

| Property | Statement |
|---|---|
| Ownership | Schemas are OS-owned, versioned artifacts in RO's authority — never provider-defined, never per-provider variants |
| Evolution | Append-mostly; a meaning change is a new schema version, published versions immutable (mirrors capability-id discipline RO-C3 and PRT registry versioning) |
| Compatibility | A request names exactly one schema version; outputs are judged against that named version forever — replay-stable |
| Provider independence | Schema describes what the output must contain, never how a provider produces or formats it natively — the renderer (§11) maps schema expectations into provider-consumable form; the same schema version serves every provider |

No actual schemas are defined in this document.

---

## 11. Serialization Independence

A prompt is one renderer (RO/00 §14 materialization/renderer).

**Architecture:** Reasoning Request (canonical, abstract) + Provider
Resolution (target) → renderer → the provider-consumable form the resolved
descriptor row declares: prompt text, structured API payload, program input,
or forms not yet invented.

| Renderer property | Statement |
|---|---|
| Deterministic | Same request + resolution → byte-identical rendering |
| Lossless w.r.t. governance | Every constraint, boundary, and contract in the request survives rendering — a renderer that drops a constraint is defective, not lenient |
| Renderer-per-form | Form declared in descriptor row |
| Bounded extension | Renderers are bounded extensions (RO/00 §11.5) — a new modality is a new renderer plus descriptor rows, zero architectural change |

**Demonstration.** If prompts disappeared: the renderer set changes, the
request artifact is unchanged, the decision architecture is unchanged, the
capability model is unchanged.

The canonical request — not any rendering — is the audit object; renderings
are derivable.

---

## 12. Preparation Determinism Coordinates

RO/00 §8.6 deferred the concrete tuple; this phase fixes preparation's:

Identical (approved decision artifact, sealed RQM content hash,
descriptor-space version, governance policy/config version, priors version,
schema version) → byte-identical Reasoning Request + Provider Resolution.

**Forbidden:** wall-clock, arrival order, provider live state, randomness
(PRT/05 forbidden-variability discipline).

Replay reads recorded coordinates, never the live world (mirrors PRT-B
replay).

RO/04 extends coordinates for invocation-time concerns; preparation's tuple
is closed here.

---

## 13. Architectural Guarantees

| ID | Guarantee | Why it matters |
|---|---|---|
| G1 | Provider independence | Request valid for any sufficient provider, present or future |
| G2 | Minimal context | Structural downward pressure on payload (§6–§7) |
| G3 | Bounded cost | No request leaves preparation without a hard ceiling attached |
| G4 | Bounded information exposure | The engine sees exactly the justified subset, nothing more — security and privacy property |
| G5 | Deterministic preparation | Byte-replayable from §12 coordinates |
| G6 | Total auditability | Request + resolution + inclusion reasons + reduction records + budget records reconstruct every preparation decision from artifacts alone |
| G7 | Serialization freedom | Engine modality churn never reaches the architecture |

---

## 14. Invariants (RO-P)

| ID | Invariant |
|---|---|
| RO-P1 | Preparation begins only from a REASONING-APPROVED outcome; no other path constructs a Reasoning Request |
| RO-P2 | The Reasoning Request is immutable, self-contained, provider-independent; provider identity exists only in the Provider Resolution |
| RO-P3 | The two artifacts are never merged; renderers consume both |
| RO-P4 | Context is selected exclusively from sealed Request Memory; RO never retrieves, augments, re-ranks, or re-freshens (RO-I5 restated as preparation law) |
| RO-P5 | Every context element carries a recorded justification and provenance; unjustified inclusion is a structural defect |
| RO-P6 | Reduction is deterministic, recorded, and floored at sufficiency; reasoning is never used to reduce reasoning input |
| RO-P7 | Budgets are allocated from governance ceilings, attached immutably, inherited through escalation/composition from the parent envelope, and never overdrawn or silently truncated-to-fit |
| RO-P8 | Every request carries explicit constraints including scope boundary, output contract, and verification expectations; an unconstrained request never leaves preparation |
| RO-P9 | Output schemas are OS-owned and versioned; a request names exactly one schema version; providers never define schemas |
| RO-P10 | Rendering is deterministic and governance-lossless; a constraint-dropping renderer is defective |
| RO-P11 | Preparation is byte-replayable from the §12 coordinate tuple; live-world reads during preparation are forbidden |
| RO-P12 | Empty candidate set, empty eligible set, budget-infeasible minimum context, or stale RQM are loud recorded preparation failures — never substitution, relaxation, or silent degradation |

---

## 15. Glossary

Extends RO/00 §14, RO/01 §10, RO/02 §10; never redefines.

| Term | Definition |
|---|---|
| Reasoning Request (refined) | The immutable, provider-independent artifact crossing the quarantine (§1) |
| Provider Resolution | The immutable selection record binding a request to one descriptor row, with resolution coordinates (§2) |
| Descriptor row (refined) | The declared fields of §3 a candidate/eligible set resolves over |
| Candidate set | Descriptor rows matching the demand's required capability at sufficient strength (§4) |
| Eligible set | Candidate rows surviving §5's eligibility filters |
| Capability matching | Set-construction from demand capability + rung to candidate set (§4) |
| Provider selection | Deterministic resolution over the candidate set to one provider (§5) |
| Two-questions principle | Necessity is a fact about the demand; selection is a fact about fulfillment (§5) |
| Context element | One unit of RQM-sourced content included in a request |
| Inclusion justification | The recorded reason a context element was included (§6) |
| Context reduction | The deterministic, recorded shrink applied above the sufficiency floor (§7) |
| Reduction floor | The point below which reduction becomes an insufficiency failure, not a smaller request (§7) |
| Reference substitution | Replacing a context body with a stable identifier the output contract permits citing (§7) |
| Budget envelope | The immutable ceiling attached to a request at allocation (§8) |
| Budget reconciliation | Recording actual vs. allocated spend after outcome (§8) |
| Output schema (OS-owned) | The versioned, RO-owned artifact declaring required output shape (§10) |
| Renderer (refined) | The deterministic, governance-lossless transform from (request, resolution) to provider-consumable form (§11) |
| Rendering | The output of a renderer — a derivable, non-canonical artifact (§11) |
| Preparation coordinates | The §12 closed tuple from which preparation replays byte-identically |

---

Forward pointer: RO/04 consumes (Reasoning Request, Provider Resolution)
pairs into the governed invocation lifecycle: execution, retry/escalation,
outcome capture, measurement.
