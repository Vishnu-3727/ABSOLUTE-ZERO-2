# Learning & Intelligence Engine (LIE) — Phase 2: Engineering Knowledge Model

Status: canonical knowledge model for all later LIE phases. Conceptual
architecture only — no storage schemas, no record formats, no algorithms, no
retrieval, ranking, confidence, or lifecycle design. Refines within LIE/00;
contradictions require errata there, not silent divergence.

Everything in LIE/00 is canon: the five subsystems (Admission Gate, Experience
Ledger, Distillery, Advisory Interface, Curator), the two-layer knowledge model
(immutable experience layer, fully derived intelligence layer), the ten
invariants, and the governing principles. This document defines what knowledge
those layers conceptually contain.

---

## 1. Granularity — the Unit of Experience

The atomic unit of engineering experience is the **Episode**: one attested unit
of completed engineering work — one closed, verdict-tagged trace admitted
through the Gate. An Episode records what was attempted, in what context, what
was done, what VAE concluded, and what it cost.

Why this level and not the alternatives:

- **Whole projects** are too coarse. A project contains hundreds of reusable
  moments — a CUDA optimization that worked, a deployment that failed twice
  before succeeding — and project-level records bury them. Reuse happens at the
  level of "we faced this situation before," and situations are episode-sized.
- **Individual steps** are too fine. A step ("ran the linter") is meaningless
  outside its episode; storing steps as first-class records fragments the
  ledger into millions of context-free shards no derivation can honestly
  generalize from. Steps live *inside* episodes as content, not beside them as
  peers.
- **The episode matches the attestation boundary.** VAE renders verdicts on
  completed units of work; the Gate admits what VAE attested. Choosing any
  granularity other than the attested unit would force the Gate to either
  split one attestation across records (inventing provenance) or merge several
  (blurring it). One verdict, one Episode is the only granularity that keeps
  INV-1 clean.

One other unit of experience earns first-class standing: the **Decision**
(§4.2). Everything else in the knowledge model is either content inside these
two, or derived from them.

Projects are not records. A project is an *identifier* that episodes and
decisions carry — a grouping axis, like a domain or a technology. Project-level
knowledge exists, but as a derived compilation (§5.5), never as a primary
record competing with the episodes that evidence it.

---

## 2. The Three Classes of Knowledge

The two layers of LIE/00, plus one thin governance overlay:

| Class | Contents | Mutability | Origin |
|---|---|---|---|
| **Experience** (primary) | Episodes, Decisions | Immutable, append-only (INV-2) | Admission Gate, VAE-attested only (INV-1) |
| **Intelligence** (derived) | Lessons, Patterns, Anti-Patterns, Recipes, Domain Knowledge Packs, Project Dossiers | Disposable — regenerable pure function of experience + derivation version (INV-3) | Distillery |
| **Curation** (overlay) | Annotations: deprecation, supersession, contradiction rulings | Append-only; annotations are never edited, only followed by newer annotations | Curator |

The curation overlay is the one extension this phase adds to the LIE/00 layer
picture, and it exists by necessity: Curator rulings are not engineering
experience (no VAE attestation — they are governance acts, so INV-1 bars them
from the experience class) and not derived intelligence (they are judgments,
not regenerable functions of the ledger). They are append-only records that
*reference* ledger records by identifier and change how readers weigh them,
never what they say. This is the mechanism behind LIE/00's "Curator annotates,
never mutates."

Rule of thumb that later phases must preserve: **experience is what happened,
intelligence is what it means, curation is how much to trust it now.**

---

## 3. The Provenance Envelope

Every record in every class carries the same conceptual envelope:

- **Identity** — a stable identifier, unique forever, never reused.
- **Attestation** — for experience records, the reference to the VAE verdict
  that admitted it. For derived records, the derivation process version and the
  ledger state it was computed from. For curation records, the ruling's stated
  reasons and the evidence cited.
- **Origin** — which project, when, in what environment. Contributor identity
  is recorded here as provenance metadata only (§8).
- **Facets** — the record's position in the controlled vocabulary (§7):
  domains, technologies, task classes. Facets are the generalization axis of
  the whole model.
- **Relations** — typed links to other records by identifier (§6).

The envelope is what makes the ledger navigable at decade scale: any record,
found by any path, self-describes where it came from, why it is trusted, what
it concerns, and what it connects to. A record whose envelope cannot be
completed is not admissible.

---

## 4. Primary Knowledge — the Experience Layer

Two record kinds. The charter's capability list is deliberately collapsed into
them; a taxonomy with one store per capability would fragment provenance and
multiply lifecycle rules for no architectural gain.

### 4.1 Episode

The universal experience record. Conceptually: *situation* (what was needed,
under what constraints), *approach* (what was done — the workflow actually
followed, tools and plugins used, sequence of significant actions), *outcome*
(VAE verdict, resulting state, errors encountered), *cost* (time, resources,
retries).

Episodes are not subtyped into parallel record kinds. Instead an episode's
facets and content emphasis express what the charter lists as separate
capabilities:

- **Workflow History** — the approach portion of episodes, in aggregate.
- **Benchmark History** — episodes whose outcome payload is measurements taken
  under stated conditions. The measurement is only meaningful with the
  conditions, which is exactly what an episode records; a bare-numbers
  benchmark store would shed the context that makes numbers comparable.
- **Failure Records** — episodes whose verdict is a verified failure. Verified
  failure is admissible experience by LIE/00 canon, and failures are the
  highest-value records in the ledger: they are the evidence base for
  anti-patterns (§5.3).
- **Recovery Records** — episodes linked (`recovers`, §6) to a prior failed
  episode. The failure/recovery *pair* is the reusable unit — a recovery
  without its failure is a recipe with no trigger; keeping them as two linked
  episodes preserves both verdicts' provenance.

### 4.2 Decision

The record of a choice: the question faced, the options considered, the option
chosen, the rationale, the constraints in force, and the consequences expected
at decision time. Architecture Records are Decisions whose scope is
architectural — a facet, not a separate kind.

Decisions earn first-class standing beside Episodes because their value has a
different shape. An episode's value is *what happened*; a decision's value is
*what was considered* — including the roads not taken, which no trace of
executed work can capture. Rationale and rejected alternatives are precisely
the knowledge that evaporates when contributors leave, and the knowledge most
requested years later ("why is it built this way?").

A Decision is admitted like all experience: through the Gate, attested — the
attestation being the verified work that enacted it. Decisions are immutable
and record only what was known *at decision time*; whether the decision proved
right is established later by the episodes that enacted it (linked `enacts`,
§6) and by derived intelligence over those episodes — never by editing the
decision. A decision that proved wrong stays in the ledger unaltered, because
"what we believed then" is the experience; the correction lives in later
episodes and curation rulings.

---

## 5. Derived Knowledge — the Intelligence Layer

Five artifact kinds, all Distillery products, all regenerable (INV-3), all
citing the experience records that evidence them (INV-4). This phase fixes what
each *is*; how the Distillery produces them is later-phase material.

### 5.1 Lesson

A transferable insight distilled from one or more episodes: a statement of the
form "in situations with these facets, this holds," with citations. Lessons are
the smallest derived artifact — one insight, its scope, its evidence.

### 5.2 Pattern

A recurring approach with verified good outcomes across multiple episodes:
a situation signature (facets in which it applies), the approach it names, and
the evidence set. A pattern is a lesson about *approach* that has recurred —
the distinction from Lesson is evidentiary breadth, and drawing the line is
derivation policy, a later phase's concern.

### 5.3 Anti-Pattern

Structurally identical to Pattern with opposite valence: a recurring approach
with verified bad outcomes — signature, approach, evidence set, plus the
observed consequence and, where the ledger contains one, a link to the pattern
or recipe that works instead. Anti-patterns are first-class — same standing,
same citation discipline, same envelope as patterns — because at advisory time
"do not do X here, we have failed at it four times, do Y" is the single most
valuable sentence the engine can say. A model that stores successes as
knowledge and failures as embarrassments learns half of engineering.

### 5.4 Recipe

Procedural knowledge: an ordered course of action for a recurring engineering
task, generalized from the approach portions of multiple successful episodes
("Jetson deployment," "ROS2 package bring-up"). Where a pattern names *an
approach*, a recipe specifies *the steps* — patterns advise judgment, recipes
advise procedure. Recipes carry their evidence episodes and the facet scope
they were generalized within, so a recipe never silently claims more
generality than its evidence spans.

### 5.5 Project Dossier

The per-project compilation: what the project is (by facets), the significant
decisions, the notable episodes, the lessons that originated there — and the
project's *relationships to other projects*, derived from shared facet
signatures. Cross-Project Relationships and Similar Project Knowledge are the
dossier's relational half: "project A resembles project B in these facets" is
a derived, regenerable statement, recomputed as the ledger grows, never a
hand-maintained registry. The dossier is how a future contributor — or a
future ABSOLUTE-ZERO — enters a project cold and inherits its accumulated
context.

### 5.6 Domain Knowledge Pack

The named, portable compilation of everything the ledger knows about a domain:
the lessons, patterns, anti-patterns, recipes, and benchmark-bearing episodes
whose facets fall within the domain's declared facet scope ("ROS2," "CUDA,"
"embedded power management"). Membership is deterministic — a pack is defined
by its facet scope, and its contents follow from the ledger; packs are compiled
views, not curated scrapbooks. Packs exist because domains are how engineering
knowledge is *consumed*: a contributor starting Jetson work wants the Jetson
pack, not a query language. Packs are versioned like all derived artifacts and
are the natural unit of knowledge transport between installations.

### 5.7 Cross-project learning, conceptually

Cross-project learning is not a sixth artifact kind — it is a *property* of the
derivation path. Episodes are project-anchored facts; facets are
project-neutral coordinates; every derived artifact generalizes exactly as far
as its evidence's facets span. When evidence for a pattern comes from one
project, the pattern's scope says so; when episodes from five projects share a
facet signature and an outcome shape, the derived artifact is legitimately
cross-project — and its citations prove it. Generalization is therefore earned
per-artifact from evidence, never asserted, and never performed in the primary
layer (episodes and decisions stay project-anchored forever).

---

## 6. Relations

Typed, identifier-only links carried in the envelope. The minimal set, chosen
because each answers a question later phases cannot answer otherwise:

| Relation | From → To | Question it answers |
|---|---|---|
| `enacts` | Episode → Decision | What work carried out this choice? |
| `recovers` | Episode → Episode | What failure does this work respond to? |
| `follows` | Episode → Episode | What is the causal/sequential thread within a work stream? |
| `evidenced-by` | Derived → Experience | What attested records justify this artifact? (INV-4's mechanism) |
| `instead-of` | Derived → Derived | What works where this anti-pattern fails? |
| `supersedes` | Curation → any; Derived → Derived | What replaced this, and by whose ruling? |
| `about` | Any → UMS identifier | What repository entity does this concern? (INV-9: identifier only, never copied content) |

New relation types may be added by later phases (additively, per LIE/00
principle 1); none of these may be removed or redefined.

---

## 7. Facets — the Controlled Vocabulary

Facets are the model's generalization axis: controlled-vocabulary coordinates
(domains, technologies, task classes, environments) that every record carries.
Two rules make them durable over a decade:

1. **The vocabulary is versioned, additive, and owned by the Curator.** New
   facet terms are added; existing terms are never renamed or deleted (readers
   of old records must always resolve old terms — LIE/00 principle 3). Term
   merges and refinements are expressed as curation rulings, not rewrites.
2. **Facets are assigned at admission from evidence, not invented freely.**
   The Gate normalizes incoming material onto the vocabulary; free-text tags
   are content, not facets. An uncontrolled vocabulary diverges per
   contributor within months and silently destroys cross-project learning,
   which depends on facet signatures meaning the same thing in year one and
   year ten.

What stays project-specific versus generalized falls out of the facet design:
identifiers anchor records to projects (specific, forever); facets place them
in project-neutral coordinates (generalizable, by evidence). Nothing else is
needed to draw that line.

---

## 8. Contributor Independence

Engineering knowledge must outlive its authors. Three properties, all already
implied by the model, stated here as binding:

1. **Evidence is the only authority.** No record's weight derives from who
   produced it. Contributor identity is origin metadata — useful for audit,
   inadmissible as justification. Advice cites episodes, never people.
2. **The vocabulary is shared, not personal.** Facets and relation types are
   controlled (§7); records written by different contributors in different
   years remain mutually intelligible because they use the same coordinates.
3. **Records are self-contained given the envelope.** Understanding a record
   requires the record, its envelope, and the vocabulary — never a
   conversation with its author, and never a particular model's
   interpretation (INV-6). The LIE/00 "boring record wins" principle is the
   enforcement mechanism: any proposed representation is tested against a
   contributor reading it cold in 2036.

---

## 9. Evolution Without Mutation

How the model absorbs a decade of change while INV-2 holds:

- **New knowledge**: append episodes and decisions; derived artifacts
  strengthen or emerge on regeneration.
- **Corrected knowledge**: the correction is new experience (a failed approach
  is re-attempted, verified differently); the Curator rules the old record
  superseded with `supersedes` linking new to old. History remains; fresh
  advice follows the ruling.
- **Contradiction**: two records disagree → Curator issues a recorded ruling
  (a curation record citing both and the resolution rationale). Silent
  precedence is forbidden.
- **Vocabulary change**: additive only (§7); merges by ruling.
- **Representation change**: new conventions must read old records (LIE/00
  principle 3 — regenerate over migrate for derived, readers-accept-old for
  primary). A convention change that would require rewriting the ledger is
  rejected by construction.

---

## 10. What Later Phases Inherit

The derivation surface this model exposes — stated so Phases 3+ design against
it rather than reinventing it:

- **Grouping**: episodes and decisions carry facet signatures; derivation
  groups by signature. (Pattern/anti-pattern discovery, recipe generalization,
  pack compilation, dossier relationships all reduce to deterministic
  operations over facets, relations, and outcomes.)
- **Valence**: VAE verdicts give every episode an outcome polarity; derivation
  separates what works from what fails without interpretation.
- **Lineage**: relations give derivation causal threads (failure→recovery,
  decision→enactment) to distill from.
- **Trust weighting**: curation annotations tell any consumer — Distillery and
  Advisory alike — how to weigh a record *today* without touching what it
  says.

Capability coverage check (charter list → model): Engineering Experiences,
Workflow History, Benchmark History, Failure Records, Recovery Records →
Episode. Decision Memory, Architecture Records → Decision. Lessons Learned →
Lesson. Anti-Patterns → Anti-Pattern. Engineering Recipes → Recipe. Project
Knowledge, Cross-Project Relationships, Similar Project Knowledge → Project
Dossier (+ §5.7). Domain Knowledge Packs → §5.6. Contributor-independent
knowledge → §8. No capability left unmapped; no record kind exists without a
capability requiring it.

---

## 11. Phase Boundary

This document fixes the knowledge model: two primary record kinds, five derived
artifact kinds, the curation overlay, the provenance envelope, the relation
set, the facet vocabulary rules, and the evolution discipline. It deliberately
leaves open: how the Distillery discovers patterns, how similarity over facets
is computed, how recommendations are constructed and cited, confidence,
retrieval, and curation policy detail. Those are Phases 3–5 material and must
be designed inside this model.
