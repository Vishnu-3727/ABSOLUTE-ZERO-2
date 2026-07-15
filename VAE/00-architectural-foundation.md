# Verification & Assurance Engine (VAE) — Phase 0: Architectural Foundation

Status: authoritative foundation for all VAE design phases. Architecture only — no
algorithms, no interfaces, no modules, no APIs, no data structures, no event names
beyond those already canonized in ARCHITECTURE.md. Later VAE phases refine within
these boundaries; contradictions of this document require errata here, not silent
divergence.

Lineage: this document expands `COMPONENTS/verification.md` into a full design
contract. Everything that component sheet fixes (verdicts as events, unskippable
gates via Law 4, delegation of all execution via Law 3, the V1-H3 and V1-H4
lessons) remains binding. Where this document says more, it refines; where it
would say less, the component sheet still holds.

---

## 1. Mission

The Verification & Assurance Engine independently validates important execution
artifacts before the system treats them as trustworthy. It evaluates
**correctness** (does the artifact satisfy its declared contract and rules),
**consistency** (does it cohere with the system state and invariants it touches),
**completeness** (is anything the contract requires absent), and **confidence**
(how strong is the accumulated evidence). Its product is **evidence**, never
action: verdicts and evidence records that the Execution Kernel and Scheduler
enforce.

Verification exists separately from execution and reasoning because a system in
which the doer grades its own work has no assurance at all — it has optimism.
V1 proved this concretely: the honor-system verifier was bypassed and the LLM
committed over a FAIL (hazard H3). Reasoning engines are nondeterministic and
unaccountable by nature; execution is busy and self-interested by role. Only a
component that neither produced the artifact nor profits from its acceptance can
say something trustworthy about it. Separation is therefore not an organizational
preference but the precondition for the word "assurance" meaning anything.

The division of authority is permanent and one-directional:

> **Verification provides evidence. The Kernel decides.**

VAE never continues, retries, rolls back, escalates, or terminates anything. It
answers "is this trustworthy, and here is why" — the Execution Kernel alone
answers "so what do we do."

**Flow reconciliation.** The linear pipeline (Kernel → … → Reasoning Engine →
Verification → Experience & Knowledge Store) is the conceptual question order,
not topology. ARCHITECTURE.md's hub/event topology stays authoritative, as
already ruled for CP/00 §1, WS/00, and RO/00 §1. "Verification sits after the
Reasoning Engine" means verification is the question asked after reasoning
produces output, not that a dedicated pipe connects them.

---

## 2. Design Philosophy

| Tenet | Meaning |
|---|---|
| Trust nothing | No artifact is trustworthy because of who produced it. Reasoning output, plugin output, plan, diff — all arrive with zero standing. Provenance is evidence *about* an artifact, never a substitute for verifying it. |
| Verify everything that matters | Every artifact whose acceptance changes durable state, system knowledge, or user-visible outcome passes a gate. Verification depth is proportional to consequence — a matter of rules-as-data, not of skipping the gate. |
| Evidence before confidence | Confidence is never asserted, estimated, or vibes; it is derived from accumulated evidence. An artifact with no evidence has no confidence, and "no confidence" is a definite, reportable state — not a default pass. |
| Deterministic verification whenever possible | Identical artifact + identical rules + identical delegated check results → identical verdict, always (Law 6). Nondeterministic checks may exist as evidence sources, but the mapping from evidence to verdict is deterministic. A nondeterministic verdict is a defect. |
| Verification is independent | VAE shares no fate, no state, and no incentive with any producer of artifacts it judges. It runs no producer code in its own process (Law 3, V1-H4), holds no stake in throughput, and cannot be lobbied by the component awaiting its verdict. |
| Verification is continuous | Verification is not a single end-of-line ceremony. Artifacts are verifiable at every stage the system declares checkable — plans before scheduling, diffs before commit, reasoning outcomes before use, selftests after change. Trust, once granted, is scoped to what was verified; new artifacts start at zero again. |
| Explainable assurance | Every verdict carries structured reasons reconstructible by a human or a downstream component. A bare pass/fail without evidence is a defect. "Why did the gate close" must never require archaeology. |
| Definite verdicts | Every gated item receives a terminal verdict — pass or fail with reasons. Limbo is forbidden; enforcers treat a missing verdict as *not passed*, and VAE guarantees it never goes silent (a hung delegated check becomes a definite fail, per V1-H4). |

The coherent philosophy these tenets form: **assurance is manufactured, not
assumed**. The system's trust in any artifact is exactly the evidence VAE has
produced about it — no more, no less, and never on credit.

---

## 3. Architectural Position

In the conceptual question order, VAE sits **after the Reasoning Engine** and
**before the Experience & Knowledge Store**.

**Why after the Reasoning Engine.** Reasoning output is the least trustworthy
artifact class in the operating system: nondeterministic, unaccountable, and
produced under the quarantine (CP/03 §9, RO/00 §8). RO hands outcomes downstream
*unjudged* by explicit ruling (RO-I / RO §10: "RO never grades outcomes;
Verification never edits RO artifacts"). Someone must grade them; VAE is that
someone. Placing verification before reasoning would be incoherent — there would
be nothing yet to verify. Placing it inside reasoning would collapse the
producer/judge separation that Section 1 establishes as the point of the
subsystem.

**Why before the Experience & Knowledge Store.** Experience distills lessons,
priors, and reusable knowledge from execution history. If it learned from
unverified execution, every defect would compound: a wrong-but-unverified
outcome becomes a prior, the prior biases future necessity decisions and plans,
which produce more wrong outcomes, which become stronger priors. That is a
knowledge-poisoning feedback loop, and it is the single most dangerous failure
mode of a learning system. The permanent rule is therefore:

> **Experience never learns from unverified execution. Only verified knowledge
> becomes trusted system knowledge.**

VAE is the membrane between "things that happened" and "things the system
believes". Unverified history may be retained as raw episodic record, but it
enters the trusted knowledge path only through a VAE verdict.

**Position relative to enforcement.** VAE is upstream of no one and downstream
of no one in authority terms: it is a peer service on the bus whose verdicts the
Kernel and Scheduler enforce (Law 4). The only edge from a step to
`task.completed`/commit passes through `verify.passed`; that edge is owned by
the enforcers, not by VAE.

---

## 4. Responsibilities

| # | Responsibility | Architectural meaning |
|---|---|---|
| 1 | Verification model ownership | VAE owns the mapping from artifact type to required checks: which checks a plan, diff, artifact, reasoning outcome, or selftest result must satisfy. The mapping is rules-as-data, versioned, and the sole authority on "what does verified mean for this kind of thing". |
| 2 | Correctness evaluation | Judging whether an artifact satisfies its declared contract and rules — structural validity of plans, invariant compliance of diffs (acyclic layering, selftest law), contract conformance of reasoning outcomes against the output contract RO declared before invocation. |
| 3 | Consistency evaluation | Judging whether an artifact coheres with the system state and invariants it touches — no artifact is checked in a vacuum when it claims relationships to things outside itself. |
| 4 | Completeness evaluation | Judging whether everything the contract requires is present — missing sections, missing dependents, missing selftests are findings, not silence. |
| 5 | Confidence derivation | Deriving a confidence assessment from accumulated evidence — which checks ran, at what depth, with what results. Confidence is an output computed from evidence, never an input asserted by a producer. Its semantics are Phase 2's subject; that it exists and is evidence-derived is fixed now. |
| 6 | Delegated check orchestration | Deciding *which* selftests and executable checks are required (scoped via repository knowledge to changed + dependent units, never whole-repo by default), requesting their execution from Execution, and interpreting the results. VAE decides what runs; Execution runs it (Law 3). |
| 7 | Verdict production | Emitting a definite terminal verdict per gated item — `verify.passed` / `verify.failed` with structured reasons — as first-class events on the bus. Verdict semantics are VAE's to define; verdict enforcement is not. |
| 8 | Evidence records | Producing the durable, explainable record behind every verdict: what was checked, against which rules version, with what results, deriving what confidence. Persisted via Storage; immutable once emitted. |
| 9 | Assurance telemetry | Emitting verification activity, outcomes, latency, and coverage as telemetry in Observability's one schema, so assurance itself is measurable. |

---

## 5. Non-Responsibilities

| Never VAE's | Owner | Why the boundary exists |
|---|---|---|
| Execution policy decisions (continue, retry, rollback, escalate, terminate) | Execution Kernel | The moment the judge also sentences and schedules, verification pressure becomes throughput pressure and independence dies. Evidence and decision must be separable to be auditable. |
| Gate enforcement | Kernel / Scheduler (Law 4) | VAE produces verdicts; structural unskippability lives in the enforcers' edges. If VAE enforced its own verdicts it would need execution authority, violating the previous row. |
| Process spawning / sandboxing | Execution (Law 3) | The core V1-H4 fix: a hanging check ran inside the verifier and crashed it. Delegation makes a hung check an ordinary `process.timeout` result — the verifier stays alive to fail it. |
| Planning, intent interpretation | Capability Planning | A verifier that shapes plans pre-approves its own future workload; producer/judge separation must hold in both directions. |
| Scheduling, ordering, dispatch | Workflow Scheduler | Verification order is demand-driven by events; deciding *when* work runs is control, and VAE holds no control. |
| Memory, retrieval, similarity | Unified Memory System (Law 2) | VAE consumes repository knowledge for check scoping; it never indexes, scans, or retrieves on its own — the path that caused V1's memory chaos. |
| Context assembly | Context Manager | One assembler in the OS; VAE is not a second one. |
| Plugin execution, tool binding | Plugin Runtime | Verifying a plugin's output must not require trusting — or running — the plugin. |
| Reasoning | Reasoning Engines (via RO) | If VAE reasons to verify, its verdicts inherit the untrustworthiness it exists to contain. Any reasoning-assisted check is an evidence *source* obtained through RO's gate like every other invocation, never a verdict authority (see §6, Principle 6). |
| Modifying artifacts under judgment | The artifact's producer | VAE is read-only over everything it judges — including reasoning outputs and plugin outputs. A judge that edits the evidence has destroyed it. Findings are reported; repair is someone else's decision (the Kernel's) and someone else's work. |
| Request lifecycle ownership | Kernel / Request State Manager | VAE observes and judges moments in a request's life; it never owns or advances the lifecycle. |
| Learning, prior distillation | Experience & Knowledge Store | VAE certifies what may be learned from; it does not do the learning. Judge of admissibility, not author of lessons. |
| Durable writes | Storage | Single-writer law. Evidence records and verdicts persist via Storage; VAE has no local durable path. |
| Bus transport | Communication | VAE publishes and consumes; it never carries. |

---

## 6. Architectural Principles

1. **Verification produces evidence; it never controls execution.** The entire
   value of VAE is that its output is decision-*input*. The moment a verdict
   directly moves the machine, verification has become policy and the Kernel has
   a rival. This principle prevents the two-headed-authority failure where
   nobody can say which component decided to halt.

2. **Verification must remain independent.** No shared process, shared fate, or
   shared incentive with any producer. Independence is what makes a pass mean
   something; a verifier that producers can crash (V1-H4), bypass (V1-H3), or
   pressure is decoration. Every future design choice is tested against "could a
   producer influence its own verdict through this."

3. **Verification must be explainable.** Verdicts without reasons cannot be
   audited, appealed to the Kernel's policy, or learned from. Explainability is
   also the anti-drift mechanism: rules-as-data plus structured reasons mean the
   difference between two verdicts is always attributable to artifact, rules
   version, or check results — never to mood.

4. **Confidence is derived from evidence.** Nothing may inject confidence from
   outside — not producer self-scores, not reasoning-engine self-reports, not
   defaults. This prevents the cheapest attack on any assurance system:
   asserting trustworthiness instead of demonstrating it.

5. **Deterministic verification whenever possible.** The verdict function is
   deterministic over declared inputs (Law 6). This is what makes verification
   replayable, disputable, and testable — and what prevents "run it again until
   it passes" from being a strategy.

6. **Nondeterministic evidence never becomes verdict authority.** Where a check
   itself is nondeterministic (a reasoning-assisted review, a flaky
   environment), its output enters as one evidence item, weighed by
   deterministic rules — and any reasoning it requires crosses RO's quarantine
   gate like all reasoning in the OS (RO-I2). This keeps the quarantine total
   and keeps VAE's own core deterministic.

7. **Only verified knowledge becomes trusted system knowledge.** The membrane
   principle of §3: the Experience & Knowledge Store's trusted path admits only
   VAE-verdicted material. This prevents knowledge poisoning — the compounding
   of unverified error into system belief.

8. **Definite verdicts; absence is failure.** Every gated item terminates in an
   explicit verdict; enforcers treat missing verdicts as not-passed. This
   closes the "silent skip" hole: no path exists where an item is treated as
   verified because verification never got around to it.

9. **Assurance is proportional, by rules, not by exception.** Verification
   depth scales with consequence, but the scaling lives in the versioned
   rules-as-data, never in ad-hoc judgment at check time. This keeps
   proportionality itself auditable.

---

## 7. Inputs and Outputs

Conceptual level only; formats, schemas, and event payloads are later phases'
work (and the already-canonized events `verify.passed`/`verify.failed`,
`plan.created`, `process.*`, `write.committed` stay binding from the hub doc).

**Consumes:**

| Input | Origin | Nature |
|---|---|---|
| Verifiable artifacts | Producers, by Storage-backed reference | Plans, diffs, generated artifacts, reasoning outcome records (with RO's declared output contracts), plugin outputs — read-only |
| Verification rules | Config / Storage, versioned | The artifact-type → required-checks mapping and check definitions, as data |
| Delegated check results | Execution | Selftest and executable-check outcomes, including timeout/failure as ordinary results |
| Repository knowledge | Unified Memory System | Dependency context for scoping which selftests a change requires |
| Verification demand | Bus events | The signals that something gated awaits judgment |

**Produces:**

| Output | Nature |
|---|---|
| Verdicts | Definite, terminal, per gated item, as first-class events with structured reasons |
| Evidence records | Durable (via Storage), immutable, reconstructible: checks run, rules version, results, derived confidence |
| Confidence assessments | Evidence-derived measures attached to verdicts (semantics defined in Phase 2) |
| Assurance telemetry | Verification activity, coverage, and latency in Observability's one schema |

**Never crosses the boundary:** modified artifacts (VAE is read-only over what
it judges); execution commands or lifecycle transitions (VAE controls nothing);
confidence accepted from outside (Principle 4); spawned processes (Law 3).

---

## 8. Relationships with Other Subsystems

| Subsystem | Relationship | What NEVER crosses |
|---|---|---|
| Execution Kernel | The sole consumer of verdicts as decision input. Kernel enforces gates (Law 4) and owns every continue/retry/rollback/escalate/terminate decision. VAE informs; Kernel decides. | Policy authority into VAE; verdict authorship into Kernel. The Kernel may decide *against* a failed artifact's acceptance forever, but it cannot mint a pass. |
| Request State Manager | VAE's verdicts and evidence are observable moments in a request's recorded life; RSM tracks state, VAE judges artifacts. | Lifecycle ownership into VAE; verdict production into RSM. Telemetry is never a control edge back (RSM-I15 discipline). |
| Unified Memory System | Supplier of repository/dependency knowledge for check scoping (Law 2: UMS is the sole retrieval authority). | VAE-side indexing, scanning, or similarity search; UMS opinion on verdicts. |
| Context Manager | Effectively no seam. CM assembles Request Memory for reasoning; VAE does not consume assembled context and never asks CM for any. If a check needs to know what context an invocation received, that arrives inside the sealed outcome record, not via CM. | Context assembly requests from VAE; verification duties into CM. |
| Capability Planner | Producer whose plans are verifiable artifacts (structural/quality validity before scheduling). | Plan shaping by VAE; verification-rule authorship by CP. CP never pre-certifies its own plans. |
| Workflow Scheduler | Enforcement peer: Scheduler's edges make gates structurally unskippable; it dispatches nothing past a missing or failed verdict. | Scheduling authority into VAE; verdict production into WS. |
| Plugin Runtime | Producer-side infrastructure whose outputs (via Execution/Storage) are verifiable artifacts. VAE judges plugin output without loading, running, or trusting plugins. | Plugin execution by VAE; plugin self-verdicts into the gate. |
| Reasoning Orchestrator | Upstream neighbor in the question order. RO hands outcome records downstream unjudged; VAE grades them against the output contracts RO declared. Mutual non-interference is already ruled: RO never grades outcomes; Verification never edits RO artifacts (RO/00 §10). | VAE influence on in-flight reasoning decisions; RO influence on verdicts. Reasoning-assisted checks go *through* RO's gate as ordinary governed invocations. |
| Reasoning Engine | No direct seam, ever. Engines are reached only through RO (RO-I2); VAE sees engine output only as sealed outcome records. | Direct engine invocation by VAE; engine self-assessment as verdict input (it may exist inside the record as data — it carries no authority). |
| Experience & Knowledge Store | Downstream beneficiary of the membrane: its trusted-knowledge path admits only verified material (§3). Experience may learn *about* verification (which checks catch what) from VAE's telemetry and evidence records like any consumer. | Unverified execution into trusted knowledge; learning duties into VAE; priors as verdict input outside the versioned rules discipline. |
| Storage / Communication / Observability (substrate) | Storage persists evidence and verdict records (single writer); Communication carries all VAE events; Observability consumes all VAE telemetry (Law 7). | Local durable writes; private channels; unmeasured verification activity. |

---

## 9. Architectural Constraints

Binding on every future phase.

| Constraint | Consequence |
|---|---|
| Event-driven | VAE reacts to bus events and emits bus events; it polls nothing, owns no scheduler, and holds no control loop over other components. |
| No execution policy | No VAE construct may encode continue/retry/rollback/escalate/terminate semantics. If a future design needs "what should the system do about this verdict," that design belongs to the Kernel. |
| No modification of judged artifacts | Read-only over reasoning outputs, plugin outputs, plans, diffs — everything. Findings describe; they never patch. |
| No process spawning | Every executable check runs in Execution; a VAE design that runs producer code in-process is a defect regardless of convenience (V1-H4). |
| Deterministic verdict function | Same artifact + same rules version + same delegated results → same verdict and same evidence record. Nondeterminism is confined to evidence sources and weighed deterministically. |
| Explainable evidence, always | No check, rule, or confidence mechanism may be introduced whose contribution to a verdict cannot be stated in the evidence record. |
| Definite terminal verdicts | Every gated item ends in pass or fail; every failure mode of VAE itself (timeout, crash, missing rule) must degrade to a definite fail or a loud absence the enforcers treat as fail — never to an implicit pass. |
| Modular checks, rules as data | New artifact types, checks, and depth policies arrive as versioned rules/data and bounded check modules — never as architectural change. |
| Vendor / model / implementation independence | Nothing in VAE assumes a provider, a model, a language, or a prompt concept (same discipline as RO §9). |
| Bounded self-work | Verdict latency is bounded by delegated check runtime plus fixed VAE overhead; VAE performs no unbounded computation of its own. |
| Sealed consumption | VAE judges from the artifact, declared rules, and recorded results — it re-queries no live world mid-judgment, preserving replayability (same discipline as RO-I3 and CP determinism tuples). |

---

## 10. Success Criteria

1. **No unverified acceptance:** 100% of gated artifacts that the system
   accepts carry a `verify.passed` verdict; zero structural paths exist around
   the gate (Law 4 upheld end-to-end).
2. **No limbo:** every gated item receives a definite terminal verdict; missing
   verdicts are provably treated as not-passed by all enforcers.
3. **Independence holds under failure:** no producer failure mode (hang, crash,
   malformed output) can crash, stall, or corrupt VAE — the V1-H4 class is
   structurally impossible, demonstrated, not asserted.
4. **Replayable verdicts:** any verdict reconstructs byte-identically from its
   evidence record (artifact reference + rules version + recorded results)
   without re-querying anything live.
5. **Explainability in practice:** every `verify.failed` carries reasons
   sufficient for the Kernel's policy to act and for a human to understand
   without reading VAE internals.
6. **Clean knowledge membrane:** the Experience & Knowledge Store's trusted
   path contains zero unverified material, auditable from records.
7. **Zero policy leakage:** no VAE artifact, rule, or record encodes an
   execution decision; the Kernel's decision log and VAE's evidence log remain
   separable authorities.
8. **Evolution without redesign:** a new artifact type or check onboards as
   rules/data plus a bounded check module, with no change to this foundation.

---

## 11. Future Phase Roadmap

| Phase | Scope (content set by future prompts) |
|---|---|
| 1 | **Verification Model** — the artifact-type taxonomy, check taxonomy, rules-as-data model, scoping (changed + dependents), and verdict semantics |
| 2 | **Assurance & Confidence** — evidence model, confidence derivation, proportional-depth policy, handling of nondeterministic evidence sources |
| 3 | **Kernel Integration** — verdict/evidence flow to the enforcers, gate topology with Kernel and Scheduler, failure-mode contract (limbo prevention, absence-as-fail) |
| 4 | **Operational Architecture** — delegation lifecycle with Execution, event choreography, persistence of evidence via Storage, telemetry, performance envelope |
| 5 | **System Integration** — full event canon, integration with Experience's trusted-knowledge path, invariant scans, hub-doc errata if any |

Each phase designs strictly inside this document's boundaries. The evolution
test (CP/04 precedent): if a future development requires VAE to answer a
question outside "is this artifact trustworthy, with what evidence, at what
confidence, explained how" — that is a new component, not a VAE extension.

---

## 12. Glossary

| Term | Definition |
|---|---|
| Verifiable artifact | Any sealed object the system may gate on: plan, diff, generated artifact, reasoning outcome record, plugin output, selftest result set |
| Check | A single evidence-producing evaluation of an artifact against a rule; executable checks run in Execution, static checks run in VAE |
| Rules-as-data | The versioned mapping from artifact type to required checks and depth; VAE's sole configuration authority |
| Verdict | The definite terminal judgment on a gated item (`verify.passed` / `verify.failed`), emitted as a first-class event with reasons |
| Evidence record | The immutable, durable, reconstructible account behind a verdict: checks run, rules version, results, derived confidence |
| Confidence | An evidence-derived measure of assurance strength attached to a verdict; never asserted from outside |
| Gate | An enforcement point owned by Kernel/Scheduler whose only opening is a passed verdict (Law 4) |
| Limbo | The forbidden state of a gated item with no terminal verdict; treated by enforcers as not-passed |
| Delegated check | An executable check VAE requires but Execution runs (Law 3); its timeout or crash is an ordinary result |
| Knowledge membrane | VAE's role between raw execution history and trusted system knowledge: only verified material crosses |

---

## 13. Foundation Invariants (VAE-I)

1. **VAE-I1** — VAE produces evidence and verdicts only; it never makes or
   encodes an execution policy decision. The Kernel decides.
2. **VAE-I2** — Verdict enforcement lives in Kernel/Scheduler edges (Law 4);
   VAE never enforces, and no component can accept a gated artifact without a
   passed verdict.
3. **VAE-I3** — VAE spawns no process; every executable check is delegated to
   Execution, and a hung or crashed check is an ordinary failed result (Law 3,
   V1-H4).
4. **VAE-I4** — VAE is read-only over every artifact it judges; it modifies no
   reasoning output, plugin output, plan, or diff.
5. **VAE-I5** — Every gated item receives a definite terminal verdict; absence
   of a verdict is treated system-wide as not-passed.
6. **VAE-I6** — The verdict function is deterministic: identical artifact,
   rules version, and recorded check results yield an identical verdict and
   evidence record (Law 6).
7. **VAE-I7** — Confidence is derived from evidence inside VAE; no external
   self-assessment, producer score, or default carries verdict authority.
8. **VAE-I8** — Every verdict is explainable from its immutable evidence
   record alone, without re-querying anything live.
9. **VAE-I9** — Only VAE-verified material enters the Experience & Knowledge
   Store's trusted-knowledge path; Experience never learns from unverified
   execution.
10. **VAE-I10** — Any reasoning used as an evidence source crosses RO's
    quarantine gate as a governed invocation (RO-I2) and enters as weighed
    evidence, never as verdict authority.
11. **VAE-I11** — VAE performs no retrieval, indexing, or context assembly
    (Law 2); repository knowledge for check scoping comes from UMS, and durable
    persistence goes through Storage (single writer).
12. **VAE-I12** — All VAE activity is observable: every verdict, evidence
    record, and delegation is telemetry in Observability's one schema (Law 7).
