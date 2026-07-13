# Phase 11 — Validation Review

Post-implementation review of `src/kernel/` against the three implementation
sources (INVARIANTS.md, 09-interfaces.md, 10-test-spec.md). Phase docs 01–08
consulted for rationale only.

## Scope

| Reviewed | Against |
|---|---|
| 9 modules in `src/kernel/` + `tests/test_kernel_spec.py` | 22 invariants (INVARIANTS.md) |
| Public surface | 09-interfaces.md |
| Behavioral coverage | 10-test-spec.md (34 spec IDs) |
| Emissions | Kernel matrix rows only — no invented emissions found |

## Findings

| ID | Module | Issue | Invariant | Fix |
|---|---|---|---|---|
| F1 | coordinator.py | Outbound event ids were counter-based (`out-N`) — replay after crash re-emits the same logical event under a NEW id, so consumer dedup-by-event-id fails; duplicate effects possible | D5a exactly-once effect; log-before-publish replay | Deterministic id `request_id:transition_sequence:index` for table-row emissions. Fault/alert emissions keep counter ids (not deduped work items, I9 outbound-only) |
| F2 | ledger.py | `RequestState.pending_gates` written but never read — dead state that can silently diverge from the transition table (the real authority on which gates guard which rows) | Single source of truth for gate state | Field dropped; ponytail-marked (derivable from table: guarded rows not yet permitted) |
| F3 | config_view.py | `raw()` exposed the underlying snapshot dict — mutable escape hatch on an immutable versioned view; zero callers | Config snapshot immutability | Removed (dead code) |
| F4 | tests/test_kernel_spec.py | Ledger canonicalization referenced `pending_gates` | — | Updated for F2 |

## Verdict

| Check | Result |
|---|---|
| 22 invariants | PASS (F1–F3 were the only violations; fixed) |
| Public interface vs 09 | PASS — surface unchanged by fixes |
| 34 spec IDs | Covered (spec numbers 34, not 36 — known discrepancy, spec is authority) |
| Emission matrix | PASS — no emissions outside Kernel's rows |

## Caveats

- Test suite NOT re-run this phase (owner directive). Fixes are
  review-verified only; F1/F2 touch replay + ledger canon — run
  `tests/test_kernel_spec.py` before building on the kernel.
- Interpretation decisions from Phase 10 stand (3 ponytail-marked:
  eviction at session.sleep; log records carry event_id+info; CR-2
  created-state via redelivery).

Phase 11 closes kernel design + implementation. Kernel = runtime, not an
AI agent; LLM stays off-center.
