# Verification & Assurance Engine (VAE) — Phase 2: Assurance & Confidence

Status: authoritative for the assurance model — what confidence means, how
evidence contributes to it, how uncertainty is represented, and the
assurance-level taxonomy. Architecture only: no algorithms, no scoring
formulas, no equations, no numeric weights or thresholds, no APIs, no
events, no data structures, no schemas, no Kernel policy. How verdicts and
assurance flow to the enforcers, retry/rollback recommendations, Request
State integration, and operational behavior are VAE/03–04 territory
(VAE/00 §11). VAE/00 and VAE/01 are immutable above this document: where
this document is silent they govern; where they speak, this document
refines and never contradicts.

---

## 1. Assurance Model

**What assurance represents.** Assurance is the system's accumulated,
evidence-derived account of how strongly an artifact's trustworthiness is
established — the answer to "how well do we know this is sound," where
verification (VAE/01 §1) answers "is this sound against these rules."
VAE/00 §2 already fixes the philosophy ("assurance is manufactured, not
assumed"); this phase fixes what the manufactured product *is*: a
structured summary over the evidence body that verification produced.

**Assurance vs. verification.** Verification is the act; assurance is the
standing that the act's outputs establish. One verification act produces
evidence and (where gated) a verdict (VAE/01 §1, §6); assurance is read
*from* the accumulated evidence across all acts that touched an artifact or
scope (VAE/01 §7's progression). Verification can complete while assurance
remains modest — a pass reached on thin evidence is a real pass (VAE-I5)
carrying weak assurance. The distinction prevents the two-values-collapse
failure: if "verified" and "well-assured" were the same word, the system
could not express "this passed, but on the minimum evidence the rules
required."

**Assurance vs. confidence.** Confidence (§2) is the representational
substance — the evidence-derived measure attached to a verdict (VAE/00 §4
responsibility 5). Assurance is the interpreted whole: confidence plus its
explicit uncertainty (§6) plus the coverage of what was and was not
examined, summarized into a communicable classification (§7). Confidence is
a component of assurance the way evidence is a component of a verdict.

**Why evidence-driven.** Any assurance not derived from recorded evidence
is asserted trust — the "optimism" VAE/00 §1 names as V1's failure and
Principle 4 forbids at the confidence level. Deriving assurance exclusively
from the evidence body means assurance can never exceed what was actually
checked, and can always be challenged by pointing at the record.

**How it summarizes verification without replacing it.** Assurance is a
read-only projection over evidence records; it adds no facts, removes none
(VAE-M2), and grants nothing the underlying verdicts did not grant. No
assurance construct may substitute for a verdict at a gate: the gate opens
on `verify.passed` alone (VAE-I2, VAE-I5), never on an assurance level.
This prevents the summary-becomes-authority failure, where a convenient
aggregate quietly displaces the definite terminal verdicts it was derived
from.

---

## 2. Confidence Model

**What confidence means.** Confidence is a structured representation of the
strength of accumulated verification evidence supporting an artifact's
conformance to its declared rules — how much independent, corroborating,
covering evidence stands behind the verdict (extending VAE/00 Principle 4
and VAE-I7 from "confidence is evidence-derived" to "confidence *is* the
evidence body's strength, represented").

**What it does not mean:**

| Not this | Why not |
|---|---|
| Probability | A probability claims a calibrated long-run frequency of correctness. VAE has no ground-truth oracle over which such a frequency could be defined per artifact; presenting confidence as probability would assert a precision the evidence cannot support, and precision the reader would wrongly act on. Confidence orders and characterizes evidence strength; it does not predict. |
| Correctness | Correctness is what verification *judged* (VAE/01 §1); confidence describes how strongly that judgment is evidenced. A defect the rules never test for (VAE/01 §1, "What it cannot prove") passes at any confidence. Conflating the two would let high confidence be read as a proof the ceiling explicitly denies. |
| Producer self-assessment | Already forbidden (VAE-I7, VAE/00 Principle 4); restated only because it is the cheapest attack: asserting trust instead of demonstrating it. |
| A quality score of the artifact | Confidence measures the *evidence about* conformance, not the artifact's merit. An artifact can be excellent and thinly verified, or mediocre and exhaustively verified. |

**Why never arbitrary.** Confidence derivation is deterministic over the
evidence record (Law 6, VAE-I6 discipline extended): identical evidence
body + identical rules version → identical confidence. Two artifacts with
the same evidence and rules carrying different confidence is a defect, not
a nuance. This is what makes confidence disputable and replayable rather
than mood — the same property VAE/00 Principle 5 demands of verdicts,
applied to the measure attached to them.

**Confidence as accumulated-evidence representation.** Confidence has no
existence apart from the evidence record it summarizes; it is derivable
from that record alone at any time (VAE-I8 discipline), and it changes only
when the evidence body changes (§4). An artifact with no evidence has no
confidence — and "no confidence" is a definite, reportable state, never a
default (VAE/00 §2, "Evidence before confidence").

---

## 3. Confidence Dimensions

**Decision: multi-dimensional, with one dimension per VAE/01 verification
level plus a coverage dimension.** Neither a single scalar nor a deep
hierarchy.

| Dimension | What it represents | Source levels (VAE/01 §5) |
|---|---|---|
| Structural confidence | Strength of evidence that the artifact is well-formed | Structural |
| Execution confidence | Strength of delegated-check evidence (which checks ran, at what depth, with what results) | Execution |
| Semantic confidence | Strength of evidence for contract satisfaction in substance | Semantic |
| Consistency confidence | Strength of evidence for coherence with related artifacts and state transitions | Cross-artifact + System |
| Evidence coverage | How much of what the rules *could* require was actually examined — the dimension that says how much the other four are entitled to claim | All levels; the scoping record itself |

Cross-artifact and System share a dimension because both answer coherence
questions over already-verified parts (VAE/01 §5) and separate reporting
would manufacture a distinction no consumer of the confidence can act on
differently — a fifth judgment dimension is speculative structure until a
later phase demonstrates a consumer that needs the split.

**Why not a single percentage.** A scalar destroys exactly the information
assurance exists to preserve. "82%" cannot distinguish "structurally
airtight, semantically barely examined" from "uniformly moderately
evidenced" — yet those two states warrant entirely different reactions
from whoever reads them. A scalar also invites false-precision reasoning
(ranking artifacts by two-point differences the evidence cannot support)
and hides coverage gaps: the single worst failure a confidence
representation can have is reporting high confidence while silently having
examined only one level. Per-level dimensions keep every claim attached to
the level of question that produced its evidence (VAE-M7 already forces
this attribution at the evidence-item grain; dimensions carry it up to the
summary grain instead of discarding it).

**Why not hierarchical.** A hierarchy (dimensions of sub-dimensions) adds a
representational layer with no consumer: nothing in VAE/00–01 asks
questions at a grain between "evidence item" (already attributed, VAE-M7)
and "level" (already defined, VAE/01 §5). Structure without a consumer is
bloat; the evidence record itself remains the full-fidelity substrate for
any future need.

No numeric form, scale, banding, or combination rule is prescribed here —
representation semantics are fixed; their expression is later-phase
rules-as-data (VAE/00 §9, "Modular checks, rules as data").

---

## 4. Confidence Evolution

**Begins incomplete.** At an artifact's first appearance, confidence is
minimal in every dimension — the artifact arrives with zero standing
(VAE/00 §2, "Trust nothing") and coverage is by definition near-empty.
There is no default starting confidence; a starting default would be
confidence injected from outside the evidence (VAE-I7).

**Grows with evidence.** Each verification act appends evidence (VAE/01 §6)
and confidence is re-derived from the enlarged body. Growth is earned per
dimension: a new selftest result moves execution confidence and coverage;
it does not move semantic confidence it says nothing about. This per-
dimension discipline prevents halo growth — evidence in one dimension
silently inflating claims in another.

**New evidence influence.** New evidence can raise, leave unchanged, or
*lower* confidence — a later delegated check that fails, or a dependent
artifact whose verification contradicts an earlier coherence conclusion
(VAE/01 §7's progression explicitly produces such late evidence about
earlier artifacts). Confidence that could only rise would be a ratchet, not
a measure.

**Contradictory evidence effect.** When independently sourced evidence
conflicts (VAE/01 §11, "Contradictory evidence"), confidence in the
affected dimension is *reduced below what either item alone would support*
— a contradiction is information that at least one evidence source is
wrong, which is itself a fact about the evidence body's reliability. The
contradiction stays distinguishable in the record (VAE-M4); confidence
reflects it rather than averaging over it, because averaging would let two
conflicting sources masquerade as moderate agreement. Evidence
insufficiency and inconclusive results (VAE/01 §11) likewise express
themselves as low coverage and low dimensional confidence respectively —
the failure taxonomy and the confidence representation describe the same
states from two sides.

**Why evolve rather than calculate once.** Verification is continuous and
cumulative (VAE/01 §2, §7): evidence about an artifact keeps arriving
after its own verdict, from dependents, integrated verification, and
system-level questions. A calculate-once confidence would be frozen at the
artifact's least-informed moment and silently wrong forever after — the
assurance-level analogue of verifying only at request completion (VAE/01
§3). Evolution is re-derivation from the current evidence body, never
mutation of past records: every historical confidence remains
reconstructible from the evidence that existed at its time (VAE-M2,
VAE-I8).

---

## 5. Evidence Contribution

Evidence items contribute unequally to confidence by *kind of relationship
to the claim*, not by numeric weight (weighting expression is rules-as-data,
not architecture):

| Contribution kind | Meaning | Effect on confidence | Why the distinction exists |
|---|---|---|---|
| Independent | Bears on a claim no other evidence addresses | Extends coverage; first standing for that claim | Coverage is the dimension most easily faked by volume; only genuinely new claims may extend it. |
| Corroborating | Independently sourced, agrees with existing evidence on the same claim | Strengthens the claim's confidence beyond what either source alone supports | This is VAE/01 §6's independence principle made operational: agreement across methods narrows where a defect could hide. Corroboration requires source independence — the same check re-run is not corroboration (see Redundant). |
| Conflicting | Independently sourced, disagrees with existing evidence on the same claim | Reduces confidence below either item alone (§4); both items preserved distinguishably (VAE-M4) | Prevents conflict-averaging; a disagreement is a reliability fact, not noise to smooth. |
| Redundant | Repeats an existing item's claim from a non-independent source (same check, same method, same inputs) | No confidence increase | The core anti-gaming rule: without it, re-running one cheap check inflates confidence indefinitely — "run it again until it looks trustworthy," the confidence-level twin of the verdict failure Law 6 exists to prevent. Redundant evidence is still recorded (VAE-M2); it just does not count twice. |
| Missing | Evidence the rules identify as obtainable for this artifact but absent | Caps coverage; visible as explicit uncertainty (§6) | Absence must be load-bearing: a confidence representation that ignores what *wasn't* checked reports the same assurance for a fully-examined artifact and a barely-examined one. This is VAE/01 §11's "evidence insufficiency" carried into the measure. |

**Why unequal contribution.** Equal contribution makes confidence a count,
and counts are gameable by the producer of the cheapest evidence.
Contribution-by-relationship makes confidence answer the only question that
matters — *how hard would it be for a defect to have evaded this evidence
body* — which volume alone never answers.

---

## 6. Uncertainty Model

**Uncertainty is expected.** Verification proves conformance to what was
checkable, never truth in general (VAE/01 §1); the gap between the two is
uncertainty, and it exists for every artifact, always. A model that treats
uncertainty as an anomaly will be engineered to hide it.

**Uncertainty vs. failure.** Failure is evidence *against* a claim
(VAE/01 §11, "Verification failure" — a positive, evidence-backed negative
conclusion). Uncertainty is the absence or weakness of evidence *about* a
claim. Conflating them punishes honesty: if "we don't know" reads as "it's
bad," the system is incentivized to not-ask rather than to ask-and-report.

**Uncertainty vs. low confidence.** Low confidence in a dimension says the
evidence that exists is weak; uncertainty says how much territory the
evidence never reached (the coverage dimension, §3, and Missing evidence,
§5). An artifact can carry high dimensional confidence with high
uncertainty — everything examined looked strong, but little was examined.
These must remain separately readable, because they call for different
responses from whoever consumes them (what those responses are is Phase 3's
business, not this document's).

**Uncertainty stays explicit.** Uncertainty is always represented as its
own visible component of assurance, never absorbed into a lowered
confidence value. Folding uncertainty into confidence destroys the
distinction above and makes the record unexplainable: a reader of a folded
value cannot tell whether it reflects weak evidence or absent evidence,
violating the spirit of VAE-I8 (every conclusion reconstructible from the
record).

**Coexistence with confidence.** Confidence and uncertainty are complements
over the same evidence body, not opposites on one axis: confidence
summarizes what the evidence establishes; uncertainty summarizes what the
evidence body admits it never established. Both derive from the same
record, both are deterministic over it (§2), and both accompany every
assurance readout (§7).

---

## 7. Assurance Levels

A closed classification taxonomy summarizing an artifact's assurance state
for human and downstream consumption. Levels are **evidence summary**, not
gate output: the gate sees only the two terminal verdicts (VAE-I5,
`verify.passed` / `verify.failed`), and no level ever substitutes for,
overrides, or reinterprets a verdict (§1). The taxonomy exists because the
two verdict values are deliberately information-poor at the gate — the
richness lives in evidence, and levels are the standard shorthand for that
richness.

| Level | Meaning | Interpretation |
|---|---|---|
| **Verified — High Assurance** | Terminal pass; evidence strong across all applicable dimensions; coverage substantially complete; no unresolved conflicts | The strongest statement VAE can make: passed, and the evidence body makes evasion by a defect hard. Still not a correctness guarantee (§2). |
| **Verified — Moderate Assurance** | Terminal pass; evidence adequate but uneven — some dimensions thin, or coverage materially incomplete | Passed on what was checked; the assurance readout tells the reader *which* dimensions carry the thinness (§3). |
| **Verified — Low Assurance** | Terminal pass reached on minimal evidence — the least the rules required, high uncertainty | A real pass (VAE-I5 admits no half-verdicts) that any reader should treat as thinly established. Exists so that "passed on minimum evidence" is sayable without weakening the verdict. |
| **Unverified** | No terminal verdict yet exists for this artifact | Not a judgment — the pre-judgment state. Enforcers already treat it as not-passed (VAE-I5); the level only names the state for reporting. |
| **Verification Failed** | Terminal fail, for any of the VAE/01 §11 causes | The evidence record carries *which* cause (failure, insufficiency, inconclusiveness, contradiction) per VAE/01 §11; the level does not re-encode the cause because the record already does. |

**Why this shape.** Three graded pass levels because §3–§6 establish that
passes differ meaningfully in evidence strength and that difference must be
communicable; exactly three because finer gradation implies a precision the
non-numeric model deliberately refuses (§2, "not probability"). One fail
level because fail causes are already fully distinguished by VAE/01 §11 and
duplicating that taxonomy into levels would create two authorities for the
same distinction. One pre-verdict level because limbo must be nameable to
be reportable, while remaining exactly the not-passed state VAE-I5 already
defines.

Level assignment is deterministic over the evidence record and rules
version (§2 discipline); the mapping's expression is rules-as-data. No
level connects to any execution decision — what the Kernel does with
"Verified — Low Assurance" is Phase 3's question and is not prejudged here.

---

## 8. Explainable Assurance

Extends VAE-I8 (every verdict explainable from its immutable evidence
record alone) from verdicts to the assurance constructs this phase adds:

| Property | Requirement | What failure it prevents |
|---|---|---|
| Traceability | Every confidence dimension value, uncertainty statement, and assurance level traces to the specific evidence items (and identified absences) that produced it, via the attribution VAE-M7 already forces at the item grain | An assurance readout that cannot answer "which evidence made you say that" is an assertion, not a summary — the exact thing Principle 4 forbids entering; it must not be manufactured internally either. |
| Supporting evidence | An assurance readout is never presented apart from the ability to reach its underlying record; the summary and its substrate are permanently linked | Summaries drift into circulation detached from evidence and get treated as facts; linkage keeps the summary challengeable. |
| Reproducibility | Confidence, uncertainty, and level re-derive identically from the same evidence body and rules version, at any later time, by any party (Law 6 extended per §2) | Irreproducible assurance cannot be disputed or audited — disagreement decays into whose derivation ran last. |
| Auditability | The history of assurance over an artifact's life is reconstructible: what the confidence was at any point, from what evidence then existed (VAE-M2 makes the substrate non-lossy; this requires the derivation to honor it) | Without historical reconstruction, "why did we trust this at the time" requires archaeology — the exact failure VAE/00 §2 names for verdicts, recurring one level up. |

**Why opaque confidence is unacceptable.** An opaque confidence — one whose
derivation cannot be stated from the record — is indistinguishable from an
asserted one, and asserted confidence is the cheapest attack on the whole
subsystem (VAE/00 Principle 4). Opacity also breaks the anti-drift
mechanism: with explainable derivation, two differing confidence values are
attributable to evidence, rules version, or derivation — never to mood
(VAE/00 Principle 3 applied to the measure). Any confidence mechanism whose
contribution cannot be stated in the record is forbidden — VAE/00 §9
("Explainable evidence, always") already binds this; assurance adds no
exemption.

---

## 9. Confidence Benchmarking

Assurance must itself be measurable — a confidence representation nobody
ever checks against reality drifts into decoration. Architectural intent
only; no metrics, no math, no thresholds. All benchmarking consumes VAE's
own telemetry and records through the ordinary observability path (VAE-I12)
and its findings enter VAE only as versioned rules revisions (VAE/00 §9,
rules-as-data) — never as live adjustment mid-judgment (sealed consumption,
VAE/00 §9).

| Benchmarking concern | Question it answers | Why it exists |
|---|---|---|
| Calibration | Do artifacts carrying stronger assurance in fact go on to exhibit fewer downstream-discovered defects than weaker-assured ones? | A confidence that does not order outcomes is noise wearing a uniform; calibration is the only external test the representation has. |
| Evidence coverage | Is the coverage dimension honest — do rules identify as "obtainable" the evidence that actually matters, or does formally-complete coverage still miss defect classes? | Coverage caps every other claim (§3, §5); if coverage itself is miscalibrated, the whole readout inherits the error. |
| Agreement between independent verification activities | When independent checks address the same claim, how often do they agree — and is corroboration (§5) therefore earning the extra trust it is granted? | Corroboration's value rests on source independence; systematically correlated "independent" checks are redundancy in disguise, and only agreement history exposes that. |
| Historical verification effectiveness | Which checks, at which levels, have historically caught defects — and which have never failed anything? | A check that cannot fail contributes coverage on paper and nothing in fact; effectiveness history is what keeps rules-as-data revisions grounded in evidence rather than intuition. |
| Consistency across repeated executions | Do identical evidence bodies yield identical confidence and levels across time, versions, and re-derivations? | The determinism obligation (§2, §8) must be demonstrated, not asserted — the same "demonstrated, not asserted" standard VAE/00 §10 sets for independence. |

Whether and how benchmarking findings feed the Experience & Knowledge
Store's learning about verification is governed by the existing membrane
rules (VAE/00 §8, Experience row) and needs nothing new here.

---

## 10. Assurance Boundaries

The VAE/00 §5 and VAE/01 §9 boundaries bind assurance unchanged; this
section states only the *assurance-specific* form each takes — the new
temptation each boundary faces once confidence exists:

| Boundary | Assurance-specific form | Why it exists here specifically |
|---|---|---|
| Never executes | Assurance never triggers evidence-gathering execution to improve a confidence value — low confidence is a reportable state, not a work order VAE issues to itself | Confidence creates a new incentive to act (raise the number); acting on it would hand VAE a control loop, which VAE/00 §9 forbids. Which additional checks the rules require is fixed before judgment (rules-as-data), not demanded mid-derivation. |
| Never retries | Assurance never re-runs a check because the resulting confidence "looks low" — redundant re-runs earn nothing anyway (§5), and requesting them to shift a summary is "run it again until it passes" migrated up one level | Law 6's target failure recurs at the measure: a confidence that can be farmed by repetition is not evidence-derived. |
| Never repairs | Assurance never adjusts, annotates, or reframes an artifact — nor its evidence — to warrant a better level | Repairing the *evidence* is subtler and more tempting than repairing the artifact (VAE-I4 covers the artifact); §10's "never modifies evidence" row closes the remaining half. |
| Never decides policy | No assurance level, confidence dimension, or uncertainty statement encodes what should be done — no "requires re-verification," no "safe to proceed," no risk-acceptance semantics | Levels sit adjacent to decisions and will be pulled toward becoming them; the moment a level implies an action, VAE is making Kernel policy under a taxonomy's disguise (VAE-I1). Phase 3 designs the consumption; this phase keeps the product decision-free. |
| Never modifies evidence | Confidence derivation and level assignment are read-only projections over the record; no derivation step writes back, reweights in place, summarizes destructively, or prunes evidence items | The judge that edits the evidence has destroyed it (VAE/00 §5); a *summarizer* that edits its substrate has done the same thing one step removed — and additionally broken reproducibility (§8), since the record a later auditor re-derives from is no longer the record that was derived from. |

---

## 11. Architectural Invariants (VAE-A)

New Phase 2 register, extending VAE-I1–I12 and VAE-M1–M7 without
duplication; binding on all later VAE phases.

1. **VAE-A1** — Confidence is derived exclusively and deterministically from
   the recorded evidence body and rules version: identical body + identical
   rules → identical confidence, uncertainty, and assurance level, at any
   time, by any party. *Prevents:* confidence-by-mood and
   confidence-farming; makes assurance disputable (§2, §8).
2. **VAE-A2** — Confidence is multi-dimensional per §3; no construct may
   collapse the dimensions into a single value that then circulates in
   place of them. *Prevents:* the scalar failure — coverage gaps and
   dimensional imbalance hidden inside one flattering number.
3. **VAE-A3** — Uncertainty is always explicit and separately readable from
   confidence; no derivation folds absence-of-evidence into
   weakness-of-evidence. *Prevents:* "we didn't look" becoming
   indistinguishable from "we looked and it's shaky" (§6).
4. **VAE-A4** — Evidence contributes to confidence by relationship kind
   (§5): only source-independent corroboration strengthens beyond a single
   source; non-independent repetition never increases confidence.
   *Prevents:* gaming confidence through volume of cheap, correlated
   checks.
5. **VAE-A5** — Contradictory evidence reduces confidence in the affected
   claim below what any single conflicting item would support, and is never
   averaged, reconciled by discard, or smoothed. *Prevents:* conflicts
   masquerading as moderate agreement (§4, §5; substrate preserved by
   VAE-M4).
6. **VAE-A6** — Assurance constructs (confidence, uncertainty, levels) are
   read-only projections over evidence records; no derivation modifies,
   prunes, reweights in place, or destructively summarizes its substrate.
   *Prevents:* the summarizer corrupting the record it summarizes (§10),
   which would break VAE-M2 and VAE-I8 one level up.
7. **VAE-A7** — No assurance level or confidence value carries gate
   authority or substitutes for a terminal verdict; gates open on
   `verify.passed` alone, and no component may accept a gated artifact on
   the strength of an assurance level. *Prevents:* the summary displacing
   the verdict — a soft bypass of VAE-I2/I5 through the reporting channel.
8. **VAE-A8** — No assurance construct encodes, implies, or recommends an
   execution decision; assurance vocabulary is descriptive of evidence
   only. *Prevents:* policy leaking into VAE through the taxonomy (VAE-I1's
   perimeter held at the new surface this phase creates).
9. **VAE-A9** — Confidence begins minimal for every new artifact and
   changes only when the evidence body changes; no default, decay schedule,
   inheritance from provenance, or producer input ever moves it.
   *Prevents:* confidence acquired on credit — trust existing without
   evidence having been manufactured (§4; extends VAE-I7 to the full
   lifecycle).
10. **VAE-A10** — Every assurance readout is traceable to its evidence
    items and identified absences, and the assurance history of an artifact
    is reconstructible for any past point from records alone. *Prevents:*
    opaque or archaeologically-lost assurance (§8); the VAE-I8 guarantee
    extended from verdicts to everything this phase adds.

---

## 12. Phase Summary

**Now fully defined by this document:**

- Assurance as the evidence-derived standing distinct from both the
  verification act and the confidence measure, and its summary-never-
  authority relationship to verdicts (§1).
- The confidence model: what confidence represents, its explicit
  non-meanings (not probability, not correctness, not quality, never
  asserted), and its deterministic derivation discipline (§2).
- The five-dimension confidence representation aligned to VAE/01's
  verification levels plus coverage, and the rejection of scalar and
  hierarchical alternatives (§3).
- Confidence evolution over the artifact's life: minimal start, earned
  per-dimension growth, bidirectional movement, contradiction handling,
  and re-derivation-not-mutation (§4).
- The five evidence-contribution kinds and the anti-gaming rule that
  contribution follows relationship, not volume (§5).
- The uncertainty model: expected, explicit, distinct from both failure
  and low confidence, complementary to confidence (§6).
- The five-level assurance taxonomy (three graded pass levels, Unverified,
  Verification Failed) and its reconciliation with the two terminal
  verdicts (§7).
- Explainable assurance: traceability, evidence linkage, reproducibility,
  and historical auditability (§8).
- The architectural intent of confidence benchmarking: calibration,
  coverage honesty, independence-agreement, check effectiveness, and
  derivation consistency (§9).
- Assurance-specific boundary forms and ten new invariants VAE-A1–A10
  (§10, §11).

**Intentionally deferred**, per the VAE/00 §11 roadmap:

- How verdicts, confidence, and assurance levels flow to the Kernel and
  Scheduler; gate topology; what any consumer *does* with an assurance
  level; retry/rollback recommendations and the failure-mode contract —
  **Phase 3 (Kernel Integration)**.
- Request State Manager integration and assurance's place in a request's
  recorded life — **Phase 3**.
- Operational flow: derivation timing, evidence persistence mechanics,
  telemetry shape for benchmarking, performance envelope — **Phase 4
  (Operational Architecture)**.
- Full event canon and Experience trusted-knowledge integration detail —
  **Phase 5 (System Integration)**.

This document introduces no formula, scale, threshold, algorithm, event, or
schema, and settles no question VAE/00 or VAE/01 already settled. Every
construct traces to a responsibility, principle, or invariant it refines.
