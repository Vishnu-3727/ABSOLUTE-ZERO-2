# Kernel — Test Specification

Implementation is complete when all tests here pass. These tests encode behavioral contracts derived from INVARIANTS.md (22 rules) and the phase-3 execution lifecycle transition table — code must satisfy them without architectural compromise.

## 1. Invariant Tests (IT-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| IT-1 | valid Ledger | duplicate event (same event_id) | no state mutation; log no-op record verdict=duplicate | I8, I21 |
| IT-2 | executing state | task.completed arrives, no verify.passed | request stays in verifying; gate.enforced block | I5 |
| IT-3 | executing state | verify.failed recorded | task.completed never reaches completed | I5 |
| IT-4 | any state | unknown request_id verdict event | fault.recorded emitted; no Ledger entry | I4, phase-4 D4a |
| IT-5 | routing gate | declared type unknown/ambiguous | request.rejected emitted; never routed | I3, I6 |
| IT-6 | any state | unmatched (state, event) pair | fault.recorded; state unchanged | I4 |
| IT-7 | code audit/trace | any | Coordinator is sole Ledger mutator | I1, I2 |

## 2. Determinism Tests (DT-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| DT-1 | same event sequence, config version | run twice | byte-identical transition logs | I17, I18 |
| DT-2 | any guard evaluation | decision-time check | no timestamp participates in guards | I10 |
| DT-3 | same declared type, routing table | 1000 routes | same target every time | I3 |

## 3. Replay Tests (RT-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| RT-1 | empty Ledger, full transition log | replay all records | final Ledger byte-identical to original | I16, I17 |
| RT-2 | complete log | one record altered, replayed | deviation detected; halt; fault.recorded | I17, I22 |
| RT-3 | request with logged config_version | full replay | decisions use logged version, not current | I18 |
| RT-4 | dedup no-op records in log | full replay | no-ops remain no-ops | I8 |

## 4. Crash Recovery Tests (CR-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| CR-1 | directive logged | crash after log write, before publish | directive re-emitted on recovery | phase-5 D5a, I7 |
| CR-2 | request in state (created, initialized, scheduled, executing, verifying) | crash at state, recover | recovery rejoins exact state | I16 |
| CR-3 | recovery in flight | crash during recovery | second recovery still correct; idempotent | I17, I22 |

## 5. Fault Injection Tests (FI-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| FI-1 | admission loop | communication unavailable | halts; no event loss; fault.recorded when possible | I22, L1 |
| FI-2 | config.changed event | invalid snapshot | rejected; last-good retained; fault.recorded | L2 |
| FI-3 | steady state | resource exhaustion signal | new admissions refused; active requests untouched | L4 |
| FI-4 | event loop | poison/malformed envelope | rejected + fault.recorded; loop continues | I22 |

## 6. Event Ordering Tests (EO-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| EO-1 | one request, events E1, E2, E3 | all arrive | transitions in arrival order | I15 |
| EO-2 | two requests' event streams | interleaved arbitrarily | each outcome identical to isolated run | phase-2 D1 |
| EO-3 | verify.passed for request R | arrives before task.completed | verdict recorded; gate permits on completion | phase-3 executing |

## 7. Cancellation Tests (CT-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| CT-1 | request in (created, initialized, scheduled, executing, verifying) | request.cancelled | transition to cancelled; ack; cleanup | phase-3 table |
| CT-2 | terminal request | request.cancelled | no-op; no state change | phase-3 table |
| CT-3 | cancelled request | second cancel | single ack; dedup no-op | I8 |

## 8. Configuration Tests (CF-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| CF-1 | request in executing | config.changed mid-flight | in-flight use old config; all decisions log version | I14, I18 |
| CF-2 | gate/timeout/retry in config | policy value changed | takes effect without Kernel recompile | I13 |
| CF-3 | task.failed loop | replans hit max_replans (config) | request → failed + request.failed | phase-7 |

## 9. Boundary Tests (BT-x)

| ID | Given | When | Then | Invariant |
|---|---|---|---|---|
| BT-1 | code audit, runtime trace | any scenario | zero calls to storage write/process spawn/retrieval/LLM | I12, I19 |
| BT-2 | every emitted event | schema check | passes phase-6 envelope (event_id, event_name, request_id, timestamp, config_version, payload) | phase-6 envelope |
| BT-3 | any scenario | any action | emitted event or transition-log record | I21 |
| BT-4 | Kernel code/contracts | grep domain terms | zero matches; domain-neutral | I20 |

---

Test IDs are stable — PRs reference them; a PR that cannot pass without changing a test is an architectural change, escalate.
