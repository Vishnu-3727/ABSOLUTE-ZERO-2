# Plugin Runtime — Phase 5: System Integration

Closes the Plugin Runtime design: resolves the event-canon drift PRT/00 §7 flagged (D1–D4),
sweeps Phases 0–4 for residual ambiguity, and fixes PRT's seams against every neighboring
subsystem in one place. Architecture only — no code, no schemas, no APIs. Builds within
`PRT/00-architectural-foundation.md` through `PRT/04-health-reliability.md` (all locked; every
invariant PRT-I/R/A/B/H* binds here unchanged). Cites `ARCHITECTURE.md`, `CP/00–04`, `WS/00–02`,
`COMPONENTS/plugin-runtime.md`. Restates none of them.

---

## 1. Overall execution flow

One fulfillment, seam by seam. WS dispatches a **capability id** — never a provider id (PRT/00
C3, WS/02 §1) — the moment a unit becomes READY (WS/02 §2). Execution requests resolution of that
id. PRT runs the binding process (PRT/03 §3, stages 1–6: capability lookup → candidate set →
eligibility filtering → policy evaluation → deterministic resolution → contract commitment) and
hands the resulting Binding Contract to Execution (PRT/03 §7). Execution acquires resources,
spawns, and enforces isolation policy (Law 3; PRT/03 Ruling 1) — PRT's involvement in this
fulfillment ends at handoff. Execution emits outcome events (`exec.completed`/`exec.failed`/
`exec.timeout`). A unit's dependency is satisfied only at **verified success** — execution
completion AND the required verification verdict (WS/02 §1, §7) — so Verification's gate sits
between Execution's outcome and the dependency being usable downstream. All outcomes land in
Observability's episodic traces (PRT/04 §9). Learning closes the loop: it distills closed traces
into `reliability.updated`, consumed by both PRT (health input, PRT/04 §4) and CP (planning prior,
PRT/00 §5).

| Step | From → To | Artifact/event crossing the seam |
|---|---|---|
| 1 | WS → Execution | Capability id (dispatch of a READY unit, WS/02 §2) |
| 2 | Execution → PRT | Binding request for that id |
| 3 | PRT internal | Binding process, PRT/03 §3 stages 1–5 |
| 4 | PRT → Execution | Binding Contract (PRT/03 §7), binding ends here |
| 5 | Execution → bus | `exec.completed` / `exec.failed` / `exec.timeout` |
| 6 | Execution outcome → Verification | Verification gate evaluates the unit (WS/02 §7, §10c) |
| 7 | Verification → bus | `verify.passed` / `verify.failed` |
| 8 | Verified outcome → WS | Dependency satisfaction (WS/02 §1) or failure-path resolution (WS/02 §7) |
| 9 | All of the above → Observability | Episodic trace entries (PRT/04 §9) |
| 10 | Observability (closed traces) → Learning → PRT, CP | `reliability.updated` (PRT/04 §4, §9) |

Only architectural transitions appear above; dispatch policy, retry, and resilience mechanics are
WS/scheduling-policy territory, out of scope here (WS/02 §10 pointer).

## 2. Cross-subsystem integration

| Subsystem | Direction | What crosses | What NEVER crosses |
|---|---|---|---|
| Kernel | — | Nothing direct; admission/routing authority is Kernel's, PRT has no seam beyond the bus + config discipline it shares with every component | Kernel never queries or gates on provider identity |
| RSM | PRT → RSM | PRT's published events mirrored as downstream telemetry | RSM never becomes a control edge back into PRT (RSM-I15: `state.*`/mirrored events are telemetry only) |
| UMS / Repository Memory | — | Nothing | No seam at all: registry lookup is exact/indexed (id, category, facet), never similarity retrieval (Law 2) — a retrieval edge here would violate the one-retrieval-path law |
| Context Manager | Registry → CM | Read-only capability metadata for Request Memory assembly, if needed | CM never writes registry state, never assembles Request Memory from provider identity |
| CP | Registry, events → CP | Registry (read), `plugin.health.changed`, `reliability.updated` — CP's principal reader status (PRT/01 §3, PRT-R3) | CP never writes the registry, never proposes capability definitions (PRT/01 §3 ownership clarification) |
| WS | Events → WS | `plugin.health.changed`, `plugin.unloaded` for eligibility awareness (scheduling-adjacent, not provider-level) | WS never talks to providers directly; it schedules capability ids only (PRT/00 C3) |
| Execution | Bidirectional | PRT → Execution: Binding Contract. Execution → PRT (via bus): `exec.*` evidence | Execution never receives provider selection input from anywhere but the contract; PRT never spawns (PRT-I5) |
| Prompt Compiler | — | Nothing | Provider identity never crosses above Execution; model-agnosticism holds because the Prompt Compiler line is below any provider-identity leak point |
| Reasoning Engine | — | Nothing | No seam whatsoever — PRT is deterministic territory; a reasoning call never influences binding (PRT-B1, PRT/00 §4) |
| Verification | Registry → Verification | PRT supplies capability verification expectations via registry read (PRT/01 §8, CP/01 §7) | Verification never asks PRT which provider ran; that's recorded in the contract, not re-derived |
| Learning / Experience | Bidirectional | PRT → Observability → Learning: closed-trace material. Learning → PRT: `reliability.updated` (PRT/04 §9 seam) | PRT never writes semantic memory, Learning never touches live health (PRT-H10) |

## 3. Architectural contracts

| Contract | Classification | Why it matters |
|---|---|---|
| Capability Registry (versioned read surface) | Immutable per version; historical — every version replayable forever | CP/04's determinism tuple cites "registry version" as a citable coordinate (PRT/01 §4); replay must reach an unaltered past state |
| Binding Contract | Immutable + historical — the replay artifact | Carries the frozen registry version + health snapshot a fulfillment was resolved under (PRT/03 §7, PRT-B6); this is what makes "why did provider X run" mechanically answerable (PRT-B12) forever |
| Health Snapshot | Operational → frozen: live until read, immutable once inside a contract | Before binding, it's a moving fact; the instant it's read it becomes a citable coordinate — the two-coordinate design (PRT/00 §4) depends on this exact transition happening once, not continuously |
| Provider Metadata | Immutable per registry version | Same replay guarantee as the registry itself — provider metadata is registry content (PRT/01 §2), not a side channel |
| Operational State (health, load) | Live view — operational, never historical, never citable except via a contract snapshot | PRT-B8/PRT-H2: operational state never mints a version; citing it directly (rather than via a contract) would poison replay with a moving target |

Classification is what tells a future developer which coordinates a replay, an audit, or a
determinism tuple may trust: immutable/historical coordinates are safe to cite directly forever;
operational coordinates are safe to cite only through the one artifact (Binding Contract) that
freezes them.

## 4. Event canon

This section **resolves PRT/00 §7 D1–D4**. The drift table is now closed; no future phase may
reopen it without a new architecture change.

| Event | Publisher | Consumers | Semantics |
|---|---|---|---|
| `plugin.discovered` | Plugin Runtime | Lifecycle, Observability | Discovery observed a candidate + collected its declaration (PRT/02 §1); announces candidacy existence, not a registry change |
| `plugin.registered` | Plugin Runtime | Capability Planning, Lifecycle, Observability | Publication minted a new registry version containing the provider (PRT/02 §7) |
| `plugin.loaded` | Plugin Runtime | Execution, Observability | Provider entered loaded/prepared operational state (Lifecycle-legalized, PRT-enacted, PRT/03 §9) |
| `plugin.unloaded` | Plugin Runtime | Scheduling, Observability | Provider left loaded state (released/reclaimed) |
| `plugin.health.changed` | Plugin Runtime | Scheduling, Capability Planning, Observability | Health threshold crossing — includes quarantine entry/exit, degradation, recovery (PRT/04 §6–§7) |
| `plugin.lifecycle.changed` | Lifecycle | Plugin Runtime, Observability | Authoritative operational-state transition decision PRT must enact (C7, PRT-A4) |
| `reliability.updated` | Learning | Plugin Runtime, Capability Planning, Observability | Already canonical, unchanged |

**Resolutions, with rationale:**

- **D1 — `plugin.disabled` rejected, `plugin.unloaded` adopted.** `plugin.disabled`'s meaning
  (provider barred from eligibility) is exactly the fact `plugin.health.changed` already announces
  (PRT/04: quarantine = health threshold crossing, an operational availability fact, PRT-H3). A
  second event for the same fact would be two names for one truth — every consumer would have to
  reconcile them instead of reading one. Its former matrix consumers (Scheduling, Capability
  Planning) move to `plugin.health.changed`. `plugin.unloaded` (the frozen spec's name) is adopted
  for load-state exit, because load-state change (loaded/unloaded) is a *different fact class*
  than eligibility change (health.changed) — a provider can unload while healthy (idle reclaim,
  PRT/03 §9) and can be barred while still loaded (quarantine, PRT/04 §3). Both facts exist;
  neither substitutes for the other.
- **D2 — `process.failed`/`process.timeout` are dead vocabulary.** They were never published by
  anyone; the frozen spec's Inputs section named a draft vocabulary that no publisher ever
  implemented. Canon = `exec.failed`/`exec.timeout`, Execution's actually-published names (matrix,
  `ARCHITECTURE.md`). PRT consumes `exec.*` as health evidence (PRT/04 §2).
- **D3 — `plugin.lifecycle.changed` adopted, gets a matrix row.** It is the C7/PRT-A4 enactment
  trigger: Lifecycle decides a transition, PRT enacts its registry/load-state effect. Without a
  declared event, Lifecycle's decisions have no transport and PRT-I9 ("Lifecycle transitions are
  enacted, never originated") has nothing to enact against.
- **D4 — ARCHITECTURE plugin-lifecycle diagram realigned.** State `Disabled` renamed
  `Quarantined` (matches PRT/04 §3 vocabulary exactly — "Disabled" never appeared in any PRT phase
  as a health state). Transition `Degraded → Disabled: plugin.disabled` becomes
  `Degraded → Quarantined: plugin.health.changed`. Transition `Disabled → Registered: re-enable
  after recovery` becomes `Quarantined → Registered: re-enable after recovery
  (plugin.health.changed)` — recovery is itself a threshold crossing in the opposite direction
  (PRT/04 §3 Recovering → Recovered), not a distinct event.

**Why each rejection is safe — no information loss.** `plugin.disabled` ⊂ `plugin.health.changed`:
every fact the former would carry is a health-threshold fact the latter already carries; nothing a
consumer needed is lost by consuming one event instead of two. `process.failed`/`process.timeout`
were never published by anyone — removing a name nobody emitted removes zero information, only a
draft label that outlived its own accuracy.

## 5. Architectural consistency review

Sweep of Phases 0–4 for residual ambiguity. One finding: terminology. Everything else PRT/00-04
already fixed holds without amendment.

| Term | Canonical meaning | Where fixed |
|---|---|---|
| Plugin | The packaged artifact Discovery finds (a candidacy, pre- or post-admission, as raw thing-in-the-world) | PRT/02 §1 |
| Provider | The admitted registry entity bound to capabilities — what a plugin becomes once PRT-R2 admits it | PRT/01 §7, PRT/02 §2 |
| Candidacy | A pre-publication processing instance of a plugin moving through Unknown→Discovered→Candidate→Validated | PRT/02 §2 |
| Binding Contract | The immutable artifact minted at binding stage 6, carrying resolved provider + registry version + health snapshot | PRT/03 §7 |
| Health snapshot | The frozen, once-read value inside a Binding Contract | PRT/04 §6 |
| Health state | The live, continuously-moving runtime view health is computed from | PRT/04 §1, §6 |
| Quarantine | Operational barring via threshold crossing; reversible | PRT/04 §7 |
| Retirement | Registry-mutating, Lifecycle-decided, permanent tombstone | PRT/02 §8, PRT/04 §7 |

**Ruling — events keep `plugin.*` names for matrix continuity; docs say "provider."** The event
canon (§4) is frozen vocabulary shared with `ARCHITECTURE.md` and every consumer's expectations;
renaming events to `provider.*` would be a breaking, purely cosmetic churn with zero semantic
gain. Prose in this and future PRT docs says "provider" when referring to the admitted entity,
"plugin" only for the pre-admission artifact — the words distinguish two objects, the events
distinguish nothing new.

**The three recurring splits are one pattern.** The admission pipeline (PRT/02 §4: PRT admits,
Lifecycle has no authority pre-publication), the load three-way split (PRT/03 §5 Ruling 3: PRT
decides policy, Lifecycle decides legality, Execution realizes effects), and the health transition
split (PRT/04 §3, §7: PRT requests via threshold, Lifecycle legalizes, PRT enacts) are the same
shape three times. Named once, here, for all future citation: **PRT proposes-or-enacts, Lifecycle
legalizes, Execution realizes machine effects.** Any future PRT design question that looks like a
new ownership question is very likely this pattern recurring at a new seam, not a new problem.

## 6. Failure boundaries

| Failure class | Owner | Propagation | Recovery owner |
|---|---|---|---|
| Admission failures | PRT | Loud refusal, stage- and rule-specific (PRT/02 §9, PRT-A12) | Resubmission = a new candidacy (PRT/02 §2); never resumed from the failure point |
| Binding failures, incl. empty eligible set | PRT | Ordinary loud result event (PRT/03 §3, PRT-B5) | CP/WS via alternative-relationship capabilities or `plan.revised` (CP/03), entered only after PRT's loud failure |
| Loading failures | Execution realizes process effects → evidence events → PRT health (PRT/03 §7) | `exec.*` evidence lands as health input (PRT/04 §2) | Lifecycle legality governs any resulting state transition (PRT-A4) |
| Health-driven barring | PRT thresholds request it | Lifecycle legalizes (PRT-H11) | Healing — guaranteed recovery path from every quarantine (PRT-H5) |
| Execution failures | Execution contains them (Law 3, V1-H4) | `exec.failed`/`exec.timeout` | PRT only consumes evidence; it never intervenes in Execution's containment |
| Verification failures | Verification's verdicts | `verify.failed` (WS/02 §7 FAILED path) | PRT uninvolved entirely |
| Learning failures | Learning's own | Worst case: stale priors | PRT keeps functioning on live evidence alone — graceful degradation of the seam (PRT/04 §4, §10) |

**Key line:** PRT never recovers anyone else's failure; it only turns evidence into availability.

## 7. End-to-end determinism

| Seam | Determinism source | Citable coordinate |
|---|---|---|
| Registry | Immutable versions | Registry-global version (PRT-R4) |
| Admission | Deterministic outcome | Declaration set + prior version (PRT-A9) |
| Binding | Pure function + contract | Capability id, registry version, health snapshot, policy (PRT-B1, PRT-B6) |
| Loading | Policy deterministic; state outside registry | Load policy is registry content, load *state* is runtime (PRT-B8) |
| Health | Deterministic from ordered evidence | Ordered evidence history + priors version + admin acts (PRT-H1) |
| Execution | Nondeterminism contained | Contained in Execution/Reasoning per CP/03; the contract records what was decided, not what might vary |
| Verification | Gates on recorded expectations | Registry-declared verification expectation (PRT/01 §8) |
| Learning | Priors versioned | Folded as one declared input (PRT/04 §4) |

Every seam above is crossed by a citable coordinate, never ambient state. The full reproducibility
story: replay reads (registry version, Binding Contract, evidence journal, priors version) — zero
live-world re-queries, ever. This is why PRT-B12 holds unconditionally: a binding decision is
always mechanically explainable from what was recorded, never from re-asking the world what it's
doing now.

## 8. Architectural evolution

| Grows freely | Never changes |
|---|---|
| Providers (admission is the fixed gate, PRT/02 §10) | Registry shape (identity, categories, four relationships, one admission gate, one global version — PRT/01 §10) |
| Capabilities | Admission gate (nine stages, PRT/02 §3) |
| Categories/facets (rare, curated additions — CP/01 §5) | Contract shape (Binding Contract's five elements, PRT/03 §7) |
| Execution environments, as new platform-restriction constraint values | Health ownership split (PRT vs. Learning, PRT/04 §5) |
| Provider classes, as data | Four relationships (dependency, composition, alternative, conflict — PRT-R7) |
| — | Event canon (§4 above) |

New execution environments require only new platform-restriction values plus Execution-side
enforcement — zero PRT redesign, per PRT-R11 and CP/01 §10. Historical replay survives every one
of these changes because old coordinates (registry versions, contracts) stay readable forever;
growth adds new coordinates, it never invalidates old ones (PRT/01 §4, PRT/02 §7).

## 9. Performance objectives

Mechanisms only — no target numbers, none are architectural commitments.

| Objective | Mechanism |
|---|---|
| Reasoning reduction | Deterministic binding spends zero model calls choosing a provider (PRT-B1); capability indirection means plans never get re-planned purely because providers churned underneath a stable id (PRT/00 §4) |
| Prompt size | Provider identity never enters a prompt — it stays below the Prompt Compiler line (§2) |
| Execution latency | Indexed O(1) registry lookup (C9); demand-driven loading with a policy-eager option (PRT/03 §5); binding is mechanical resolution, not search (PRT/03 §3) |
| Operational failures | Graduated health states + quarantine containment + guaranteed healing (PRT/04 §3, §7) |
| Registry inconsistency | Single writer + admission gate + atomic publication makes drift structurally impossible, not merely policed (PRT/01 §1, PRT/02 §4, §7) |
| Provider instability | Evidence-driven barring + guaranteed recovery + late binding isolates plan-level churn from any one provider's instability (PRT/00 §4, PRT/04 §7) |

## 10. Final architectural summary

**Purpose.** Plugin Runtime is the OS's tool-agnosticism layer: capabilities live above it,
providers live below it, and deterministic resolution sits between the two. Nothing above PRT
ever needs to know which concrete plugin, tool, or skill answers a capability id.

**Responsibilities.** Three, one owner each: registry authority (sole catalog of capability
definitions, provider bindings, versions — PRT/00 §1); provider metadata and load policy
(discovery, admission, isolation-policy-as-data); live health and reliability (incremental
scoring, quarantine, guaranteed healing).

**Major concepts.** A versioned, immutable-per-version registry (PRT/01 §4); candidacy admission
through one nine-stage gate (PRT/02 §3); the Binding Contract as the sole replay artifact for a
fulfillment (PRT/03 §7); an availability ladder from Registered to Retired (PRT/03 §6); and a
strict health/reliability split between PRT's live score and Learning's healed priors (PRT/04 §5).

**Subsystem interactions, in one paragraph.** WS schedules capability ids and never touches a
provider; Execution is the sole requester of binding and the sole spawner of anything PRT resolves
to; CP reads the registry and health/reliability signals as its principal non-writing consumer;
Lifecycle owns every post-publication state transition PRT enacts but never originates; Learning
closes the loop from Observability's closed traces back into PRT's health computation and CP's
planning priors; everything else (Kernel, UMS, Context Manager, Prompt Compiler, Reasoning Engine,
Verification) either has no seam at all or touches PRT only through a registry read.

**Deterministic philosophy.** Two coordinates — a durable registry version and a frozen health
snapshot — are the entire domain of a binding decision. Reasoning never chooses a provider;
binding is a pure function, replayable forever from recorded coordinates, never from re-querying
a moving world.

**Long-term goals.** Years of registry growth are pure data addition against a fixed architecture:
new providers, new capabilities, new categories (rarely), new platform values — none of it touches
the admission gate, the contract shape, the health split, or the event canon this document closes.

---

## Invariants (PRT-S1..S9)

Binding on all future PRT work. Supersedes nothing in PRT-I/R/A/B/H*; adds integration-level
guarantees only.

1. **PRT-S1** — The event canon (§4) is closed and exhaustive for PRT's declared publish/consume
   set; a new event requires an errata to this document, never a silent addition.
2. **PRT-S2** — Dead vocabulary (`plugin.disabled`, `process.failed`, `process.timeout`) is never
   revived; a future need for similar information is served by an existing event (§4) or a new,
   explicitly-added one, never a resurrection.
3. **PRT-S3** — "Plugin" names the pre-admission artifact; "provider" names the admitted registry
   entity; events keep `plugin.*` names for matrix continuity regardless (§5).
4. **PRT-S4** — The decide-legalize-enact pattern (PRT proposes-or-enacts, Lifecycle legalizes,
   Execution realizes) is the single shape behind admission, load, and health transitions; a new
   ownership question at a new seam is presumptively this pattern, not a new one.
5. **PRT-S5** — No reasoning influence reaches any PRT decision — not admission, not binding, not
   health, not quarantine; every one is a deterministic function of recorded/declared inputs.
6. **PRT-S6** — PRT recovers only its own failures (admission, binding); it never recovers
   Execution's, Verification's, or Learning's, and degrades gracefully (on live evidence alone) if
   Learning's feed goes stale.
7. **PRT-S7** — Every replay-citable coordinate PRT produces (registry version, Binding Contract)
   is immutable once minted; operational state is citable only via a contract snapshot, never
   directly.
8. **PRT-S8** — Registry growth, provider churn, and new execution environments are content-only
   changes; none require redesign of registry shape, admission gate, contract shape, or event
   canon.
9. **PRT-S9** — PRT has zero direct seam with UMS/Repository Memory, Prompt Compiler, or
   Reasoning Engine; any future design proposing one is a violation of Law 2 or the
   deterministic-binding discipline (§2), not a new integration to accommodate.

---

Status: Phase 5 integration frozen. PRT/00 through PRT/05 together are the authoritative Plugin
Runtime architecture; `COMPONENTS/plugin-runtime.md` is corrected by errata where it drifted from
this canon and otherwise stands as the original component spec.
