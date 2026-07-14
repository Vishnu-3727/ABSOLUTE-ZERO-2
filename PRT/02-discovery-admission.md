# Plugin Runtime — Phase 2: Discovery & Admission

One question: how does a provider become part of the registry, and how does it leave. Architecture
only — no code, no APIs, no filenames, no directory structures, no serialization, no algorithms.
Builds within `PRT/00-architectural-foundation.md` (locked) and `PRT/01-registry-model.md` (locked,
especially PRT-R2 mutations-as-declarations, PRT-R4 version-per-mutation, PRT-R10 admission-time
consistency). Cites `CP/01-capability-model.md` §6 and `COMPONENTS/lifecycle.md` for the provider
state-machine boundary. Restates none of them.

---

## 1. Provider discovery defined

**Discovery** = observing that candidate providers exist and collecting their declarations. Output
is **declarations only** — PRT-R2's input, never a registry mutation.

Why discovery is not admission:

| If discovery wrote the registry directly | Failure |
|---|---|
| Environmental observation (a manifest is present, a workspace is scanned) is fallible and unvalidated | Unvalidated environment state leaks into a published version — the exact thing PRT-R10 forbids |
| Discovery is inherently plural (many sources, many trust levels) | Merging discovery and admission would mean as many admission gates as sources — registry drift (PRT/01 §1) reborn at the discovery seam |

Discovery sources, conceptually, by trust spectrum:

| Source class | Trust posture | Effect on admission |
|---|---|---|
| Built-in / first-party | Highest a priori trust | None — same gates, same rigor |
| Local / workspace-declared | Author-controlled, unvetted by anyone else | None |
| Enterprise / organization-curated | Vetted by a third party PRT doesn't audit | None |
| Remote / marketplace-style registries | Lowest a priori trust, largest surface | None |

Source class informs how much *scrutiny a human or policy layer expects to have already
happened* — it never changes what PRT itself checks and never bypasses a single stage of §3. All
sources funnel into the **same** admission pipeline. Two pipelines (a "trusted fast path" and an
"untrusted full path") is the dual-authority failure this document exists to avoid; see §2.

## 2. Discovery lifecycle vs. the plugin state machine

Conceptual provider states, one line each:

| State | Meaning |
|---|---|
| Unknown | Not yet observed by any discovery source |
| Discovered | A source has surfaced a candidate; declaration not yet collected in full |
| Candidate | Declaration collected; awaiting admission |
| Validated | Declaration passed every admission stage (§3) but not yet published |
| Admitted | Publication has minted the version containing this provider (PRT-R4) |
| Published | Synonym for Admitted from a reader's perspective — visible in the current registry |
| Deprecated | Discouraged-but-visible operational state, post-publication |
| Retired | No longer matchable for new binding; tombstoned, permanently present in history |
| Rejected | Declaration failed an admission stage; not part of any registry version |

Legal forward flow: `Unknown → Discovered → Candidate → Validated → Admitted/Published`. Rejection
can occur from Candidate or Validated (a later stage can still fail after an earlier one passed).
Re-entry: **Rejected → re-discovered with a corrected declaration is a new candidacy**, not a
resurrection of the old one — there is no "resume from where it failed." A corrected declaration
re-enters at Discovered/Candidate and re-earns every stage.

**Boundary ruling (binding).** Unknown through Published are **PRT-internal processing stages of a
candidacy** — a pipeline for something that does not yet exist in the registry. They are *not* the
plugin state machine. Deprecated and Retired, by contrast, are **post-publication operational
states of a provider that already exists**, and that state machine is owned by Lifecycle (PRT/00
C7, COMPONENTS/lifecycle.md §Owns): Lifecycle decides the transition, PRT enacts the registry
effect (PRT-I9).

| Phase | States | Who decides | Who enacts |
|---|---|---|---|
| Pre-publication | Unknown, Discovered, Candidate, Validated | PRT's own admission pipeline (§3) | PRT |
| Post-publication | Deprecated, Retired (and Lifecycle's broader plugin states — loaded, disabled, quarantined, etc.) | Lifecycle | PRT |

**Why the split is drawn here, not somewhere else.** Before publication, nothing exists in the
registry yet — there is no entity for Lifecycle to hold a state for. Lifecycle governs long-lived
*things* (COMPONENTS/lifecycle.md §Purpose); a candidacy is not yet a thing, it's a proposal about
one. The moment publication mints a version containing the provider, an entity exists, and from
that instant its operational state belongs to Lifecycle, never PRT. Two state machines with
overlapping ownership of the same moment is precisely the V1 dual-authority failure PRT/01 §1
names; this ruling keeps the seam at a single, unambiguous instant — publication.

**Provider states vs. capability lifecycle (CP/01 §6).** "Deprecated" and "retired" appear in both
vocabularies. They are never the same object: CP/01 §6's states describe a **capability id**'s
lifecycle (proposed → active → deprecated → retired); this section's Deprecated/Retired describe a
**provider's** operational state. A capability can be active while every provider bound to it is
deprecated in favor of newer ones; a provider can retire while the capability it fulfilled remains
active, served by other providers. Same words, disjoint objects — PRT-R8 (binding independence)
already establishes the mechanism; this is its terminology consequence.

## 3. Admission pipeline

Ordered stages. Order rationale: cheapest and most-local checks first, whole-registry consistency
last, publication only after every earlier stage has passed — a candidacy is never allowed to
consume the expensive whole-registry check before it's cleared the cheap ones.

| Stage | Purpose |
|---|---|
| 1. Identity validation | Confirm the declared provider identity is well-formed and not a tombstone-reuse or hijack attempt (§5, §9) |
| 2. Capability validation | Every capability id the declaration binds to must exist and be matchable (CP/01 §6), or the declaration itself proposes new capabilities admitted atomically alongside it |
| 3. Metadata validation | Declaration completeness, including the mandatory verification expectation (PRT-I4) |
| 4. Constraint validation | Declared constraints (PRT/01 §8) are internally coherent and statable |
| 5. Relationship validation | Any relationship edges reference existing ids, and are one of exactly the four types (PRT-R7) |
| 6. Binding validation | The three PRT/01 §7 conditions — matchable target, registered provider, compatible constraints |
| 7. Compatibility validation | Version-conflict refusal per C10 — no silent shadowing of another capability or binding |
| 8. Consistency validation | Full PRT/01 §9 rule sweep run against the **would-be next version** — the candidacy is checked as if already merged, not in isolation |
| 9. Publication | Only reached if 1–8 all passed; mints exactly one new version (§7) |

A failure at any stage halts the pipeline for that candidacy; later stages are never attempted (no
value in checking compatibility for a declaration that already failed identity).

## 4. Admission authority

**Only PRT admits.** Two reasons, not one:

- Single-writer (PRT-R1): the registry has exactly one writer; admission is that writer's sole
  point of entry.
- Admission is where consistency is *manufactured*, not merely checked. Distributing admission
  across subsystems (a "fast admit" path for trusted sources, a slow path elsewhere) would
  recreate registry drift one seam later — each admitter making its own partial consistency
  judgment.

External subsystems cannot write the registry **by architecture**, not by convention (PRT/01 §3):
there is no path from Discovery, CP, Execution, Lifecycle, or anything else directly into a
published version. Lifecycle decides post-publication transitions but still routes through PRT to
enact them (§2, PRT-I9) — even the one other subsystem with legitimate authority over provider
*state* has zero authority over provider *admission*.

## 5. Provider identity

- A provider id is stable across every version of that same provider — upgrading a provider never
  changes its identity, only its version coordinate.
- **Provider identity and version identity are distinct**, mirroring PRT-R5's capability-vs-registry
  version distinction: same provider, new version = same identity, new version coordinate. A
  version change is never an identity change.
- **Identity ownership**: PRT assigns and curates identity within the registry; declarations
  *propose* an identity, they do not self-grant one (mirrors PRT/01 §3's "declarations, admitted or
  refused" framing applied to identity specifically).
- Replacement, deprecation, and retirement mirror the capability discipline (CP/01 §6, §12.8)
  conceptually — alias-style continuity toward a successor, tombstones on retirement, no id reuse —
  but these are **provider-level facts**, tracked independently of the capability ids a provider
  binds to (binding independence, PRT-R8). Retiring a provider never touches the capability
  lifecycle state of anything it used to fulfill, and vice versa.
- **Why identity continuity matters**: it is what lets anything attach to "this provider" across
  its whole lifetime rather than to a version snapshot — health/reliability history (Phase 4) and
  any future priors need a stable subject to accumulate against. Identity churn would fragment that
  history across what is really one continuous provider.

No syntax, no id shape is specified here — only that continuity and ownership hold.

## 6. Admission rules

| Rule | What it requires |
|---|---|
| Metadata completeness | Declaration states everything §3 stage 3 requires, including a statable verification expectation |
| Capability completeness | Every capability id referenced exists and is matchable, or is admitted atomically with this candidacy |
| Relationship validity | Every edge resolves to an existing id; exactly the four PRT-R7 types |
| Constraint consistency | Declared constraints do not contradict themselves or the capability they bind to |
| Binding validity | The three PRT/01 §7 conditions all hold |
| Version compatibility | No C10 conflict with anything already published |
| Deterministic publication | Same declaration set + same prior registry version → same admission outcome and same resulting version content, every time — no wall-clock, no ordering nondeterminism between independently-arriving candidacies |

**Concurrent candidacies.** If two candidacies arrive close enough in time to be logically
concurrent, a deterministic serialization rule (fixed total order — not specified here, a Phase-3/5
mechanism) decides which is evaluated against which prior version. The requirement fixed at this
phase is only that *some* deterministic order exists; wall-clock arrival time is never itself the
tie-break (consistent with PRT/00 §4's binding tie-break discipline).

**All-or-nothing, why.** A declaration is one coherent claim about one provider. Partially admitting
it — accepting the metadata but not the bindings, say — would publish a version containing a
half-true claim. That directly violates PRT-R10 (no observably inconsistent published version) and
poisons every determinism tuple citing that version, since "same version" would no longer imply
"same coherent content." Admission is atomic at the level of one candidacy: all nine stages pass,
or none of them count.

## 7. Publication

Publication is the sole act that changes what readers can see, and it is atomic: one candidacy's
acceptance = exactly one mutation = exactly one new monotonic registry-global version (PRT-R4).
There is no intermediate observable state — a reader sees version N or version N+1, never a
partially-applied candidacy in between.

- **Publication is the version mint**, not a step that happens after one. "Admitted" (§2) and
  "the version now exists" are the same instant, not two.
- **Determinism preservation**: plans and determinism tuples cite the registry version they read
  (CP/04). Because historic versions are immutable (PRT/01 §4), a replay against version N always
  sees exactly what version N contained at mint time — publication never retroactively touches
  anything a prior plan already cited.
- **Event emission**: publication conceptually announces itself on the bus once it happens. Exact
  event names are drift-flagged canon (PRT/00 §7, D1–D4) resolved at Phase 5 integration; this
  phase does not pick names, does not add to the drift list, and does not resolve it early.

## 8. Provider retirement

Two triggers, one mechanism:

| Trigger | Requested by | Decided by | Enacted by |
|---|---|---|---|
| Voluntary — provider withdrawn by its own source | The source | Lifecycle (transition legality, C7) | PRT |
| Forced — policy or health threshold crossed | Policy/health signals (health-triggered specifics are Phase 4; cited only, not designed here) | Lifecycle | PRT |

A source *requests* withdrawal; it never decides the transition — every post-publication
transition is decided by Lifecycle (PRT-A4), whoever asked for it.

Either way, PRT is the sole enactor (§4), consistent with the pre/post-publication split in §2.

- **Replacement** happens via a successor provider plus a deprecation pointer toward it — the same
  alias-style continuity pattern CP/01 uses for capabilities (§5, above), applied to provider
  identity.
- **Deprecated** = discouraged but visible: still bindable, still shows up to a reader, just not
  preferred (selection/preference is Phase 3 territory, out of scope here).
- **Retired** = invisible to new binding and new planning, but permanently present in every historic
  version already minted — a tombstone, never a deletion.
- **Historical preservation**: retirement mutates only *future* versions. Every version minted
  before the retirement still contains the provider exactly as it was admitted; replay determinism
  (§7) is untouched by a later retirement.
- **Bindings to a retiring provider** are removed in the *same* atomic mutation that retires it —
  never a two-step "retire, then separately clean up bindings." A dangling binding to a
  no-longer-matchable provider would violate PRT/01 §9's relationship/binding consistency rules the
  instant it existed; retirement and its binding cleanup are one mutation, one version, never two.

## 9. Failure philosophy

| Failure class | Refusal type | Path forward |
|---|---|---|
| Metadata incompleteness | Recoverable | Resubmit a corrected declaration as a new candidacy |
| Constraint inconsistency | Recoverable | Same |
| Relationship dangling-reference | Recoverable | Same |
| Binding invalidity | Recoverable | Same |
| Compatibility conflict (C10) | Recoverable | Same |
| Identity conflict with a tombstone (id reuse attempt) | Permanent | No resubmission fixes this under the same id — the id is permanently inadmissible; a genuinely new provider must take a new id |
| Semantic hijack (same id, different meaning) | Permanent | Same as above — a meaning change always needs a new id (mirrors CP/01 §6's capability rule, applied to providers) |
| Publication failure (infrastructure — e.g. Storage refuses the persist) | Neither — the mutation never happened | No version is minted; the candidacy stays Validated and is retryable exactly as it was; never a half-published version |

**Fail loud, always.** Every refusal — recoverable or permanent — is loud, recorded, and specific
about which stage (§3) and which rule (§6) it failed. Silent drops of a candidacy are forbidden;
a rejected candidacy is an observable fact, not a disappearance.

## 10. Registry evolution through admission

Years of repeated admissions compound into the same properties PRT/01 §10 already fixed for the
registry as a whole; admission is the gate that keeps every one of them true at every step:

| Property | How admission preserves it |
|---|---|
| Incremental | Each admission = exactly one version, one small delta (§7) |
| Backward compatible | Append-mostly; an id never changes meaning once published (§5, §9) |
| Controlled expansion | New categories are rare, curated (CP/01 §5); everything else is free data growth through the same nine-stage gate |
| Historically traceable | The version chain is a complete, immutable audit of how the registry got here — every published version reachable, none ever edited (§7) |
| Integrity | The admission gate (§3) means every one of the thousands of future versions is individually consistent, not just the current one |

Growth changes registry **content**, never its **architecture** (PRT-R11) — admission is the fixed
gate every future candidacy, for as long as the OS exists, passes through unchanged.

---

## 11. Invariants (PRT-A1..A12)

Binding on Phases 3–5.

1. **PRT-A1** — Discovery produces declarations only; it never mutates the registry directly.
2. **PRT-A2** — All discovery sources, regardless of trust class, pass through the same single admission pipeline; no source bypasses any stage.
3. **PRT-A3** — Pre-publication states (Unknown/Discovered/Candidate/Validated) are PRT-internal admission stages, not plugin states; Lifecycle has no authority over them because nothing yet exists for it to govern.
4. **PRT-A4** — Post-publication operational transitions (deprecate, retire, and the broader plugin state machine) are decided by Lifecycle and enacted by PRT (PRT-I9); PRT never originates one.
5. **PRT-A5** — Provider operational states and capability lifecycle states (CP/01 §6) are distinct vocabularies over distinct objects; identical words never imply the same subject.
6. **PRT-A6** — Admission is all-or-nothing per candidacy: every stage (§3) must pass, or none of it is published.
7. **PRT-A7** — Only PRT admits; no other subsystem, including Lifecycle, has a direct write path into the registry.
8. **PRT-A8** — Provider identity is stable across a provider's versions and distinct from version identity; identity is PRT-assigned/curated, never self-granted by a declaration.
9. **PRT-A9** — Admission outcomes are deterministic: identical declaration set against identical prior registry version yields identical outcome and content; concurrent candidacies resolve via a fixed deterministic order, never wall-clock.
10. **PRT-A10** — Publication is atomic and is the sole act that changes reader-visible registry state; there is no intermediate observable state between versions.
11. **PRT-A11** — Retirement removes any bindings to the retired provider in the same atomic mutation; historic versions are never altered by a later retirement.
12. **PRT-A12** — Every admission refusal is loud, recorded, and stage-specific; silent drops are forbidden regardless of failure class.

---

Status: Phase 2 discovery & admission frozen within PRT/00–01 walls. Phase 3 (binding & load
policy) designs selection/preference mechanisms over admitted providers; it does not redefine how a
provider is admitted or retired.
