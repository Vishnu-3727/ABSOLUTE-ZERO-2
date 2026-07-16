# Learning & Intelligence Engine (LIE) — Phase 3: Intelligence & Knowledge Derivation

Status: canonical derivation architecture. Conceptual only — no algorithms, no
confidence formulas, no similarity or ranking math, no indexing, no storage.
Refines within LIE/00 and LIE/01; contradictions require errata there.

All Phase 1–2 concepts are canon and keep their names: the five subsystems, the
three knowledge classes, Episode, Decision, Lesson, Pattern, Anti-Pattern,
Recipe, Project Dossier, Domain Knowledge Pack, the provenance envelope,
facets, and the relation set. This document defines how the Distillery and
Advisory Interface work *conceptually* — the transformation from attested
experience to citable advice.

---

## 1. Derivation Is Compilation

The governing idea of this phase, from which everything else follows:

> **The intelligence layer is a build artifact. The Experience Ledger is the
> source. The Derivation Ruleset is the compiler.**

The **Derivation Ruleset** is this phase's central new concept: the complete,
versioned, declarative statement of how intelligence follows from experience —
what constitutes recurrence, what evidentiary thresholds gate each maturity
grade (§4), how curation rulings weigh records (§8), what makes evidence sets
(§2) cohere. Rules are explicit criteria over facets, relations, verdicts, and
counts — data, not code behavior, in the same rules-as-data spirit as VAE's
verification rules. The numeric values inside the ruleset (thresholds, weights)
are implementation-phase material; the *existence, versioning, and authority*
of the ruleset are fixed here.

This one move discharges several charter requirements at once:

- **Determinism (INV-3, INV-8):** identical ledger + identical curation overlay
  + identical ruleset version → identical intelligence layer. There is no other
  input. "The system learned something" always reduces to "this ruleset version
  applied to these records yields this artifact" — no AI magic by construction.
- **Explainability:** every derived artifact's envelope already records its
  derivation provenance (LIE/01 §3); with the ruleset versioned and
  declarative, that provenance is *readable* — a human can open the ruleset
  version cited and see exactly which rule fired on which evidence.
- **Evolution:** improving how the system learns = a new ruleset version +
  regeneration. Old artifacts remain explainable under the version that
  produced them. Learning-about-learning changes the compiler, never the
  source.
- **Order-insensitivity:** derivation is a function of the ledger's *contents*,
  never of admission order. Two installations replaying the same records in
  different order compile identical intelligence.

The Distillery is therefore not a "learner" — it is the executor of the
current ruleset. All learning behavior lives in the ruleset, where it is
versioned, diffable, and auditable like everything else in this system.

---

## 2. Evidence Accumulation — the Evidence Set

The intermediate concept between raw experience and derived artifacts:

An **Evidence Set** is the collection of ledger records sharing a **signature**
— a facet-and-relation profile the ruleset defines as "the same engineering
situation" — partitioned by outcome polarity (VAE verdict). Evidence sets are
not stored knowledge; they are the deterministic grouping the Distillery
computes over the ledger, and every derived artifact is derived from exactly
one evidence set (its `evidenced-by` relations enumerate that set's members).

Evidence sets grow monotonically: new admitted episodes join the sets their
signatures match; nothing ever leaves (curation rulings change *weight*, §8,
never membership). This monotonicity is what makes evidence accumulation
honest — an artifact's evidence set at any point in history is reconstructible.

What "the same situation" means — which facets matter, how much signature
overlap suffices — is ruleset policy. The architecture fixes only that
grouping is by declared signature, not by any model's judgment of similarity.

---

## 3. How Each Artifact Kind Is Derived

All six derived kinds are compilations over evidence sets. This section fixes
each kind's *derivation shape*; thresholds and mechanics are ruleset content.

- **Lesson** — the minimal derivation: an insight compiled from a small
  evidence set (potentially a single episode), scoped to exactly the facet
  signature of its evidence. Lessons are where all insight enters the
  intelligence layer; they are cheap, narrow, and provisional by default (§4).
- **Pattern** — compiled from a *positive* evidence set that has recurred:
  multiple episodes, shared approach structure, verified success. The
  ruleset's recurrence criteria draw the lesson/pattern line (as LIE/01 §5.2
  anticipated).
- **Anti-Pattern** — the same derivation as Pattern over a *negative* evidence
  set: recurring approach, verified failures. When the ledger also contains a
  positive evidence set for the same situation signature, the Distillery
  derives the `instead-of` link automatically — "don't do X, do Y" is compiled,
  not authored.
- **Recipe** — compiled from a positive evidence set whose episodes share
  *ordered* approach structure (the `follows` threads within episodes agree on
  a step sequence). A recipe's scope is the facet span of its evidence — it
  never claims generality its episodes don't cover.
- **Project Dossier** — compiled per project identifier: its decisions,
  notable episodes, originated lessons, plus the relational half built on
  Project Signatures (§5).
- **Domain Knowledge Pack** — the final compilation stage: a declared facet
  scope selects the lessons, patterns, anti-patterns, recipes, and
  benchmark-bearing episodes within it (LIE/01 §5.6). Packs compile *from the
  intelligence layer plus the ledger*, making them views over already-derived
  knowledge — they introduce no new derivation of their own, which is why they
  stay deterministic for free.

---

## 4. Maturity — How Observations Become Trusted Knowledge

Derived artifacts carry a **Maturity Grade** in their envelope — an attribute
orthogonal to artifact kind, recomputed on every derivation, expressing how
well-evidenced the artifact currently is:

- **Provisional** — thin evidence (few episodes, single project). Honest but
  weakly supported; advice citing it says so.
- **Corroborated** — recurrence within scope: multiple independent episodes
  agree.
- **Established** — evidence spans multiple projects (§6): the artifact has
  survived transplantation, the strongest test short of time.

Plus one orthogonal flag: **Contested** (§7).

**Knowledge Promotion** is therefore not a ceremony and not a stateful
workflow: an artifact's grade *is* a function of its evidence set, curation
overlay, and the ruleset's thresholds, recomputed at derivation. Promotion
happens when new evidence lands and regeneration re-grades; demotion happens
the same way when contrary evidence lands or rulings down-weight the evidence
base. No one promotes knowledge; evidence does. This keeps the maturity ladder
inside INV-3 — grades regenerate with everything else — and eliminates an
entire class of state-management design that a workflow-based promotion system
would drag in.

The grade names and ladder shape are canon; the thresholds between rungs are
ruleset policy.

---

## 5. Similar Projects and Cross-Project Learning

A **Project Signature** is the aggregate facet profile of a project's ledger
records — what domains, technologies, and task classes the project's verified
work actually touched, weighted by that work. It is derived, per project,
during dossier compilation; it is never authored.

Similarity between projects is *conceptually* signature overlap: two projects
are similar in exactly the facets their signatures share, and any similarity
statement in a dossier cites those shared facets — "A resembles B" is always
"A resembles B *in these coordinates*," never a bare scalar. (How overlap is
computed is implementation; that similarity is facet-explainable is
architecture.)

Cross-project learning then *emerges* rather than being a mechanism: because
evidence sets group by signature and signatures are project-neutral (LIE/01
§5.7), an evidence set naturally accumulates episodes from every project whose
work matches. When it does, the derived artifact's maturity reaches
Established (§4) and its scope statement shows the project span. Nothing
transfers knowledge between projects; projects contribute evidence to shared
situations. The similar-projects machinery merely makes this visible to humans
(dossiers) and consumable at advisory time ("projects with signatures like
yours have this experience").

---

## 6. Recommendation Generation and Traceability

The Advisory Interface constructs recommendations at consultation time; it
stores none. A consultation presents a situation (as facets — the consumer's
declared context); the interface matches it against artifact signatures in the
current intelligence layer and constructs advice.

Every recommendation is a four-part object, all parts mandatory:

1. **Advice** — the artifact's content: the lesson, the pattern to apply, the
   anti-pattern to avoid (with its `instead-of` alternative), the recipe to
   follow.
2. **Scope statement** — the facet signature within which the evidence holds,
   and how the consumer's situation matched it. Advice never claims beyond
   its artifact's scope.
3. **Maturity and standing** — the artifact's grade, its Contested flag if
   set, and any curation rulings touching its evidence.
4. **Citation chain** — the complete traceability path:
   recommendation → artifact → evidence set members → episodes/decisions →
   VAE verdicts. Every link is an identifier resolvable in the ledger.

The chain is INV-4 made mechanical: justification is *constructed from the
envelope graph*, never narrated. A recommendation whose chain cannot be walked
end-to-end is a defect, and "no relevant experience" remains the definite
answer when no artifact's signature matches (LIE/00 tenet).

Because recommendations are pure functions of (situation, intelligence layer),
they are as deterministic and regenerable as the layer itself: same question,
same ledger state, same ruleset — same advice, forever.

---

## 7. Conflicting Intelligence

Conflict is information, not breakage. Two regimes:

- **Disjoint scopes** — artifacts that disagree but whose signatures differ
  ("prefer X on Jetson" / "avoid X on constrained-memory targets") coexist
  legitimately: engineering truth is contextual, and the scope statements
  already disambiguate at advisory time. No action needed; this is the common
  case and the model handles it by construction.
- **Same scope, opposite conclusions** — identical situation signatures with
  conflicting valence. The Distillery detects this deterministically during
  derivation (identical signatures are comparable strings, not judgments) and
  sets **Contested** on both artifacts. Contested artifacts remain in the
  layer and remain citable — advice presents both sides with both evidence
  sets — until a Curator ruling resolves precedence (LIE/01 §9), after which
  derivation follows the ruling. Silent precedence — resolution by recency,
  by count, by any automatic tie-break — is forbidden: automatic resolution
  would put a judgment call inside the compiler, and judgment is the
  Curator's mission, not the Distillery's.

New contrary evidence therefore *weakens* existing intelligence in exactly two
architecturally-visible ways: by re-grading (demotion, §4) and by contesting
(§7). Both happen at derivation, both are reproducible, and neither touches
history.

---

## 8. Supersession and the Curation Overlay at Derivation Time

The Distillery reads the curation overlay as a weighting input, completing the
loop LIE/01 §2 opened ("curation is how much to trust it now"):

- Records under a deprecation ruling are excluded from *fresh* evidence sets
  (they remain in the ledger and in the historical record of older artifact
  versions).
- Records under supersession contribute only through their superseding
  records.
- Contested-resolution rulings direct which side of a conflict fresh
  derivation follows.

Because the overlay is append-only and is an explicit derivation input (§1),
supersession never mutates history: old ledger records stand, old artifact
versions remain reconstructible (that ledger state + that overlay state + that
ruleset version), and *current* intelligence reflects current rulings.
"Stale intelligence" is thus not a special state to manage — staleness is
resolved at the next derivation, and what the system used to believe stays
answerable forever.

---

## 9. The Equivalence Obligation

LIE/00 requires both incremental absorption (INV-10) and full regenerability
(INV-3). This phase binds them:

> **Incremental derivation must produce an intelligence layer identical to
> full regeneration over the same inputs.**

Incremental processing is an optimization of the compilation, never a
different compiler. If an incremental path and the regeneration path can
disagree, the incremental path is defective by definition — regeneration is
always the reference semantics. This obligation is testable by construction
(run both, compare), giving the implementation phase a built-in oracle for the
Distillery's correctness.

---

## 10. Phase Boundary and Plan Adjustment

This document fixes: the Derivation Ruleset (versioned, declarative, the sole
seat of learning behavior), Evidence Sets and signatures, the derivation shape
of all six artifact kinds, the Maturity Grade ladder (Provisional /
Corroborated / Established + Contested), Project Signatures and emergent
cross-project learning, the four-part recommendation object with its citation
chain, the two conflict regimes, overlay-weighted derivation, and the
Equivalence Obligation.

It leaves open: all numeric thresholds and weights (ruleset content), signature
matching mechanics, retrieval, and everything operational.

**Plan adjustment (accepted, canon):** the remaining phases are re-scoped —

- **Phase 4 — Operational Lifecycle:** when each subsystem acts; what triggers
  admission, derivation, and regeneration; how episodes flow Gate → Ledger →
  Distillery → Curator → Advisory; how the rest of ABSOLUTE-ZERO consumes
  recommendations in practice.
- **Phase 5 — Integration & Implementation Blueprint:** end-to-end
  architecture review, full invariant reconciliation, integration contracts
  with the wider OS, and the implementation blueprint for Sonnet.
