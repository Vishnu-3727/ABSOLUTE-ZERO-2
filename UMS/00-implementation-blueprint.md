# UMS Implementation Blueprint

Build specification for the Unified Memory System (Repository Memory per
`COMPONENTS/memory.md`). Architecture frozen — this document only translates it
into an executable roadmap. Implementation sources for coders: this file +
`COMPONENTS/memory.md` + `KERNEL/INVARIANTS.md` (event discipline). Python
3.12+, stdlib-first, `src/ums/` package beside `src/kernel/`.

Global laws that bind every phase:

| Law | Meaning here |
|---|---|
| Law 2 | UMS is the ONLY component that reads repositories or scores similarity |
| Law 3 | UMS never writes disk — index bytes persist via Storage's write API |
| Law 6 | Same query + same index state = identical ranked results |
| Law 7 | Every event published lands on the bus; Observability consumes all |
| Freshness | Never serve stale as fresh; flag or refuse |
| Token | Never re-read, re-extract, re-summarize unchanged content |

---

## Phase 1 — Foundation: inventory, freshness, persistence

| Section | Content |
|---|---|
| Objective | UMS can manage a repository: know what files exist, detect what changed, persist and reload its state. Zero semantics yet. |
| Responsibilities | Repo registration (`repository.onboarded`/`offboarded`), file inventory, change detection, staleness map, index persistence/reload via Storage, event publication skeleton. |
| Internal components | **Registry** (which repos are managed); **Inventory** (per-file identity: path, content hash, size, mtime); **Freshness tracker** (per-region fresh/stale state, the single staleness authority); **Persistence adapter** (serialize/load logical index through Storage; detect corruption on load, mark region for rebuild); **Event emitter** (publishes `repo.indexed`, `index.stale`, `index.updated` per the component spec — no invented events). |
| Data produced | File inventory per repo; freshness map; durable, reloadable index skeleton. |
| Dependencies | None (first phase). Storage + Communication consumed as interfaces; in-memory test doubles acceptable (kernel bus pattern). |
| Completion criteria | Onboard fixture repo → inventory built → persisted → process restart → reloaded identical. File mutated → exactly that region flagged stale. Corrupt index file → detected, region marked rebuild-needed, loud not garbage. |
| Testing goals | Round-trip determinism (inventory → persist → load → byte-identical canon); change detection precision (only touched files flagged); corruption detection; no direct disk writes anywhere (grep-level law check). |
| Risks | Hash-everything on large repos too slow → mtime+size prefilter, hash only on suspicion. Freshness granularity chosen too coarse (whole-repo) forces Phase 5 rework — region = file from day one. |
| Deliverables | Inventory + freshness + persistence modules, selftests, fixture repo under `tests/fixtures/`. |

## Phase 2 — Structural extraction (deterministic)

| Section | Content |
|---|---|
| Objective | From inventoried files, extract structure without any LLM: symbols, modules, dependencies, conventions. |
| Responsibilities | Symbol understanding, dependency understanding, file classification, convention measurement. |
| Internal components | **Language classifier** (extension + marker based); **Symbol extractor** (Python `ast`: classes/functions/signatures/docstrings; non-Python falls back to file-level records — pluggable extractor seam, one built-in); **Dependency mapper** (import edges, internal vs external via `sys.stdlib_module_names`); **Convention profiler** (indent, quotes, naming, docstring/hint coverage — measured, not judged); **Module model** (files grouped into packages/modules). |
| Data produced | Symbol table; typed dependency graph (file/module/symbol nodes; imports/contains edges); convention profile; language/role classification per file. |
| Dependencies | Phase 1 (inventory supplies the file set; freshness scopes what to extract). |
| Completion criteria | Fixture repo → asserted symbol table + edge list, reproducible run-to-run. Extraction consumes only Phase-1 inventory (never re-walks disk). Unparseable file → recorded as unparsed, loud, never silently skipped. |
| Testing goals | Golden extraction fixtures; determinism replay; extraction cost proportional to file count; unparsed-file accounting. |
| Risks | Over-investing in multi-language parsing (YAGNI — vault is Python; seam suffices). `ast` version drift across Python versions → pin fixtures to syntactic constructs, not formatting. |
| Deliverables | Extractor modules + graph model, selftests, golden fixtures. |

## Phase 3 — Semantic layer

| Section | Content |
|---|---|
| Objective | Turn structure into understanding: summaries, relationships, architecture knowledge. Deterministic first; LLM only where interpretation is genuinely non-mechanical, and every LLM result is stored permanently (never re-asked while region unchanged). |
| Responsibilities | Semantic summaries (file/module/repo tiers), relationship graph beyond imports (implements/related-to), architecture knowledge (layer roles, entrypoints, boundaries). |
| Internal components | **Deterministic summarizer** (docstrings, signatures, headings, README → compact summaries with token ceilings, ≤25-token reference tier); **Semantic gap detector** (decides what deterministic summarization could NOT cover — the only place an LLM request may originate; emits a work order, does not call models itself); **Relationship deriver** (doc-mentions, co-change from git history via Storage, spec-implements links); **Architecture modeler** (top-dir roles, entrypoints, dependency layering — bootstrap-engine heuristics from V1, deterministic); **Summary store** (summaries keyed to content hash — hash unchanged = summary reused forever). |
| Data produced | Tiered summaries (full/section/≤25-token); enriched relationship graph; per-repo architecture model. |
| Dependencies | Phase 2 (symbols/graph are the summarizer's input), Phase 1 (hash keys). |
| Completion criteria | Fixture repo fully summarized with zero LLM calls; every summary within its token ceiling; unchanged file re-run produces zero new summarization work; LLM gap list is explicit output, not hidden behavior. |
| Testing goals | Summary reuse (run twice, second run does nothing); ceiling enforcement; gap-detector precision on fixtures with/without docstrings. |
| Risks | Biggest token-efficiency risk in UMS: sloppy hash keying silently re-summarizes → key = content hash, tested. LLM creep (summarizing what docstrings already say) → gap detector must default to deterministic. |
| Deliverables | Summarizer + relationship + architecture modules, summary store, selftests. |

## Phase 4 — Query engine

| Section | Content |
|---|---|
| Objective | The single system-wide retrieval/similarity implementation: ranked, explained, budget-fitted, freshness-flagged queries over Phases 1–3 knowledge. |
| Responsibilities | All similarity scoring; query planning; budget fitting; explainable ranking; freshness flagging. |
| Internal components | **Query planner** (query class → which stores to consult, what depth — bounded, never full-repo scan); **Ranker** (one scoring function; lexical/stem/structural signals composed with declared weights — V1 `core.retrieve` lineage; embedding backends = future seam, not built); **Explainer** (each hit carries per-signal score breakdown); **Budget fitter** (fidelity tiers full→section→summary→reference packed under caller ceiling; truncation reported, never silent); **Freshness gate** (hits from stale regions flagged; stale-as-fresh structurally impossible — flag attached by the store, not caller courtesy). |
| Data produced | Ranked result sets with explanations, freshness flags, coverage + truncation metadata. |
| Dependencies | Phases 1–3 (all stores queried; freshness map gates results). |
| Completion criteria | Golden-query fixture suite passes (fixed repo, fixed queries, asserted ranked order); identical query+state → identical results (Law 6); no result set exceeds its ceiling; stale-region hit always flagged. |
| Testing goals | Golden queries; determinism replay; budget ceiling property (never exceeded across randomized budgets); explanation completeness (every hit explains its score). |
| Risks | Ranking quality disputes → explainability is the mitigation (scores inspectable, weights in one table). Scan-per-query creep → planner depth caps asserted in tests. Fuzzy-score floor gotcha from V1 (short-string ratio ~0.2 noise) — carry the known floor discipline. |
| Deliverables | Query engine modules, golden-query fixture suite, ranking-weight table documented in-code. |

## Phase 5 — Incremental updates + system integration

| Section | Content |
|---|---|
| Objective | Close the loop: change events drive region-scoped reindex; huge-repo onboarding is incremental; UMS is consumable by the rest of the OS and the law is enforceable. |
| Responsibilities | Incremental update pipeline, invalidation cascade, partial-index onboarding, event wiring, law enforcement. |
| Internal components | **Change consumer** (`write.committed`/`commit.created` → changed paths → freshness tracker; publishes `index.stale` immediately); **Invalidation cascade** (file → its symbols → its edges → its summaries → architecture model iff structural facts changed; everything else untouched); **Reindex scheduler** (processes stale regions through Phases 2–3 extractors; publishes `index.updated`; cost proportional to change set); **Onboarding orchestrator** (large repo indexed in slices; queries answered mid-build with coverage metadata, never blocking); **Law enforcer** (cross-component check: no other component's code scans repositories or implements similarity — automated, part of verifier/selftest). |
| Data produced | Continuously fresh index; onboarding progress/coverage state; law-compliance report. |
| Dependencies | All prior phases (the cascade invalidates Phase 2–3 data; queries during update exercise Phase 4 flags). |
| Completion criteria | Mutate one file in fixture repo → `index.stale` then `index.updated`; only that file's knowledge changed (canon diff of index before/after touches one region); mid-update queries flag staleness; partial onboarding answers with coverage; law check green against `src/`. |
| Testing goals | Proportionality (change 1 of N files → reindex work ~1/N); event ordering (`stale` before `updated`, never a fresh-flagged stale hit between); cascade precision (untouched regions byte-identical); crash mid-reindex → reload → stale regions still marked (no lost staleness). |
| Risks | Cascade over-invalidates (architecture model rebuilt on every touch) → rebuild only on structural change. Event loss = permanent staleness → freshness recomputable from inventory hash sweep as recovery path. Multi-repo scale → per-repo isolation already given by Phase-1 registry. |
| Deliverables | Update pipeline, onboarding orchestrator, law-enforcement check, end-to-end selftest, `11`-style validation review after build. |

---

## Build order

| Aspect | Order |
|---|---|
| Dependency order | 1 → 2 → 3 → 4 → 5 (strictly linear; 4 needs 3's summaries for tiered results; 5 exercises everything) |
| Implementation order | Same as dependency order. One phase per session. Each phase = modules + selftests + spec-ID tests, committed per module (kernel Phase-10 pattern). |

## Subsystem interaction

```
Storage ──(file bytes, git history)──▶ UMS ◀──(events: write.committed, commit.created,
                                        │       repository.onboarded/offboarded)── Bus
                                        │
                    publishes: repo.indexed / index.stale / index.updated ──▶ Bus ──▶ Observability
                                        │
        query API (ranked, explained, budget-fitted, freshness-flagged)
                                        ▼
   Context Management · Capability Planning · Verification · Learning · Frontend
```

UMS reads repository bytes ONLY via Storage. UMS writes index bytes ONLY via
Storage. Consumers get knowledge ONLY via the query API — never files.

## Data flow

repo bytes (Storage) → Inventory → Structural extraction → Semantic layer →
stores (symbols, graph, summaries, architecture) → Query engine → consumers.

## Update flow

`write.committed`/`commit.created` → changed paths → Freshness tracker marks
regions → `index.stale` published → Reindex scheduler → cascade (symbols →
edges → summaries → architecture-if-structural) → stores updated → persisted
via Storage → `index.updated` published → Context Management invalidates
dependent packages (its spec, not ours).

## Lifecycles

| Lifecycle | Sequence |
|---|---|
| Repository indexing | `repository.onboarded` → inventory → extract → summarize → persist → `repo.indexed` (queryable) |
| Incremental update | change event → mark stale → `index.stale` → region reindex → persist → `index.updated` |
| Semantic query | request(query, budget) → planner → rank → freshness-flag → budget-fit → explained result set |
| Memory freshness | fresh —(change event)→ stale —(reindex)→ fresh; stale results always flagged; recovery = hash sweep rebuilds freshness from inventory |
| Startup | load persisted index via Storage → integrity check (corrupt region → rebuild-needed) → hash-sweep changed-while-down files → mark stale → queryable immediately (flags carry honesty) → background reindex |

Startup never re-reads unchanged files' content — inventory hash comparison
gates all work. Cold start on an already-indexed repo costs one metadata sweep.

---

## Project Execution Guide (for the coding model)

| Topic | Directive |
|---|---|
| Sources of truth | This blueprint + `COMPONENTS/memory.md`. Phase docs elsewhere = rationale. If they conflict, `COMPONENTS/memory.md` wins. |
| Never modify | `src/kernel/` (frozen, phase-11 reviewed); `COMPONENTS/*.md`; `ARCHITECTURE.md`; event names/payload contracts from `COMPONENTS/memory.md`; the five-phase boundaries. |
| Fixed assumptions | Python 3.12+ stdlib only (no third-party without owner approval); Storage/Communication consumed via thin interfaces with in-memory test doubles (kernel bus pattern) until those components exist; region granularity = file; summary keys = content hash; one similarity implementation, in Phase 4, nowhere else. |
| Coding priorities | 1 correctness of freshness (never stale-as-fresh) 2 determinism 3 token efficiency 4 speed. One module per commit with selftest (kernel Phase-10 pattern). Modules small, single-responsibility. `ponytail:` comments on deliberate ceilings. |
| Testing priorities | Golden fixtures + determinism replays + budget-ceiling properties per phase, as listed above. Selftest per module (`__main__` asserts). No frameworks beyond stdlib `unittest`-style asserts. |
| Performance priorities | Reindex cost ∝ change set, query cost bounded by planner depth caps — both asserted in tests, not assumed. |
| Token-efficiency priorities | Hash-gated reuse everywhere (read/extract/summarize each content-hash at most once, ever); summaries within declared ceilings; LLM work orders only from the Phase-3 gap detector, results stored permanently. |
| Scalability priorities | Per-repo isolation; incremental everything; partial answers with coverage over blocking. Do NOT build embeddings, DBs, or multi-language parsers — seams exist, filling them is future work. |
| Process | Fable medium = plan/review each phase; Sonnet high = code; Sonnet low = docs. Push to origin only after ALL five phases complete and reviewed. |
