# Capability Planner (CP) — Phase 2: Capability Graph Planning

How CP transforms an understood request (CP/00 §13 boundary: intent + goals + constraints + Request Memory, already validated upstream) into a validated **Capability Graph**. Conceptual only — no algorithms, data structures, APIs, schemas, or code. Builds within CP/00 (architectural foundation) and CP/01 (capability model, frozen vocabulary); neither is restated here except where a decision is anchored to it.

---

## 1. Inputs & outputs

| Inputs (assumed valid) | Source |
|---|---|
| Intent | Upstream classification (CP/00 §3) |
| Goals + sub-goal candidates | Upstream decomposition input |
| Constraints (request-level) | Request admission |
| Request state | RSM (read-only, CP/00 §13) |
| Request Memory | Context Manager (CP/00 §13 — CP never builds context) |
| Capability registry (read-only) | Plugin Runtime (CP/01 §9) |

| Outputs | Note |
|---|---|
| Capability Graph | Nodes = requirements, edges = typed relations (§3) |
| Priorities | Bands per node, ranks within alternative groups (§6) |
| Constraints (propagated, annotated with origin) | §5 |
| Requirements | Discovered per §2 |
| Confidence | Per-node + whole-graph (§7) |
| Gaps | Typed, declared (§8) |

**Out of scope, explicitly:** execution plan, workflow, scheduling order, provider/plugin selection, prompt construction, verification algorithms. This phase stops at a validated graph — CP/00 invariant 1.

## 2. Planning philosophy

Deterministic **staged refinement**. Stages are conceptual obligations — what must be true of the output — not a pipeline mandated in code (CP/00 §7, §9).

| Stage | Obligation |
|---|---|
| Interpret | Read intent + goals at capability level — what abilities do these goals imply, in the vocabulary of CP/01 |
| Decompose | Split goals into sub-goals only where a goal is not itself capability-addressable; decomposition is validated, never naive text splitting (CP/00 V1-H6, CP/01 §2) |
| Extract requirements | Each goal/sub-goal names the abilities it needs (§4) |
| Select from registry | Normalize named abilities onto registry ids (§4) |
| Expand dependencies | Recurse over registry-declared relations to fixpoint (§4, CP/01 §8) |
| Propagate constraints | Attach request/capability/cross-capability constraints to nodes and relations (§5) |
| Assign priorities | Importance bands + alternative ranks (§6) |
| Annotate alternatives/conflicts | Group substitutable branches; record mutual exclusions (§3, CP/01 §8) |
| Identify gaps | Mark unfillable or ambiguous requirements (§8) |
| Validate | Run gates (§9) |
| Publish or reject | `plan.created` or `plan.rejected` (§9) |

Every stage is deterministic (CP/00 §9); every stage's contribution is traceable in the final artifact — provenance (§4) is how the graph explains itself, not a separate audit log.

## 3. Discovery

**Three requirement origins** — every node records which one produced it:

| Origin | Meaning | Example shape |
|---|---|---|
| Explicit | Intent names the ability directly | Request literally asks for it |
| Implicit | Entailed by goal semantics + OS discipline | Any mutation goal entails its verification-expectation capability (CP/01 §7); gates are structural, not requested |
| Derived | Introduced by dependency/composition expansion | A selected capability's registry-declared `requires` pulls in another node |

**Domain inference.** Matching goals onto category/facet vocabulary (CP/01 §5) is not a separate mechanism — it is requirement extraction applied per goal. A multi-domain request simply selects capabilities across categories; the flat category + open facet structure (CP/01 §5) makes this ordinary, not a special case requiring cross-domain logic.

**Minimum capability principle.** The graph contains the smallest requirement set whose verification expectations (CP/01 §7) jointly cover the stated goals. Nothing enters without a goal or a dependency justifying it. Mirrors CM's "context is constructed, not collected" (CP/00 §13): here, **plans are constructed, not collected** — no speculative, "might be useful," or convenience nodes.

**Normalization.** Intent-level ability phrasings map onto canonical registry ids via declared aliases (CP/01 §3, §6). CP never invents near-duplicate vocabulary to approximate a phrasing that doesn't cleanly resolve — an unresolved phrasing is a mapping-ambiguity signal (§7), not license to mint an ad hoc id.

**Deduplication.** One registry id = at most one node per graph. A capability needed by multiple goals is a single shared node with multiple inbound `serves-goal` / `requires` edges — never duplicate nodes for the same id.

## 4. Capability Graph semantics

**Why a graph, not a list.** A list cannot express dependency, shared sub-requirements, alternative branches, independent subgraphs, or conflicts without forcing an artificial order onto them. Forcing order at this stage is smuggled scheduling — a fence violation (CP/00 invariant 1, §6: Scheduler owns WHEN).

**Nodes** — capability *requirements*, not capabilities themselves:

| Node field (conceptual) | Purpose |
|---|---|
| Capability id (or gap marker) | References CP/01 timeless vocabulary — the graph never redefines a capability, only cites it |
| Origin / provenance | Explicit / implicit / derived (§3), plus which goal or dependency justified it |
| Situational constraints | This usage instance's constraints (§5) — capability-model relations stay timeless (CP/01 §8); a node is where timeless meets situational |
| Priority band | §6 |
| Node confidence | §7 |

**Edges** — typed, drawn only from CP/01 §8's four relations as exercised by this request, plus one provenance-only relation:

| Edge type | Source | Meaning in this graph |
|---|---|---|
| requires | CP/01 dependency | This node's fulfillment presumes the target node also present |
| composes | CP/01 composition | This node is a declared decomposition of a coarser one |
| alternative-of | CP/01 alternative | Nodes in the same branch group satisfy the same outcome class |
| conflicts-with | CP/01 conflict | Nodes structurally incompatible within one context |
| serves-goal | Provenance only, not a CP/01 relation | Links a root requirement to the stated goal it fulfills — traceability, not a capability relation |

**Roots and leaves.** Roots = goal-level requirements (directly serve a stated goal). Leaves = requirements needing no further expansion — directly fulfillable as declared in the registry.

**Independent subgraphs.** Disconnected components are allowed and expected wherever goals share no capability — no artificial bridging edge is ever added to make the graph "look" connected.

**Shared dependencies.** A dependency needed by more than one branch is one node with fan-in (§3 dedup) — never re-expanded per branch.

**Alternatives.** Represented as a declared branch group with relative rank (§6). The graph records that alternatives exist and their order of preference; it never picks one — selection is scheduling/fulfillment territory (CP/00 §6), strictly downstream of CP.

**Conflicts.** Explicit annotated `conflicts-with` edges. A **published** graph may carry conflicts only between nodes that are mutually exclusive alternative branches (structurally impossible to co-select by construction). A conflict touching the required core is a validation failure, not a publishable annotation (§9).

**Immutability.** A published graph is immutable, same discipline as Request Memory / RSM records (CP/00 §13, §5). Revision is a new graph artifact (`plan.revised`, per the closed event set CP/00 §4) — never an in-place mutation of a published graph.

## 5. Dependency expansion

Recursive expansion over registry-declared `requires` relations to a fixpoint: the registry is finite and a visited-set discipline guarantees termination (no unbounded search — CP/00 §8 latency bar). Direct dependencies expand first; transitive dependencies follow from those, layer by layer, until no new node is admissible.

| Condition | Resolution |
|---|---|
| Dependency cycle in registry data | Registry defect, not a planning puzzle — expansion detects it, planning **rejects** with a reason naming the cycle. CP never breaks a cycle by guessing (CP/00 invariant 9, §11) |
| Dependency target missing (id absent/retired) | Gap node (§8); every node depending on it is marked gap-affected — degradation is visible and transitive, never silently absorbed |
| Registry inconsistency (dangling alias, contradictory declared relations) | Reject with reason — data corruption is not plannable-around |

**Dependency validation = closure check:** every `requires` edge must resolve to a node present in the graph, real or gap. An edge pointing nowhere is not a valid graph state at any stage past expansion.

## 6. Constraint propagation

**Three constraint origins**, each retaining its own ownership (propagation never transfers ownership):

| Origin | Scope | Example source |
|---|---|---|
| Request-level | Inherited by every node in the graph | Budget ceilings, safety limits, scope restrictions from the request itself |
| Capability-local | Applies only to the node it came from | Registry metadata constraints (CP/01 §7) |
| Cross-capability | Recorded on the relation that creates it | A `requires` or `composes` edge whose combination implies a constraint neither node carries alone |

**Propagation is additive-only.** CP records what request and registry declare; it never invents, weakens, or drops a constraint. Ownership of a constraint's *meaning* stays with its origin — CP is a carrier, not an author, of constraint content.

**Conflicting constraints on one node:**

| Where | Resolution |
|---|---|
| Required-core node | Unsatisfiable → reject with reason (CP/00 §11) |
| Optional / alternative-branch node | Branch marked unsatisfiable, excluded from selectable alternatives, recorded — not deleted (gaps beat guessing, §8) |

**Constraint visibility.** Every constraint appears on the published artifact with its origin attached. Scheduler and Verification read constraints from the graph; neither re-derives them — CP is the single point where request/registry constraints become plan-visible (CP/00 §13: "the plan artifact is the entire interface").

## 7. Prioritization

Priority is **importance**, never **order** — this is the load-bearing distinction of this section.

| Band | Meaning |
|---|---|
| CRITICAL | A stated goal fails outright without this node |
| REQUIRED | Needed by a critical-path node via dependency |
| OPTIONAL | Enhances the outcome; the goal survives without it |
| DEFERRED | Recognized as relevant but explicitly out of this request's scope — recorded for the Experience layer, never expanded further |

Bands are deterministic thresholds, policy-as-data (CP/00 §2) — not heuristic judgment calls made per request. Assignment derives strictly from goal linkage (`serves-goal`) and dependency role (`requires` chain to a critical node) — never from a guessed or inferred execution order. Alternatives additionally carry a rank within their branch group (§4), also importance-derived (preference), not order.

**Why priority must never become scheduling.** The instant priority encodes *order*, CP has answered WHEN — a fence violation of CP/00 invariant 1. Scheduler consumes priority as one input among its own concerns (resources, preemption, budgets) and produces the actual order; CP producing an order too would mean two components deciding the same question — exactly the drift the single-owner law (CP/00 §1) exists to prevent.

## 8. Confidence

**Confidence measures uncertainty about WHAT is needed** — resolvable before anything runs. It belongs to planning, not to Verification, which measures whether execution *succeeded*; conflating the two re-creates the V1-H1 cascade pattern CP/00 was built to kill (CP/00 §3, §11).

**Named uncertainty sources**, deterministically aggregated per node and for the whole graph:

| Source | What it captures |
|---|---|
| Classification confidence | Carried forward from the pluggable classifier (CP/00 §3, V1-H1) |
| Mapping ambiguity | An intent phrase resolves to multiple candidate registry ids (§3 normalization) |
| Information incompleteness | Request Memory lacked knowledge the requirement needed |
| Gap presence | A required node has no resolvable target (§9) |

Both per-node and whole-plan confidence are explainable: each value traces to the sources that produced it. Deterministic uncertainty (CP/00 §9): identical inputs yield identical confidence and identical disposition, every time.

**Confidence bands** (config data, CP/00 §2) drive disposition:

| Disposition | Trigger |
|---|---|
| Publish | Confidence within the publishable band, no unresolved gaps in required core |
| Publish-with-fallbacks | Confidence marginal but alternatives/fallbacks cover the shortfall |
| Reject-for-clarification | Confidence below threshold — CP fails loud rather than commit a low-confidence graph (CP/00 §11) |

## 9. Gaps

Gaps are **first-class typed markers**, not silent omissions:

| Gap type | Trigger |
|---|---|
| Unknown ability | Intent names something no vocabulary (CP/01) covers at all |
| Missing capability | Vocabulary should cover it but the registry has no active id (deprecated/retired with no replacement, or never declared) |
| Unsatisfiable constraint | §6 — conflicting constraints with no resolution |
| Ambiguous mapping | §3/§8 — normalization could not settle on one registry id |

**Disposition by region:**

| Region | Rule |
|---|---|
| Required core | Plan carries the explicit gap + a declared fallback, or the plan is rejected — threshold is config data (CP/00 §2). CP never guess-binds to the nearest plausible id (CP/00 invariant 9) |
| Optional region | Publish degraded, gap declared — the graph is honest about what it doesn't cover |

**Gap reporting.** Every gap names: what was wanted, why it's unfillable, and nearest alternatives if any exist. Gaps feed the Experience layer as future-capability signals (CP/00 §13) — a declared gap is actionable and auditable; a guessed binding is a silent wrong branch, the exact V1-H1 failure mode this component exists to prevent.

## 10. Validation & publication

**Gates** — all must pass; each is explicit; failure of any one gate is `plan.rejected` with a named reason; an invalid graph never leaves CP (CP/00 §11, invariant 3):

| Gate | Checks |
|---|---|
| Capability existence | Every non-gap node's id is active in the registry |
| Dependency closure | Every `requires` edge resolves to a present node (§5) |
| Cycle-free | No dependency cycle survived expansion (§5) |
| Constraint consistency | No unresolved conflict in the required core (§6) |
| Conflict resolution | No unresolved `conflicts-with` outside declared alternative-exclusion pairs (§4) |
| Dedup integrity | One registry id → one node (§3) |
| Goal completeness | Every stated goal is covered by ≥1 CRITICAL/REQUIRED node or a declared gap |
| Provenance completeness | Every node's origin is recorded and traceable (§3) |
| Confidence computed | Whole-plan confidence is within a publishable band (§8) |
| Determinism | Identical inputs replay to an identical graph (CP/00 §9) |

**Publication.** Pass all gates → `plan.created` carries the immutable graph artifact (CP/00 §4). Fail any gate → `plan.rejected` with a machine-readable reason. No third outcome exists.

## 11. Completion

Planning is done when, structurally (not heuristically):

1. Dependency expansion reached fixpoint (§5), and
2. Every stated goal is accounted for — covered by a node or declared as a gap (§9), and
3. All validation gates pass (§10).

"Done" is a structural condition CP can check against the artifact itself, never a judgment call about whether the graph "looks complete enough."

## 12. Phase-2 invariants

Immutable for all later CP phases.

1. The graph is the smallest requirement set whose verification expectations jointly cover the stated goals (minimum capability principle) — nothing enters without a goal or dependency justifying it.
2. Every node records its origin (explicit / implicit / derived); every node's presence is traceable from the published artifact alone.
3. Nodes reference CP/01 timeless capability ids; the graph never redefines a capability, only cites and situates it.
4. Edges are drawn exclusively from CP/01's four relations (requires, composes, alternative-of, conflicts-with) plus goal-provenance linkage — no other relation type is admitted.
5. One registry id = at most one node per graph; shared need is shared node with fan-in, never duplication.
6. A published graph is immutable; revision is a new artifact, never in-place mutation.
7. Conflicts may survive publication only between mutually exclusive alternative branches; any conflict in the required core is a rejection, not an annotation.
8. Constraint propagation is additive-only; CP never invents, weakens, or drops a constraint, and ownership stays with the constraint's origin.
9. Priority is importance, never order; CP never encodes execution sequence in a plan artifact.
10. Confidence is a deterministic aggregate of named uncertainty sources, computed per-node and per-plan, and always traceable to its sources.
11. Gaps are explicit, typed, and reported with cause and alternatives; CP never guess-binds a requirement to a capability that doesn't fit.
12. A graph publishes only after every gate in §10 passes; any gate failure is `plan.rejected` with a named reason, and an invalid graph never leaves CP.

---

Status: Phase 2 capability graph planning frozen. Later phases (matching/binding mechanics, if any remain in CP's scope) operate within this graph shape; they never redefine node, edge, priority, confidence, or gap semantics fixed here.
