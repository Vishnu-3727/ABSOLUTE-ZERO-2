# Plugin Runtime — Phase 4: Health & Reliability

One question: how does PRT maintain accurate operational knowledge about providers while
preserving deterministic binding. Architecture only — no code, no APIs, no scoring formulas, no
transition algorithms, no learning algorithms. Builds within `PRT/00-architectural-foundation.md`
(locked, especially §5 reliability ownership split, PRT-I8, drift flags D1–D4),
`PRT/03-binding-load-policy.md` (locked, especially PRT-B8, §6 availability ladder, §2 health
snapshot), `PRT/01-registry-model.md` (§2/§4 registry content and versioning), `PRT/02-discovery-
admission.md` (§8 forced retirement). Cites `COMPONENTS/plugin-runtime.md` and
`COMPONENTS/learning.md`. Restates none of them.

---

## 1. Provider health defined

**Health is PRT's current operational judgment of a provider's fitness to be bound**, derived from
observed evidence. It is not a registry fact.

| | Registry metadata | Health |
|---|---|---|
| Nature | Declared, durable, admission-gated | Observed, live, evidence-derived |
| Answers | What a provider *claims* to be | How a provider *actually behaves* |
| Moves on | Admitted mutation (PRT/01 §4) | Ordinary outcome events |
| Stability | Immutable once minted (PRT-R4) | Continuously current |

Why the two must stay separate: folding observation into registry content either freezes a
transient blip into an immutable version, or forces a version mint on every blip — the exact
flooding argument PRT/03 Ruling 2 already closes (PRT-B8, cite, not restated). Health is
operational, not architectural — it describes the present machine-world and keeps moving; registry
versions describe declared truth and never do. The two-coordinate binding design (PRT/00 §4,
PRT/03 §1) exists precisely so each half can move at its own speed without corrupting the other.

## 2. Health model

Health is a set of **evidence dimensions**, not a number. Each dimension names a category of
observation; how dimensions combine into an eligibility judgment is scoring — an implementation
concern, out of scope for architecture.

| Dimension | What it observes | Evidence supplied by |
|---|---|---|
| Availability | Is the provider currently reachable at all | Execution outcome events |
| Operational readiness | Has the provider completed load preparation (PRT/03 §9) | Lifecycle-enacted load state |
| Execution success | Do fulfillment attempts complete without error | Execution outcome evidence |
| Timeout behavior | Does the provider complete within expected bounds | Execution outcome evidence |
| Failure behavior | Pattern/severity of observed failures | Execution outcome evidence |
| Dependency readiness | Do declared prerequisite bindings (PRT/01 §6) currently hold | Registry state, checked not enforced |
| Administrative disablement | Has an operator explicitly barred this provider | Administrative act (§4) |
| Compatibility status | Does the provider remain compatible with the capability version in force | Registry state at current version |
| Resource exhaustion | Is the provider failing under resource pressure | Execution outcome evidence |

Evidence arrives via events — frozen-spec citation only: `process.failed`/`process.timeout`
(`COMPONENTS/plugin-runtime.md` Inputs) vs. the matrix's `exec.*` naming is exactly drift D2
(PRT/00 §7); this document names dimensions, never event identifiers, and resolves nothing.

## 3. Health lifecycle

Conceptual states — no transition algorithm, only what each state means and why it exists.

| State | Meaning |
|---|---|
| Healthy | No adverse evidence outstanding; fully eligible |
| Degraded | Adverse evidence present but below quarantine threshold; still eligible, disfavored |
| Unavailable | Barred from eligibility by an operational fact other than quarantine (e.g. dependency unmet, admin disable) |
| Quarantined | Barred from eligibility by threshold-crossing adverse evidence (§7) |
| Recovering | Evidence trending favorable after Quarantined/Unavailable; not yet re-eligible |
| Recovered | Transient waypoint back to Healthy |
| Retired | Registry fact (PRT/02 §8), not a health state — health lifecycle *ends* here, never owns it |

**Why Recovered exists as a waypoint, not a flag flip.** Recovery is earned gradually — a single
favorable outcome does not erase a quarantine history. Smoothing through a waypoint state prevents
the flapping the frozen spec names as Score-thrash (`COMPONENTS/plugin-runtime.md` Failure Modes):
a provider oscillating Quarantined → Healthy → Quarantined on noisy evidence is worse than one that
recovers deliberately.

**Mapping onto PRT/03 §6's availability ladder:**

| Health state | Availability rung |
|---|---|
| Healthy, Degraded, Recovered | Available |
| Unavailable, Quarantined, Recovering | Unavailable — Recovering is trending favorable but not yet re-eligible (§3 table) |
| Retired | Retired |

**Transition ownership.** PRT's threshold policy (frozen spec "Owns: reliability scoring model +
healing/decay") *requests* a transition when evidence crosses a threshold. Operational transition
*legality* belongs to Lifecycle (PRT-A4, PRT/00 C7) — the same split PRT/03 §9 fixes for load
state. PRT enacts its runtime-view consequence once Lifecycle legalizes the change. No algorithm
for when a threshold fires is specified here.

## 4. Health inputs

A closed, enumerable input-class table — mirrors PRT-B1's closed-set discipline. Nothing outside
it may influence health.

| Class | Content | Nature |
|---|---|---|
| Live observations | Execution outcome/timeout evidence (§2); dependency-unmet facts; environmental availability changes surfaced as events | Continuous, event-driven |
| Administrative policy | Operator disable/enable — a deliberate, recorded act, both directions | Discrete, deliberate |
| Historical knowledge | Learning's healed reliability priors, via `reliability.updated` | Versioned, declared, folded deterministically |

Anything not in this table never influences health — no live environment probing beyond declared
events (PRT/03 §2 forbidden-inputs discipline, same reasoning applied here).

**Why Learning is not PRT-owned.** Learning distills *closed* traces across requests into durable
priors — a semantic-memory-tier product (`COMPONENTS/learning.md` Owns: "reliability/prior
*derivations*"). PRT reacts to live evidence within the operational moment. Two timescales, two
owners — PRT/00 §5's split table, cited not restated. If PRT also learned from raw traces, two
authorities would independently derive "how reliable is this provider," and reliability truth
would fork — the same dual-authority failure class PRT/01 §1 and PRT/02 §2 already close at other
seams.

## 5. Reliability vs health

| | Health | Reliability |
|---|---|---|
| Horizon | Short — the operational moment | Long — historical characteristic |
| Owner | PRT | Learning |
| Moves on | Every outcome event | Every closed trace |
| Behavior | Direct, incremental | Heals/decays |
| Feeds | Binding eligibility, now | CP planning priors *and* PRT's health computation |

Why neither alone suffices: reliability alone is blind to a provider on fire right now (it only
updates on closed traces, cross-request); health alone has no stable long-term prior — every blip
would need to be re-learned from scratch with no memory across requests. The two meet at exactly
one seam: `reliability.updated` folds into PRT's live health computation as one declared input
(§4). One direction each way — PRT never writes reliability, Learning never reads live health —
no shared ownership.

## 6. Health publication

PRT maintains **one current health state per provider** — its runtime view, not a registry entry.
Binding never reads that live view mid-decision: it takes a snapshot **once**, at binding start
(PRT/03 §2), and that snapshot is frozen into the Binding Contract (PRT-B6).

**Snapshot stability.** Within one binding resolution, the snapshot is fixed the instant it is
read; no re-read of the live world occurs mid-decision, no matter how long resolution takes.

**Why contracts record snapshots, not live references.** Replay reads the contract, not the world
(PRT-B12) — a contract is a record of what *was* true at binding time, never a claim about what
stays true. Future health changes, however large, never invalidate a historical Binding Contract;
the contract's coordinates are already citable facts (PRT/03 §4).

**Visibility.** Health-change threshold crossings publish to the bus — exact event names are
Phase-5 canon (D1–D4); this phase names the fact of publication only.

**Determinism.** Same ordered evidence history + same priors version + same administrative acts →
same health state, always (PRT-I8). Health is live, but it is deterministic and replayable exactly
like registry state — it just replays over a different kind of history (§8).

## 7. Quarantine

> **Clarification note** (same register as PRT/01 §3's ownership clarification). PRT/00 §5's
> phrase "threshold crossing → registry effect + events" is imprecise wording. It is superseded by
> the more specific later canon: PRT-B8 (health/load state never mints a registry version) and
> PRT/03 §6 (Quarantined is explicitly classified under the Unavailable availability rung — an
> operational fact, not a registry mutation). The accurate statement: quarantine changes what
> binding's eligibility filter sees, publishes health-change events, and may persist as PRT runtime
> state via Storage — but it never mints a registry version and never edits registry content. The
> registry-mutating path for a permanently bad provider is forced **retirement** (PRT/02 §8), a
> distinct, Lifecycle-decided, version-minting act. Quarantine is reversible; retirement tombstones.
> This document is the errata; PRT/00 itself is not edited here.

| Aspect | Substance |
|---|---|
| Entry | PRT's threshold policy over §2's evidence dimensions requests it |
| Operational meaning | Barred from eligibility (Unavailable rung); never deleted, never version-minted |
| Visibility | Readers/binding see it via availability + health-change events; registry content unchanged |
| Recovery | Guaranteed healing path (PRT-I8) — no permanent blacklist from evidence alone; earned re-entry via Recovering → Recovered (§3) |
| Administrative override | Explicit recorded operator act, both directions (force-quarantine, force-release); never silent |

**Why reversible.** Evidence is circumstantial and environments heal — the frozen spec's Healing
tests exist for exactly this (`COMPONENTS/plugin-runtime.md` Testing Strategy). Treating evidence-
derived quarantine as permanent would turn a transient environmental fault into permanent
capability loss, with no path back short of re-admission under a new identity.

**Permanent removal is a different act.** Forced retirement (PRT/02 §8) is Lifecycle-decided,
PRT-enacted, and mints a registry version. Quarantine and retirement are never the same mechanism
wearing two names — one is operational and reversible, the other is registry and terminal.

## 8. Health consistency

| Guarantee | Statement |
|---|---|
| No registry mutation | Health updates never mutate registry versions (PRT-B8) |
| Contract immutability | Health observations never rewrite issued Binding Contracts (PRT-B6) |
| Append-only history | Health changes never rewrite history; a correction is a *new* observation, never an edit to a prior one |
| Deterministic visibility | Same ordered evidence + same priors version + same admin acts → same health state, replayable (PRT-I8) |

Why every one of these is required, not merely convenient: each protects a replay coordinate a
downstream component has already cited — determinism tuples (CP/04), Binding Contracts (PRT/03
§7), and Observability's journals all assume the coordinate they read is stable. One poisoned
coordinate poisons every conclusion built on it (echoing PRT/01 §9's admission-time-consistency
argument, applied here to health instead of registry content).

## 9. Reliability feedback loop

PRT produces health-change events, binding outcomes (visible in issued contracts), and quarantine/
recovery telemetry — all published to the bus, all landing in Observability's episodic traces.
Learning consumes *closed* traces from Observability and produces healed reliability priors
(`reliability.updated`) plus separate planning priors for CP. PRT consumes those priors as **one**
versioned declared input (§4) into its own health computation — it never re-mines episodic memory
directly (Law 2 retrieval discipline; PRT never scans Observability's raw stream). Ownership stays
disjoint across the loop: PRT never writes semantic memory, Learning never touches live health, CP
reads both products only through their respective owners.

## 10. Tradeoffs

| Choice | Rejected alternative | Why rejected | Chosen |
|---|---|---|---|
| Static vs dynamic health | Admission-time judgment only | Goes stale the moment a provider's real behavior diverges from its declaration | Dynamic — but deterministic, evidence-driven, never clock-driven |
| Quarantine trigger | Immediate one-strike | Flapping; a single transient fault becomes a full outage | Graduated degradation with threshold-triggered quarantine |
| Quarantine trigger | Pure-gradual only | Slow to contain a real, ongoing fire | Both speeds available, thresholds are policy data (§3), not hardcoded |
| Evidence source | Operational observations alone / learned reliability alone | Either alone is insufficient (§5) | Both, through one declared seam |
| Live state vs immutable history | Blended into one coordinate | Would make binding's "now" answer depend on slow-moving history, or corrupt stable history with live noise | Both kept, never blended — live state serves now, immutable history serves replay/learning; the snapshot (§6) is the one bridge |

Every choice compounds toward: deterministic execution (§6, §8), reproducibility (contract-carried
snapshots), and long-term stability — healing prevents permanent capability loss from a transient
fault, and strict ownership separation (§4, §9) prevents reliability truth from forking.

---

## 11. Invariants (PRT-H1..H12)

Binding on Phase 5.

1. **PRT-H1** — Health is a deterministic function of (ordered evidence history, priors version,
   administrative acts); no other input may influence it (PRT-I8).
2. **PRT-H2** — Health updates never mutate registry content and never mint a registry version
   (PRT-B8).
3. **PRT-H3** — Quarantine is an operational state (Unavailable availability rung); it is never a
   registry mutation, per the §7 clarification.
4. **PRT-H4** — Retirement is the only permanent removal path; it is a registry act, Lifecycle-
   decided and PRT-enacted (PRT/02 §8), distinct from quarantine in owner, mechanism, and
   reversibility.
5. **PRT-H5** — No provider is permanently blacklisted from evidence alone; a healing/recovery
   path exists from every quarantine (PRT-I8).
6. **PRT-H6** — Health-state history is append-only; a correction is a new observation, never a
   retroactive edit to a prior one.
7. **PRT-H7** — A health snapshot is taken exactly once, at binding start, and frozen into the
   Binding Contract; it is never re-read mid-resolution (PRT/03 §2).
8. **PRT-H8** — A Binding Contract's frozen health coordinate is never retroactively invalidated
   by a later health change; replay reads the contract, never the live world (PRT-B12).
9. **PRT-H9** — Health inputs are a closed set (live observations, administrative policy,
   historical priors); nothing outside it influences health.
10. **PRT-H10** — The Learning/PRT seam is one-directional each way: `reliability.updated` flows
    Learning → PRT as a declared input; health-change/binding/quarantine telemetry flows PRT →
    Observability → Learning as closed-trace material. Neither owns the other's state.
11. **PRT-H11** — Threshold policy (when to request a transition) is PRT's; transition legality is
    Lifecycle's (PRT-A4); PRT originates no transition on its own authority.
12. **PRT-H12** — Health lifecycle ends at retirement; it never owns the retirement decision.

---

Status: Phase 4 health & reliability frozen within PRT/00–03 walls. Phase 5 (integration) resolves
event canon (D1–D4) and reconciles the ARCHITECTURE matrix; it does not redefine health's ownership
split, the quarantine/retirement distinction, or the snapshot mechanism fixed here.
