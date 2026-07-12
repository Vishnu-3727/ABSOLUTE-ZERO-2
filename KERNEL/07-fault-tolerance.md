# Kernel — Phase 7: Fault Tolerance

All fault **policy** is Config View data (phase 2, "no retry or timeout module"). Kernel applies it as table lookups, never discretion. Kernel handles coordination faults only; work faults route via phase-3 table; component faults are those components' responsibility.

---

## Fault Taxonomy

| Fault class | Example | Handled by | Kernel action |
|-------------|---------|-----------|-----------------|
| Work fault | task.failed, verify.failed | Capability Planning replan loop | Apply phase-3 transition; no new logic |
| Component fault | Peer crash, unresponsive | That component + supervisor | None directly; surfaces as missing events → timeout policy |
| Delivery fault | Duplicate, out-of-order, poison | Communication dead-letter (D6a) | Drop duplicate / `fault.recorded` |
| Kernel fault | Own crash, corrupted replay | Replay recovery (phase-3) | Halt admission; recover by log replay |
| Config fault | Invalid config.changed | Kernel validation at adapter | Reject snapshot, retain prior version; `fault.recorded` |

---

## Timeout Policy as Data (D7a)

Config View gate definitions carry optional timeout spec: `gate | timeout_source | on_expiry`. Kernel owns no timers (phase 2, single-threaded). **Decision D7a:** Scheduling owns clocks and publishes `task.failed` with `reason=timeout` (reuse phase-3 vocab; no new event). Kernel consumes deterministically: verifying → failed, executing → scheduled. Timeouts enter log as ordinary events; replay stays byte-identical.

---

## Retry Policy as Data

Config View per request type: `max_replans` (task.failed → scheduled loop count), `on_exhaust = failed`. RequestState Ledger adds `replan_count` (amendment). Kernel: count in Ledger, compare against config, boolean only. Exhaust → `failed` + `request.failed` emitted.

---

## Checkpointing

None beyond transition log (D2). Log **is** the checkpoint. Ledger rebuild = deterministic replay. Snapshot optimization deferred: add only if replay measured slow. Upgrade path: periodic snapshots + log suffix replay.

---

## Rollback

Kernel never rolls back (no writes, no spawns). Domain compensations = Capability Planning plans compensating tasks; Kernel runs resulting requests through phase-3 table unchanged.

---

## Degradation Ladder (Deterministic)

| Level | Trigger | Action | Recovery path |
|-------|---------|--------|----------------|
| 1 | Communication unavailable | Halt admission; in-flight stall (events blocked) | `fault.recorded` when possible; operator resume |
| 2 | Config invalid | Keep last-good snapshot; reject new config.changed | Operator fix + new config.changed |
| 3 | Replay deviates (byte-compare) | Halt; human/Observability alert | Operator diagnosis; log/code audit |
| 4 | Ledger memory pressure | Refuse new admissions (halt); protect active requests | Operator scale or evict stalled requests |

Never guess, skip gates, or silent-continue.

---

## Partial Failure & Isolation

Per-request isolation (D1, D2 zero shared state): one fault never touches another's entry. Poison events dead-lettered by Communication (D6a), surfaced as `fault.recorded`.
