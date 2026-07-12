# Execution — Component Specification

## Purpose
Execution runs external processes and tools deterministically and is the **sole process spawner**
in the system (Global Law 3). It owns sandboxing, timeouts, retries, resource caps, and failure
containment for *every* external process. It exists to fix V1-H4: in V1, uncaught subprocess
timeouts crashed the verifier itself because process control was ad hoc and scattered. In V2 no
other component spawns a process — a runaway or hanging tool is contained here and can never take
down a caller.

## Responsibilities
- Spawn, supervise, and reap all external processes/tools (CLI engines, plugin tools, git, selftests).
- Enforce timeouts, resource caps (CPU/mem/fd), and sandbox isolation on every process.
- Apply bounded retry policy; contain and report failures without propagating crashes to callers.
- Emit deterministic lifecycle events for every process so outcomes are auditable and replayable.
- Guarantee that a hung/killed process yields a definite terminal event — never a silent hang.

## Owns
- Process lifecycle: spawn → supervise → terminate → reap.
- Sandbox/isolation policy and resource caps.
- Timeout and retry enforcement; failure containment boundary.

## Never Owns
- **Durable writes** — Storage only; a process's *outputs* are handed to callers/Storage, Execution does not persist them itself.
- **The bus** — Communication only.
- **Deciding what to run or when** — Scheduling dispatches; Execution runs.
- **Verification logic** — it *runs* selftests on request; Verification interprets results.
- **Repository retrieval** — Repository Memory only.

## Inputs
- `task.dispatched` (from Scheduling) — the authoritative signal to run something.
- Execution requests carrying command, sandbox profile, caps, and timeout.
- Selftest-run requests delegated by Verification.

## Outputs
- Process results (exit status, captured stdout/stderr/artifacts) returned to the requester.
- Definite terminal status for every spawned process.

## Events Published
- `process.started` — a sandboxed process began.
- `process.completed` — process finished within limits (with exit status).
- `process.failed` — process failed (non-zero/error) after retry policy exhausted.
- `process.timeout` — process exceeded its timeout and was contained/killed.

## Events Consumed
- `task.dispatched` (Scheduling)

## Dependencies
- **Scheduling** — the only authorized dispatcher of executable work.
- **Storage** — receives any outputs that must be durably written (Execution never writes disk itself).
- **Communication** — carries all process events.
- **Observability** — universal consumer; receives process telemetry and resource accounting.

## Failure Modes
- **Runaway / hung process** (V1-H4) → hard timeout kills it; `process.timeout` is emitted; the
  caller (e.g. Verification) receives a definite failure and is never crashed by the hang.
- **Resource exhaustion** → caps enforced; offending process killed and reported, host protected.
- **Sandbox escape attempt** → isolation denies; process terminated and flagged via `alert.raised` (Observability).
- **Flaky tool** → bounded retries; after exhaustion emit `process.failed` — never infinite retry.
- **Zombie/orphan** → guaranteed reaping; no leaked processes across restarts.

## Performance Goals
- Spawn/teardown overhead bounded and predictable.
- Timeout enforcement precise within a small tolerance; no unbounded wait ever.
- Determinism (Law 6): identical command + identical sandbox/caps → identical terminal event class (modulo intrinsic tool nondeterminism, which is surfaced, not hidden).

## Testing Strategy
- Selftest: run a fast fixture process, assert `process.completed`.
- Timeout tests: run a deliberately hanging fixture, assert `process.timeout` and caller survival.
- Cap tests: run a fixture that exceeds mem/CPU caps, assert containment.
- Retry tests: flaky fixture, assert bounded retries then `process.failed`.
- Orphan/zombie reaping tests across simulated restart.

## Future Expansion
- Pluggable sandbox backends (container, microVM) behind one isolation contract.
- Distributed execution pools with per-node resource accounting.
- Warm process pools for hot tools to cut spawn overhead.

## Acceptance Criteria
- No component other than Execution spawns a process.
- Every spawned process yields exactly one terminal event; no silent hangs.
- Timeouts and caps are enforced on every process without exception.
- All published events consumed by Observability; all consumed events have a named publisher.
