# Verification & Assurance Engine (VAE) — Phase 1: Verification Model

Status: authoritative for the verification model — the artifact taxonomy,
verification-level decomposition, evidence model, and Phase 1 invariant
register. Architecture only: no algorithms, no interfaces, no APIs, no
message formats, no event names beyond those already canonized in
ARCHITECTURE.md, no classes, no schemas, no storage design. Confidence
scoring, assurance levels, retry policy, rollback policy, Kernel policy
integration, and operational behavior are explicitly out of scope — they
are VAE/02 (Assurance & Confidence) and VAE/03 (Kernel Integration)
territory (VAE/00 §11). Where this document is silent, VAE/00 governs. Where
VAE/00 speaks, this document refines and never contradicts.

---

## 1. Verification Model

**What verification is.** Verification is the architectural process of
producing independent, explainable evidence about whether an artifact
satisfies the contract, rules, and system state it claims to relate to
(VAE/00 §1, §4). It is a judging process, not a producing process: it
consumes a sealed artifact and declared rules, and emits an account of how
well the artifact holds up against them.

**What it attempts to prove.** For a given artifact: that it is structurally
valid, that it is internally coherent, that it coheres with the system state
and invariants it touches, and that nothing its contract requires is absent
(VAE/00 §4, responsibilities 2–4). The claim verification makes is always
scoped to *this artifact, against these rules, using these recorded
results* — never a claim about the world beyond what was checked.

**What it cannot prove.** Verification cannot prove that an artifact is
*good* in any sense beyond its declared contract; it cannot prove absence of
defects the rules do not test for; it cannot prove a producer's intent,
future behavior, or fitness for a use the contract never declared; and it
cannot prove anything about artifacts it never received. Verification proves
conformance to what was checkable, not truth in general. This ceiling is not
a defect to be engineered away — it is what keeps VAE-I8 (explainability)
honest: a verdict only ever claims what its evidence record can support.

**Why evidence production, not decision making.** VAE/00 §1 already fixes
the division: "Verification provides evidence. The Kernel decides." The
verification model exists to make that division precise at the level of
*what kinds of things get evidence produced about them* and *at what
granularity* — it does not touch the boundary itself, which is immutable
Phase 0 content.

**Verification vs. adjacent activities:**

| Activity | Relationship to verification |
|---|---|
| Execution | Produces the artifacts verification judges; execution changes system state, verification only observes it (VAE/00 §5, §9). An executor asking "did this work" is not verifying — it is self-reporting, which VAE/00 §1 names as the exact failure V1 committed (H3). |
| Reasoning | Produces artifacts (outcome records) that are among the least trustworthy inputs to verification (VAE/00 §3). Reasoning may appear *inside* a check as a governed evidence source (VAE/00 Principle 6), but that use is itself downstream of verification's own judgment, never a substitute for it. |
| Testing | A testing framework running a suite is execution — it produces a result. Verification is the act of treating that result as one item of evidence, weighing it against declared rules, and reaching a verdict. Selftests are inputs to verification, not verification itself (VAE/00 §5 — "Process spawning" belongs to Execution). |
| Validation | In everyday usage "validation" often means "confirm this is acceptable" — an outcome. Verification is the evidence-producing precursor to that outcome; the acceptance decision itself belongs to the Kernel (VAE/00 §1, §5). This document uses "verification" exclusively and avoids "validation" as a synonym for the reasons above. |
| Assurance | Assurance is the accumulated, evidence-derived confidence that spans possibly many verifications over time (VAE/00 §4 responsibility 5, glossary). A single verification act produces one verdict; assurance is a longer-lived property built from many such verdicts. Assurance semantics are VAE/02's subject — this document only establishes that verification is what assurance is built *from*. |

---

## 2. Verification Lifecycle

**Where it begins.** Verification begins the moment an artifact becomes a
candidate for gating — the earliest point at which the system could act on
the artifact in a way that would matter if the artifact were wrong (VAE/00
§2 "Verify everything that matters"). It does not begin at request
completion, and it does not begin only when a human or Kernel explicitly
asks; it begins wherever the system's own process produces something whose
acceptance would change durable state, system knowledge, or user-visible
outcome.

**Where it ends.** Verification of a given artifact ends when that artifact
receives a definite terminal verdict (VAE/00 §4 responsibility 7, VAE-I5).
It does not end when a request ends — a request may contain many artifacts,
each with its own verification lifecycle, some concluding long before the
request itself concludes.

**How it accompanies execution.** Verification is not a phase that follows
all execution; it is a companion process that runs alongside execution,
judging what execution has produced so far without waiting for execution to
finish producing everything. This is a direct consequence of VAE/00 §2
("Verification is continuous") and of the architectural position rule
(VAE/00 §3): verification sits after each reasoning/execution output
individually, not after the request as a whole.

**Why continuous, not a single gate at the end.** A request that only
verifies its final output defers all evidence production to the point of
maximum accumulated risk — every intermediate artifact the final output
depends on was accepted on credit. If any intermediate artifact was wrong,
the defect propagates silently through everything built on it, and the
single end-of-request check must somehow catch a compounded error it was
never designed to decompose. Verifying at each meaningful point instead
means every dependency a later artifact relies on already carries its own
verdict — trust composes from verified parts rather than being asserted
once over an unverified whole.

---

## 3. Event-Driven Verification

**Why verify after meaningful execution stages, not only at completion.**
A "meaningful execution stage" is any point where execution has produced
something durable-state-changing, knowledge-changing, or user-visible
enough to matter (VAE/00 §2). Verifying at each such point means a defect is
caught at the stage that produced it, where the evidence for *why* it is
wrong is freshest and most attributable. Deferring all verification to
request completion collapses this attribution: by the time verification
runs, ten stages may have built on the defective one, and the resulting
failure describes the symptom (the final artifact is wrong) rather than the
cause (which stage broke).

**Why never deferred to request completion.** VAE/00 §2 states trust is
"scoped to what was verified; new artifacts start at zero again." A design
that only verifies the final output cannot honor this — there would be
nothing granular to scope trust *to*. It would also violate VAE/00 §9's
"No unbounded computation of its own": a single end-of-request check that
must reconstruct and judge an entire request's worth of accumulated
artifacts is exactly the unbounded, un-scoped self-work the constraint
forbids. Bounded, stage-scoped verification is the only shape compatible
with VAE/00's determinism and boundedness constraints.

**How stage completion produces verification opportunities.** Each
meaningful stage's completion is, conceptually, an occasion where a new
verifiable artifact becomes available (VAE/00 §7 "Verification demand").
Verification does not search for work — it reacts to these occasions as
they arise (VAE/00 §9 "Event-driven... VAE reacts to bus events... it
polls nothing"). The stage itself decides nothing about verification; it
merely makes an artifact available for judgment. Whether and how densely
stages produce such occasions is a scoping/rules concern (VAE/00 §4
responsibility 1), not a lifecycle concern — this section fixes only that
the *opportunity* exists at every meaningful stage, not the *policy* for
which stages require it.

**Why this improves reliability.** Event-driven, per-stage verification
bounds the blast radius of any single defect to the stage that produced it,
keeps verdicts and their evidence temporally close to the artifact they
describe (supporting explainability, VAE/00 Principle 3), and keeps VAE's
own workload proportional to what actually happened rather than to the
whole shape of a request. It is the architectural expression of "assurance
is manufactured, not assumed" (VAE/00 §2) applied to *when* manufacturing
happens, not only to *whether* it happens.

---

## 4. Verification Scope

Verifiable artifact kinds, extending VAE/00 §12's glossary entry with the
justification for each:

| Artifact kind | What it is | Why VAE verifies it |
|---|---|---|
| Execution artifacts | Diffs, generated files, committed changes produced by Execution | These directly become durable state (VAE/00 §2 "Trust nothing"); unverified execution output is the shortest path to corrupting the system the moment it is accepted. |
| Reasoning artifacts | Sealed reasoning outcome records handed downstream by RO, judged against the output contract RO declared before invocation | RO explicitly hands these downstream *unjudged* (VAE/00 §3, RO/00 §10); reasoning is the least trustworthy artifact class in the OS (VAE/00 §3), so someone must grade it before it can be trusted — that someone is VAE. |
| Workflow artifacts | Plans from Capability Planning, prior to scheduling | A structurally invalid or incomplete plan propagates its defect into every step scheduled from it; catching it before scheduling is cheaper than catching it after (VAE/00 §4 responsibility 1, §5 "Planning, intent interpretation" boundary). |
| Integrated artifacts | Combinations of previously-verified pieces presented as a coherent whole (e.g., a set of diffs that together claim to satisfy one contract) | Individually-valid parts can still combine incoherently; consistency evaluation (VAE/00 §4 responsibility 3) exists precisely because no artifact is checked "in a vacuum when it claims relationships to things outside itself." |
| System state transitions | The claim that a change moved system state from one coherent condition to another without violating invariants the change touches | This is the concrete form consistency evaluation takes when the "state" an artifact touches is itself a moving target — the transition, not just the endpoint, is what coherence claims are about. |
| Selftest result sets | Delegated check outcomes returned by Execution | These are evidence Execution produced at VAE's request (VAE/00 §4 responsibility 6); VAE's role is interpreting them into verdict-relevant evidence, not re-running them. |

**What VAE never attempts to verify** (restating VAE/00 §5 at the scope
level, not duplicating its rationale):

| Never verified | Why it falls outside scope |
|---|---|
| Producer intent or reasoning process | Verification judges artifacts, not the mind or procedure that produced them — judging process instead of product would require VAE to trust or reconstruct something it has no standing over (VAE/00 §5 "Reasoning"). |
| Anything not sealed and referenceable | VAE consumes from Storage-backed references (VAE/00 §7); a live, mutating, or unrecorded target cannot be judged because it cannot be reconstructed later, breaking replayability (VAE/00 §9 "Sealed consumption"). |
| Future or hypothetical states | VAE-I8 requires every verdict to be explainable from its evidence record "without re-querying anything live"; a claim about the future has no recorded evidence to explain it from. |
| Value judgments outside declared rules | "Is this a good idea" beyond the artifact's declared contract is not a checkable claim; admitting it would reintroduce the honor-system subjectivity VAE/00 §1 exists to remove. |
| Anything requiring VAE to execute, retrieve, or assemble context itself | Out of scope by construction — those are Execution's, UMS's, and CM's authorities respectively (VAE/00 §5), not gaps in verification's ambition. |

---

## 5. Verification Levels

Five layers, ordered by what each presupposes from the one below it. The
decomposition is a taxonomy of *questions asked*, not a pipeline of *steps
executed* — VAE/00 §9 forbids VAE from owning any control loop, so nothing
below implies sequencing, blocking, or a fixed order across artifacts.

| Level | Purpose | Scope | Architectural responsibility | Relationship to neighbors |
|---|---|---|---|---|
| **Structural** | Is the artifact well-formed on its own terms? | The artifact in isolation: required fields present, declared shape honored, internal well-formedness | VAE/00 §4 responsibility 4 (completeness) and part of responsibility 2 (correctness) at the artifact's own boundary | Presupposes nothing beyond the artifact itself; every higher level assumes structural soundness as a precondition — a structurally invalid artifact has nothing further worth asking about it. |
| **Execution** | Did the delegated checks that ran against this artifact report success? | Interpretation of selftest/executable-check results Execution returned | VAE/00 §4 responsibility 6 (delegated check orchestration and interpretation) | Consumes Execution's results as sealed evidence (VAE-I3); feeds Semantic level as one evidence source among several, never as the whole verdict on its own. |
| **Semantic** | Does the artifact satisfy its declared contract and rules in substance, not just in shape? | Correctness against the artifact's own declared contract (VAE/00 §4 responsibility 2) | Core correctness evaluation | Builds on Structural (a malformed artifact cannot be meaningfully judged for contract satisfaction) and may draw on Execution-level evidence (a selftest result can be one input to a semantic judgment); does not itself reach outside the artifact to the wider system. |
| **Cross-artifact** | Does the artifact cohere with other artifacts and system state it claims relationships to? | Consistency evaluation across artifact boundaries — invariant compliance, dependency coherence, integrated-artifact coherence (§4) | VAE/00 §4 responsibility 3 (consistency evaluation) | Presupposes each individual artifact already cleared Semantic; a coherence claim between two artifacts is meaningless if either artifact is independently unsound. |
| **System** | Does accepting this artifact leave the system's declared invariants intact across the transition? | System state transitions (§4) — the broadest lens, judging the move itself, not only the endpoint | The system-state-transition artifact kind (§4), read against invariants the transition touches | The outermost level; it can only be asked once every artifact contributing to the transition has cleared the levels beneath it, but asking it is still a question about evidence already produced, never a re-execution of anything. |

**Why this decomposition.** Each level answers a narrower question than the
one above it, and each higher-level question is meaningless to ask before
the lower one is settled — a coherence claim (Cross-artifact) presupposes
contract satisfaction (Semantic), which presupposes well-formedness
(Structural). This ordering is why the levels compose into layered
*evidence*, not into a required *execution order*: nothing prevents VAE from
holding partial evidence at multiple levels simultaneously for different
artifacts, since each level's applicability is a property of the question,
not a clock. Execution-level sits beside Structural/Semantic rather than
strictly beneath them because it is evidence-shaped (a result VAE
interprets) rather than judgment-shaped (a question VAE asks directly) —
it is consumed at whichever level(s) its content is relevant to.

---

## 6. Evidence Model

**What constitutes evidence.** Evidence is any recorded, attributable
observation that bears on whether an artifact satisfies a declared rule —
a structural check's finding, a delegated check's result, a consistency
comparison's outcome. VAE/00 §4 responsibility 8 and §12 already fix the
durability and immutability of the *record*; this section fixes what
counts as a *contributor* to that record. An observation is evidence only
if it is attributable to a specific rule and a specific artifact reference
— an unattributed impression is not evidence, it is exactly the "vibes"
VAE/00 §2 rules out ("Evidence before confidence").

**Where evidence originates.** Evidence originates from checks VAE performs
directly against declared rules (Structural, Semantic, Cross-artifact,
System-level questions, §5) and from delegated check results Execution
returns (Execution-level, §5). Both are equally admissible; origin does not
rank evidence — only what the evidence attests and against which rule
determines its weight, which is VAE/02's confidence-derivation territory.

**Why explainable.** VAE/00 Principle 3 already fixes that verdicts must be
explainable; the evidence model is the mechanism that makes this possible
at all. A verdict is explainable exactly to the degree that every
contributing observation can be traced to a rule, an artifact reference,
and a result. Evidence that cannot be traced this way cannot support an
explainable verdict, and VAE/00 §9 ("Explainable evidence, always") forbids
introducing any check or mechanism whose contribution cannot be stated this
way.

**Why independent evidence increases trust.** A single check answers one
narrow question under one method; if that method has a blind spot, the
verdict inherits it undetected. Independent evidence — observations
produced by different checks, different rules, or different evidence
sources bearing on the same claim — narrows the space in which a defect
could hide from every contributing observation at once. This is the
evidentiary expression of VAE/00 §1's separation principle applied
*within* verification itself: no single check is trusted merely because it
ran, the same way no producer is trusted merely because it produced.

**Why accumulation beats binary validation.** A binary pass/fail per check
discards the difference between "one weak signal barely passed" and "many
independent signals all agree." Treating evidence as something that
accumulates — rather than as a single gate that either opens or does not —
preserves that difference for whoever reads the evidence record later,
and is the necessary substrate beneath confidence derivation (VAE/00 §4
responsibility 5), even though the derivation mechanism itself is VAE/02's
subject. This document fixes only that evidence *accumulates* as a
recorded body, not how it is weighed into a number.

---

## 7. Verification Progression

Verification is not one act per artifact; it is a progression that mirrors
how execution itself unfolds:

**execution → verification → additional evidence → further verification →
integrated verification → complete.**

- An execution stage completes and produces an artifact (§3).
- Verification runs against that artifact at whichever level(s) apply (§5),
  producing evidence (§6) and, where the artifact is independently gate-able,
  a verdict.
- Later execution may produce further artifacts that relate to the first —
  a dependent diff, a further reasoning outcome, a further delegated check.
  Each contributes additional evidence, some of it about the same earlier
  artifact (e.g., a dependent's selftest result bearing on whether the
  original change was sound) and some about the new artifact itself.
- This additional evidence supports further verification — Cross-artifact
  and eventually System-level questions (§5) that could not have been asked
  before the dependent artifacts existed.
- Where a request's artifacts together form an integrated artifact (§4),
  integrated verification asks the coherence question over the accumulated
  individually-verified pieces.
- The progression is complete for a given scope when every artifact in that
  scope holds a definite terminal verdict (VAE-I5) and every applicable
  cross-artifact and system-level question that scope's rules require has
  been asked.

**Why cumulative, not isolated.** Each stage of the progression consumes
evidence already recorded from earlier stages rather than re-deriving it —
Cross-artifact questions build on Semantic verdicts already reached;
System-level questions build on Cross-artifact conclusions already reached.
Treating each stage as isolated would mean either re-verifying settled
ground (violating VAE/00 §9's bound on self-work) or reasoning about later
artifacts with no memory of what was already established about their
dependencies (breaking the very coherence Cross-artifact and System levels
exist to judge). Cumulative progression is what lets verification stay
bounded per stage (§3) while still being able to answer questions that only
make sense in light of everything verified so far.

---

## 8. Verification Independence

VAE/00 §1 and Principle 2 already fix independence as foundational; this
section states what it means at the model level, not a new rule.

**Independence from Plugin Runtime.** VAE judges plugin output without
loading, running, or trusting the plugin that produced it (VAE/00 §5, §8).
A verification model that needed to execute or introspect a plugin to judge
its output would have re-created the exact coupling VAE/00 §5 rules out —
verifying a plugin's output must not require running the plugin.

**Independence from the Reasoning Orchestrator.** VAE grades RO's outcome
records against the output contracts RO itself declared, but never
influences in-flight reasoning, and RO never grades its own outcomes
(VAE/00 §3, §8; RO/00 §10 restated). This is a mutual non-interference
pact, not a one-directional courtesy: RO's independence from VAE matters as
much as VAE's independence from RO, because either direction of influence
would let the producer shape the standard it is judged by.

**Independence from the Execution Kernel.** VAE's verdicts are decision
input the Kernel consumes; the Kernel's policy pressure (throughput,
urgency, retry budgets) never reaches back into what counts as a passing
verdict (VAE/00 §5, Principle 1). If Kernel pressure could bend a verdict,
"pass" would stop meaning "the evidence supports this" and start meaning
"the Kernel needed this" — collapsing the entire reason verification exists
as a separate authority.

**Objectivity and avoiding circular validation.** A verification model is
circular the moment any component judged by VAE can also shape the rules,
data, or process VAE uses to judge it. This is why capability
characteristics, verification rules, and evidence weighing are declared
data owned by VAE (VAE/00 §4 responsibility 1) rather than parameters a
producer supplies at judgment time — a producer that could tune its own
pass criteria has, functionally, graded its own work.

**Separation of concerns.** Each of the three relationships above is a
restatement of the same discipline at a different seam: VAE never shares
process, state, or incentive with anything it judges (VAE/00 Principle 2).
The verification model adds nothing here except naming the seams explicitly
so that "independence" is checkable at each boundary individually, not only
assertable as a global property.

**Why verification never validates itself.** If VAE's own verdicts could be
inputs back into VAE's own rules — a passing verdict lowering the bar for
the next check on the same artifact, for instance — trust would compound
without new evidence ever being produced, exactly the "optimism" VAE/00 §1
identifies as the failure of self-graded work. Every verdict VAE reaches
must trace to evidence about the *artifact*, never to VAE's own prior
conclusions treated as evidence about itself.

---

## 9. Verification Boundaries

Expanding VAE/00 §5's non-responsibilities into the shape they take
specifically within the verification model:

| Boundary | What it means here | Why it exists |
|---|---|---|
| Observes | Verification reads artifacts, rules, and delegated results (VAE/00 §7) — it is a consumer of state, never a mutator of it. | An observer that could also change what it observes could shape its own findings; observation-only is what makes a finding independent of the observer's convenience. |
| Evaluates | Verification's active content is entirely judgment against declared rules (§5, §6) — comparing, checking, weighing recorded evidence. | Evaluation is the whole of VAE's work product; anything beyond evaluating would be VAE doing someone else's job under cover of a verdict. |
| Reports | Verification's output is the evidence record and verdict (VAE/00 §4 responsibilities 7–8) — a statement handed to the Kernel and to Storage, not an action taken on the artifact or the system. | Reporting is what keeps evidence and decision separable (VAE/00 Principle 1); a report cannot itself change anything, which is exactly why it can be trusted as a report. |
| Never executes | No verification-model construct spawns, runs, or drives execution of anything — every executable check is delegated to Execution (VAE-I3). | This is the direct V1-H4 fix (VAE/00 §5, §9): the moment verification runs producer-shaped code in its own process, a hang or crash in that code becomes a hang or crash in the verifier. |
| Never repairs | Verification never edits, patches, or supplies a corrected version of an artifact it finds deficient (VAE-I4). | A verifier that repairs has stopped reporting on the artifact and started producing a new one — that new artifact would need its own independent verification, which the repairing verifier cannot supply for its own work. |
| Never retries | Verification does not re-run a check "to see if it passes this time," and does not decide that an artifact should be re-attempted. | Retry is an execution-policy decision (VAE/00 §5, "Execution policy decisions"); a verifier that retries is quietly making the Kernel's decision for it and laundering that decision as a verdict. |
| Never rewrites outputs | Verification never changes an artifact's content, framing, or presentation to make it pass, nor summarizes/transforms it into something else. | Rewriting an output under judgment is a stronger form of "never repairs" — it destroys the very evidence (the original artifact) that any later audit would need to check the verdict against (VAE/00 Principle 3, replayability). |

---

## 10. Architectural Invariants (VAE-M)

New Phase 1 invariants. These extend VAE-I1–I12 (VAE/00 §13) and do not
restate them; each is binding on every later VAE phase per VAE/00's phase
discipline (§11).

1. **VAE-M1** — Every meaningful execution stage (§3) produces an
   independently verifiable artifact; no stage may be architected such that
   its output is only judgable bundled with later stages. *Prevents:*
   accumulation of unverifiable, un-attributable risk that only surfaces at
   request completion (§2).
2. **VAE-M2** — Evidence, once recorded, never decreases in fidelity: a
   later observation may add to or supersede an evidence item for cause, but
   no process may quietly weaken, generalize, or drop detail from evidence
   already recorded. *Prevents:* evidence records drifting toward
   unexplainable summaries over the life of a progression (§6, §7),
   undermining VAE-I8.
3. **VAE-M3** — A verification act never depends on a future stage's
   outcome to reach its verdict on the present artifact. *Prevents:*
   circular or premature verdicts that silently assume a not-yet-produced
   artifact will turn out fine — the exact shortcut that would make "verify
   continuously" collapse back into "verify once at the end" (§2, §3).
4. **VAE-M4** — Independently produced evidence for the same claim remains
   distinguishable in the evidence record; merging evidence into a combined
   judgment never destroys the ability to see which independent source said
   what. *Prevents:* loss of the very independence (§6, §8) that gives
   accumulated evidence more trust than a single source — indistinguishable
   evidence cannot be checked for whether it was truly independent.
5. **VAE-M5** — Integrated verification (§7) never destroys or supersedes
   the individual verification history of the artifacts it integrates; the
   integrated verdict is additive to, not a replacement for, the
   per-artifact verdicts beneath it. *Prevents:* a system-level or
   cross-artifact pass being used to retroactively excuse re-litigating (or
   erasing the record of) a component artifact's own verdict.
6. **VAE-M6** — Verification levels (§5) are asked in a fixed dependency
   order per artifact — a higher level's question is never answered before
   its prerequisite lower-level questions are settled for the same artifact
   — but nothing requires a fixed order *across* artifacts or across the
   system. *Prevents:* meaningless higher-level judgments (e.g., a coherence
   claim about a structurally invalid artifact) while preserving the
   event-driven, non-blocking topology of §3.
7. **VAE-M7** — Every verification act declares which artifact kind (§4) and
   which level (§5) it addresses; no evidence item may be recorded without
   both being attributable. *Prevents:* evidence that cannot be traced back
   to a specific question being asked — the precondition for VAE-I8's
   explainability at the level of individual evidence items, not only whole
   verdicts.

---

## 11. Failure Philosophy

Verification distinguishes several outcomes that a coarser model would
collapse into a single "failed" bucket. This section names the
distinctions; it does not discuss what happens next (retry, rollback,
escalation are VAE/00 §5 non-responsibilities and VAE/03 territory).

| Outcome | Meaning | How it differs from the others |
|---|---|---|
| **Execution failure** | The artifact-producing process itself did not complete successfully (a crash, a timeout, a process error reported by Execution). | This is a fact about *execution*, reported to VAE as one input; VAE does not cause it and does not need to independently re-establish it — it is admissible evidence, not a verification outcome (§6). |
| **Verification failure** | The artifact completed, was judged against declared rules at the applicable level(s), and the evidence does not support satisfaction of those rules. | This is VAE's own definite negative verdict (VAE-I5, VAE-I6) — a positive, evidence-backed conclusion that the artifact is not trustworthy, not an absence of information about it. |
| **Evidence insufficiency** | Too little evidence exists to reach any verdict — required checks did not run, delegated results never arrived, or the artifact's scope was never fully covered. | Distinct from verification failure: the artifact is not *known* to be wrong, it is *unassessed*. VAE-I5 and VAE/00 §9 ("Definite terminal verdicts... every failure mode of VAE itself... must degrade to a definite fail") require that this state still resolve to a definite terminal verdict rather than remaining open — insufficiency is a reason for a fail verdict, not an exemption from producing one. |
| **Inconclusive verification** | Applicable checks ran and returned results, but the results do not, even combined, settle the question the level was asking (e.g., a check whose own output is ambiguous by design). | Distinct from evidence insufficiency: evidence exists and is complete by scope, but its content does not resolve the claim. Also resolves to a definite terminal verdict per VAE-I5 — "inconclusive" describes *why* the evidence record looks the way it does, never a third verdict state alongside pass/fail. |
| **Contradictory evidence** | Two or more independently sourced evidence items (VAE-M4) bear on the same claim and disagree. | Distinct from all of the above: evidence is neither missing nor ambiguous individually — it actively conflicts. The evidence record must preserve both contradicting items distinguishably (VAE-M4) rather than silently resolving the conflict by discarding one side; how a verdict is derived from contradictory evidence is a deterministic-weighing concern for VAE/02, not a model concern here. |

These five are conceptually disjoint causes that can each lead to the same
two terminal verdict values (VAE-I5, VAE-I6): the *reason* a verdict is
`verify.failed`, or the *reason* it took the evidence it took to reach
`verify.passed`, is always one of these — and always recorded in the
evidence record (VAE/00 Principle 3) so the distinction is never lost by
the time a human or the Kernel reads the verdict.

---

## 12. Phase Summary

**Now fully defined by this document:**

- Verification as a distinct architectural process, differentiated from
  execution, reasoning, testing, validation, and assurance (§1).
- The verification lifecycle's start and end points, and why verification
  is continuous rather than end-of-request (§2).
- Why verification is event-driven per meaningful execution stage rather
  than deferred to completion (§3).
- The taxonomy of verifiable artifact kinds and what falls outside
  verification's scope entirely (§4).
- A five-level decomposition of verification questions — Structural,
  Execution, Semantic, Cross-artifact, System — with each level's purpose,
  scope, and relationship to its neighbors (§5).
- The evidence model: what counts as evidence, why it must be explainable,
  why independent evidence increases trust, and why evidence accumulates
  rather than resolving as a single binary gate (§6).
- Verification progression across a request's life, and why it is
  cumulative (§7).
- Verification independence from Plugin Runtime, RO, and the Kernel, stated
  at the model level (§8).
- The observe/evaluate/report boundary and the four explicit prohibitions —
  never executes, never repairs, never retries, never rewrites outputs
  (§9).
- Seven new Phase 1 invariants (VAE-M1–M7) extending VAE-I1–I12 (§10).
- A five-way failure taxonomy distinguishing execution failure,
  verification failure, evidence insufficiency, inconclusive verification,
  and contradictory evidence (§11).

**Intentionally deferred**, per the VAE/00 §11 roadmap:

- Confidence derivation semantics, proportional-depth policy, and handling
  of nondeterministic evidence sources — **Phase 2 (Assurance &
  Confidence)**.
- How contradictory or insufficient evidence resolves into a specific
  verdict weighting, assurance levels, and retry/rollback policy — **Phase
  2 and Phase 3**.
- The verdict/evidence flow to Kernel and Scheduler enforcement, gate
  topology, and the limbo-prevention failure-mode contract at the
  integration level — **Phase 3 (Kernel Integration)**.
- Delegation lifecycle detail with Execution, event choreography,
  persistence mechanics, telemetry shape, and performance envelope —
  **Phase 4 (Operational Architecture)**.
- Full event canon, Experience trusted-knowledge integration detail, and
  cross-phase invariant scanning — **Phase 5 (System Integration)**.

This document introduces no algorithm, interface, event name, or storage
design, and settles no question VAE/00 already settled. Every rule above
traces to a VAE/00 responsibility, principle, or constraint it refines.
