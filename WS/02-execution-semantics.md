# WS/02 — Execution Semantics

Phase 2 of the Workflow Scheduler (WS) design. Builds within WS/00 (constraints C1-C10 binding)
and defines the semantics of the immutable Execution Workflow artifact of WS/01 (invariants WS-W1
through WS-W12 binding). Conceptual only — no classes, APIs, or algorithms; no retries,
checkpoints, rollback, optimization, or runtime-queue design (later phases). This document is the
authoritative semantic contract for dependencies, readiness, parallelism, synchronization,
ordering, barriers, completion, and consistency of the workflow — it does not decide *when* or in
*what policy order* eligible work is actually dispatched.

---

## 1. Dependency semantics

| Property | Definition |
|---|---|
| What a dependency is | A directional semantic guarantee: the consumer unit's execution may rely on the verified, completed effects of the producer unit |
| Why it exists | CP determined the consumer's capability requirement needs the producer's outcome — a requires-edge |
| Origin | EXCLUSIVELY graph requires-edges (C1, WS-W4). WS evaluates dependencies; it never reinterprets, adds, or drops them |
| Satisfaction condition | Producer unit reaches VERIFIED SUCCESSFUL completion (§7) — execution success AND the required verification verdict |
| What satisfaction grants | A contribution toward the consumer's readiness — necessary, never sufficient. Resource/budget/backpressure admission is a later dispatcher-policy concern |
| Correctness preservation | Structural: dependency edges are frozen in the immutable artifact (WS-W10); satisfaction is evaluated against runtime completion state — the artifact is never edited |

## 2. Execution readiness

A unit is **READY** iff ALL of the following hold:

| # | Condition |
|---|---|
| 1 | The workflow is in the Active lifecycle state (WS/01 §7) |
| 2 | Every incoming dependency is satisfied per §1 |
| 3 | Every gate condition covering its predecessors holds (§6) |
| 4 | If the unit belongs to an alternative branch group, its branch has been SELECTED |

Branch selection is an execution-time act recorded in runtime state, never in the artifact (C2).
Units of unselected branches never become ready — they are recorded as **not-executed**, not
failed (§7).

Readiness is eligibility only. Dispatch timing, ordering among ready units, and admission are
later phases. Readiness evaluation is a **deterministic pure function** of (immutable artifact,
runtime completion/selection state) — identical inputs produce an identical ready set (C7).

## 3. Parallelism

Parallelism is **derived**, never independently authored: two units may execute concurrently iff
no directed path connects them in the DAG (independence = absence of any transitive dependency).
This is a corollary of WS/01 §3 — the DAG is the sole structural truth, and "parallelism sets" in
WS/01 §2 names a derived view, not a stored co-equal truth.

| Guarantee | Statement |
|---|---|
| Observable equivalence | Concurrent execution's observable outcome is indistinguishable from SOME dependency-respecting serial order |
| No partial-effect observation | No unit ever observes a concurrent sibling's partial effects — they are independent by construction; if they weren't, CP would have emitted an edge |
| Arrival order vs. semantics | Runtime completion-arrival order MAY vary; semantic state transitions and eligibility evaluation remain deterministic. Arrival order never changes WHAT becomes ready, only when evaluation observes it |

**Artifact interaction.** Concurrency limits/width are dispatcher policy (later phase). The
artifact only encodes what MAY run concurrently, never what MUST.

## 4. Synchronization

A **synchronization point** is any unit with multiple incoming dependencies (a join). It is not a
separate mechanism — it is the multi-predecessor case of §2 readiness: ALL incoming dependencies
must be satisfied (conjunction, never quorum/race).

| Question | Answer |
|---|---|
| Why it exists | Independent branches produce effects a downstream consumer needs together |
| Downstream protection | The readiness rule itself — a join unit cannot become ready while any predecessor branch is incomplete, so incomplete-predecessor observation is unrepresentable |
| Convergence | Independent branches converge at their common join unit(s) |
| Role of derived views | Stage/level views (WS/01 §3) make joins inspectable but add no semantics |

## 5. Execution ordering

| Concept | Definition |
|---|---|
| Partial order | The artifact encodes the DAG's partial order. Any linearization respecting it is a valid execution order — an equivalence class of correct orders |
| Canonical total order | The artifact additionally defines ONE canonical total order: deterministic linearization using unit ids as total tie-break (WS-W6, CM prioritizer precedent) |
| Canonical order's use | Inspection, replay comparison, and the default when policy expresses no preference |
| Owned by the artifact | The partial order + the canonical linearization |
| Deferred | WHICH valid order actually occurs under priorities/budgets/resource state — later scheduling-policy phases. Policy may choose any dependency-respecting order but must itself be deterministic given identical state (C7) and may never leave the partial order's equivalence class |
| Priority bands | Inputs to that later policy, never encoded sequence (C3) |

## 6. Execution barriers

A **barrier** is a point in the workflow beyond which no successor may become ready until every
unit on the barrier's frontier has reached verified completion.

| Relationship | Detail |
|---|---|
| vs. synchronization | A barrier is a promoted/named synchronization boundary with declared scope (subgraph or whole workflow); a plain join is local to one unit |
| Primary barrier class | **Verification barriers** — the gate-boundary markers of WS/01 §4, structural encoding of Global Law 4 / C5: progress beyond the marker requires the relevant `verify.passed` verdict; no priority fast-tracks it (scheduling.md) |
| Placement | Barriers are visible in the artifact (markers + derivable frontier), placed at derivation time — never improvised at runtime |
| Scope discipline | Barriers exist only where semantics require them (verification contracts); no decorative staging barriers — staging for human inspection comes free from derived level views |
| Resilience anchoring | Checkpoint/rollback anchoring on barriers is a later resilience phase (pointer only, WS/00 §7 principle 6) |

## 7. Completion semantics

| Terminal outcome | Meaning |
|---|---|
| SUCCEEDED | Execution completed AND the required verification verdict passed (§10c). Per-unit verification is the default: every capability carries mandatory verification expectations (CP/01), so success is recognized only at verified success — an exec-completion signal alone is necessary, not sufficient |
| FAILED | Execution failure, timeout, or verification failure |
| NOT-EXECUTED | Member of an unselected alternative branch — terminal, not a failure |

Only SUCCEEDED satisfies outgoing dependencies.

**Failure consequence.** Downstream units with a failed predecessor can never become ready within
THIS workflow — the workflow cannot self-heal structure. Resolution paths:

| Path | Description |
|---|---|
| (a) | Execution-time alternative selection, if the failed unit's group has remaining ranked branches |
| (b) | Replan request → `plan.revised` → a new superseding workflow (C2, WS/01 §6) |

Retry-before-fail semantics are a later resilience phase, explicitly out of scope here — this
section defines only what a terminal outcome MEANS. Completion state lives in RSM/dispatcher
runtime state, never the artifact (WS-W12).

## 8. Workflow consistency

Rules that hold while the workflow is Active:

| Rule | Statement |
|---|---|
| Dependency integrity | No unit executes before all dependencies are satisfied |
| Ordering integrity | Observed execution never contradicts the partial order |
| At-most-once semantic completion | A unit reaches a terminal state exactly once per workflow. Re-execution semantics are deferred to the resilience phase but can never yield two conflicting terminal outcomes |
| Barrier correctness | No successor beyond a barrier is ready before its frontier is verified-complete |
| Deterministic progression | Identical artifact + identical runtime event history → identical unit-state evolution |
| Monotonic unit state | pending → ready → executing → terminal; no backward transition; terminal is final within the workflow |
| Artifact inviolability | No consistency rule is maintained by editing the artifact — all state is external |

## 9. Invariants

| # | Invariant |
|---|---|
| WS-E1 | Readiness requires full prerequisite satisfaction — no partial credit |
| WS-E2 | No dependency bypass — no priority, budget, or policy fast-tracks an unmet dependency (mirror of C5 for dependencies) |
| WS-E3 | Only verified successful completion satisfies a dependency |
| WS-E4 | Units of unselected alternative branches never become ready |
| WS-E5 | Readiness evaluation is a deterministic pure function of artifact + runtime state |
| WS-E6 | Concurrent execution never violates the partial order |
| WS-E7 | Synchronization is conjunctive — all predecessors, never quorum |
| WS-E8 | Unit state progression is monotonic with exactly one terminal outcome |
| WS-E9 | A failed predecessor makes downstream units permanently unready in this workflow — never silently skipped (fail loud, supersede to proceed) |
| WS-E10 | No execution-semantics state is stored in the artifact |

## 10. Ambiguities & canonical resolutions

| # | Ambiguity | Resolution (canon) |
|---|---|---|
| a | Who selects among alternative branches at execution time, and by what rule? | CP/03 locks that selection never mutates artifacts and CP never picks. Selection is a WS runtime act; its policy is defined in the scheduling-policy phase. Default principle locked now: highest-ranked branch whose capability is currently servable, deterministic given identical registry/health state |
| b | Do OPTIONAL/DEFERRED unit failures block workflow completion? | Workflow COMPLETED requires terminal-success of all CRITICAL and REQUIRED units. OPTIONAL/DEFERRED units may end FAILED or NOT-EXECUTED without blocking completion, but their outcomes are always recorded (feeds Experience) |
| c | Per-unit verification vs. only marked gate boundaries? | Per-unit verified completion is the default dependency-satisfaction bar (§7); explicit gate-boundary markers additionally express cross-cutting barriers. A capability whose verification expectation is declared trivially-self-verifying still passes through the same structural gate — uniform path, no bypass lane |

---

Status: Phase 2 complete — semantic contract locked; later phases (scheduling policy, resilience,
optimization, implementation blueprint) consume this contract unchanged.
