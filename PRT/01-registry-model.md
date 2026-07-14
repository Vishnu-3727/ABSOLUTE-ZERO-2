# Plugin Runtime — Phase 1: Capability Registry Model

Architecture of the Capability Registry: what it is, what it holds, who may touch it, and the
consistency rules that hold at every published version. Architecture only — no schemas, no field
lists, no serialization, no APIs. Builds within `PRT/00-architectural-foundation.md` (Phase 0,
locked) and `CP/01-capability-model.md` (locked vocabulary). Cites both; restates neither.

---

## 1. What the registry is

**The Capability Registry is the single, live, queryable record of every capability the OS knows
about and every provider bound to fulfill one.** It is not a cache, not a mirror, not one of
several sources — it is *the* source (PRT/00 C1, frozen spec Acceptance Criteria).

Why single-source, not federated:

| If registry authority were split... | Failure |
|---|---|
| Each component keeps its own capability/tool list | Lists drift the moment one component updates and another doesn't — frozen spec names this **Registry drift** as a named failure mode, inherited from a real V1 defect class |
| Two components could each "define" a capability | Two live truths about what exists — the same divergent-authority failure CP/03 rules out at the Scheduler seam, recreated at the vocabulary seam (CP/04 §3) |
| Providers registered metadata directly with consumers | No admission gate — unverifiable, incomplete, or conflicting capabilities enter unchecked |

No other subsystem owns capability metadata because ownership elsewhere reintroduces exactly the
problem CP/01 §9 and PRT/00 §1 both fence against: two authorities answering "what capabilities
exist," each convinced it's authoritative. PRT is the only one that gets to answer.

## 2. Information categories

The registry holds *categories* of information, not fields. Each category answers a downstream
question; none is a data-modeling instruction.

| Category | What it answers | Origin |
|---|---|---|
| Identity | Which permanent id, forever | CP/01 §3 |
| Descriptive metadata | What does fulfilling this mean, in words; category + facets | CP/01 §5, §7 |
| Relationships | How this capability relates to others (§6, below) | CP/01 §8 |
| Constraints | Under what conditions is fulfillment valid (§8, below) | CP/01 §7 |
| Provider bindings | Which providers declare fulfillment, and under what terms (§7, below) | frozen spec "Owns" |
| Verification expectations | How fulfillment would be checked — mandatory, admission-gated | CP/01 §7, PRT-I4 |
| Lifecycle information | proposed/active/deprecated/retired state, alias/deprecation pointers | CP/01 §6 |
| Versioning information | Per-entry compatible-clarification revision, and the registry-global version (§4 distinguishes the two) | CP/01 §7; PRT/00 §3 |
| Compatibility information | What a version change is compatible with, for both capabilities and provider bindings | CP/01 §6; PRT/00 C10 |
| Policy information | Provider load/isolation policy — **declared here as data**; enforcement is Execution's (C5) | frozen spec "Owns"; PRT/00 §2 |

Policy information is the one category worth flagging explicitly: the registry stores *what a
loaded provider may touch*, but never touches anything itself. PRT never spawns (PRT-I5); storing
the policy and enforcing it are different acts owned by different subsystems.

## 3. Ownership

**PRT is the registry's sole writer (PRT-I1).** Only PRT creates, modifies, deprecates, retires, or
versions a registry entry — and only through its own admission machinery, never by direct edit.

| Mutation source | What arrives | What PRT does with it |
|---|---|---|
| Discovery sources / provider manifests | Declarations — proposed capabilities, proposed bindings | Admits or refuses (Phase 2 gates); never accepted verbatim |
| Lifecycle (`plugin.lifecycle.changed`) | An already-decided state transition | Enacts the registry-side effect; PRT does not decide the transition (PRT-I9, C7) |

Every other subsystem — CP, Workflow/Scheduling, Execution, Context Management, Learning, and
everything else — is a **reader only**. Reading is unrestricted; writing is impossible by
architecture, not by convention.

**Ownership clarification.** An earlier phase framing suggested capability metadata "originates
from the Capability Planner." That framing is superseded by locked canon and does not carry
forward: CP/01 invariant 10 fixes CP as read-only, and CP/01 §9 fixes the registry as
Plugin-Runtime-owned. The accurate statement is: **CP is the registry's principal reader and the
capability vocabulary's principal consumer** — it reads the registry live to plan against — **but
no capability definition enters the registry except through PRT admission.** CP proposes nothing to
the registry; it consumes what's there. No drama, no ambiguity: one writer, many readers, CP among
them.

## 4. Registry versioning

**Why versions exist.** CP/04's determinism tuple — `f(request, registry version, priors version,
Request Memory hash, config version)` — cites "registry version" as one of exactly five acceptable
sources of variability. That citation only works if there is one countable, monotonically
increasing coordinate to cite. Versioning exists to make the registry's state at any point in time
a nameable, replayable fact.

**What counts as a mutation.** Any change to any information category in §2 — a new capability, a
lifecycle transition, a new or changed provider binding, an updated constraint, a policy change.
Per PRT-I2, every mutation mints a new monotonic version, unconditionally. There is no "minor"
registry change that skips versioning.

**Published versions are immutable forever.** Once minted, a version's observable content never
changes retroactively (consistent with CP/03 §on published-artifact immutability). A later mutation
produces a *new* version; it never edits an old one in place.

**Version is registry-global — exactly one monotonic counter for the whole registry, not one per
entry.** Justification:

| If versioning were per-entry only | Global version |
|---|---|
| A determinism tuple would need to cite a vector of entry-versions, or none at all — neither is a single citable coordinate | One number, one citation, matches CP/04's tuple shape exactly |
| Replay would need to reconstruct "the state of every entry as of some undefined joint point" | Replay reads one historic global version; new planning reads current (CP/04 §3) — no pinning |

This is distinct from the **per-entry Version attribute** CP/01 §7 already defines (a capability's
own compatible-clarification revision, for audit and clarification history). Both exist,
side by side, answering different questions: the per-entry version says "which revision of this
capability's description"; the registry-global version says "which cut of the whole registry does
this plan/replay/tuple point at." Neither substitutes for the other.

## 5. Capability identity

Identity rules are CP/01's, verbatim, restated by citation only:

- Permanent, dotted ids; never reused, never repurposed (CP/01 §3).
- Same id, same meaning, forever (CP/01 §3).
- Renames happen via alias + deprecation, never in-place mutation (CP/01 §3, §6).
- A meaning change always mints a new id; retired ids are permanent tombstones (CP/01 §6, §12.8).

**What's registry-specific: canonical identity resolution.** Every alias chain must resolve to
exactly one canonical id, which is always either active or deprecated (never itself a further
alias, never retired-as-a-live-target). Chains never cycle. Resolution is the registry's job, not
each consumer's, for one reason: if every consumer resolved aliases independently, two consumers
could reach different answers for the same input id under a bug or a race. Centralizing resolution
in the registry guarantees every consumer — CP, telemetry, replay — sees the same canonical answer
for the same id at the same version. No new syntax is introduced; this is a resolution guarantee,
not a naming scheme.

## 6. Relationships

Exactly the four CP/01 §8 defines — no more:

| Relationship | Registry's role |
|---|---|
| Dependency / requires | Stored as an edge; lets scheduling-adjacent validation refuse a step whose prerequisite is registry-absent, before it is ever scheduled |
| Composition | Stored as an edge; lets a later phase decompose a coarse capability without inventing splitting logic at plan time |
| Alternative / substitutable | Stored as an edge; gives a low-confidence or unavailable binding a declared escape hatch (fallback) |
| Conflict / mutual exclusion | Stored as an edge; lets validation reject an incoherent step (two mutually exclusive capabilities in one context) before scheduling |

**Mapping requested concepts onto the four — not new relationship types:**

| Requested concept | Registry treatment |
|---|---|
| Specialization / hierarchy | **Rejected as a relationship.** CP/01 §5 already rejects containment hierarchy and inheritance outright; category + facets cover organizational grouping without implying meaning inheritance. |
| Replacement | **Not a relationship — a lifecycle mechanism.** A replacement is an alias-plus-deprecation pointer (§5, CP/01 §6), not an edge between two live capabilities. |
| Compatibility | **Not a relationship — constraint/versioning information.** Whether two things are compatible is a fact carried in §2's constraints and versioning categories, not a timeless ability-relation between capability ids. |

**How the four enable deterministic execution.** All four are edges the registry stores as data;
their planning *meaning* belongs to CP (CP/01 §8, closing line). What the registry guarantees is
that the edges are always present, always resolvable, and always validated at admission — so that
whatever CP does with them (refuse an incoherent step, pick a fallback, order a dependency) is
built on data that cannot itself be inconsistent. The registry never interprets an edge; it only
ever refuses to publish a broken one (§9).

## 7. Provider bindings

A **binding** is a provider's declared fulfillment of one capability id, admitted by PRT. The
relationship is many-to-many: one capability may have many providers bound to it; one provider may
be bound to many capabilities.

**Binding lifecycle is independent of capability lifecycle.** A provider can register, upgrade,
degrade, quarantine, or unbind without touching the capability definition it binds to. This
independence is what makes late binding (PRT/00 §4, C3) possible at all: plans and workflows
reference capability ids only, so provider churn underneath a stable id never invalidates anything
that referenced the id.

**Validity conditions for a binding**, all checked at admission, never after:

| Condition | Refusal if violated |
|---|---|
| Target capability is in a matchable lifecycle state (active, or deprecated-for-compatibility) | Binding to a proposed or retired id is refused |
| Provider is itself registered | Binding to an unregistered provider is refused |
| Provider's declared constraints are compatible with the capability's constraints | Incompatible binding refused, never silently accepted with a mismatch |

Per C10: a version or compatibility conflict at binding time is a **refusal at admission**, never a
silent shadowing of another capability or another binding.

**Out of scope here:** which of several valid bindings gets *selected* for a given fulfillment
(ranking, tie-break, preference order) is late-binding/health territory — PRT/00 §4–§5, Phase 3/4.
This section only fixes that bindings exist as registry data and what makes one admissible.

## 8. Capability constraints

Constraints are declarative data the registry stores and gates for completeness; it never enforces
any of them at runtime. Architectural families:

| Family | What it declares |
|---|---|
| Execution restrictions | Conditions under which fulfillment may be attempted |
| Platform restrictions | Environment/target assumptions fulfillment depends on |
| Security / sandbox requirements | Isolation policy data (§2) — enforcement is Execution's, per C5 |
| Resource expectations | What fulfillment is expected to consume |
| Verification expectations | How fulfillment would be checked — **mandatory**, admission-gated (PRT-I4, CP/01 §7) |
| Dependency expectations | What else must hold or be available for fulfillment to be meaningful (feeds §6 dependency edges) |

The one non-negotiable item in this list is verification expectations: a capability without a
statable one is refused at registration, full stop (PRT-I4, CP/01 §12.7) — not deferred, not
admitted-with-a-warning.

## 9. Consistency rules

All of the following are enforced **at admission** — a mutation that would violate any of them is
refused outright, never published as an inconsistency to be cleaned up later:

| Rule | Enforcement |
|---|---|
| Identity uniqueness | No two live entries share an id |
| Alias-resolution acyclicity | No alias chain may cycle (§5) |
| Relationship endpoint validity | Every relationship edge (§6) must reference an id that exists in the registry; a dangling reference is refused |
| Binding consistency | No binding may target a retired id (§7) |
| Version monotonicity | The registry-global version (§4) only increases; no reuse, no rollback |
| Lifecycle legality | Only forward transitions per CP/01 §6 (proposed → active → deprecated → retired); no other direction is admitted |
| Metadata completeness | A verification expectation must be present (§8) before admission |

**Why admission-time, not eventual, consistency.** Readers replay historic registry versions for
determinism (§4, CP/04). If a published version were ever allowed to be observably inconsistent,
every determinism tuple citing that version would be built on a poisoned coordinate — and because
published versions are immutable (§4), there would be no way to retroactively fix it. The registry
is never allowed to be observably inconsistent at any published version; the only way to guarantee
that is to refuse bad mutations before they mint a version at all.

## 10. Evolution over years

The registry is designed to be append-mostly for its entire lifetime (CP/01 §9):

| Growth vector | How it lands |
|---|---|
| New domain (new science, hardware target, language, reasoning paradigm) | New category (rare, architectural decision) or facet value (free) + new capability rows — data, not code |
| New capability within an existing domain | Ordinary data addition, zero architectural decision required |
| Deprecated/retired capability | Tombstoned in place; never deleted, never reused |
| Provider ecosystem growth/churn | Independent of capability vocabulary growth (§7) — providers come and go against a stable id set |

Every one of these changes registry **content**. None of them requires PRT redesign: new
categories are curated additions to a closed dimension (CP/01 §5), not new registry architecture;
new capabilities and bindings are rows; retirement is a lifecycle state, not a schema change. The
registry's shape — identity, categories of information (§2), four relationships (§6), one
admission gate (§9), one global version (§4) — is the fixed architecture growth happens inside of.

---

## 11. Invariants (PRT-R1..R11)

Binding on Phases 2–5.

1. **PRT-R1** — The registry is the sole capability source in the OS; every other subsystem is a reader only.
2. **PRT-R2** — All registry mutations arrive as declarations (discovery/manifests) or enacted Lifecycle transitions, admitted or refused by PRT; no direct edits.
3. **PRT-R3** — CP is the registry's principal reader and the vocabulary's principal consumer, never a writer or co-author of capability definitions.
4. **PRT-R4** — Every mutation to any information category (§2) mints a new monotonic registry-global version; published versions are immutable forever.
5. **PRT-R5** — The registry-global version and a capability's per-entry version (CP/01 §7) are distinct coordinates and are never conflated.
6. **PRT-R6** — Alias-chain resolution is centralized in the registry; every consumer resolving the same id at the same version gets the same canonical answer.
7. **PRT-R7** — Exactly four capability-to-capability relationships exist (dependency, composition, alternative, conflict); no relationship type is added without amending CP/01 first.
8. **PRT-R8** — Provider bindings are many-to-many, admitted only against matchable capabilities and registered providers with compatible constraints; binding lifecycle never touches capability definitions.
9. **PRT-R9** — A capability without a statable verification expectation is inadmissible; no other constraint family is enforced by the registry itself (enforcement lives downstream, per C5).
10. **PRT-R10** — All consistency rules (§9) are enforced at admission; no published registry version is ever observably inconsistent.
11. **PRT-R11** — Registry growth is append-mostly and content-only; no future domain, capability, or provider requires redesign of the registry's architecture.

---

Status: Phase 1 registry model frozen within PRT/00 walls. Phase 2 (discovery & admission) and
Phase 3 (binding & load policy) design their mechanisms inside this model; they do not redefine it.
