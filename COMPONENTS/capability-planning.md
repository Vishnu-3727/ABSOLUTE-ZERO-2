# Capability Planning — Component Specification

## Purpose
Capability Planning turns intent into **validated plans**: it classifies intent, decomposes work,
matches capabilities (which tools/skills/agents can perform each step), and attaches plan
confidence and fallbacks. It fixes two V1 failures. V1-H1: a single brittle lexical
keyword-argmax intent classifier steered the whole pipeline, and one misclassification cascaded —
so in V2 classification is a **pluggable service with first-class confidence and fallback**, never
a lone keyword authority. V1-H6: naive decomposition (split on the word "and") bloated DAGs — so in
V2 decomposition quality is validated and plans are verifiable artifacts carrying confidence.

## Responsibilities
- Classify intent via a pluggable classifier service; emit confidence, never a bare argmax label.
- Decompose intent into a validated task graph; reject/repair low-quality decompositions.
- Match each step to capabilities using the Plugin Runtime registry + Repository Memory context.
- Attach plan confidence and explicit fallback paths for low-confidence steps.
- Produce plans as inspectable, verifiable artifacts (persisted via Storage, verified by Verification).

## Owns
- Intent classification policy and confidence/fallback semantics.
- Decomposition and task-graph construction/validation.
- Capability-matching logic (consuming the registry — it does not own the registry).
- Plan confidence scoring.

## Never Owns
- **Repository retrieval/similarity** — queries Repository Memory; never scans (Law 2).
- **The capability registry** — owned by Plugin Runtime; Capability Planning only reads it.
- **Durable writes** — Storage persists plans.
- **Process spawning / the bus / verification** — respective owners.
- **Context/prompt assembly** — Context Management (though it requests context for classification/matching).

## Inputs
- `request.admitted` (from Kernel) — the intent to plan.
- Repository knowledge (via Repository Memory query API).
- Capability registry + reliability (from Plugin Runtime, via `plugin.registered` / `plugin.health.changed`).
- Planning priors (from Learning, via `prior.updated`).

## Outputs
- Validated plan artifacts (task graph + capability bindings + confidence + fallbacks).
- Classification results with confidence.

## Events Published
- `intent.classified` — intent labeled with confidence (and alternatives).
- `plan.created` — a validated plan artifact is ready for verification/scheduling.
- `plan.rejected` — planning failed quality/confidence thresholds; reason attached.

## Events Consumed
- `request.admitted` (Kernel)
- `plugin.registered`, `plugin.health.changed` (Plugin Runtime) — keep capability view current.
- `prior.updated` (Learning) — refresh planning/classification priors.

## Dependencies
- **Repository Memory** — all repo context for classification and matching.
- **Plugin Runtime** — capability registry and reliability scores.
- **Context Management** — assembles the context package for LLM-driven classification/decomposition.
- **Learning** — supplies priors that improve classification/decomposition over time.
- **Storage** — persists plan artifacts.
- **Communication / Observability** — event transport and universal telemetry consumer.

## Failure Modes
- **Misclassification cascade** (V1-H1) → mitigated: low confidence triggers fallback/clarification
  rather than committing a wrong branch; classifier is swappable, never a single point of steering.
- **Decomposition bloat** (V1-H6) → validation rejects degenerate graphs (e.g. naive "and"-splits);
  `plan.rejected` with reason rather than a bloated DAG.
- **No capable plugin for a step** → plan carries an explicit gap + fallback, or is rejected; never binds to a nonexistent capability.
- **Stale registry/priors** → consumes health/prior events; matches against current reliability, not stale scores.

## Performance Goals
- Planning latency bounded; capability matching is a registry lookup, not a repo scan.
- Token budgets for LLM-driven planning steps are explicit (Law 5) and enforced via Context Management.
- Determinism (Law 6): identical intent + identical registry/priors/context → identical plan and confidence.

## Testing Strategy
- Selftest: fixture intents → asserted classification labels + confidence bands.
- Decomposition-quality tests: adversarial "and"-heavy inputs must not produce bloated graphs.
- Fallback tests: force low confidence, assert fallback path emitted, not a hard commit.
- Capability-gap tests: registry with missing capability → `plan.rejected` or explicit gap.
- Determinism replay tests.

## Future Expansion
- Multiple pluggable classifier strategies with ensemble/confidence fusion.
- Cost/latency-aware capability matching using Learning throughput priors.
- Hierarchical planning and plan-repair loops.

## Acceptance Criteria
- Classification always carries confidence; no single-keyword decision steers the pipeline.
- Every plan is a validated, verifiable artifact with confidence and fallbacks.
- No repository scanning occurs here — only Repository Memory queries.
- All published events consumed by Observability; all consumed events have a named publisher.
