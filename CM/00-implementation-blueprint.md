# Context Manager (CM) — Implementation Blueprint

Build spec for `src/cm/`. Sources of truth: this file + `COMPONENTS/context-management.md` (amended 2026-07-13) + `KERNEL/INVARIANTS.md` + CM-I invariants below. Python 3.12+, stdlib only. Five phases, one per session; commit + push after each; module-per-commit with `__main__` selftest (kernel Phase-10 pattern).

**Purpose.** CM transforms Unified Memory into **Request Memory** (formerly "Optimal Context Package") — the smallest correct working set for one execution. The Reasoning Engine never sees the repository; it sees only Request Memory. Context is constructed, not collected. Output = exactly one artifact: Request Memory.

**Scope rulings (2026-07-13).** Prompt compilation is OUT — future Prompt Compiler Execution Service consumes Request Memory. CM integrates only with Kernel, UMS, RSM.

## Global laws that bind every phase

| Law | Meaning here |
|---|---|
| Law 1 single owner | CM is the sole assembler of Request Memory; owns nothing else |
| Law 2 retrieval authority | Zero similarity/retrieval code in `src/cm/`; all retrieval via `ums.query.query(bundle, text, budget_tokens, query_class)` |
| Law 3 single writer | CM persists nothing durable; Request Memory is ephemeral |
| Law 6 determinism | Identical Assembly Spec + identical UMS/RSM state → byte-identical Request Memory |
| I7/I8 bus discipline | Log before publish; consumers idempotent by event_id |
| I21/I22 | Every action emits telemetry; fail loud, never degrade silently |
| Closed events | `context.assembled` / `context.overflow` / `context.invalidated` only; inventing names forbidden |
| Event-name canon | UMS code names are canonical: `repo.indexed` / `index.stale` / `index.updated` (NOT the ARCHITECTURE.md matrix `memory.*` rows — matrix fixed in Phase 5). CM invalidation trigger = `index.updated` |

## CM invariants (CM-I)

1. Budget = hard ceiling; Request Memory never exceeds it. Overflow is tiered + reported via `context.overflow`, never silent.
2. Identical Assembly Spec + identical UMS/RSM state → byte-identical Request Memory (hash-equal).
3. CM contains zero retrieval/similarity code (Law 2).
4. CM persists nothing durable; Request Memory lives for one execution.
5. Every item carries provenance; stale is flagged, never hidden (UMS query supplies `stale` — CM must not re-derive it).
6. CM never mutates UMS, RSM, or the Ledger; reads only. RSM mirrors CM output (context-package id) downstream; RSM is never an upstream dependency of CM decisions (RSM/04).
7. Closed event set (see laws).
8. Exactly one assembler system-wide; CM does not compile prompts.
9. Context is constructed, not collected: nothing enters without spec-driven justification.
10. Zero duplicated retrieval: one UMS query per store per assembly.

## Module decomposition (src/cm/)

| Module | Purpose | Phase |
|---|---|---|
| `request_memory.py` | Frozen artifact: objective, constraints, sections (symbols, files, dependency graph, knowledge, experience), assembly/validation/budget metadata; canonical JSON serialization (`envelope.canonical` style); deterministic content hash | 1 |
| `spec.py` | Assembly Spec intake: normalize inputs (request-id, objective, budget, capability requirements, constraints, references) into canonical spec; spec hash = cache key | 1 |
| `events.py` | Closed event set; structurally refuses invented names (`ums/events.py` pattern) | 1 |
| `config_view.py` | Policy as data: default budgets, section weights, resolver depth caps (kernel pattern) | 1 |
| `bus_double.py` | In-memory bus double for tests (own copy — never import another component's double) | 1 |
| `sources.py` | Source adapters: UMS query adapter (one query per store per assembly), RSM snapshot/block reads, knowledge/experience reference resolvers; provenance stamped on every item | 2 |
| `resolver.py` | Dependency-aware expansion: seeds → bounded-depth BFS over UMS dependency records; cycle-safe; sorted frontier for determinism | 3 |
| `dedup.py` | Duplicate elimination by id/content-hash; contradictions surfaced, never blended | 3 |
| `prioritizer.py` | Deterministic priority: section class > relevance score > id tie-break; stable ordering | 3 |
| `budgeter.py` | Per-section budget envelopes + hard total ceiling; tier degradation mirroring `ums/budget.py` (full→section→reference→drop); token = whitespace word | 4 |
| `assembler.py` | Pipeline orchestrator: intake → gather → resolve → dedup → prioritize → budget → order → validate → emit; progressive loading; log-before-publish | 4 |
| `validator.py` | Structural gates: ceiling respected, zero dupes, provenance complete, stale flagged, hash-stable; fail loud, blocks emit | 4 |
| `cache.py` | Ephemeral Request-Memory registry keyed (request_id, spec-hash); never persisted | 5 |
| `freshness.py` | Consume `index.updated` → invalidate cached artifacts touching changed paths; section-scoped incremental rebuild | 5 |
| `law_enforcer.py` | Automated checks: no similarity impl in `src/cm/`, single assembler, closed event set | 5 |

## Phase 1 — Foundation & artifact

| Section | Content |
|---|---|
| Objective | Request Memory artifact + Assembly Spec fully specified, deterministic, serializable |
| Responsibilities | Artifact shape, canonical serialization, content hash; spec normalization + hashing; closed event set; policy defaults; bus double |
| Internal components | **request_memory** (frozen artifact), **spec** (intake/normalize/hash), **events** (closed set), **config_view** (policy data), **bus_double** |
| Data produced | Request Memory schema; Assembly Spec schema; event payload shapes (`context.assembled` = {request_id, memory_id, hash, tokens_used, coverage}) |
| Dependencies | None (pure additive package) |
| Completion criteria | All module selftests green; `tests/test_cm_phase1.py` green; existing 161 tests untouched |
| Testing goals | Artifact immutability; byte-identical serialization replay; spec-hash determinism; event-name closure (invented name raises) |
| Risks | Over-specifying sections before pipeline exists — keep sections a closed tuple, content opaque |
| Deliverables | 5 modules + phase tests, committed module-per-commit, pushed |

## Phase 2 — Sources

| Section | Content |
|---|---|
| Objective | Spec → deterministic raw candidate set from UMS + RSM |
| Responsibilities | Single-query-per-store gathering; provenance stamping; RSM block reads (identity/plan/budget via `rsm.query.block`/`snapshot` -- RSM has no "constraints" block; see sources.py RSM_BLOCKS) |
| Internal components | **sources** (UMS adapter, RSM adapter, knowledge/experience reference resolvers); fixture UMS bundle under `tests/fixtures/` |
| Data produced | Candidate item = {id, section, content tiers, score, stale, provenance} |
| Dependencies | Phase 1 spec; `src/ums/query.py`, `src/rsm/query.py` (read-only) |
| Completion criteria | Phase 1+2 tests green; UMS query call-count assertion proves zero duplicated retrieval |
| Testing goals | Provenance completeness; RSM store not mutated; absent request handled loud-but-graceful; determinism of candidate order |
| Risks | Bundle provisioning unwired (Lifecycle/Kernel future) — bundle is injected input; `ponytail:` seam comment |
| Deliverables | `sources.py` + fixtures + `tests/test_cm_phase2.py`, pushed |

## Phase 3 — Selection core

| Section | Content |
|---|---|
| Objective | Candidate set → ordered, unique, dependency-complete selection |
| Responsibilities | Dependency expansion, dedup, prioritization, stable ordering |
| Internal components | **resolver** (bounded BFS, sorted frontier, cycle-safe, depth cap from config_view), **dedup** (id/content-hash; contradiction surfacing), **prioritizer** (section class > score > id) |
| Data produced | Ordered selection list; expansion trace metadata |
| Dependencies | Phase 2 candidates; UMS dependency records |
| Completion criteria | Phases 1–3 tests green |
| Testing goals | Cycle safety; depth cap honored; dedup idempotence; ordering stability across shuffled input |
| Risks | Nondeterministic set iteration — sort everything, tie-break by id |
| Deliverables | 3 modules + `tests/test_cm_phase3.py`, pushed |

## Phase 4 — Budget, assembly, validation

| Section | Content |
|---|---|
| Objective | First end-to-end Request Memory; events emitted |
| Responsibilities | Envelope allocation + global ceiling with tier degradation; progressive loading; validation gates; `context.assembled`/`context.overflow` emission |
| Internal components | **budgeter** (mirrors `ums/budget.py` semantics), **assembler** (pipeline orchestrator, log-before-publish), **validator** (gates before emit, fail loud) |
| Data produced | Complete Request Memory instances; overflow/coverage metadata |
| Dependencies | Phases 1–3 |
| Completion criteria | End-to-end assembly deterministic (Law 6 hash-equal replay); full suite green |
| Testing goals | Budget sweep never exceeds ceiling (mirror `ums/budget.py` selftest style); overflow event fires and reports tiering; validator blocks bad artifacts; end-to-end determinism |
| Risks | Token counting = whitespace words (inherited ceiling) — isolate behind one function; upgrade path = real tokenizer |
| Deliverables | 3 modules + `tests/test_cm_phase4.py`, pushed |

## Phase 5 — Freshness, incremental, integration

| Section | Content |
|---|---|
| Objective | CM complete: caching, invalidation, incremental rebuild, law enforcement, doc reconciliation |
| Responsibilities | Cache keyed (request_id, spec-hash); `index.updated` → path-overlap invalidation + `context.invalidated`; section-scoped incremental rebuild; automated law checks |
| Internal components | **cache**, **freshness**, **law_enforcer** |
| Data produced | Invalidation records; rebuild equivalence guarantees |
| Dependencies | Phases 1–4; UMS `index.updated` payload (`{"paths":[...]}` — ASSUMED in UMS, producers absent; verify when Storage built) |
| Completion criteria | Full suite kernel+ums+rsm+cm green; law_enforcer green across `src/`; ARCHITECTURE.md event matrix fixed (`memory.*` rows → `repo.indexed`/`index.stale`/`index.updated`; add `context.overflow`, `context.invalidated` rows) |
| Testing goals | Invalidation on `index.updated`; **incremental rebuild == full rebuild (equivalence property — the critical test)**; cache-hit determinism |
| Risks | Incremental-rebuild equivalence is the subtle algorithm; equivalence property test is the guard |
| Deliverables | 3 modules + `tests/test_cm_phase5.py` + doc amendments + CM completion note, pushed |

## Build order

| Order | Phase | Depends on |
|---|---|---|
| 1 | Foundation & artifact | — |
| 2 | Sources | 1 |
| 3 | Selection core | 2 |
| 4 | Budget/assembly/validation | 3 |
| 5 | Freshness/incremental/integration | 4 |

Strictly linear; one phase per session; no spillover; each phase leaves repo production-ready.

## Subsystem interaction

```
            spec (objective, budget, constraints, refs)
                          |
                          v
   RSM  --read-only-->  [ CM pipeline: intake > gather > resolve >
   UMS  --query API-->    dedup > prioritize > budget > order >
                          validate > emit ]
                          |                       |
                          v                       v
                   Request Memory          bus: context.assembled /
                (ephemeral, one exec)      context.overflow / .invalidated
                                                  |
                                                  v
                                     RSM mirrors memory-id into
                                     record's `context` block (downstream)
```

## Data flow

Assembly: Assembly Spec → UMS query per planned store (once each) + RSM blocks → candidates with provenance/stale → dependency expansion (bounded) → dedup → prioritize → per-section envelopes + global ceiling with tier degradation → deterministic order → validation gates → Request Memory + `context.assembled`.

Update flow: `index.updated{paths}` → cache scan for path overlap → invalidate (+`context.invalidated`) → on next demand, incremental rebuild of affected sections only; result must equal full rebuild.

## Project Execution Guide

| Topic | Directive |
|---|---|
| Sources of truth | This blueprint + amended `COMPONENTS/context-management.md` + `KERNEL/INVARIANTS.md` + CM-I list |
| Never modify | `src/kernel/`, `src/ums/`, `src/rsm/` code; kernel invariants; UMS/RSM specs |
| Fixed assumptions | Token = whitespace word; bundle injected by caller; `index.updated` payload `{"paths":[...]}`; RSM read optional never required |
| Coding | Stdlib only; module-per-commit with selftest; `ponytail:` comments mark deliberate ceilings + upgrade paths; docstrings cite CM-I ids |
| Testing | `tests/test_cm_phase<N>.py` per phase; run full suite before and after each phase; no redundant tests |
| Process | Implement → test → fix → commit → push → stop; fresh conversation per phase; Fable medium = plan/review, Sonnet high = code |

## Status

| Phase | Status |
|---|---|
| 1 Foundation & artifact | Done |
| 2 Sources | Done |
| 3 Selection core | Done |
| 4 Budget/assembly/validation | Done |
| 5 Freshness/incremental/integration | Done -- CM complete, 15/15 modules, `tests/test_cm_phase1..5.py` green |
