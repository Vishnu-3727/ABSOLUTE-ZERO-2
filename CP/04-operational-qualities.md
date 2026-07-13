# Capability Planner (CP) — Phase 4: Operational Qualities & Final Assessment

Long-term operational qualities and closing architectural assessment. Conceptual only — no algorithms, APIs, schemas, storage, scheduling/execution/plugin/prompt/verification internals. Builds on CP/00 (foundation), CP/01 (capability model), CP/02 (graph planning), CP/03 (integration); nothing here restates them beyond citation, and nothing here adds new planning behavior — this phase only fixes how the already-frozen design behaves over time.

---

## 1. Determinism (operational)

The determinism tuple (CP/03 §11 invariant 13, precise form): **plan = f(request, registry version, priors version, Request Memory hash, config version)**. Acceptable variability is exactly a change in one of these five declared inputs — nothing else.

| Forbidden variability | Why it's forbidden |
|---|---|
| Wall-clock time | Not a declared input; a plan may not differ by when it was computed (CP/00 §7) |
| Iteration/dict/set ordering | Internal mechanics, not a declared input; graph shape must not depend on incidental ordering |
| Hash randomization | An ambient runtime setting, not a declared input |
| Concurrency/races | Two runs of the same tuple must converge to one artifact, not a race-dependent one |
| Ambient environment (env vars, locale, filesystem state) | Not part of the tuple; CP touches no filesystem and reads no repository (CP/03 §4) |
| Retry count | At-least-once redelivery must replay to the identical plan (CP/03 §2) — retry is not a sixth input |
| Hidden caches | Any cache is either irrelevant to output (pure speedup) or it is a smuggled sixth input; the latter is forbidden |
| Model calls | CP never calls a model (CP/00 §7, invariant 6) — no such source exists to vary |

**Deterministic uncertainty.** Confidence values are not a side effect of planning — they are part of the deterministic output. Same tuple → same confidence, same band, same disposition, every time (CP/02 §8).

**Reproducibility = artifact reproducibility.** Replaying the five inputs yields the byte-identical graph. This is what "reproducible" means for CP; there is no separate notion of reproducibility that doesn't reduce to re-running the tuple.

**Long-term reproducibility.** A plan stays replayable only if the tuple's five components are individually retrievable years later: the artifact itself, plus the registry/priors/config version identifiers it was planned against, plus the Request Memory hash (not necessarily the memory content — the hash is what the tuple binds to). Retention of these identifiers is a Storage/Observability contract (CP/03 §12, §14), not new CP behavior.

**Explainability is determinism's twin.** Because output is a pure function of declared inputs, the artifact plus the event stream can explain every decision without touching CP internals (CP/03 §12) — explainability is not a separate mechanism bolted onto determinism, it is what determinism looks like from outside CP.

---

## 2. Extensibility

Everything new arrives as **data through existing contracts** — no CP code changes, no new planning semantics.

| New thing | How it enters |
|---|---|
| New capability / domain / science | Registry row + category/facet values (CP/01 §5, §10) |
| New reasoning paradigm | New capability + provider declaring fulfillment — late binding (CP/03 §9) |
| New hardware target | New capability + provider — same path, no CP awareness of hardware |
| New language / provider ecosystem | New capabilities + providers through Plugin Runtime (CP/03 §7) |

**What never changes with content growth.** Staged refinement (CP/02 §2), graph shape (CP/02 §4), gates (CP/02 §10), and the confidence model (CP/02 §8) are content-agnostic — they describe *how* CP plans, not *what* it plans over. A registry ten rows deep and a registry ten million rows deep are planned against by the identical semantics.

**The one extension that is not data.** A new capability **relationship type** beyond CP/01's four (CP/01 §8) or a new **event name** beyond the closed set (CP/00 §4) is an architecture change by definition — both are structural to the vocabulary/contract, not content within it. Everything else — including entirely new domains — is silent growth.

---

## 3. Registry evolution

Growth is append-mostly (CP/01 §9). One operational decision this phase adds, not previously stated:

| Situation | Rule |
|---|---|
| Replaying a historical plan | Uses the **registry version recorded on that plan** — historical fidelity; replay must reproduce what was actually planned, not what would be planned today |
| Planning a new request | Always uses the **current** registry — no version pinning for new plans |
| Why no pinning for new plans | Pinning a "stable" registry version for new planning would fork vocabulary authority — two live truths about what capabilities exist, which is exactly the divergent-authority failure CP/03 §6 rules out at the Scheduler seam, recreated here at the registry seam |
| Deprecated capability, new plan | Matchable for compatibility (CP/01 §6) but discouraged; if bound anyway, the plan records that fact plus the replacement pointer — the deprecation is visible on the artifact, never silently absorbed |
| Retired id, replay | Never matchable for new planning; a replay encountering a retired id resolves it **historically** via its tombstone — the id is permanent (CP/01 §3), so the historical meaning is always recoverable even though the id can never be bound again |

**Governance.** Registry stewardship — curation, category additions, lifecycle transitions — is Plugin Runtime's ownership (CP/01 §9, §12 invariant 10). Category additions are explicit architectural decisions (CP/01 §5). CP consumes the registry; it never governs it, at any point in this lifecycle.

---

## 4. Artifact lifecycle

| State | Meaning | Observable? |
|---|---|---|
| draft | In-progress graph construction (CP/02 staged refinement) | Never — CP-internal, ephemeral (CP/03 §3) |
| published | `plan.created`, immutable forever (CP/02 §4) | Yes — the artifact of record |
| consumed | Read by Scheduler/Verification; RSM mirrors a reference | Yes — via reads, not mutation |
| superseded | `plan.revised` produced a successor | Yes — predecessor stays valid history, never deleted (CP/03 §3, §6) |
| retained | Append-only history via Storage/Observability | Yes — per their own contracts (CP/00 §13) |

**Lineage.** Revision chain + determinism tuple, per artifact. Any historical plan is re-derivable (replay the tuple) and re-explainable (artifact + event stream) at any point in the future.

**Reliability as historical record.** Follows directly from three already-fixed properties, not a new guarantee: immutability (CP/02 §4 invariant 6) + recorded input versions (§1 above) + provenance-complete nodes (CP/02 invariant 2). Together they mean a plan read five years from now carries the same meaning it carried the day it was published.

---

## 5. Quality model

Attributes CP is judged on long-term. Performance-tuning attributes (latency numbers, throughput targets) are excluded on purpose — see note below the table.

| Attribute | Binding meaning for CP | How observed |
|---|---|---|
| Correctness | Published graphs satisfy all CP/02 §10 gates | Structural, machine-checkable against the artifact |
| Completeness | Every stated goal covered by a node or a declared gap (CP/02 §10, §11) | Goal-completeness gate |
| Determinism | 100% replay identity — not a target, a gate | Replay the tuple, byte-compare |
| Explainability | Artifact self-explains every decision | Artifact + event stream alone, no CP internals (CP/03 §12) |
| Predictability | Same request class → structurally similar graphs; no surprise nodes | Minimum capability principle (CP/02 §3) makes this checkable, not aspirational |
| Replaceability | CP swappable behind its event + artifact contract; internals swappable behind seams | Contract compatibility only (CP/00 §12) |
| Modularity / maintainability | Classifier, decomposer, matcher independently replaceable | Seam boundaries (CP/00 §7, §12) |
| Observability / auditability | Every decision in the event stream; lineage reconstructable | CP/03 §12 |
| Robustness | All failure is a declared rejection with reason; no crash path | `plan.rejected` is the only failure exit (CP/00 §11) |
| Consistency | Same vocabulary reading as every other component | Ids resolve from CP/01 only, never a private synonym |
| Scalability | Bounded by registry size + graph fixpoint, never by repository size | CP never touches the repository (CP/03 §4) |
| Reliability | Idempotent consumption, at-least-once safe | CP/03 §2 retry philosophy |

**Why performance-tuning attributes are excluded.** Latency is bounded-by-construction: capability matching is a registry lookup and dependency expansion is a finite fixpoint (CP/00 §8, CP/02 §5) — the *shape* of the bound is architecture, but a numeric millisecond target is an implementation benchmark, not a design decision this document can fix. Naming a number here would smuggle an implementation detail into a phase that promised none.

---

## 6. Benchmarking philosophy

Benchmarks are **fixture-based and deterministic** — golden scenarios against golden artifacts, never live-model or statistical evaluation. Nothing stochastic exists inside CP to sample (CP never calls a model, CP/00 invariant 6), so there is nothing a statistical eval would even measure.

| Conceptual metric | What it checks | Owner of the underlying data |
|---|---|---|
| Discovery precision | No false-positive capability nodes (violates minimum capability principle, CP/02 §3) | CP |
| Discovery recall | No false-negative — goal left uncovered without a declared gap | CP |
| Graph validity rate | Fraction of runs passing all CP/02 §10 gates | CP |
| Dependency + constraint correctness | Expansion and propagation match fixture expectation | CP |
| Gap quality | Every gap names cause + nearest alternative (CP/02 §9) | CP |
| Determinism rate | Must be 100% — a gate, not a metric with a target below 100 | CP |
| Replay reproducibility across versions | Old goldens replay identically against the registry version they were planned against (§3) | CP |
| Explainability | Artifact-only audit answers every "why" without internals | CP |
| Registry coverage | Fraction of scenario-corpus goals plannable without gaps | **Registry health**, surfaced by CP, not a CP score |
| Evolution stability | Registry growth never changes existing fixture outputs — the append-mostly proof, empirically | CP + Registry jointly |
| Latency bound | Relative — proportional to graph size, never to repository size | CP |

**Success criterion.** All structural gates pass, always; precision/recall meet or exceed golden fixtures; zero determinism violations, ever — not "rare," zero.

---

## 7. Testability

CP is testable **fully in isolation** — every neighbor has a contract-faithful double. Built neighbors (Kernel, UMS, RSM, CM) already have doubles in `src/`; future neighbors (Scheduler, Plugin Runtime, Experience) arrive as doubles first, per CP/00 §5's foundational assumption — this is not a new commitment, it is that assumption exercised at Phase 4.

| Element | Definition |
|---|---|
| Reference planning scenario | (intent, registry fixture, priors fixture, Request Memory fixture) → expected graph |
| Golden artifact | The committed expected graph for a scenario |
| Regression | Byte-diff against the golden; any diff is either a defect or a consciously versioned golden update |
| Golden update discipline | Reviewed, never silent — a changed golden is itself a reviewable change, same as a code change |
| Compatibility testing | Replay old goldens against new registry versions to empirically prove append-mostly evolution (§3, §6) doesn't disturb historical plans |

**Why independent testability matters.** CP is the pipeline's steering component. Testing it only end-to-end would hide *which* authority made a wrong decision when something fails downstream — the same diagnosis failure V1 suffered when one component quietly answered two questions (CP/00 §1, CP/03 §6). Isolated testability is what makes the single-owner law auditable, not just declared.

---

## 8. Resilience

Mostly fixed by prior phases; this section consolidates, it does not add new failure modes.

| Input class | CP behavior |
|---|---|
| Malformed input | Reject with reason — loud (CP/00 §11) |
| Unknown intent | Low classification confidence → reject-for-clarification (CP/02 §8) |
| Incomplete context | Information-incompleteness confidence source (CP/02 §8, CP/03 §5) |
| Registry inconsistency | Reject — a data defect, not a planning puzzle (CP/02 §5) |
| Missing capability | Typed gap (CP/02 §9) |
| Future capability (requested, not yet existing) | Gap that feeds Experience as a capability-evolution signal (CP/02 §9) |

**Rejection is not degradation.** Rejection is loud and terminal for the attempt. Degradation — publishing with declared gaps in optional regions — is explicit and recorded (CP/02 §9 disposition-by-region table). The two are not points on a spectrum; they are different outcomes with different visibility guarantees, and conflating them would hide which one happened.

**Forward compatibility.** Unknown metadata fields on a registry entry are ignored-but-preserved conceptually — CP reads what CP/01 §7 defines and nothing past that; extra data passes through untouched, available to whoever added it.

**Backward compatibility.** Every published artifact remains readable and replayable forever — a direct consequence of immutability (CP/02 §4) plus tombstoned ids (CP/01 §6) plus recorded input versions (§1 above).

**Principle.** Resilience is predictable behavior under every input class, never best-effort guessing. A gap and a rejection are both *answers*; a guess is not.

---

## 9. Maintenance & governance

| Concern | Rule |
|---|---|
| Architectural governance | The invariant lists (CP/00 §14, CP/01 §12, CP/02 §12, CP/03 §15) are the review gates — any change touching one is an architecture change requiring its own review, with errata discipline (precedent: CP/00 §13's UMS amendment) |
| Capability review / registry stewardship | Plugin Runtime ownership, exercised through CP/01's lifecycle states (§3 above) |
| Evolution policy | Append-mostly everywhere — registry, artifacts, history alike |
| Deprecation philosophy | Deprecation over deletion, always, with alias pointers (CP/01 §6) |
| Version compatibility | Registry, priors, and config versions are all declared tuple inputs (§1); skew between them is visible in the tuple, never silent |

**What this section is not.** It invents no new governance body and no new process — it names where the existing invariant lists already function as governance, so that a future maintainer knows the review gate exists before they touch one.

---

## 10. Future evolution

| Development | How it integrates | What changes in CP |
|---|---|---|
| Autonomous scientific research | New categories/capabilities — data (CP/01 §10) | Nothing |
| Multi-agent planning | Agents are providers fulfilling capabilities (late binding, CP/03 §7); if agent-*coordination* itself needs representing, that's a new capability | Nothing — CP still answers WHAT per request |
| Robotics / edge / cloud / distributed execution | Execution-layer and Scheduler concerns; plans stay abstract | Nothing — location/topology of fulfillment is HOW/WHERE, never CP's question (CP/00 §1) |
| Novel reasoning engines / future AI paradigms | Reasoning Engine swaps behind its fence (CP/03 §9) | Zero impact — model neutrality is absolute |
| Future provider ecosystems | Registry + Plugin Runtime (CP/03 §7) | Nothing |

**The constant.** CP's question — WHAT abilities are required — survives every one of these developments unchanged. If a future development seems to require CP to answer a *second* question, that is a new component to design, not a CP extension to design into this one. This is the same single-owner law from CP/00 §1 and CP/03 §6, restated as a forward-looking test rather than a present-tense rule.

---

## 11. Final architectural assessment

**What CP is.** The single interpreter of intent and single author of plans. Nothing upstream of CP independently reinterprets raw intent (CP/03 invariant 9); nothing downstream re-derives what CP already decided (CP/03 §6, invariant 3).

**Boundaries.** The four-phase fence set: CP/00 fixes the walls (philosophy, assumptions, terminology, invariants); CP/01 fixes the vocabulary CP plans against; CP/02 fixes graph semantics — what a valid plan *is*; CP/03 fixes every contract with every neighbor. Four fences, one component, no phase re-opens an earlier one except by declared errata.

**Guarantees.** Deterministic, explainable, immutable, gap-honest plan artifacts — every word in that sentence is a section of this document (§1, §1, §4, §8) plus its grounding in CP/00–03.

**Assumptions carried forward, not re-litigated here.** Validated inputs (admission legality decided upstream, CP/03 §2); CM-gated knowledge (single knowledge channel, CP/03 §4–5); registry stewardship elsewhere (§3, §9 above); contract-faithful doubles standing in for unbuilt neighbors (§7 above, CP/00 §5).

**Contracts.** CP/03's matrix (§14 there) is exhaustive and is not restated here; this document adds operational behavior *within* that matrix, not new entries to it.

**Qualities.** This document, in full — determinism as operational discipline, extensibility as pure data-growth, registry evolution with a resolved replay-vs-new-plan rule, an artifact lifecycle with historical reliability, a quality model that excludes implementation benchmarks by design, fixture-based benchmarking, isolated testability, resilience as predictable behavior under every input class, governance anchored to the existing invariant lists, and a future-evolution test that survives every named development without touching CP's core question.

**Long-term role.** CP is the stable translation layer that lets everything above it (intent, users) and everything below it (providers, models, hardware) churn independently for the operating system's lifetime. Neither side needs to know the other is changing.

**Declaration.** CP architecture is **COMPLETE**. Five documents (CP/00 through CP/04) are sufficient for implementation without further architectural decisions. Implementation phases may begin.

---

## 12. Phase-4 invariants

Distilled, not new — each restates a rule already argued above with its section reference.

1. The determinism tuple — (request, registry version, priors version, Request Memory hash, config version) — is the only source of acceptable variability; wall-clock time, ordering, hash randomization, concurrency, ambient environment, retry count, hidden caches, and model calls are all forbidden variability (§1).
2. Replay uses the registry version recorded on the plan; new planning always uses the current registry — no pinning (§3).
3. Golden artifacts are versioned deliberately, reviewed, never silently updated (§7).
4. Evolution is append-mostly everywhere — registry, artifacts, history (§3, §4, §9).
5. A new capability relationship type or a new event name is an architecture change, never ordinary extension (§2).

---

Status: Phase 4 operational qualities frozen. CP architecture complete — CP/00 through CP/04 are the entire design; implementation may begin within these walls.
