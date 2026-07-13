# Capability Planner (CP) — Phase 1: Capability Model

Defines the vocabulary CP plans against: what a capability *is*, how it is identified, organized, versioned, described, and related to other capabilities. Conceptual only — no schemas, no algorithms, no matching/planning logic (later phases). Builds within the walls fixed by `CP/00-architectural-foundation.md`; nothing here contradicts it.

---

## 1. Definition

**A capability is a stable, abstract, verifiable contract of ability — what the OS can have done, never how.** It is the indirection layer between intent (what a request wants) and implementation (what a plugin/model does).

| Is | Is not |
|---|---|
| A named class of verifiable outcome the OS can reason about | A plugin, tool, or function |
| A stable point of vocabulary providers bind to | A prompt or model skill |
| An abstraction independent of any implementation | A task or a plan step |
| Meaningful before any provider exists for it | An algorithm or execution recipe |

**Why stability matters.** Intent decomposes onto capabilities, not onto implementations. Providers declare fulfillment of capabilities, not the other way around. Because the vocabulary is stable while implementations churn underneath it, either side changes without touching the other: a plugin can be replaced, upgraded, or removed and every plan, prior, and binding that referenced the capability stays valid. Capabilities are the OS's vocabulary; implementations are volatile.

## 2. Role in the OS

CP's fenced question is "what abilities are required" (CP/00 §1). The capability model is the answer space that question is posed against — the set of things CP is even allowed to say a plan step needs. Nothing about matching, scheduling, or fulfillment lives here; this phase only fixes what the words mean.

## 3. Identity & naming

- Every capability has a **permanent, stable, dotted id**, aligned with the system's `family.verb` event-naming discipline (conceptually `domain.action` — a shape, not a grammar spec).
- Identity is forever: ids are **never reused, never repurposed**. An id retired for one meaning can never later mean something else.
- Semantics bind to the id: **same id = same meaning, always.** A consumer that resolves an id years apart gets the same contract.
- Renames happen via **alias + deprecation**, never mutation of an existing id's meaning.

## 4. Granularity

A capability is **planning-grained**: coarse enough to be a meaningful ability at the level of a single plan step, fine enough that one provider can fulfill it whole and Verification can check it whole.

**Litmus test:** one capability = one verifiable outcome class. If its verification expectation cannot be stated independently of some other capability, it is not one capability — it is part of one, or several.

| Too fine | Right grain | Too coarse |
|---|---|---|
| Function-level operations — registry explosion, planning noise, nothing meaningful to verify in isolation | One statable, checkable outcome a single provider can own end to end | "Do engineering" — unmatchable (no provider can claim it truthfully), unverifiable (no single check bounds it) |

Granularity disputes are resolved by this test, not by taste: draw the boundary wherever an independent verification expectation stops being statable.

## 5. Hierarchy — evaluation and recommendation

Three candidate organizations, evaluated on their own merits:

| Option | Description | Verdict |
|---|---|---|
| (a) Deep containment taxonomy | Universal → Engineering → Domain → Specialized layers, capabilities nested inside | **Rejected.** Deep trees rot: capabilities straddle layers, forcing arbitrary placement. Reclassification becomes registry churn. Containment invites implicit inheritance of meaning — exactly what capabilities must not have. |
| (b) Flat namespace, no structure | All capability ids in one undifferentiated set | **Rejected.** Unbrowsable at scale, no curation surface, nothing stops naming collisions or duplicate near-capabilities. |
| (c) Shallow categorization + faceted tags | Single-level closed **category** + open capability set within categories + free **facet** tags | **Recommended.** |

**Recommendation, elaborated:**
- **Category** — a single-level, closed dimension. The set of categories is curated and grows rarely, by explicit architectural decision (not by every new capability proposal).
- **Capability set** — open within a category. New capabilities are ordinary data additions; no architectural decision required to add one.
- **Facets** — open, free tags describing domain or trait (e.g. the kind of thing the old Universal/Engineering/Domain/Specialized layering was reaching for). A capability may carry multiple facets. Facets carry no containment and no inherited semantics — they are searchable/browsable attributes, nothing more.

**Inheritance philosophy: none.** Composition over inheritance. A capability never implicitly acquires meaning, constraints, or verification expectations from a category, a facet, or another capability. Every capability's contract is self-contained and explicit. Where finer capabilities compose into coarser ones, that is a declared *relationship* (§8), not structural inheritance.

The deep-layer idea is not lost — it survives as category/facet **values**, evaluated data, never as containment structure or inheritance.

## 6. Lifecycle & versioning

Conceptual states, one direction only:

```
proposed → active → deprecated → retired
```

- **proposed** — declared, not yet a matchable target.
- **active** — matchable, plannable, verifiable.
- **deprecated** — matchable for compatibility, discouraged for new plans; carries an alias to its replacement where one exists.
- **retired** — no longer matchable; the id is kept forever as a tombstone. Retired ids are never reused for a different meaning.

**Evolution boundary:** a capability may only evolve through *compatible clarification* — enriched description, added facets, tightened-but-still-satisfied metadata. Any change that narrows or shifts what counts as fulfillment is a **meaning change**, and a meaning change always produces a **new id**, never an in-place edit of an existing one. This is what makes "same id = same meaning forever" (§3) enforceable rather than aspirational.

## 7. Metadata

Each attribute answers a question for a specific downstream consumer. CP reads all of it; CP owns none of it (§9).

| Attribute | Question it answers | Primary consumer(s) |
|---|---|---|
| Identity (id) | What is this, permanently? | Everyone — the reference key |
| Description | What does fulfilling this mean, in words? | CP matching (human/plan review), discoverability |
| Category | Which curated top-level bucket does this sit in? | Discoverability, registry curation |
| Facets | What domains/traits does this touch? | Discoverability, CP matching breadth |
| Constraints | Under what conditions is fulfillment valid? | CP matching, Plugin Runtime fulfillment |
| Dependencies | What other capabilities must be available for this to be meaningful? | CP planning (later phase), Scheduler ordering |
| Inputs | What must be given for fulfillment to be attempted? | CP matching, Plugin Runtime fulfillment |
| Outputs | What does fulfillment produce? | CP matching, downstream step wiring |
| Preconditions | What must hold before fulfillment starts? | Scheduler ordering, Verification gating |
| Postconditions | What must hold after fulfillment completes? | Verification gating |
| Verification expectations | How would anyone check this was actually done? | Verification gating — **first-class, mandatory** |
| Cost characteristics | What does fulfillment typically cost? | Scheduler ordering, future cost-aware matching |
| Parallelization characteristics | Can this run concurrently with siblings? | Scheduler ordering |
| Determinism | Is fulfillment expected reproducible? | Planning/verification reasoning — never a promise about any model |
| Version | Which revision of compatible clarification is this? | Registry lifecycle, audit |
| Aliases | What older ids point here? | Backward-compatible resolution |
| Deprecation | Is this discouraged, and what replaces it? | CP matching (avoid for new plans), registry curation |

**Verification expectations are non-negotiable.** A capability without a statable verification expectation is not admissible into the registry — it fails the granularity litmus (§4) and violates the unskippable-gate discipline CP/00 inherits from the Kernel (Law: fail loud, block over guess). "Statable" does not mean "automatable everywhere" — it means the *kind* of check that would confirm fulfillment can be named, even if the check itself is designed in a later phase.

**Determinism is descriptive, not promissory.** It declares an expectation planning and verification can reason about (e.g., "retry and compare" vs. "accept variation within outcome class"); it says nothing about, and never names, any model or provider.

## 8. Relationships

Capabilities relate to each other in exactly four ways. Each is justified by what it enables downstream; nothing else is admitted.

**Kept:**

| Relationship | Meaning | Why it's in the model |
|---|---|---|
| Dependency / requires | This capability is only meaningful with another capability also available | Lets later planning phases refuse to bind a step whose prerequisite is absent, instead of producing a silently broken plan |
| Composition | A declared decomposition of a coarser capability into finer ones | Enables hierarchical planning in a later phase without inventing ad hoc splitting logic at plan time |
| Alternative / substitutable | Distinct ids that satisfy the same outcome class | Feeds fallback semantics (CP/00 §3, §11) — a low-confidence or unavailable binding has a declared escape hatch |
| Mutual exclusion / conflict | Two capabilities cannot both be exercised within one plan-step context | Lets later validation reject an incoherent step before it is ever scheduled |

**Excluded, and why:**

| Rejected relationship | Why it does not belong here |
|---|---|
| Optional | Optionality is a property of a *plan step's* use of a capability, not of the capability itself — a plan-level concern |
| Conditional | Whether a capability applies depends on situational plan state, not on timeless capability semantics — a plan-level concern |
| Aggregation-as-ownership | Capabilities never own each other; composition (kept, above) already covers legitimate decomposition without implying ownership |
| Shared / reusable | Every capability is reusable by nature — declaring it as a relationship would be recording a universal truth as if it were a fact about specific pairs |

**The line, stated explicitly:** the capability model describes **timeless ability relations** — true regardless of any particular request. Plans describe **situational usage** — true only for one task graph, one time. A relationship belongs in the capability model only if it would hold even with no plan in existence.

## 9. Registry philosophy

The Capability Registry is **owned by Plugin Runtime** (frozen spec, `COMPONENTS/plugin-runtime.md`). CP reads it; CP never mutates it, never owns it, never forks a private copy of it (CP/00 §6, §13, invariant 5).

| Registry does | Registry never does |
|---|---|
| Catalogs declared capabilities and their metadata | Matches capabilities to plan steps |
| Holds lifecycle authority — introduce, evolve, deprecate, alias | Plans, schedules, or executes anything |
| Is the binding point where providers declare fulfillment | Verifies fulfillment |
| Serves capability data as a read surface | Assembles prompts or retrieves repository content |

Capability definitions are **policy-as-data** (CP/00 §2). Introducing a new capability is a data change through the registry's lifecycle — zero redesign of CP, zero redesign of any capability already in the registry.

**Backward compatibility, restated as registry discipline:** evolution is append-mostly. A semantic-narrowing or semantic-shifting change to an existing capability requires a **new id** (§6). Old ids deprecate with alias pointers to their replacement. Deprecation is always preferred over deletion; retired ids are **never** reused (§3, §6).

## 10. Extensibility & new domains

A wholly new domain — quantum computing, bioinformatics, mechanical engineering, a future programming language, a future hardware target, a future reasoning method — enters the system as:

1. New category or facet values (§5), added by architectural decision if a new category, or freely if only a new facet.
2. New capability declarations within existing or new categories.
3. Providers declaring fulfillment of those capabilities through the registry.

None of this touches existing capability definitions, requires CP code changes, or requires the OS to enumerate domains anywhere in code. Capabilities are data; the OS's domain coverage grows by adding rows, never by adding branches.

## 11. Discoverability

Capabilities must be:

- **Browsable** — enumerable through the registry by category and by facet.
- **Referenceable** — addressable by stable id from plans, priors, and telemetry, independent of how they were discovered.

No discovery *algorithm* is specified here — ranking, search, or recommendation over the registry is a later-phase (or Plugin Runtime-owned) concern. This phase only guarantees the vocabulary is structured well enough to be browsed and cited.

## 12. Capability-model invariants

Immutable for all later CP phases.

1. A capability is an abstract, verifiable contract of ability — never a plugin, tool, function, prompt, model skill, task, or plan step.
2. Capability ids are permanent: never reused, never repurposed; same id always means the same thing.
3. Renames occur only via alias + deprecation, never by mutating an existing id's meaning.
4. Organization is single-level category (closed, rarely-changing) + open capability set + open facet tags — never a deep containment hierarchy, never an unstructured flat set.
5. Capabilities carry no behavioral inheritance; every contract is self-contained.
6. Granularity is fixed by the verification-boundary litmus: one capability = one independently verifiable outcome class.
7. A capability without a statable verification expectation is not admissible.
8. Any semantic-narrowing or semantic-shifting change to a capability requires a new id; deprecation over deletion; retired ids are permanent tombstones.
9. The only capability-to-capability relationships are dependency, composition, alternative, and conflict; all other apparent relationships are plan-level, not vocabulary-level.
10. The registry is owned exclusively by Plugin Runtime; CP and every other consumer only read it.
11. New domains extend the model purely as data — new categories/facets/capabilities/providers — never as code or redesign.
12. Every capability is browsable by category/facet and referenceable by stable id from any consumer.

---

Status: Phase 1 capability model frozen. Later phases (matching, planning, decomposition) operate within this vocabulary; they never redefine it.
