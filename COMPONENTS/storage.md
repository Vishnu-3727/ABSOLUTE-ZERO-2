# Storage — Component Specification

## Purpose
Storage is the **sole durable-write authority** (Global Law 3): atomic writes, file locking,
transactions, the config source of truth, index files, vault layout, and git integration all live
here. It fixes V1-H5 (no file locking / no atomic writes → multi-agent + multi-machine lost
updates) and M4 (config duplicated across engines). Every component that must persist anything
routes through Storage; **no component writes disk directly.** Storage preserves V1's artifact
discipline — runtime artifacts committed but never indexed — by owning the vault layout that keeps
work memory and knowledge memory separate.

## Responsibilities
- Perform all durable writes atomically, with locking and transactional guarantees.
- Serve as the single config source of truth; hand config to every component (no per-engine copies).
- Own vault layout, index-file persistence, and the committed/indexed artifact split.
- Own git integration: commits, history, and the durable record; emit `commit.created`.
- Guarantee no lost updates under concurrent multi-agent / multi-machine writers.

## Owns
- Atomic write / lock / transaction machinery.
- Config source of truth and its distribution.
- Vault layout, index-file bytes, git repository integration.

## Never Owns
- **Process spawning** — Execution only (even git runs as a process via Execution; Storage owns the durable *semantics*, and spawns nothing itself).
- **The bus** — Communication only.
- **Retrieval/similarity/index logic** — Repository Memory owns the logical index; Storage persists its *files*.
- **What to write / when** — callers decide content; Storage guarantees durability, not policy.
- **Telemetry schema** — Observability.

## Inputs
- Write/commit/transaction requests from any component (direct write API).
- Config read requests from all components.
- `repository.onboarded` / `repository.offboarded` (Lifecycle) — provision/tear down vault layout.

## Outputs
- Durable write acknowledgements (committed / failed).
- Config values to all components.
- Persisted index files, artifacts, and git commits.

## Events Published
- `write.committed` — a durable write completed atomically.
- `write.failed` — a durable write failed (lock/transaction/IO); no partial state left behind.
- `config.changed` — the config source of truth changed.
- `commit.created` — a git commit landed in history.

## Events Consumed
- `repository.onboarded`, `repository.offboarded` (Lifecycle)

## Dependencies
- **Execution** — spawns the git/tool processes Storage's operations require (Storage spawns nothing itself).
- **Communication** — carries write/config/commit events.
- **Observability** — universal consumer of Storage events (durability audit trail).
- (All components depend on Storage; Storage depends on very little — kept near the base of the acyclic layering.)

## Failure Modes
- **Concurrent lost update** (V1-H5) → prevented: locking + atomic write + transaction; conflicting
  writers serialize or fail loud with `write.failed`, never silently clobber.
- **Partial/torn write** → atomic swap semantics; a failed write leaves the prior state intact.
- **Config divergence** (M4) → single source; `config.changed` propagates; no component caches a private copy as truth.
- **Disk full / IO error** → `write.failed` with reason; caller and Observability notified; no corruption.
- **Multi-machine contention** → distributed lock discipline; cross-host writers do not lose updates.

## Performance Goals
- Write path latency bounded; locking overhead minimal on the uncontended common case.
- Config reads are fast and cache-coherent via `config.changed` invalidation.
- Determinism at the durability layer: an acknowledged `write.committed` is durable and reproducible; no acknowledged write is later lost.

## Testing Strategy
- Selftest: write/read round-trip → asserted durability and `write.committed`.
- Concurrency test: parallel writers to the same target → no lost update (serialized or `write.failed`).
- Atomicity test: injected mid-write failure → prior state intact, `write.failed` emitted.
- Config test: change propagation via `config.changed`; no stale private copies honored.

## Future Expansion
- Pluggable durable backends (filesystem, object store, DB) behind one transactional contract.
- Snapshot/rollback and time-travel over the vault.
- CRDT-based multi-machine merge for high-concurrency writers.

## Acceptance Criteria
- No component writes disk directly; every durable write goes through Storage.
- Concurrent/multi-machine writers never lose updates.
- Exactly one config source of truth exists, distributed by Storage.
- All published events consumed by Observability; all consumed events have a named publisher.
