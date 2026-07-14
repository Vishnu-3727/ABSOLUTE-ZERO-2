# Plugin Runtime (PRT) — Phase 0: Architectural Foundation

Full architecture review for the Plugin Runtime subsystem. Architecture only — no code, no
schemas, no APIs. Frozen spec `COMPONENTS/plugin-runtime.md` is authoritative; this doc situates
PRT inside everything designed since (CP/01–04, WS/00–02, CM, RSM, Kernel) and fixes the walls the
5 build phases must stay inside. Later phases design internals; they never widen these walls.

---

## 1. Role

PRT answers exactly one question for the OS: **"what providers exist, what capabilities do they
declare, and how healthy are they right now?"** It is the indirection that keeps the OS
model-agnostic and tool-agnostic: everything above PRT speaks capability ids (CP/01); PRT alone
knows which concrete plugin/tool/skill stands behind an id at fulfillment time.

Three responsibilities, one owner each inside PRT:

| Responsibility | Substance |
|---|---|
| Capability registry authority | Sole catalog of capability definitions + provider bindings + versions. Every other component reads; none writes. (CP/01 invariant 10.) |
| Provider metadata & load policy | Discovery, registration, version/compat refusal, isolation *policy* (what a loaded provider may touch — Execution enforces at spawn time). |
| Live health & reliability | Per-provider score updated incrementally from outcome events; quarantine thresholds; healing so no one-blip permanent blacklist. |

## 2. Ownership walls (what PRT never does)

| Never | Owner | Consequence for PRT design |
|---|---|---|
| Spawn processes | Execution (Law 3) | "Loading" a plugin = registry/state effect + isolation policy handed to Execution; PRT holds no process handles. |
| Durable writes | Storage | Registry + scores persist via Storage; PRT keeps the authoritative in-memory view. |
| Transport | Communication | All events on the bus; consumed idempotently by event id. |
| Plugin state-machine legality | Lifecycle | Lifecycle owns transitions; PRT *enacts* their registry/load effects on `plugin.lifecycle.changed`. PRT never invents a transition. |
| Matching/planning | CP | PRT serves data; CP decides which capability a plan step needs. PRT's only "choice" is provider binding at fulfillment (§4). |
| Reliability priors | Learning | Learning distills closed traces into healed priors (`reliability.updated`); PRT folds them into its live score. Two signals, one score, split in §5. |
| Retrieval/similarity | Repository Memory | Registry lookup is exact/indexed (id, category, facet) — never similarity search. |

## 3. Registry as CP/01's landing zone

CP/01 defined the capability *vocabulary* and assigned the registry to PRT. Phase 0 formally
accepts the obligation: the registry carries **all** CP/01 §7 metadata, specifically:

- Capability lifecycle states `proposed → active → deprecated → retired`; retired ids = permanent tombstones, never reused.
- Single-level closed **category** + open **facets**; no containment hierarchy, no inheritance.
- **Aliases** + deprecation pointers; meaning change = new id, append-mostly evolution.
- **Verification expectations** mandatory — a capability without one is inadmissible (fail loud at registration, not at planning).
- Exactly the 4 relationships (dependency, composition, alternative, conflict); registry stores them, CP interprets them.
- Provider bindings: which provider declares fulfillment of which capability id, with provider version and constraints.

Registry state is **versioned**: every mutation (registration, deprecation, binding change,
quarantine) produces a new monotonic registry version. CP/04's determinism tuple cites "registry
version" — PRT is the component that must actually mint it. Replays read historic versions;
new plans always read current (CP/04, no pinning).

## 4. Late binding (CP/03 contract, PRT side)

Plans and workflows reference **capability ids only**. PRT resolves id → concrete provider at
fulfillment time, when Execution asks to load. Consequences:

- Provider churn (install, upgrade, quarantine) never invalidates a published plan or workflow.
- Binding is **deterministic**: identical (registry version, health state) → identical provider choice. Tie-break = fixed total order (declared preference, then reliability, then stable id) — never wall-clock, never randomness.
- If no healthy provider serves an id: binding *fails loud* as an ordinary result event; WS/CP handle it via alternatives or `plan.revised`. PRT never guesses a substitute across capability ids — substitution across ids is CP's alternative-relationship territory.

## 5. Reliability model — ownership split

| Signal | Owner | Timescale | Feeds |
|---|---|---|---|
| Live health score | PRT | Per outcome event (`exec.failed`/`exec.timeout` evidence), incremental | Quarantine decisions, binding tie-break, `plugin.health.changed` |
| Healed priors | Learning | Per closed trace, cross-request | `reliability.updated` → PRT folds into score; CP reads as planning prior |

Score discipline (frozen spec, restated): identical registry + identical outcome history →
identical scores (Law 6). Healing/decay smoothing prevents quarantine flapping. Quarantine =
threshold crossing → registry effect + events; recovery path always exists (no permanent
blacklist). Score movement rules are Phase-4 design; the *ownership split above is fixed now*.

> **Errata (Phase 4):** "registry effect" above is imprecise — quarantine is an operational
> availability state, never a registry mutation and never a version mint (PRT-B8, PRT-H3;
> clarified in PRT/04 §7). The registry-mutating removal path is forced retirement (PRT/02 §8).

## 6. Inherited constraints (C1–C10)

| # | Constraint | Source |
|---|---|---|
| C1 | Registry = sole capability source; no component keeps a private tool list | frozen spec, CP/00 inv 5 |
| C2 | All capability-vocabulary rules of CP/01 §12 bind the registry verbatim | CP/01 |
| C3 | Plans/workflows never name providers; binding happens at fulfillment | CP/03 (late binding) |
| C4 | Registry versions are monotonic and citable in determinism tuples | CP/04 |
| C5 | PRT never spawns; isolation is policy PRT declares, Execution enforces | Law 3, frozen spec |
| C6 | Persistence via Storage only; bus via Communication only | Laws, ARCHITECTURE |
| C7 | Lifecycle owns plugin state transitions; PRT enacts effects only | frozen spec Dependencies |
| C8 | Event consumption idempotent by event id (at-least-once bus) | Communication model |
| C9 | Registry lookups indexed/O(1); health updates incremental, never rescans | frozen spec Performance |
| C10 | Version conflict = refusal at registration/load; never silent shadowing of another capability | frozen spec Failure Modes |

## 7. Event-canon drift (flagged now, fixed in implementation phase)

| # | Drift | Recommendation |
|---|---|---|
| D1 | Spec publishes `plugin.unloaded`; ARCHITECTURE matrix has `plugin.disabled` + `plugin.discovered` (absent from spec's Published list) | Pick one canon set covering discover/register/load/disable-or-unload/health; fix matrix + spec errata together |
| D2 | Spec consumes `process.failed`/`process.timeout`; matrix defines only `exec.failed`/`exec.timeout` | Canon = `exec.*` (Execution's published names); spec's `process.*` = stale draft vocabulary |
| D3 | Spec consumes `plugin.lifecycle.changed`; no such matrix row | Either add the row (publisher Lifecycle) or fold into the D1 canon set |
| D4 | ARCHITECTURE plugin-lifecycle state diagram (Degraded/Disabled/Unloaded) must name-align with the D1 outcome | Reconcile in the same pass |

Pattern precedent: UMS/CM/CP all resolved drift at implementation time with a matrix fix commit.
Same here — Phase 5 (integration) owns the reconciliation; no phase before it may invent event names.

## 8. Build phases (outline — Vishnu prompts each; subject to per-phase briefs)

| Phase | Scope |
|---|---|
| 1 | Registry model: capability records (CP/01 metadata), provider records, bindings, registry versioning, events/config-view/bus+storage doubles |
| 2 | Discovery & registration: manifest sources, admission gates (verification expectation mandatory, C10 refusal), lifecycle enactment |
| 3 | Binding & load policy: deterministic late binding, version/compat rules, isolation policy artifact handed to Execution |
| 4 | Health & reliability: incremental scoring, healing/decay, quarantine thresholds, `reliability.updated` fold-in |
| 5 | Integration: event canon fix (D1–D4), persistence via Storage double, law enforcer, ARCHITECTURE matrix/diagram reconciliation |

## 9. Invariants (PRT-I1..I10)

1. The registry is the sole capability source in the OS; PRT is its sole writer.
2. Every registry mutation produces a new monotonic registry version.
3. All CP/01 §12 capability-model invariants hold inside the registry, enforced at admission.
4. A capability without a statable verification expectation is refused at registration.
5. PRT never spawns a process and never holds a process handle.
6. Provider binding is deterministic on (registry version, health state); no wall-clock, no randomness.
7. Plans, workflows, and priors reference capability ids only; provider identity appears solely in binding results and telemetry.
8. Health scores are a deterministic function of registry state + ordered outcome history; healing guarantees a recovery path from every quarantine.
9. Lifecycle transitions are enacted, never originated, by PRT.
10. PRT publishes/consumes only its declared event set; drift D1–D4 resolves to one canon before any event code exists.

---

Status: Phase 0 frozen. Phases 1–5 design/build within these walls; contradictions require an
errata note here, never a silent divergence.
