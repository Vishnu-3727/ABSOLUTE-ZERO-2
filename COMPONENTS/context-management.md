# Context Management — Component Specification

> **Errata (2026-07-14, RO Phase 5).** This spec's references to a "future Prompt Compiler Execution Service" are superseded: request preparation and rendering (prompt compilation, where prompts exist at all) live inside the Reasoning Orchestrator (RO/00 §5.7, RO/05 §9). CM's own boundary is unchanged — sole assembler of Request Memory, which RO consumes sealed (RO-I5).

## Purpose
Context Management assembles **Request Memory** (formerly the "Optimal Context Package") — the
smallest correct working set required to execute one request — and is the **sole context
assembler** (Global Law 1). It pulls candidate material from Repository Memory and other
memories, ranks and dedups it, and fits it to an explicit token budget across fidelity tiers.
Prompt compilation is NOT owned here; it belongs to the future Prompt Compiler Execution
Service, which consumes Request Memory. It upholds a V1 strength — token budget-as-ceiling with
mandatory ≤25-token summaries — making token cost computable rather than honor-system, and
centralizes context so different callers can't drift into inconsistent, ad hoc context building.

## Responsibilities
- Gather candidate context from Repository Memory (retrieval) + Learning lessons + working memory.
- Rank, dedup, and select material to fit an explicit token budget; apply fidelity tiers (full → summarized → reference).
- Enforce mandatory compact summaries so every included item's token cost is bounded and known.
- Return the assembled Request Memory to the caller.
- Report overflow rather than silently dropping or exceeding budget.

## Owns
- Request Memory (the ephemeral, per-execution working set).
- Context selection/ranking/dedup policy and fidelity-tier assignment.
- Per-call token budgeting of the context package.

## Never Owns
- **Prompt compilation/generation** — future Prompt Compiler Execution Service; it consumes Request Memory.
- **Retrieval/similarity** — that is Repository Memory (Law 2); Context Management *consumes* ranked results.
- **Durable writes** — Storage only.
- **Process spawning / the bus** — Execution / Communication only.
- **The LLM call itself** — callers (Capability Planning, Verification, etc.) invoke the model; Context Management prepares the package.
- **Planning/verdicts** — respective owners.

## Inputs
- Context requests carrying purpose, token budget, and fidelity constraints.
- Ranked retrieval results (Repository Memory query API).
- Lessons/priors (Learning, via `lesson.recorded` / query).
- `plan.created` / `task.dispatched` as triggers for pre-assembling context.
- `index.updated` (Repository Memory) — invalidate cached context built on stale index.

## Outputs
- Request Memory (selected, ranked, deduped, budget-fitted working set). Exactly one artifact.
- Overflow/coverage metadata.

## Events Published
- `context.assembled` — a context package is ready for an LLM call.
- `context.overflow` — requested material exceeds budget; truncation/tiering applied and reported.

## Events Consumed
- `plan.created` (Capability Planning)
- `task.dispatched` (Scheduling)
- `index.updated` (Repository Memory)
- `lesson.recorded` (Learning)

## Dependencies
- **Repository Memory** — sole source of repository retrieval candidates.
- **Learning** — lessons/priors that enrich context.
- **Storage** — reads persisted memories/config; caches via Storage, not direct disk.
- **Communication / Observability** — transport and universal telemetry consumer.

## Failure Modes
- **Budget overshoot** → forbidden; over-budget requests truncate by fidelity tier and emit `context.overflow`. Never exceed silently (keeps token cost computable).
- **Stale context** → `index.updated` invalidates dependent cached packages; never compile on known-stale retrieval.
- **Duplicate/contradictory material** → dedup + provenance ranking; contradictory items surfaced, not blended blindly.
- **Missing summary** → an item without a compact summary cannot be admitted at reference tier; enforced, not optional.

## Performance Goals
- Assembly latency bounded; ranking operates over Repository Memory's returned candidate set, not a fresh scan.
- Deterministic packing (Law 6): identical request + identical memory/index state → identical Request Memory.
- Token accounting exact against Observability's tokenizer accounting.

## Testing Strategy
- Selftest: fixture memories + fixed budget → asserted package contents and byte/token totals.
- Budget tests: over-budget input → `context.overflow`, output within ceiling.
- Dedup/ranking tests: duplicated and contradictory fixtures → expected selection order.
- Determinism replay tests; stale-invalidation tests on `index.updated`.

## Future Expansion
- Learned ranking/packing policies from Learning outcomes.
- Multi-model tier profiles (different budgets per model) behind one interface.
- Streaming/partial context assembly for long-running agents.

## Acceptance Criteria
- Exactly one context assembler exists system-wide, and it is here (prompt compilation lives in the future Prompt Compiler service).
- Every package respects its explicit token ceiling; overflow is reported, never silent.
- No retrieval/similarity is implemented here — only Repository Memory queries.
- All published events consumed by Observability; all consumed events have a named publisher.
