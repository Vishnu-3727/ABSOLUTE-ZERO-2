# WS/01 — Execution Workflow: Architectural Spec

Phase 1 of the Workflow Scheduler (WS) design. Builds within WS/00 (architectural foundation,
constraints C1-C10 binding here) and consumes CP/02 (Capability Graph). Conceptual only — no
classes, APIs, schemas, code, scheduling algorithms, or retry/rollback/checkpoint mechanics
(later phases).

---

## 1. Definition

**Execution Workflow** = the immutable, deterministic compilation of a sealed Capability Graph
into an execution plan.

The graph answers **WHAT** abilities are required — timeless requirements and their relations. The
workflow answers **HOW** execution is organized — order, concurrency, synchronization. Two
distinct artifacts because:

| Reason | Detail |
|---|---|
| Different questions | WHAT vs. HOW (WS/00 §7 principle 1 — one question per component) |
| Different evolution triggers | Graph changes on replan (`plan.revised`); workflow changes on re-derive from a (possibly unchanged) graph plus config |
| Different owners | CP owns the graph; WS owns the workflow (C1, C4) |

**Why it exists:**

- Dispatch never re-derives ordering — the hot path reads a precompiled structure, it never plans (WS/00 §7 principle 5).
- Execution is reproducible: identical sealed graph + WS config version → byte-identical workflow — the same determinism discipline as CP/04 §1 and CM's memory_id precedent.
- The plan is inspectable by humans and Verification before anything runs (WS/00 §4, gate 2 of the three-gate split).
- Plans are reusable and cacheable — an OS-level goal: minimal reasoning cost, reusable execution plans (WS/00 §7 principle 7).

**Immutability.** Once produced, the workflow does not change. All runtime progress state — what's
dispatched, what's completed, what's waiting — lives in RSM/dispatcher state, **never** in the
artifact itself.

**Determinism tuple (conceptual form, precise analog of CP/04 §1).** workflow = f(sealed plan
artifact id + version, WS config version). The only acceptable source of a different workflow for
the same graph is a declared WS config change — never wall-clock time, ordering, hash
randomization, or ambient environment. This is the same determinism discipline CP/04 established
for the graph, carried one artifact downstream.

## 2. Relationship with the Capability Graph

| Preserved (verbatim / by reference / copy-with-provenance) | Added by WS | Never modified |
|---|---|---|
| Capability requirement node ids + cited capability ids | Execution units | Dependency semantics |
| Requires-edges (sole dependency truth, C1) | Derived execution ordering (topological structure) | Alternative rankings (WS never selects a branch at compile time — selection is execution-time and never mutates artifacts, C2) |
| Alternative branch groups with CP ranking | Parallelism sets | Intent |
| Priority bands | Synchronization boundaries | Priority band VALUES (bands are input expressing importance; ordering derived from them is WS's output, C3) |
| Constraints | Workflow identity + versioning metadata | |
| Provenance/goal links | The determinism tuple (source plan artifact id + version, WS config version) | |
| Gap markers | Gate-boundary markers (where a verify verdict is required before progress) | |

**Ownership.** CP owns the Capability Graph; WS owns the Execution Workflow. The workflow
**references** the source plan artifact by id + version — it does not become a second authority
on capability semantics.

**Late binding preserved (C4).** Execution units carry capability ids, never plugin/provider ids.
Provider churn never invalidates a workflow, exactly as it never invalidates a graph.

## 3. Representation evaluation

| Representation | Strengths | Weaknesses | Determinism | Inspectability | Recovery suitability | Future-optimization suitability |
|---|---|---|---|---|---|---|
| Pure DAG | Preserves maximal legitimate parallelism; direct 1:1 mapping from graph requires-edges | No inherent notion of "phase" for humans to reason about at a glance | High — structure is a pure function of the graph | Moderate — requires traversal to see "what runs together" | Good — any node's dependents are locally computable | Good — nothing to unlearn before adding fusion/reordering later |
| Stage-based (linear phases) | Simple mental model; easy progress reporting | Serializes independent work into artificial phases; loses graph fidelity where true parallelism existed | High, but the flattening itself is a lossy transform | High for a shallow plan; misleading for a deep one | Coarse-grained only — a stage boundary is not a real synchronization need | Poor — collapsing parallelism up front makes it unrecoverable later |
| Layered execution graph (DAG + computed levels) | Adds inspectable structure without discarding the DAG | Extra derived structure to keep synchronized with the source | High if levels are a pure function of the DAG | High — levels read like stages, but honestly | Good — levels double as natural checkpoint anchors | Good |
| Hybrid: DAG + derived stage views | Same benefits as layered, generalized: any number of derived views (stage, level, critical-path) can coexist | None, provided every view is provably derived, never independently authored | High — all views are pure functions of one DAG | High — pick the view that suits the audience | Good | Good |

**Conclusion (LOCKED).** Canonical representation = **DAG of execution units**. Stages/layers are
deterministically **derived** views, never independent truth.

**Rationale.**

1. A single source of structural truth prevents dual-truth drift — the same disease as the
   ARCHITECTURE-matrix event drift (WS/00 §6).
2. The DAG preserves maximal legitimate parallelism that a stage-based representation would flatten.
3. Derived layering gives stage-based inspectability and natural synchronization/checkpoint
   anchors for later (resilience) phases, without paying stage-based costs now.
4. Derivation is a pure deterministic function of the DAG, so any view can be recomputed
   identically at any time — nothing to keep in sync by hand.

Pure stage-based is rejected outright (serializes independent work, loses graph fidelity). Storing
both graph-as-DAG and stages as co-equal truth is also rejected (drift risk — exactly the failure
mode this conclusion exists to avoid).

## 4. Workflow components (conceptual inventory)

| Component | Role |
|---|---|
| Identity & versioning metadata | Names this workflow artifact and its version |
| Provenance metadata | Source plan artifact id + version, WS config version — the reproducibility tuple (§1, §6) |
| Execution units | The 1:1 compiled form of graph requirement nodes (§5) |
| Dependency edges | Derived one-to-one from graph requires-edges — never invented, never dropped |
| Alternative branch groups | Carried unresolved, with CP ranking intact — WS never resolves them at compile time |
| Synchronization boundaries | Derived from the DAG structure — where concurrent units must rejoin |
| Gate-boundary markers | Which units require `verify.passed` before successors dispatch — structural encoding of Global Law 4 / C5 |
| Scheduling constraint annotations | Priority bands + budget-relevant constraints, carried as declarative inputs for later dispatcher phases — no policy lives here |
| Planning metadata | Derivation notes for inspection and audit |

## 5. Execution Units

**Definition.** The smallest schedulable and independently verifiable unit of work.

**LOCKED: strict 1:1.** One execution unit per capability requirement node of the sealed graph —
in this architecture, no grouping and no fusion.

| Property | Rule |
|---|---|
| Cardinality | Exactly one unit per graph requirement node — no dropped nodes, no invented units (§8 WS-W2) |
| Relation to capability | Unit cites the requirement node id + capability id; it does not redefine capability semantics |
| Verification expectations / contracts | Remain CP/registry-owned; the unit carries a reference, never a redefinition |
| Identity | WS owns unit identity + execution attributes; unit ids are deterministically derived from (workflow id, source node id) — no random ids, same discipline as CM's memory_id precedent |

**Future upgrade path (not present scope).** Grouping/fusion of units into coarser schedulable
blocks is a possible future optimization, decided in a later optimization phase. If ever
introduced, fused units must (a) preserve per-capability verification expectations, and (b) retain
provenance to the original requirement nodes they replace. This document locks the 1:1 baseline
only — it does not design the fusion mechanism.

## 6. Immutability

| Concern | How immutability serves it |
|---|---|
| Reproducibility | Replay = re-dispatch the same artifact; no re-derivation step to introduce drift |
| Debugging / audit | The plan that ran is exactly the plan that was produced — no in-flight edits to explain away |
| Deterministic execution (C7) | Dispatch reads a frozen structure; identical verdict/budget state → identical dispatch order |
| Replanning interaction | Execution failure → replan request → CP emits `plan.revised` (a new graph artifact) → WS compiles a **new** workflow that **supersedes** the old. The old artifact is retained for audit, never edited (C2) |

**Runtime state exclusion.** Progress state — what has dispatched, what has completed, what is
waiting on a gate — lives in RSM and dispatcher working state, never in the workflow artifact. RSM
is a downstream telemetry mirror of WS state transitions (WS/00 §4); it is never a control input
back into the artifact.

## 7. Lifecycle

| State | Meaning |
|---|---|
| Derived | Compilation output, internal — not yet checked |
| Validated | WS structural gates passed (§8 invariants); also subject to pre-scheduling plan admissibility verification per the three-gate split (WS/00 §4, CP/03 — gate 2) |
| Published | Immutable, announced on the bus |
| Active | Driving dispatch |
| Completed | All units resolved, workflow's execution lifecycle ended normally |
| Superseded | Replaced by a workflow compiled from a `plan.revised` graph |
| Rejected | Failed structural gates — **never published** |
| Retained | Append-only history for audit/replay — same artifact discipline as CP/04's lineage guarantee |

**Invalid workflows are never published.** Fail loud, no partial publication — same discipline as
CP/02 §10's gate-or-reject rule.

**No third outcome.** As with CP/02's plan lifecycle, a compiled workflow either reaches Validated
and proceeds to Published, or it fails a structural gate and is Rejected — there is no partially-
published or provisionally-active state.

## 8. Architectural invariants

| # | Invariant |
|---|---|
| WS-W1 | Acyclicity — the execution DAG contains no cycle |
| WS-W2 | Complete coverage — every graph requirement node maps to exactly one execution unit; no dropped node, no invented unit |
| WS-W3 | No duplicate units — one unit per requirement node, never more |
| WS-W4 | Dependency fidelity — every workflow dependency edge traces to a graph requires-edge; no invented dependencies, no dropped ones |
| WS-W5 | Deterministic byte-stable output — identical sealed graph + WS config version → identical workflow |
| WS-W6 | Deterministic total tie-break ordering — unit ids are baked into ordering keys; never input-order or hash-order dependent (CM prioritizer precedent) |
| WS-W7 | Capability semantics preserved — units cite capabilities, never redefine them |
| WS-W8 | Alternatives carried unresolved — compile-time branch selection is forbidden |
| WS-W9 | Gate boundaries structurally present wherever the graph or verification contract requires them — no representable way to schedule around a gate |
| WS-W10 | Immutability after publication — any change is a new artifact plus supersede, never an in-place edit |
| WS-W11 | Late binding — no plugin/provider identifiers anywhere in the artifact |
| WS-W12 | Runtime-state-free — the artifact contains no mutable progress fields |

## 9. Ambiguities identified & canonical recommendations

| # | Ambiguity | Status / recommendation |
|---|---|---|
| a | Event drift from WS/00 §6 (`task.dispatched`/`backpressure.engaged` vs. matrix `task.started`/`task.completed`) | Still open — resolved in the implementation blueprint phase. This document takes no dependency on either disputed name. |
| b | No `workflow.*` event exists in the ARCHITECTURE.md matrix or scheduling.md — the workflow artifact's publication announcement has no canonical event name yet | Recommendation: the implementation blueprint proposes the canon (likely a `workflow.created`-style row) and fixes the matrix in the final phase, same pattern as CP's `classify.completed` fix. Do not add the event to any doc outside this note. |
| c | scheduling.md specifies queue state persists via Storage but is silent on workflow-artifact persistence | Recommendation: workflow artifacts persist via Storage (double until real Storage exists), consistent with CP plan persistence. Final call deferred to the implementation blueprint. |

---

Status: Phase 1 complete; Phase 2+ = scheduling policies (ordering/dispatch), then resilience
(retry/rollback/checkpoints), per Vishnu's phase prompts.
