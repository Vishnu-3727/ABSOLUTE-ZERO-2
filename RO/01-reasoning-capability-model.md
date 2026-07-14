# Reasoning Orchestrator (RO) — Phase 1: Reasoning Capability Model

Status: authoritative; defines the language of all later RO phases. Architecture
only — no algorithms, no interfaces, no event names, no thresholds. This phase
decides nothing about invocation; it fixes what the words mean. Necessity,
gating, scoring, selection, and budgeting are RO/02+ territory. Vendor and
model names (e.g. Claude, GPT, Gemini, Qwen) are forbidden throughout this
document, including this sentence which names them only to forbid them.

---

## 1. Definition of Reasoning

**Reasoning is computation whose required output is not uniquely determined by
its declared inputs plus any available deterministic procedure** — the
production of novel structure or judgment across an information gap.

Architectural test — both conditions must hold:

| Condition | Statement |
|---|---|
| (a) Underdetermination | The declared inputs, recorded knowledge, and registered deterministic procedures do not jointly determine a sufficient output. |
| (b) Generalization | Producing the output requires inference beyond mechanical application of declared rules — judgment, abstraction, or synthesis. |

Neither condition alone qualifies work as reasoning. A demand that is
underdetermined only because no procedure was *registered yet* is a coverage
gap, not evidence of (b); a demand that requires elaborate but fully declared
steps is (b)-shaped only if it is also (a)-shaped.

**Distinction from adjacent territory:**

| Territory | What it is | Why it is not reasoning |
|---|---|---|
| Deterministic computation | Output = function of inputs, replayable byte-identically | Fails (a) — inputs already determine the output |
| Retrieval | Locating existing recorded information (UMS territory, Law 2) | Fails (a) — the answer already exists and is found, not produced |
| Memory lookup | Exact/indexed access to stored facts | Fails (a) — access is a procedure, not a judgment |
| Plugin execution | Running a declared provider against a declared contract (PRT/Execution territory) | Fails (a) and (b) — the contract fixes the output shape and the procedure fixes how it is reached |
| Algorithmic search | Search space and evaluation function both fully declared | Fails (a) even at scale — declared search remains deterministic no matter how large |
| Repository understanding | Structural extraction and indexing (owned by UMS) | Fails (b) — extraction follows declared structure, no synthesis required |
| Workflow execution | Ordered dispatch of already-decided units (WS territory) | Fails (a) — the decisions were already made; only sequencing remains |

**Key line: expensive is not reasoning; underdetermined is.** Scale, duration,
or cost never converts deterministic work into reasoning, and cheapness never
disqualifies genuine underdetermination from being reasoning. Cost is a later
concern (RO/00 §5.6, §8.1); this test is the only admission gate.

---

## 2. The Information Boundary

The **Information Boundary** is the conceptual point where the union of
(declared inputs, recorded knowledge, registered deterministic procedures)
stops determining the required output.

| Side | Territory |
|---|---|
| Below the boundary | Deterministic territory — everything the OS has already built to answer without an engine |
| At the boundary | The information gap — the span the §1 test identifies |
| Above the boundary | Reasoning-only territory — only generalization can cross it |

**Properties:**

- **Per-demand, not global.** Every demand has its own boundary position; there
  is no single system-wide line.
- **Moves down over system life.** As Experience converts recurring gaps into
  registered deterministic answers, the boundary descends — the declining
  asymptote of RO/00 §2 restated in boundary terms: fewer demands sit above the
  line as the system matures.
- **Crossing it is a later decision.** This phase defines only the concept of
  the boundary and its motion. Whether a specific demand's position above the
  boundary is *sufficient reason to invoke reasoning* is RO/02's necessity
  decision to make. No decision algorithm exists here.

---

## 3. Reasoning Capability

A **reasoning capability** is a stable, abstract, vendor-blind class of
reasoning ability, owned by the operating system, described entirely by
declared characteristics (§5), and implemented by zero or more reasoning
providers via descriptor rows (RO/00 §10, RO-I9).

| Property | Statement |
|---|---|
| Ownership | The OS owns the capability; providers borrow it by declaring fulfillment (§8) |
| Identity | Permanent id, never reused; a meaning change produces a new id, never an in-place edit (mirrors CP/01 §3, §6) |
| Existence independent of providers | A capability is meaningful with zero registered providers |
| Description | Entirely by the characteristics of §5 — no implementation detail |

**Reasoning capability ≠ CP/01 execution capability.** RO/00 §14 already rules
this a collision to avoid; this phase restates it as load-bearing: a CP/01
capability is a verifiable contract of *execution* ability living in PRT's
registry. A reasoning capability is a class of *reasoning* ability living in
RO's own descriptor space. The two vocabularies never mix, never share an id
space, and live in disjoint authorities.

---

## 4. Capability Taxonomy

Structure: a shallow closed **category** set, an open **capability** set within
it, and free **facets** — deliberately mirroring CP/01 §5's rejection of both
deep taxonomy and flat namespace. Category membership carries **no behavioral
inheritance**; every capability's characteristics (§5) are self-contained.

**Five closed categories:**

| Category | Meaning | Illustrative open-set members |
|---|---|---|
| INTERPRETIVE | Making recorded or given material meaningful | Knowledge application, explanation |
| ANALYTIC | Decomposing and judging what exists | Analysis, evaluation |
| GENERATIVE | Producing what does not yet exist | Creative synthesis, transformation |
| DELIBERATIVE | Choosing among futures | Planning, decision, prediction |
| INFERENTIAL | Deriving what follows | Multi-step inference, deduction chains |

The category set is closed and changes only by explicit architectural
decision, exactly as CP/01 §5 fixes for its category dimension. The
capabilities listed above are illustrative rows within the open set, not an
exhaustive registry — adding a new capability is a data addition, never a
redesign, and never touches the category set.

**Facets** are free descriptive tags (e.g., domain, modality, horizon). They
are searchable/browsable attributes only, never load-bearing: no policy,
selection, or downstream mechanism may depend on a facet value existing or
having any particular value. No capability→provider or capability→model
assignment is expressed anywhere in this taxonomy — assignment lives entirely
in descriptor rows (§8, RO/00 §10).

---

## 5. Capability Characteristics

Every capability declares eight characteristics. Each is **declared,
categorical data attached to the class itself** — bands or classes, never
numeric thresholds (thresholds are later-phase policy, RO-C7). Characteristics
describe the capability class; they never describe a provider. Provider
fitness against a class lives only in descriptor rows (RO/00 §10) — the two
never merge.

| # | Characteristic | Describes | Why it exists (future consumer, undesigned here) |
|---|---|---|---|
| 1 | Inference depth | How many dependent inference steps the class implies | Deeper inference costs more; later budgeting must see the cost class (RO/00 §5.6) |
| 2 | Context sensitivity | How strongly output quality depends on supplied context volume/fit | Context sizing (RO/00 §5.5) selects from Request Memory and must know the class's appetite |
| 3 | Determinism tolerance | How much output variance across identical invocations is acceptable | Verification and retry policy treat low-variance classes differently |
| 4 | Knowledge dependency | Degree to which the class needs external recorded knowledge vs. supplied material alone | Bounds what context is even relevant to select |
| 5 | Creativity requirement | Degree to which output must be novel rather than derivable | Strongest predictor of verification difficulty and variance |
| 6 | Reasoning complexity | Position on the §6 hierarchy | The single coarse cost/effort coordinate later phases cite |
| 7 | Verification difficulty | How mechanically checkable the output is | The OS gates everything through Verification; harder classes need stronger contracts |
| 8 | Expected output structure | How strictly the output shape can be pre-declared | Output contract preparation (RO/00 §5.8) depends on it |

---

## 6. Reasoning Complexity

A conceptual hierarchy of five levels attached to a demand's required
capability. No thresholds, no numeric boundaries — level assignment is a
later-phase policy concern, not a model concern.

| Level | Name | Meaning |
|---|---|---|
| C0 | Recall-adjacent | Single-shot production where the gap is minimal; borderline — many C0 demands should eventually fall below the Information Boundary entirely as Experience matures |
| C1 | Single-step inference | One inferential move over supplied material |
| C2 | Bounded multi-step | Several dependent steps, closed scope, endpoint known in advance |
| C3 | Open synthesis | Output structure itself must be invented; scope discoverable only during reasoning |
| C4 | Compositional deliberation | Multiple interacting reasoning acts; intermediate judgments feed later ones |

**Complexity is a property of the demand's required capability, not of any
provider.** The escalation ladder (RO/00 §8.5) walks this hierarchy — cheapest
sufficient rung first, escalating only on demonstrated insufficiency.

Later consumers, named without design:

| Consumer | How it uses the level |
|---|---|
| Token budgeting | Higher level implies a larger ceiling class |
| Provider selection | Level maps to required capability strength |
| Request preparation | Level shapes contract strictness |

---

## 7. Capability Relationships

Exactly three relationship kinds — a closed set, deliberately smaller than
CP/01's four (§8). Reasoning capabilities are ability classes, not fulfillment
units: no *conflict* relation is meaningful where nothing executes
concurrently, and *alternative* is a provider-selection concern resolved over
descriptor rows (§8), not a fact about the capability vocabulary itself.

| Relationship | Meaning | Constraint |
|---|---|---|
| Composition | A capability's work can be expressed as a governed combination of other capabilities (typically C4 territory) | Descriptive only — never an execution plan |
| Specialization | A capability is a narrower form of another, constrained by facet | Never implies behavioral inheritance (mirrors CP/01 §5) |
| Dependency | Exercising one capability presupposes another's result class being available | Dependency relations are acyclic |

Relationships are declared data rows between capability ids. No relationship
ever names a provider.

---

## 8. Capability Independence

Capabilities belong to the OS; providers borrow them (echoes CP's late-binding
philosophy, PRT/00 §4). The following scenarios each require **zero
architectural change**:

| Scenario | What happens | Why the model is untouched |
|---|---|---|
| A new model appears | New descriptor rows are added, each claiming fulfillment of existing capability ids | Capabilities were already meaningful before the provider existed (§3) |
| A provider disappears | Its descriptor rows are removed | Capabilities and demands referencing them are unchanged; only the fulfillment surface shrinks |
| Multiple providers coexist | Multiple descriptor rows exist per capability | Selection among them is later-phase mechanical resolution over data, not a capability-model concern |
| A local engine is introduced | It enters as a descriptor row like any other, carrying its own cost/latency class | Locality is a descriptor attribute, never a new mechanism |

---

## 9. Invariants (RO-C)

Permanent for this phase; all later RO phases are bound by these.

| ID | Invariant |
|---|---|
| RO-C1 | Reasoning is defined by underdetermination + generalization (§1), never by cost, size, or duration. |
| RO-C2 | The Information Boundary is per-demand and monotonically descends over system life; architecture never assumes a fixed boundary. |
| RO-C3 | Capabilities are OS-owned, vendor-blind, permanently identified; ids are never reused; a meaning change produces a new id. |
| RO-C4 | The category set is closed (five categories); the capability set is open; facets are free and never load-bearing. |
| RO-C5 | No capability, category, characteristic, or relationship ever names or assumes a provider or model. |
| RO-C6 | Characteristics are declared categorical data on the class; provider fitness lives only in descriptor rows; the two never merge. |
| RO-C7 | Complexity is a five-level conceptual hierarchy attached to a demand's required capability; thresholds and numeric boundaries are policy, never model. |
| RO-C8 | Exactly three relationship kinds exist — composition, specialization, dependency; extending this set requires an RO/01 errata, never ad-hoc addition. |
| RO-C9 | Specialization carries no behavioral inheritance. |
| RO-C10 | Dependency relations are acyclic. |
| RO-C11 | Nothing in the capability model decides invocation — necessity, gating, scoring, selection, and budgeting are RO/02+ territory. |
| RO-C12 | Reasoning capability vocabulary and CP/01 execution capability vocabulary never mix — disjoint authorities (RO-I9). |

---

## 10. Glossary

Consistent with RO/00 §14; extends it, never redefines it.

| Term | Definition |
|---|---|
| Reasoning | Computation satisfying both the underdetermination and generalization conditions (§1) |
| Information gap | The span between what declared inputs/knowledge/procedures determine and what the demand requires |
| Information Boundary | The per-demand point where determination by declared inputs, knowledge, and procedures stops (§2) |
| Deterministic territory | Everything below the Information Boundary — answerable without an engine |
| Reasoning capability | A stable, abstract, vendor-blind class of reasoning ability owned by the OS (§3) |
| Capability category | One of the five closed top-level buckets a capability sits in (§4) |
| Facet | A free, non-load-bearing descriptive tag on a capability (§4) |
| Capability characteristic | One of the eight declared, categorical properties describing a capability class (§5) |
| Complexity level (C0–C4) | Position on the reasoning complexity hierarchy (§6) |
| Composition | A capability relationship: expressible as a governed combination of other capabilities (§7) |
| Specialization | A capability relationship: a narrower, facet-constrained form of another capability, with no inheritance (§7) |
| Dependency | A capability relationship: one capability presupposes another's result class; acyclic (§7) |
| Descriptor row | The provider-declared data row claiming fulfillment of a capability (RO/00 §10) |
| Demand's required capability | The reasoning capability a specific demand needs, as identified above the Information Boundary |

---

Forward pointer: RO/02 (necessity decision + governance gate) consumes this
model's language to decide, for a given demand, whether and how the
Information Boundary may be crossed.
