# Capability Planner (CP) — Phase 0: Architectural Foundation

Immutable architectural reference for all later CP design phases. This document designs NOTHING — no algorithms, APIs, classes, data structures, or implementations. It fixes the environment, assumptions, philosophy, terminology, and constraints that every later phase must assume. Where this document and `ARCHITECTURE.md` / `COMPONENTS/capability-planning.md` overlap, they must agree; conflicts found later are architecture changes, not patches.

## 1. Operating-system philosophy

ABSOLUTE-ZERO V2 is a Model-Agnostic Agentic Operating System — not an AI agent, not a framework, not a workflow engine. It coordinates intelligent execution across models, plugins, tools, and memories. The runtime is the center; the LLM is a replaceable peripheral ("runtime, not an AI agent"). The OS answers a sequence of independent questions, each owned by exactly one component:

| Question | Owner | Status |
|---|---|---|
| Who owns execution? | Execution Kernel | ✓ built |
| What is happening right now? | Request State Manager | ✓ built |
| What does the system know? | Unified Memory System (Repository Memory) | ✓ built |
| What information is needed? | Context Manager | ✓ built |
| **What abilities are required?** | **Capability Planner — this component** | designing |
| In what order do abilities execute? | Workflow Scheduler | future |
| How are abilities fulfilled? | Plugin Runtime | future |
| How are instructions constructed? | Prompt Compiler | future |
| How is work performed? | Reasoning Engine | future |
| Was the work correct? | Verification Engine | future |
| What should the system learn? | Experience & Knowledge Store | future |

The question list is a **conceptual order of concerns, not a call graph**. The authoritative interaction topology is `ARCHITECTURE.md` (hub-and-bus: components exchange events via Communication and use a small set of direct query APIs). CP answers exactly one question — WHAT abilities are required — and refuses the neighbors: never WHEN (Scheduler), never HOW (Plugin Runtime), never the work itself (Reasoning Engine).

## 2. Architectural assumptions (as-built reality)

| Assumption | Detail |
|---|---|
| Core Runtime complete | Kernel, UMS, RSM, CM implemented in `src/` (253 tests green); deterministic, stdlib-only, model-independent |
| Substrate partially doubled | Storage and Communication exist only as per-component in-memory test doubles; every component ships its own doubles |
| Event discipline | Envelope = {event_id, event_name, request_id, timestamp, config_version, payload}; dotted `family.verb` names; closed per-component event sets; at-least-once delivery, idempotent consumers keyed by event_id; log-before-publish |
| Retrieval law (Law 2) | UMS is the sole retrieval/similarity authority. CP never scans a repository and never implements similarity |
| Context law | CM is the sole assembler of Request Memory. CP consumes Request Memory; it never builds context |
| State law | RSM is the sole materialized view of runtime request state; read-only to everyone, written only via the bus |
| Storage law (Law 3) | All durable bytes written by Storage on the owner's behalf; CP owns plan artifacts conceptually, Storage persists them |
| Determinism (Law 6) | Identical inputs + identical knowledge/registry/prior state → identical outputs, byte-comparable where serialized |
| Policy as data | Thresholds, weights, tables live in immutable config views, not code branches |
| LLM at the edge | If a planning step ever needs a model, the request is expressed as a work order consumed elsewhere; CP itself never calls a model |

## 3. System-wide terminology

| Term | Meaning (binding for all CP phases) |
|---|---|
| Intent | The normalized statement of what a request wants accomplished |
| Classification | Assignment of intent to a category **with confidence and alternatives** — never a bare argmax label (V1-H1) |
| Capability | An abstract ability the OS can reason about ("edit file", "run tests"), independent of any implementation |
| Capability requirement | A capability a plan step needs, with constraints; may be marked unfilled (gap) |
| Task graph | The decomposition of intent into steps with dependencies; a validated artifact, never a naive text split (V1-H6) |
| Capability binding | The association of a step's requirement to a registry-declared capability — an abstract match, not a plugin invocation |
| Plan | The validated artifact: task graph + capability bindings + confidence + fallbacks. Inspectable, verifiable, persisted |
| Confidence | Explicit numeric-or-banded certainty attached to every classification and plan; low confidence triggers fallback, never silent commit |
| Fallback | A pre-declared alternative path taken when confidence or capability coverage is insufficient |
| Gap | An explicitly recorded unmet capability requirement; surfaced, never silently bound |
| Prior | Learned planning/classification knowledge supplied by the Experience layer; consumed as data |
| Request Memory | CM's output artifact — the only context CP may consume for knowledge-driven decisions |
| Registry | Plugin Runtime's catalog of declared capabilities; CP reads it, never owns or mutates it |

## 4. Component interaction philosophy

- Two interaction styles only: **events** (async, fan-out, on the bus) and **direct queries** (sync read APIs: UMS query, RSM query, registry read). Commands that mutate state are events; reads that need an answer now are queries.
- CP is a **transformer, not a coordinator**: intent in, plan artifact out. It initiates no execution, spawns nothing, schedules nothing.
- Every consumed event has a named publisher; every published event has named consumers (publish/consume matrix in `ARCHITECTURE.md`). CP's declared set: publishes `intent.classified`, `plan.created`, `plan.rejected` (plus `plan.revised` per matrix); consumes `request.admitted`, `plugin.registered`, `plugin.health.changed`, `prior.updated`. Later phases refine payloads, never invent names outside the declared set without an architecture change.
- Downstream components (Scheduler, Verification) consume the plan artifact; they never reach back into CP's internals. Upstream components never depend on how CP plans.

## 5. Layering principles

Three tiers (per `ARCHITECTURE.md`): Surface (Frontend) / Core (Kernel + planning-and-doing components, CP among them) / Substrate (UMS, Storage, Communication, Observability). Rules:

1. Core components depend on Substrate contracts, never on each other's internals.
2. Nothing depends downward on a specific implementation — only on the contract.
3. The Core Runtime (Kernel, UMS, RSM, CM) is always active and deterministic; CP joins the always-consistent side of the system and must not degrade that property.
4. Absent Substrate components are represented by contract-faithful test doubles until built; code written against the contract survives the swap unchanged.

## 6. Separation of responsibilities (CP's fence)

| CP owns | CP never owns |
|---|---|
| Intent classification policy, confidence/fallback semantics | Repository retrieval/similarity (UMS) |
| Decomposition into validated task graphs | Context/prompt assembly (CM / future Prompt Compiler) |
| Capability matching logic (reading the registry) | The capability registry itself (Plugin Runtime) |
| Plan confidence scoring, gap/fallback declaration | Scheduling, ordering, timing (Workflow Scheduler) |
| Plan artifact shape and validity rules | Execution, spawning, model calls (Execution/Reasoning) |
| | Verification verdicts (Verification Engine) |
| | Durable writes (Storage) |
| | Runtime request state (RSM) |
| | Learning/prior production (Experience Store — CP only consumes) |

## 7. Design constraints

- Single responsibility per module; high cohesion, minimal coupling; no monolithic modules.
- Deterministic construction and ordering everywhere; no randomness, no wall-clock dependence in decisions.
- Model independence: no reference to any vendor, model family, SDK, API, or prompt format anywhere in CP.
- Provider independence: capabilities are abstract; nothing in CP names a concrete plugin, MCP server, or tool.
- Pluggability where the spec demands it: classification is a swappable strategy behind one seam — never a lone keyword authority (V1-H1).
- Quality gates structural, not optional: degenerate decompositions are rejected with reason (`plan.rejected`), not emitted (V1-H6).
- Simple algorithms over clever ones; every decision traceable and explainable from the artifact itself.

## 8. Non-functional requirements

| NFR | Bar |
|---|---|
| Determinism | Replay-identical plans given identical inputs and knowledge state |
| Explainability | A plan artifact alone must explain why each step, binding, confidence, and fallback exists |
| Testability | Every module independently testable with fixtures and doubles; behavior specified before code |
| Latency | Planning bounded; capability matching is a registry lookup, never a repo scan |
| Token economy | Any LLM-mediated planning step carries an explicit budget enforced via CM; large prompts are architectural failures |
| Robustness | Malformed input fails loud with reason; no silent repair, no silent defaults (missing verdict = blocked) |
| Auditability | Every action emits telemetry; no silent work (Kernel I21) |

## 9. Determinism philosophy

Determinism is the default and the tie-breaker for every design choice. Identical intent + identical registry/priors/Request Memory → identical plan, identical confidence, identical event stream. Where genuine uncertainty exists (classification confidence), the uncertainty itself is deterministic: same inputs, same confidence value, same fallback decision. Nondeterminism may enter the system only at the Reasoning Engine boundary — outside CP entirely. Anything CP emits must be reproducible for audit and replay.

## 10. Extensibility philosophy

Extend by data and by seam, never by rewrite: new intent categories, capability types, and priors arrive as data through existing contracts; new classifier strategies plug into the declared seam. Future expansion named by the frozen spec (ensemble classification, cost-aware matching, hierarchical planning, plan repair) must be reachable without moving any responsibility across a component fence. If an extension requires touching a neighbor's ownership, it is an architecture change requiring its own review — not a CP patch.

## 11. Failure philosophy

Fail loud, halt over degrade, block over guess (Kernel I22). Specific stances inherited by CP:

- Low confidence → fallback or explicit rejection; never a silent commit to a wrong branch (V1-H1 cascade).
- No capable provider for a step → explicit gap in the plan or `plan.rejected` with reason; never a binding to a nonexistent capability.
- Degenerate decomposition → rejected with reason, never emitted.
- Stale inputs (registry health, priors) → decisions use current data delivered by events; staleness is surfaced, not hidden.
- Absence never defaults to permission: a plan that cannot be validated does not exist.

## 12. Replaceability philosophy

Every subsystem replaceable without redesigning neighbors. For CP this cuts both ways: (a) CP as a whole can be swapped as long as its event contract and plan-artifact contract hold; (b) inside CP, the classifier, decomposer, and matcher are individually replaceable behind seams. Contract compatibility is the only compatibility; no neighbor may depend on CP's internal decomposition, and later CP phases must not depend on internals of Kernel/UMS/RSM/CM beyond their public query surfaces.

## 13. Contracts between major layers (boundary summary)

| Boundary | Contract character (no APIs here — later phases bind them) |
|---|---|
| Kernel → CP | Admitted requests arrive as events; CP plans only admitted work |
| CM → CP | Knowledge for planning arrives as Request Memory; CP requests context by objective + budget, consumes the artifact, never the repository |
| UMS ↔ CP | Direct query API is CM's concern; CP touches UMS only where the frozen spec permits registry-independent knowledge lookups via declared query surfaces — never scanning, never similarity. **Amended by CP/03 §4 (architecture decision, 2026-07-13): the door is closed — CP never queries UMS directly; CM is CP's sole knowledge gateway** |
| RSM ↔ CP | Read-only visibility of request state; CP output is mirrored into RSM by events, CP never writes state |
| Plugin Runtime → CP | Capability registry is read as data; reliability/health arrive as events; CP never mutates the registry |
| Experience → CP | Priors arrive as versioned data via events; CP treats them as input, never produces them |
| CP → Scheduler/Verification | The plan artifact is the entire interface: self-describing, validated, confidence-carrying. Nothing else crosses |
| CP → Storage | Plan persistence delegated; CP holds no durable bytes |
| CP → Observability | Every decision emits telemetry via the bus |

## 14. Architectural invariants (immutable for all CP phases)

1. CP answers WHAT abilities are required — never WHEN, never HOW, never the work itself.
2. Classification always carries confidence and alternatives; no bare argmax ever steers the pipeline.
3. Every plan is a validated, inspectable artifact with confidence and fallbacks; invalid plans are rejected loudly, never emitted.
4. Zero retrieval/similarity code in CP; knowledge arrives via Request Memory / declared query surfaces only.
5. CP never mutates UMS, RSM, CM, the registry, or the Ledger; reads and events only.
6. CP never calls a model, names a model, or embeds provider-specific anything.
7. Closed event set; inventing event names is an architecture violation.
8. Deterministic: identical inputs + state → identical plan, confidence, and event stream.
9. Capability gaps are explicit; CP never binds a step to a capability that does not exist in the registry.
10. Plans are persisted via Storage and verified by Verification before scheduling; CP has no path around the gates.
11. Policy lives in config data, not code branches.
12. Fail loud: every rejection carries a reason; silence is a defect.

---

Status: Phase 0 foundation frozen. Later phases design the Capability Planner within these walls.
