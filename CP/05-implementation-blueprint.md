# Capability Planner (CP) — Implementation Blueprint

Bridge between architecture (CP/00–04, IMMUTABLE) and implementation. Authoritative guide for building `src/cp/`. No code, no APIs, no classes, no signatures, no filenames — module names below are conceptual units; the implementation maps each to one source module in the flat `src/cp/` package (layout convention of kernel/ums/rsm/cm). Sources of truth for coders: this blueprint + CP/00–04 invariant lists. Python 3.12+, stdlib only, module-per-commit with selftest, one phase per session.

## Global laws binding every phase

| Law | Meaning here |
|---|---|
| Determinism tuple (CP/04 §1) | Plan = f(request, registry version, priors version, Request Memory hash, config version); artifact stamps all five; forbidden-variability table applies verbatim |
| One interpreter (CP/03 inv 9) | CP is the only component reading raw intent; nothing here forwards raw intent downstream |
| Knowledge gateway (CP/03 §4) | Zero UMS access of any kind; knowledge arrives as an injected Request Memory artifact |
| Registry read-only (CP/01 §9) | Registry consumed via read view; no mutation path may exist |
| Closed events | `intent.classified` / `plan.created` / `plan.rejected` / `plan.revised`; structurally refuse invented names |
| Event-name canon | `intent.classified` (per COMPONENTS spec + CP/00 §4) is canonical; ARCHITECTURE.md matrix row `classify.completed` is stale — matrix fixed in Phase 5 |
| Fail loud | Every rejection carries a machine-readable reason; no silent repair, no guess-binding (CP/02 inv 11-12) |
| Kernel discipline | Log-before-publish; idempotent by event_id; at-least-once safe |

## Module decomposition

Conceptual grouping (documentation only — physical package stays flat):

**Foundation** — the artifact and its inputs.

| Module | Purpose / owns | Never |
|---|---|---|
| plan artifact | Frozen Capability Graph artifact: nodes (id-or-gap, origin/provenance, situational constraints, priority band, node confidence), typed edges (requires/composes/alternative-of/conflicts-with/serves-goal), alternative groups + ranks, gaps, whole-plan confidence, determinism tuple, lineage (predecessor ref), canonical serialization + content hash | Mutation after construction; scheduling/order fields of any kind |
| planning spec | Intake normalization: request identity, intent text, goals, request-level constraints, Request Memory hash + content, RSM state snapshot (injected), registry/priors/config versions → canonical spec + spec hash | Fetching anything itself — all inputs injected by caller |
| events | Closed 4-name set + payload shapes (`plan.created` = {request_id, plan_id, hash, confidence, gap_count, predecessor}) | Any fifth name |
| config view | Policy as data: confidence bands, disposition thresholds, priority band rules, expansion depth cap, gate list | Code branches encoding policy |
| bus double | In-memory bus, own copy (kernel pattern) | Importing another component's double |
| registry double | In-memory read-only capability catalog honoring CP/01 in full: ids, categories, facets, lifecycle states (proposed/active/deprecated/retired), aliases, the 4 relations, metadata incl. mandatory verification expectations, registry version | Write surface; CP-side use in production paths beyond tests |

**Registry side** — CP's reader.

| Module | Purpose / owns | Never |
|---|---|---|
| registry view | Read adapter: id resolution through aliases, lifecycle filtering (active matchable; deprecated matchable + replacement pointer recorded; retired = tombstone, never matchable for new plans), relation lookup, version stamping | Mutation; caching across registry versions; inventing ids |

**Discovery** — intent to named requirements (CP/02 §2-3).

| Module | Purpose / owns | Never |
|---|---|---|
| classifier | Pluggable classification seam + one deterministic built-in strategy; output = label + confidence + alternatives, never bare argmax (V1-H1) | Steering the pipeline alone; model calls |
| decomposer | Goals → sub-goals only where not capability-addressable; validated decomposition (anti V1-H6: adversarial "and"-text must not bloat) | Naive text splitting as the mechanism |
| extractor | Requirement extraction with origin provenance: explicit / implicit (mutation entails its verification-expectation capability) / derived marker space | Inventing requirements without a justifying goal (minimum capability principle) |
| normalizer | Ability phrasings → canonical registry ids via registry view; ambiguity detection (multi-candidate = confidence signal, never a guess) | Minting near-duplicate vocabulary |

**Graph core** — requirements to analyzed graph (CP/02 §4-7).

| Module | Purpose / owns | Never |
|---|---|---|
| graph builder | Node/edge construction, dedup (one id = one node, fan-in), alternative branch groups, independent subgraphs, serves-goal linkage | Ordering semantics; duplicate nodes |
| expander | Dependency fixpoint expansion over registry relations; cycle detection → reject reason; missing target → gap node + transitive gap-affected marking | Breaking cycles by guessing; unbounded search |
| constraints | Additive-only propagation of 3 origins (request/capability-local/cross-capability) with retained ownership; conflict detection; unsatisfiable classification (required-core → reject; optional branch → excluded + recorded) | Inventing, weakening, or dropping constraints |
| prioritizer | Bands CRITICAL/REQUIRED/OPTIONAL/DEFERRED from goal linkage + dependency role; alternative ranks | Encoding execution order |

**Judgment** — confidence and gaps (CP/02 §8-9).

| Module | Purpose / owns | Never |
|---|---|---|
| confidence | Deterministic aggregation of the 4 named sources (classification, mapping ambiguity, information incompleteness, gap presence) per node + whole plan; disposition banding (publish / publish-with-fallbacks / reject-for-clarification) | Unexplainable values; nondeterministic aggregation |
| gaps | Typed gap construction (unknown ability / missing capability / unsatisfiable constraint / ambiguous mapping) with cause + nearest alternatives; region rule (required core vs optional) | Guess-binding; silent omission |

**Publication** — gates and orchestration (CP/02 §10-11, CP/03).

| Module | Purpose / owns | Never |
|---|---|---|
| gates | The 10 validation gates from CP/02 §10, each explicit and individually reportable; all-pass or named-failure | Silent repair; partial pass |
| planner | Pipeline orchestrator: spec → discovery → graph core → judgment → gates → publish (`plan.created`) or reject (`plan.rejected`); log-before-publish; replan entry producing `plan.revised` successor artifacts with lineage; `intent.classified` emission after classification | Mutating published artifacts; retry logic (determinism makes it pointless); scheduling anything |
| persistence | Plan artifact persistence THROUGH a Storage double (ums persistence pattern) — plans are durable per frozen spec; Storage double ships here | Direct disk access; persisting drafts |
| law enforcer | Scan-based checks: no retrieval/similarity, no UMS import, no registry mutation surface, closed events, no scheduling/model/provider references | — |

**Reasoning behind the decomposition.** One stage of CP/02's staged refinement = one module (single owner per responsibility, no overlaps); the artifact/spec/events/config foundation mirrors the proven CM Phase-1 shape; registry view isolates the only vocabulary door; judgment (confidence/gaps) separated from graph mechanics because they consume the whole graph, not single stages; gates separated from planner so validation stays independent of orchestration (CM validator/assembler precedent).

## Internal pipeline (implementation organization, not an algorithm)

spec intake → classify (`intent.classified`) → decompose → extract → normalize (registry view) → build graph → expand dependencies → propagate constraints → prioritize → aggregate confidence + construct gaps → run gates → publish/reject (+ persist on publish). Replan = same pipeline, new spec referencing predecessor plan.

## Module dependency rules

| Rule | Statement |
|---|---|
| Layering | foundation ← registry side ← discovery ← graph core ← judgment ← publication; arrows point downward only (later layers import earlier, never reverse) |
| Foundation isolation | plan artifact, spec, events, config view import nothing from other CP modules |
| Peer isolation | discovery modules never import each other's internals; each consumes the previous stage's output shape |
| Doubles | bus/registry/storage doubles imported only by tests and selftests, never by pipeline modules (injection by caller) |
| External | Only planner touches the bus; only registry view touches the registry; only persistence touches Storage; NOTHING imports ums (law-enforced); rsm read only via injected snapshot in spec intake |
| Stability | foundation is the most stable layer — changes there are architecture changes; publication is the least stable |
| Forbidden | Circular imports; pipeline module importing planner; any module importing a double into production paths |

## State ownership

| State | Owner | Readers | Mutability |
|---|---|---|---|
| Draft graph (in-pipeline) | planner (ephemeral, per invocation) | pipeline stages | Mutable until sealed; never observable outside (CP/03 §3) |
| Published plan artifact | plan artifact instances | everyone downstream | Immutable forever; enforced structurally (frozen containers, CM request_memory pattern) |
| Lineage (predecessor refs) | stamped on artifacts | everyone | Immutable, append-only chain |
| Config snapshot | config view | all modules | Immutable versioned view |
| Registry data | registry double (test) / Plugin Runtime (future) | registry view only | Read-only to all of CP |
| Event log | planner internal log + bus | Observability | Append-only, log-before-publish |

## Error handling ownership

| Failure | Owner | Behavior |
|---|---|---|
| Malformed planning inputs | planning spec | Raise loud at intake; nothing enters the pipeline |
| Classification impossible / degenerate | classifier → confidence | Low confidence, never an exception path; disposition decides |
| Registry inconsistency (cycle, dangling alias, contradictory relations) | expander / registry view | Pipeline aborts → `plan.rejected` naming the defect |
| Missing capability | gaps | Typed gap node, transitive marking, region rule decides disposition |
| Unsatisfiable constraints | constraints | Required core → reject; optional branch → excluded + recorded |
| Gate failure | gates → planner | `plan.rejected` with the named gate + reason; artifact never escapes |
| Publication/bus failure | planner | Log already written (log-before-publish); loud error, no silent retry |
| Persistence failure | persistence | Loud error surfaced to caller; published event already carries the artifact hash |

## Testing strategy

| Layer | Approach |
|---|---|
| Unit (per module) | `__main__` selftest per module + phase test files `tests/test_cp_phase<N>` (unittest, existing style); every module testable with foundation types + doubles only |
| Golden artifacts | Curated fixture corpus: (intent + registry fixture + priors fixture + Request Memory fixture + config) → committed expected graph bytes; introduced Phase 4, grown Phase 5; goldens updated only deliberately with review (CP/04 inv 3) |
| Determinism | Every phase: run-twice byte-identity on that phase's outputs; Phase 4+: full-pipeline replay identity — a gate, not a metric |
| Regression | Full suite (kernel+ums+rsm+cm+cp) green before and after every phase; golden diffs |
| Compatibility/replay | Phase 5: replay goldens against grown registry fixtures — append-mostly proof (CP/04 §6); replay uses plan-recorded registry version |
| Validation testing | Each of the 10 gates gets one targeted bad-artifact fixture that only that gate catches |
| Adversarial | V1-H1 fixture (ambiguous intent must yield low confidence, not wrong commit); V1-H6 fixture ("and"-heavy text must not bloat the graph) |
| Independence rationale | CP is the steering component; end-to-end-only testing would hide which authority erred (CP/04 §7) — every module independently verifiable |

## Implementation phases

**Phase 1 — Foundation & vocabulary door.** Modules: plan artifact, planning spec, events, config view, bus double, registry double, registry view. Milestone: artifact + spec fully specified, deterministic, serializable; registry readable with alias/lifecycle semantics. Tests: artifact immutability + byte-identical replay + hash determinism; spec-hash order-independence; event closure; registry view resolution (alias chains, deprecated pointer, retired tombstone, version stamp). Complete when: selftests + phase tests green, existing 253 tests untouched.

**Phase 2 — Discovery.** Modules: classifier (seam + deterministic default), decomposer, extractor, normalizer. Milestone: intent → named, origin-stamped, registry-normalized requirements. Tests: confidence + alternatives always present (no bare argmax); adversarial decomposition; implicit-requirement entailment (mutation goal pulls verification capability); ambiguity detected not guessed; determinism across shuffled inputs. Depends: Phase 1.

**Phase 3 — Graph core.** Modules: graph builder, expander, constraints, prioritizer. Milestone: requirements → analyzed graph (deduped, expanded to fixpoint, constrained, prioritized). Tests: fixpoint termination; cycle → named rejection; missing dep → gap + transitive marking; one-id-one-node fan-in; additive-only constraints with origin retention; band assignment from goal linkage; no ordering anywhere. Depends: Phase 2.

**Phase 4 — Judgment & publication.** Modules: confidence, gaps, gates, planner. Milestone: first end-to-end `plan.created` / `plan.rejected` / `plan.revised` with lineage; golden corpus started. Tests: 4-source aggregation traceability; disposition bands; all 10 gates individually; end-to-end determinism (byte-identical replay); replan lineage; log-before-publish; V1-H1/H6 adversarial fixtures. Depends: Phase 3.

**Phase 5 — Persistence, enforcement, integration.** Modules: persistence (+ Storage double), law enforcer. Plus: golden corpus completion; compatibility/replay tests (registry growth proof); integration tests consuming a REAL `src/cm` Request Memory artifact and RSM snapshot as injected inputs; ARCHITECTURE.md event-matrix reconciliation (`classify.completed` row → `intent.classified`; verify `plan.revised` row present; add rows if missing); CP docs status table appended to this blueprint. Tests: persistence through Storage double only; law enforcer green across `src/`; full suite green. Complete when: CP done, blueprint audit (module-by-module vs this table) reported.

Dependency graph: strictly linear 1→2→3→4→5. Each phase leaves repo production-ready; commit + push + stop per phase; fresh session per phase.

## Implementation invariants (CP-IMPL — every contributor obeys)

1. No architectural shortcuts: CP/00–04 invariant lists are review gates; deviation = defect.
2. No hidden state: everything influencing a plan is in the determinism tuple; no caches that survive an invocation, no ambient reads (clock, env, locale).
3. No implicit capability creation: every id in a graph resolved through registry view or declared as a typed gap.
4. No registry mutation: no write path may exist, even in doubles' production-facing surface.
5. No retrieval logic, no UMS import, no similarity code — law-enforced.
6. No scheduling logic: no ordering fields, no execution sequence, anywhere.
7. No plugin/provider awareness: capability ids only; no provider names in any artifact or module.
8. No model awareness: no model names, prompts, or LLM calls; classification is deterministic code behind a seam.
9. Published artifacts structurally immutable; revision = new artifact with lineage.
10. Closed event set; log-before-publish; idempotent by event_id.
11. Every rejection machine-readable: gate name + reason; silence is a defect.
12. All inputs injected: pipeline modules never fetch; the caller (tests today, Kernel wiring later) supplies spec inputs, registry view, bus.
13. Confidence is computed, never asserted: every value traceable to its 4 sources.
14. `ponytail:` comments mark deliberate ceilings + upgrade paths; interpretation calls reported per phase.

## Roadmap summary

| Order | Phase | Yields |
|---|---|---|
| 1 | Foundation & vocabulary door | Artifact, spec, events, config, doubles, registry view |
| 2 | Discovery | Intent → normalized requirements |
| 3 | Graph core | Requirements → analyzed graph |
| 4 | Judgment & publication | End-to-end plans + goldens |
| 5 | Persistence, enforcement, integration | Durable plans, law enforcement, real-CM/RSM integration, matrix reconciliation |

Status: blueprint frozen. Implementation may begin at Phase 1; no further architectural decisions required.
