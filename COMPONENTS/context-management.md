# Context Management — Component Specification

## Purpose
Context Management assembles the **Optimal Context Package** for any LLM call and is the **sole
prompt-context assembler** — it also owns prompt compilation, so no separate prompt engine
duplicates it (Global Law 1). It pulls candidate material from Repository Memory and other
memories, ranks and dedups it, fits it to an explicit token budget across fidelity tiers, and
compiles the final prompt. It upholds a V1 strength — token budget-as-ceiling with mandatory
≤25-token summaries — making token cost computable rather than honor-system, and centralizes
context so different callers can't drift into inconsistent, ad hoc prompt building.

## Responsibilities
- Gather candidate context from Repository Memory (retrieval) + Learning lessons + working memory.
- Rank, dedup, and select material to fit an explicit token budget; apply fidelity tiers (full → summarized → reference).
- Enforce mandatory compact summaries so every included item's token cost is bounded and known.
- Compile the final model-agnostic prompt (Law 5) and return the assembled package.
- Report overflow rather than silently dropping or exceeding budget.

## Owns
- Context selection/ranking/dedup policy and fidelity-tier assignment.
- Prompt compilation (the single prompt assembler).
- Per-call token budgeting of the context package.

## Never Owns
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
- The Optimal Context Package (selected, ranked, deduped, budget-fitted, compiled prompt).
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
- Deterministic packing (Law 6): identical request + identical memory/index state → identical package and prompt.
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
- Exactly one prompt/context assembler exists system-wide, and it is here.
- Every package respects its explicit token ceiling; overflow is reported, never silent.
- No retrieval/similarity is implemented here — only Repository Memory queries.
- All published events consumed by Observability; all consumed events have a named publisher.
