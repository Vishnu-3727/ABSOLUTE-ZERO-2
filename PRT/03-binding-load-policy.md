# Plugin Runtime — Phase 3: Binding & Load Policy

One question: given a scheduled capability id and a published registry, how does PRT
deterministically determine which provider becomes executable. Architecture only — no code, no
APIs, no filenames, no algorithms, no memory-management mechanisms. Builds within
`PRT/00-architectural-foundation.md` (locked, especially §4 late binding, C1–C10, PRT-I1..I10),
`PRT/01-registry-model.md` (locked, PRT-R1..R11, especially §7 bindings, §2 policy-as-data) and
`PRT/02-discovery-admission.md` (locked, PRT-A1..A12, especially §2's post-publication boundary
ruling). Cites `COMPONENTS/plugin-runtime.md`, `COMPONENTS/execution.md`, `CP/03-system-integration.md`
§ late binding. Restates none of them.

---

## 1. Late binding defined

Plans and workflows carry **capability ids only** (PRT/00 C3, CP/03 invariant 11); no provider id
is ever present in a published plan or workflow. Selection happens once, immediately before
execution, when Execution asks PRT to resolve an id it is about to fulfill.

Why immediately-before, not earlier:

| If binding happened at... | Failure |
|---|---|
| Plan-authoring time | Provider identity baked into a published, immutable artifact (PRT/01 §4) — the exact coupling CP/03 § late-binding exists to prevent; provider churn invalidates plans |
| Scheduling time (ahead of dispatch) | Health/registry state can move between scheduling and actual fulfillment; the binding would cite a coordinate that is already stale by the time it matters |
| Immediately before execution (this phase) | Freshest health snapshot, latest registry version for new work, one resolution point per fulfillment |

Determinism survives late binding because both coordinates a binding depends on are themselves
citable facts: registry version (durable, PRT/01 §4) and health-state snapshot (live, taken once,
frozen at binding instant — §2). Same (capability id, registry version, health snapshot, policy) →
same provider, every time, replayable forever (PRT/00 §4, PRT-I6).

## 2. Binding inputs

Binding is a function; its domain is a closed, enumerable input set — nothing outside this table
may influence a resolution.

| Input | Nature | Source |
|---|---|---|
| Scheduled capability id | Immutable per dispatch | Execution's fulfillment request, itself derived from a plan (WS dispatch) |
| Registry version content at binding time | Immutable once minted | PRT/01 §4 |
| Provider bindings at that version | Immutable (part of registry content) | PRT/01 §7 |
| Capability + provider constraints at that version | Immutable | PRT/01 §8 |
| Declared load/isolation policy | Immutable registry data (policy-as-data, PRT/01 §2) | PRT/01 §2, this phase's §5 |
| Health-state snapshot | **Live but snapshotted once, at binding start** | PRT/00 §5 (opaque value here; its computation is Phase 4) |
| Execution policy/config version | Immutable per citation | Cited, not designed, here |

**Immutable vs. snapshotted-live.** Registry version content never changes after mint (PRT-R4);
the health coordinate is a live runtime fact that keeps moving in the background, but binding reads
it exactly once and freezes that read inside the Binding Contract (§3, §7). From that instant
onward, binding is a pure function over two closed, unchanging inputs — one durable, one frozen —
never over the moving world itself.

**Forbidden inputs** — never consulted, at any stage:

| Forbidden | Why |
|---|---|
| Wall-clock time | Not part of the determinism tuple (CP/04); a time-of-day-sensitive binding is unreplayable |
| Load order / which candidate happened to initialize first | Not a declared coordinate; reintroduces race-shaped nondeterminism |
| Concurrency interleaving across simultaneous binding requests | Two concurrent bindings for the same id, same version, same health snapshot must resolve identically regardless of arrival order |
| Live environment probing at bind time (e.g., "is the host under load right now") | Uncontrolled variability outside the closed input set |
| Randomness of any kind | PRT/00 §4 forbids it explicitly; echoes CP/04's forbidden-variability discipline |

Any one of these, if consulted, destroys replay: the same recorded inputs would no longer
guarantee the same outcome, and a Binding Contract's citation of "registry version + health
snapshot" would become a partial lie.

## 3. Binding process

Conceptual stages, in order — no algorithm, only what each stage decides and hands to the next.

| Stage | What happens |
|---|---|
| 1. Capability lookup | Resolve the scheduled id to its canonical form (PRT-R6 alias resolution) against the cited registry version |
| 2. Candidate set | All provider bindings (PRT/01 §7) declared for the canonical id at that version |
| 3. Eligibility filtering | Deterministic predicates over §8's constraint families + §6 availability; every refusal reason recorded, not silently dropped |
| 4. Policy evaluation | Declared preferences and load policy (§5) applied to the surviving candidates |
| 5. Deterministic resolution | PRT/00 §4 fixed total order: declared preference > reliability coordinate > stable id |
| 6. Binding commitment | A Binding Contract is minted — immutable once issued (§7) |
| 7. Execution preparation handoff | Contract passed to Execution; PRT's involvement in this fulfillment ends here (Ruling 1, §7) |

**Empty eligible set.** If stage 3 leaves no eligible candidate, binding fails **loud**, as an
ordinary result event — not an exception, not a silent no-op. PRT never guesses, never widens the
candidate set, and never substitutes across capability ids to compensate (PRT/00 §4, restated).
Recovery — trying an alternative-relationship capability, replanning — is CP/WS territory (CP/03),
entered only after PRT's loud failure is observed. PRT's job stops at "no healthy provider serves
this id, under this policy, right now."

## 4. Binding determinism

**Identical inputs → identical provider, always.** No exception, no "usually," no soft tie-break.

Why nondeterministic selection is forbidden, not just discouraged:

| Consequence of nondeterminism | Why it matters |
|---|---|
| Execution outcomes become uncorrelatable with plans | The same plan step could run against a different provider on replay, making "what happened" unreproducible |
| Replay/debugging breaks | A binding decision must be fully explainable from its recorded inputs; "why did provider X run" must always have a mechanical answer |
| Learning's outcome attribution is poisoned | A prior attached to "what ran and how it did" needs to know deterministically what ran; nondeterministic binding severs outcome from cause |

Registry version is the **durable half** of reproducibility — anyone can re-read version N forever
(PRT/01 §4). Health snapshot recorded *inside* the Binding Contract is the **live half** — replay
never re-queries live health; it reads the frozen value the contract already carries. This is why
replay never touches the moving world: it reads a contract, not a snapshot of an environment that
no longer exists in that form.

## 5. Load policy

**Loading** = making an admitted provider ready to be executed against, ahead of or at the moment
of need. Load policy is the declared, registry-held data governing whether/when/how eagerly that
readiness is pursued — never the act of achieving it.

| Separation | Why |
|---|---|
| From admission | Admission (PRT/02) establishes what *exists*; loading concerns operational *readiness* of what already exists. Coupling them mints a registry version per load/unload/health blip (PRT-R4) — forbidden, see Ruling 2 (§9) |
| From execution | Loading readies; execution runs. PRT holds no process handle (PRT-I5) — readying's process-level effects are Execution's act under PRT's policy |
| Default eagerness | On-demand: providers accumulate over years (PRT/01 §10), active work touches few; demand-driven readiness keeps the operational surface proportional to actual use (minimal-reasoning philosophy). Policy may still declare specific providers eager — demand is the default, not the only mode |
| Ownership | Frozen spec names it directly: PRT "Owns: plugin load/isolation/versioning policy." Load decisions need registry knowledge (versions, constraints, bindings) only PRT curates |

### Ruling 3 — three-way load ownership split

Loading a provider touches three distinct concerns; each has exactly one owner, and no owner
crosses into another's:

| Concern | Question it answers | Owner | Basis |
|---|---|---|---|
| Load *policy* | Should/when should this provider be loadable; how eagerly; release rules | PRT | Frozen spec "Owns"; needs registry knowledge only PRT has |
| Load *state-transition legality* | Is this transition (e.g. entering/leaving a loaded operational state) legal for this published provider right now | Lifecycle | PRT-A4, C7 — PRT enacts, never originates |
| Load's *process/resource effects* | Acquiring resources, spawning, tearing down | Execution | Law 3 — sole spawner, owns sandbox/timeout/resource state |

One moment (a provider becoming ready for use), three seams. Collapsing any two would recreate a
dual-authority failure this document set exists to avoid (PRT/01 §1, PRT/02 §2).

## 6. Provider availability

Availability is a ladder; a provider occupies exactly one rung with respect to a given capability
at a given instant.

| Rung | Meaning |
|---|---|
| Registered | Present in the current registry version (PRT/01 §7 binding exists) |
| Loadable | Registered + load policy (§5) permits + no administrative bar |
| Available | Loadable + current operational state (Lifecycle-governed, PRT-A4) permits binding |
| Operational | Currently prepared/loaded and reachable |
| Unavailable | Registered but operationally barred (e.g. quarantine — mechanics are Phase 4) |
| Retired | Absent from the current registry version; historic only (PRT/02 §8) |

Availability is the eligibility predicate stage 3 (§3) consumes. It **consumes** the health-state
coordinate (§2) as an opaque input at binding time; it never itself defines a scoring or ranking
model — that computation belongs to Phase 4 and is out of scope here.

**Distinct from capability matchability (CP/01).** A capability can be `active` (matchable, per
CP/01 §6) while every provider bound to it sits at Unavailable or Retired. That combination is not
an inconsistency — it is precisely the empty-eligible-set case (§3), and it fails loud rather than
being treated as a registry defect.

## 7. Execution preparation

### Ruling 1 — where PRT's responsibility ends

The frozen spec's "load/isolation policy" language could be misread as PRT performing resource
acquisition ahead of execution. It does not, and cannot: PRT-I5 forbids PRT from spawning or
holding a process handle, and Execution's Law 3 makes it the sole spawner, owning sandbox, timeout,
and resource state end to end. Any "preparation" step that touches an OS resource or process is
Execution's, full stop — this is an ownership clarification, in the same register as PRT/01 §3's
clarification of registry-authorship framing.

**What PRT assembles instead: the Binding Contract.** This phase's artifact, minted at stage 6
(§3), immutable once issued. It carries:

| Contract element | Content |
|---|---|
| Resolved provider identity + version | The output of §3's resolution |
| The capability id it fulfills | Canonical form (§3 stage 1) |
| Applicable constraints | From §8, as evaluated at binding time |
| Declared isolation/load policy | Policy-as-data (PRT/01 §2), handed forward, not enforced here |
| Binding coordinates | The registry version and health-state snapshot it was resolved under (§2, §4) |

**The split:**

| Side | Responsibility |
|---|---|
| PRT | Assemble the Binding Contract; check (not acquire) that declared prerequisite capabilities have their own valid bindings; attach policy |
| Execution | Acquire resources, set up sandbox, spawn, supervise, tear down — everything Law 3 already owns |

**Why the line sits exactly here.** Preparation that needs only registry-and-policy knowledge
belongs to PRT because PRT is the only subsystem that has that knowledge. Preparation that touches
the machine belongs to Execution because Law 3 makes it the single spawner — a second resource
acquirer would recreate the uncontained-process failure class (V1-H4, `COMPONENTS/execution.md`)
that Execution's single-spawner design exists to close.

## 8. Binding constraints

Families of situational fact evaluated at binding time (distinct from admission-time checks,
below):

| Family | What's evaluated |
|---|---|
| Platform incompatibility | Does the target platform at this moment satisfy the provider's declared platform restriction (PRT/01 §8) |
| Capability restrictions | Does this fulfillment fall within the capability's declared execution restrictions |
| Version incompatibility | Is the resolved provider version still compatible with the capability version in force at this registry version |
| Missing prerequisites | Do declared dependency-relationship prerequisites (PRT/01 §6) currently have their own valid bindings |
| Administrative policy | Does current admin/operator policy permit this provider for this fulfillment |
| Provider operational status | Where does the provider sit on the availability ladder (§6) right now |

**Why evaluated at binding, not admission**, even though some predicates look identical to
admission-stage checks (PRT/02 §3): admission validates *declared coherence* — timeless, checkable
against the registry alone, once. Binding validates *situational fit* — facts about this specific
dispatch moment (target platform, current operational state, current admin policy). The same
predicate can appear at both without redundancy: admission checks it's statable and coherent,
binding checks it's satisfied *now*. Folding situational checks into admission would be wrong
twice — rejecting providers valid elsewhere or later, and admitting a judgment that goes stale.

## 9. Load lifecycle

Conceptual load-state transitions for an admitted provider (operational, not registry, states):

`Not Loaded → Loading → Prepared → Loaded → Released`, with `Unavailable` reachable from any of
these on a barring condition.

**Independence from admission and retirement.**

| Relationship | What holds |
|---|---|
| vs. admission | A provider is admitted once (PRT/02); it may be loaded many times, or never, across its whole admitted lifetime |
| vs. retirement | Retirement is a registry fact (a future version no longer lists the provider, PRT/02 §8); an in-flight loaded instance winding down is a separate operational fact — Lifecycle governs the wind-down transition, PRT enacts the registry-side consequence, Execution tears down the process-side state |

**Ruling 2 — load state never mutates the registry.** Load/unload transitions and momentary health
blips are runtime facts, not registry content. If they were, PRT-R4 ("every mutation mints a
version") would mean every load, unload, or health blip mints a new registry version — flooding
the determinism coordinate CP/04 depends on and making "registry version" useless as a
plan-citable fact. This is exactly why PRT/00 §4 makes binding deterministic on **two** coordinates,
not one: registry version (durable, declared truth) and health/load state (live, snapshotted once
at binding time, §2). The registry stores the *policy* for loading (§5); the *state* of loading
lives in PRT's runtime view, never mutates the registry, never mints a version — the architectural
reason loading state must never modify registry contents (PRT-R4).

**Ownership of the transitions themselves.** Transition legality (is this state change allowed for
this provider right now) is Lifecycle's plugin state machine (PRT-A4). PRT's load policy (§5)
decides *when* to request a transition. Execution realizes the transition's process-level effects.
Same three-way split as Ruling 3 (§5), restated for the lifecycle view specifically.

## 10. Tradeoffs

| Choice | Rejected alternative | Why rejected | Chosen |
|---|---|---|---|
| Binding timing | Early (author/schedule time) | Provider baked into an immutable plan; churn invalidates it; health stale by exec time | Late — capability ids only (§1), one resolution point per fulfillment |
| Loading eagerness | Persistent (always-loaded) | Holds resources for idle providers; larger operational-drift surface | Demand-driven default (§5); policy may still mark specific providers eager |
| Provider assignment | Static (hardcoded tool lists) | Recreates V1's hardcoded-list failure class; no extensibility | Dynamic, registry-driven resolution — new providers need zero binding-logic redesign (PRT-R11) |

Each choice compounds toward the same four properties: deterministic execution (§4), extensibility
without redesign (PRT-R11), reproducibility (contract-carried coordinates, §7), and minimal
reasoning (deterministic resolution spends zero runtime deliberation choosing a provider — the
answer is mechanical, not judged).

---

## 11. Invariants (PRT-B1..B12)

Binding on Phases 4–5.

1. **PRT-B1** — Binding is a pure function of its recorded inputs (§2); no input outside the closed
   set may influence resolution.
2. **PRT-B2** — Identical (capability id, registry version, health snapshot, policy) always yields
   an identical provider choice; no exception.
3. **PRT-B3** — Wall-clock time, load/arrival order, concurrency interleaving, live environment
   probing, and randomness are forbidden binding inputs, unconditionally.
4. **PRT-B4** — Binding never substitutes across capability ids; cross-capability alternatives are
   CP's territory (CP/03), entered only after a loud PRT failure.
5. **PRT-B5** — An empty eligible-candidate set is a deterministic, loud, ordinary result event —
   never an exception, never a silent no-op, never a widened search.
6. **PRT-B6** — The Binding Contract is immutable once issued and carries the exact registry
   version and health-state coordinates it was resolved under.
7. **PRT-B7** — PRT's post-binding responsibility ends at Binding Contract assembly and prerequisite
   *checking*; resource acquisition, sandboxing, and spawning are Execution's alone (Law 3, PRT-I5).
8. **PRT-B8** — Load/health state is a runtime fact, never registry content; it never mints a
   registry version (PRT-R4).
9. **PRT-B9** — Load ownership is split three ways with no overlap: PRT decides load *policy*,
   Lifecycle decides transition *legality* (PRT-A4), Execution realizes *process/resource effects*
   (Law 3).
10. **PRT-B10** — Binding-time constraint evaluation is situational (this dispatch moment); it is
    distinct from and never a substitute for admission-time coherence checking (PRT/02 §3).
11. **PRT-B11** — Availability (§6) is consumed by binding as an eligibility predicate; it is never
    itself a scoring or ranking model (Phase 4 territory).
12. **PRT-B12** — A binding decision is always mechanically explainable from its recorded inputs;
    "why did provider X run" has an answer derivable from the Binding Contract alone, without
    re-querying live state.

---

Status: Phase 3 binding & load policy frozen within PRT/00–02 walls. Phase 4 (health & reliability)
designs the health-state coordinate's computation and the reliability score consumed opaquely
here; Phase 5 (integration) resolves event canon. Neither phase may redefine the binding process,
the three-way load split, or the Binding Contract's shape fixed in this document.
