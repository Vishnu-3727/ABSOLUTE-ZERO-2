# Kernel Invariants

Immutable. A change that violates any line below is an architecture change, not a patch.

1. Coordinator is the sole mutator of the Request Ledger.
2. Every Kernel decision is a table lookup or a boolean check — never judgment.
3. Router is static forever: declared type → owning component. No content inspection, no inference, no fallback.
4. One deterministic transition table. Unmatched (state, event) pair = fault, state unchanged.
5. Missing verdict = blocked. Absence never defaults to permit.
6. Ambiguity = reject. Never guess.
7. Log before publish.
8. At-least-once delivery in; exactly-once state mutation, dedup keyed by event id.
9. Sequence numbers are outbound-only. Never inbound dedup.
10. Kernel owns no timers. Timeouts arrive as events.
11. Kernel computes no metrics. Emission unconditional, never sampled.
12. Kernel never writes durably, spawns, retrieves, assembles context, plans, reasons, or calls an LLM.
13. All policy is Config View data. Kernel never owns policy content.
14. Config View is read-only; updates arrive only as config.changed events.
15. Single-threaded loop. Events in arrival order. No locks, no parallelism inside the Kernel.
16. Ledger is in-memory only. The transition log is the sole durable record; Storage persists it.
17. Replay must be byte-identical. Deviation = corruption = halt.
18. Every decision is replayable: config_version + transition_sequence recorded per transition.
19. Zero direct edges with Repository Memory, Context Management, Plugin Runtime, Execution, or any LLM.
20. Zero domain terms in Kernel contracts.
21. Every action emits telemetry (event or transition-log record). No silent work.
22. Fail loud: halt over degrade, fault.recorded over silence, block over guess.
