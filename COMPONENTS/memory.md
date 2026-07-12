# Repository Memory — Component Specification

## Purpose
Repository Memory is the shared semantic understanding of any repository under management, and
**the single retrieval/similarity/index authority in the entire system**. It serves every query
about repository content, structure, symbols, conventions, and history. It exists to fix V1-H2:
V1 shipped **six divergent, all-lexical** similarity/retrieval implementations scattered across
engines, so retrieval quality was inconsistent and un-improvable. In V2 this is the central
architectural law (Global Law 2): **no other component scans a repository or implements its own
similarity.** Every subsystem that needs repo knowledge queries Repository Memory.

## Responsibilities
- Maintain the semantic index of each managed repository: content, structure, symbols, conventions, history.
- Serve all retrieval/similarity queries through one ranked, model-agnostic interface.
- Keep indexes fresh in response to committed changes; mark stale regions rather than serve wrong answers.
- Expose retrieval with explainable ranking so results are inspectable, not a black box.
- Provide budget-aware result sets (respect the caller's token/size ceiling — a V1 strength kept).

## Owns
- The repository index/embedding/symbol/convention model and its lifecycle.
- All similarity scoring and ranking logic.
- Query planning for repository knowledge (what to fetch, in what order, to what depth).
- Freshness/staleness tracking of indexed regions.

## Never Owns
- **Durable writes to disk** — index *files* are persisted by Storage; Repository Memory owns the
  logical index, Storage owns the bytes.
- **Process spawning** — Execution only.
- **The event bus** — Communication only.
- **Prompt/context assembly** — Context Management consumes retrieval results and assembles context.
- **Planning/classification** — Capability Planning.

## Inputs
- Retrieval queries (direct query API) from Context Management, Capability Planning, Verification, Learning, Frontend.
- `write.committed` / `commit.created` signals telling it which regions changed.
- `repository.onboarded` / `repository.offboarded` to begin/end managing a repo.

## Outputs
- Ranked, explained, budget-fitted retrieval result sets (via direct query API).
- Index freshness/staleness status.
- Index build/update completion signals.

## Events Published
- `repo.indexed` — a repository's initial index is built and queryable.
- `index.updated` — index refreshed after changes; regions re-embedded.
- `index.stale` — changed regions detected but not yet reindexed; queries flagged accordingly.

## Events Consumed
- `write.committed`, `commit.created` (Storage) → trigger incremental reindex.
- `repository.onboarded`, `repository.offboarded` (Lifecycle) → start/stop managing a repo.

## Dependencies
- **Storage** — persists index files and reads repository bytes on Repository Memory's behalf.
- **Communication** — delivers change/lifecycle events and carries published events.
- **Observability** — universal consumer; receives all events plus query telemetry.

## Failure Modes
- **Stale index served as fresh** (the V1-H2 class of bug) → forbidden; changed-but-unindexed
  regions are marked `index.stale` and results carry a freshness flag. Never silently return stale hits.
- **Index corruption** → detected on read; the region is rebuilt from source via Storage; queries
  to that region fail loud until rebuilt, never return garbage.
- **Query over budget** → truncate to the budget ceiling and report truncation; never exceed silently.
- **Onboarding a huge repo** → index incrementally; partial index answers with coverage metadata rather than blocking.

## Performance Goals
- Retrieval latency bounded and predictable for the common query classes; ranking is not an
  unbounded full-repo scan per query — that is the failure this component eliminates.
- Incremental reindex cost proportional to changed regions, not repo size.
- Determinism (Global Law 6): identical query + identical index state → identical ranked results.

## Testing Strategy
- Golden-query selftest (V1 selftest law): fixed repo fixture, fixed queries, asserted ranked outputs.
- Freshness tests: mutate a region, assert `index.stale` then `index.updated`, assert no stale hit served meanwhile.
- Budget tests: assert result sets never exceed the caller's ceiling.
- Determinism/replay tests across identical index states.
- Cross-component test: assert no other component's selftest performs repository scanning (law enforcement).

## Future Expansion
- Pluggable embedding/similarity backends behind the same ranked interface (model independence).
- Cross-repository knowledge federation for multi-repo workspaces.
- Semantic-diff-aware incremental indexing; convention-drift detection surfaced to Learning.

## Acceptance Criteria
- Exactly one retrieval/similarity implementation exists system-wide, and it is here.
- Every component needing repo knowledge lists Repository Memory as a dependency and performs no scan itself.
- All queries are budget-bounded and freshness-flagged.
- All published events consumed by Observability; all consumed events have a named publisher.
