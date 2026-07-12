# Learning — Component Specification

## Purpose
Learning harvests **closed traces** into lessons, faults, and pattern statistics, and feeds them
back as improved plugin reliability and planning priors. It is the mechanism behind the motto —
"never pay for the same mistake twice." It respects V1's clean split of work memory vs knowledge
memory: runtime artifacts (traces/plans/runs) are the raw input, distilled lessons are the durable
knowledge. Learning **writes only via Storage** (Law 3) and never scans repositories itself
(Law 2) — it queries Repository Memory when it needs repo context.

## Responsibilities
- Consume `trace.closed`, extract lessons, faults, and pattern statistics from completed work.
- Update plugin reliability signals (feeding Plugin Runtime) and planning/classification priors (feeding Capability Planning).
- Maintain the self-documenting fault ledger (a V1 strength) as distilled, queryable knowledge.
- Distill lessons into compact, retrievable form (usable by Context Management / Repository Memory).
- Emit updates as events so consumers refresh without polling.

## Owns
- Trace-harvesting and distillation logic.
- The lesson/fault ledger content model and pattern-statistics model.
- The reliability/prior *derivations* (the numbers Plugin Runtime and Capability Planning consume).

## Never Owns
- **Durable writes** — Storage persists all lessons/faults/priors (Law 3).
- **Retrieval/similarity** — Repository Memory indexes and serves lessons for search (Law 2); Learning produces them.
- **Process spawning / the bus** — Execution / Communication only.
- **The plugin registry / the plan** — it *informs* Plugin Runtime and Capability Planning; it does not own their state.
- **Telemetry storage** — Observability owns the raw trace stream; Learning consumes closed traces.

## Inputs
- `trace.closed` (Observability) — the primary raw material.
- `verify.failed` (Verification) — fault signal for the ledger.
- `process.failed` / `process.timeout` (Execution) — reliability evidence.
- Repository context (Repository Memory) for grounding lessons.

## Outputs
- Lessons and fault-ledger entries (persisted via Storage, indexed by Repository Memory).
- Reliability signals for Plugin Runtime; priors for Capability Planning.

## Events Published
- `lesson.recorded` — a distilled lesson/fault entry is available.
- `reliability.updated` — a plugin's outcome-derived reliability changed.
- `prior.updated` — planning/classification priors changed.

## Events Consumed
- `trace.closed` (Observability)
- `verify.failed` (Verification)
- `process.failed`, `process.timeout` (Execution)

## Dependencies
- **Observability** — source of closed traces (raw work memory).
- **Storage** — sole writer for lessons/faults/priors.
- **Repository Memory** — indexes lessons for retrieval; supplies grounding context.
- **Plugin Runtime / Capability Planning** — consumers of reliability/priors.
- **Communication** — carries all events.

## Failure Modes
- **Learning from noise** → distillation requires closed, verdict-tagged traces; incomplete/aborted
  traces are excluded, so a single flaky run does not become a false "lesson."
- **Prior/reliability drift** → healing/decay smoothing (aligned with Plugin Runtime) prevents overreaction to one outcome.
- **Write contention** → all writes go through Storage's atomic/locked path (fixes V1-H5 lost-update class).
- **Unbounded ledger growth** → compaction/summarization policy keeps lessons compact and retrievable, not sprawling.

## Performance Goals
- Harvesting is incremental per `trace.closed`, not periodic full-corpus rescans.
- Distillation cost bounded per trace; lessons stored in compact summarized form (token-bounded).
- Determinism (Law 6): identical closed-trace set → identical derived lessons/priors/reliability.

## Testing Strategy
- Selftest: fixture closed traces → asserted lessons, fault entries, and prior/reliability deltas.
- Noise-rejection test: aborted/incomplete traces produce no lesson.
- Smoothing test: single outlier outcome does not swing priors past bounds.
- Storage-only-writer test: assert Learning issues no direct disk write.

## Future Expansion
- Cross-repository lesson transfer; meta-lessons over pattern statistics.
- Active-learning prompts that request missing evidence.
- Counterfactual analysis of avoided repeat-mistakes (motto metrics).

## Acceptance Criteria
- Learning writes exclusively through Storage and scans no repository directly.
- Lessons/faults/priors are distilled only from closed, verdict-tagged traces.
- Consumers refresh via `reliability.updated` / `prior.updated` / `lesson.recorded` without polling.
- All published events consumed by Observability; all consumed events have a named publisher.
