# Verification — Component Specification

## Purpose
Verification provides the system's **mechanical gates**: it checks plans, diffs, artifacts, and
selftests, and emits verdicts as events that the Kernel and Scheduler enforce. It fixes V1-H3: in
V1 the verifier was honor-system and the LLM once committed over a FAIL. In V2 verdicts are
first-class events, gates are structurally unskippable (Global Law 4), and Verification **never
executes processes itself** — it delegates all execution (e.g. running selftests) to Execution, so
a hanging check can never crash the verifier (the V1-H4 lesson).

## Responsibilities
- Check plans (from Capability Planning) for structural/quality validity before scheduling.
- Check diffs/artifacts against rules (acyclic layering, selftest law, invariants — V1 strengths kept).
- Trigger selftests of changed + dependent engines via Execution and interpret their results.
- Emit `verify.passed` / `verify.failed` verdicts with reasons; verdicts are the gate authority.
- Guarantee a definite verdict for every gated item — never leave a gate in limbo.

## Owns
- Verification rules/checks and verdict semantics.
- The mapping from artifact type → required checks.
- Interpretation of selftest results into pass/fail.

## Never Owns
- **Process spawning** — delegates every execution to Execution (Law 3); this is the core V1-H4 fix.
- **Gate enforcement** — it *produces* verdicts; the Kernel/Scheduler *enforce* them (Law 4).
- **Durable writes** — verdict records persisted via Storage.
- **Repository retrieval** — Repository Memory only.
- **The bus** — Communication only.

## Inputs
- `plan.created` (Capability Planning) — plans to check.
- Diffs/artifacts submitted for verification (via Storage-backed references).
- `exec.completed` / `exec.failed` / `exec.timeout` (Execution) — selftest outcomes.
- Repository context (Repository Memory) for dependency-aware selftest selection.

## Outputs
- Verdicts (`verify.passed` / `verify.failed`) with structured reasons.
- Verification records (persisted via Storage).

## Events Published
- `verify.passed` — item satisfied all required checks.
- `verify.failed` — item failed a required check (reason attached).

## Events Consumed
- `plan.created` (Capability Planning)
- `exec.completed`, `exec.failed`, `exec.timeout` (Execution) — selftest results.
- `write.committed` (Storage) — a diff/artifact landed and needs verification.

## Dependencies
- **Execution** — runs all selftests/checks; Verification issues no process itself.
- **Repository Memory** — resolves changed + dependent engines for selftest scope.
- **Storage** — persists verdict records and reads artifacts.
- **Kernel / Scheduling** — enforce the verdicts (Verification does not enforce).
- **Communication / Observability** — transport and universal telemetry consumer.

## Failure Modes
- **Committing over a FAIL** (V1-H3) → structurally impossible: `verify.failed` blocks the gate at
  Kernel/Scheduler; there is no honor-system path around it.
- **Hanging check crashes verifier** (V1-H4) → impossible: checks run in Execution; a `exec.timeout`
  becomes `verify.failed`, and Verification stays alive.
- **Missing verdict** → treated by enforcers as *not passed*; Verification also guarantees it emits a
  terminal verdict per gated item rather than going silent.
- **Selftest scope gap** → dependency-aware selection via Repository Memory ensures dependents are checked, not just the changed file.

## Performance Goals
- Verdict latency bounded by delegated selftest runtime + fixed check overhead; no unbounded self-work.
- Check overhead deterministic (Law 6): identical artifact + identical rules/selftest results → identical verdict.
- Selftest scope proportional to change footprint, not whole-repo.

## Testing Strategy
- Selftest: fixture plan/diff + fixture selftest outcomes → asserted verdicts.
- Delegation test: assert Verification spawns no process directly (all via Execution).
- Timeout test: Execution reports `exec.timeout` → Verification emits `verify.failed`, stays up.
- Scope test: changed engine → dependents included in selftest set (via Repository Memory).

## Future Expansion
- Richer static/semantic checks (invariant proofs, policy-as-data rules).
- Confidence-weighted verdicts feeding Scheduling risk classes.
- Parallel check batching across independent artifacts.

## Acceptance Criteria
- Verification never spawns a process; all execution is delegated to Execution.
- A `verify.failed` or absent verdict cannot be bypassed by any downstream component.
- Every gated item receives a definite verdict.
- All published events consumed by Observability; all consumed events have a named publisher.
