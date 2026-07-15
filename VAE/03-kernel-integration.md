# Verification & Assurance Engine (VAE) — Phase 3: Kernel Integration

Status: authoritative for how verdicts, evidence, and assurance flow to the
Kernel and Scheduler; gate topology; the limbo-prevention failure-mode contract;
retry/rollback recommendation discipline; and the place of assurance in a
request's recorded state. Architecture only: no algorithms, no operational
event choreography, no evidence-persistence mechanics, no telemetry shape, no
performance bounds. How verdicts are delegated to Execution, how evidence is
persisted via Storage, operational latencies, and telemetry expression are
VAE/04 territory (VAE/00 §11). VAE/00, VAE/01, and VAE/02 are immutable above
this document: where this document is silent they govern; where they speak, this
document refines and never contradicts.

---

## 1. Architectural Position

Phase 3 sits at the integration boundary between VAE's evidence production
(VAE/01, VAE/02) and the enforcement systems that act on verdicts (Kernel,
Scheduler). It defines:

- How verdicts and their evidence leave VAE and arrive at enforcers
- How assurance levels are presented to components that need to understand
  artifact confidence (without those levels substituting for verdicts)
- How the system prevents limbo — the forbidden state of a gated artifact with
  no terminal verdict
- What VAE provides to Kernel/Scheduler as decision input for retry and
  rollback policy, and what remains the enforcers' exclusive authority
- Where assurance is recorded in a request's state lifetime, making it
  observable and auditable

All enforcement itself (gate opening/closing, continue/retry/rollback decisions,
dispatch routing) remains the Kernel's and Scheduler's exclusive authority
(VAE-I1, VAE-I2). This phase defines the shape of the input they receive, the
contract on which that input is reliable, and the system-wide rules that make
limbo impossible.

---

## 2. Verdict Flow to Enforcers

### 2.1 Verdict as a Definite Terminal Event

From VAE/01 §4 (Responsibilities): **"Verdict production — Emitting a definite
terminal verdict per gated item — `verify.passed` / `verify.failed` with
structured reasons — as first-class events on the bus."**

VAE emits verdicts as two event types on the Communication bus:

| Event | Emitted when | Payload includes | Consumed by (per ARCHITECTURE.md) |
|-------|---|---|---|
| `verify.passed` | VAE reaches a definite pass verdict on a gated artifact | verdict_id, artifact_id, rules_version, evidence_record_ref, assurance_level, timestamp | Scheduling, Kernel, Observability |
| `verify.failed` | VAE reaches a definite fail verdict on a gated artifact | verdict_id, artifact_id, rules_version, evidence_record_ref, failure_cause (VAE/01 §11 taxonomy), reasons, timestamp | Scheduling, Capability Planning, Observability |

No verdict exists until VAE emits one of these events. The absence of a verdict
is a defined state (VAE-I5, "Every gated item receives a definite terminal
verdict; absence is treated as not-passed"), not an implicit pass.

### 2.2 Evidence Record Attachment

VAE/00 §4 responsibility 8 fixes that verdicts carry "durable, explainable
record behind every verdict: what was checked, against which rules version,
with what results, deriving what confidence."

At verdict emission time, VAE supplies:

- **evidence_record_ref**: A Storage-backed reference (identifier) to the
  immutable evidence record for this artifact. The record itself is persisted
  by VAE via the Storage single-writer path (not a copy in the event payload;
  per RSM/02 ADR-RSM-3, ref over duplication).
- **rules_version**: The versioned rules-as-data (VAE/00 §4 responsibility 1)
  used to reach this verdict. Allows deterministic replay (VAE-I6, Law 6) and
  audit of "why was this verdict correct given the rules it was judged by."

Any component (Kernel, Scheduler, Learning, human auditor) can at any point
fetch the referenced evidence record via Storage to answer "what was checked,
with what results, deriving what confidence."

### 2.3 Assurance Level Attachment

VAE/02 §7 establishes five assurance levels: three graded passes (High, Moderate,
Low Assurance), Unverified, and Verification Failed.

At verdict emission time, VAE supplies:

- **assurance_level** (on both `verify.passed` and `verify.failed` events):
  The evidence-derived assurance level (VAE/02 §7) computed deterministically
  from the evidence body and rules version at judgment time.

The level is part of the verdict record for observability and for consumers to
understand the strength of the pass (where the verdict is a pass). The level
does not override the verdict, grant re-entry to a failed artifact, or
substitute for the binary terminal verdict at the gate (VAE-A7).

### 2.4 Structured Reasons

VAE/00 §4 responsibility 7 and Principle 3 fix that every verdict carries
"structured reasons reconstructible by a human or a downstream component."

At verdict emission time, VAE includes:

- **reasons** (on `verify.failed`): A structured account of why the verdict is
  fail — which checks failed, which evidence was insufficient, which evidence
  contradicted, which rules were not satisfied. The structure mirrors VAE/01
  §11's failure taxonomy (execution failure, verification failure, evidence
  insufficiency, inconclusive verification, contradictory evidence) so the
  Kernel and Scheduler can distinguish the kind of failure without parsing
  prose.

Reasons are immutable once emitted and remain attached to the evidence record
for audit. They are not instructions to retry or replan — they are explainers
of the verdict, and decision is the Kernel's (VAE-I1).

---

## 3. Gate Topology: Scheduler and Kernel

The Kernel and Scheduler are the sole gatekeepers. This section states their
enforcement topology; the enforcement logic itself belongs to their own phase
(not VAE's).

### 3.1 Scheduler's Gate: Task Completion

From ARCHITECTURE.md §Request lifecycle (line 207-218): the gate from a
scheduled step to either `task.completed`/commit or back to planning is
**entirely mediated by Verification's verdict**.

```
SCH -->|dispatch step| EXE
EXE -->|result| SCH
SCH -->|require gate| VER
VER -->|verify.passed or verify.failed| SCH
  alt verdict pass
    SCH --> task.completed, commit artifact
  else verdict fail
    SCH --> replan(step, failure)
```

**Structural unskippability (Law 4):** The Scheduler has no architectural path
that bypasses this gate. A step cannot be marked `task.completed` without a
`verify.passed` verdict on its artifact. A `verify.failed` routes the Scheduler
back to Capability Planning to replan, never forward to commit.

**Verdict absence is not-passed:** If a verdict never arrives (hung check,
missing dispatch, deadlock), Scheduler's gate remains closed (VAE-I5 enforced
at architecture level). The check's timeout or absence surfaces as a failure
condition the Scheduler must handle, but "no verdict yet" never becomes "pass"
by default or by waiting.

### 3.2 Kernel's Gate: Request Completion

From ARCHITECTURE.md §Request lifecycle (line 221-225): the Kernel's own gate is
higher-level.

```
SCH -->|all gates passed| K
K -->|close request state machine| LIF
K -->|request.completed| FE, Observability
```

The Kernel receives `task.completed` events from Scheduling only after the
Scheduler has already verified all gates (Scheduling consumes the verdicts). 
The Kernel's role is:

- **Authority over request lifecycle transitions** (via Kernel invariants I1, I4,
  I8): once all scheduled tasks report `task.completed`, the Kernel issues
  `request.completed` (or `request.failed` if any task reported `task.failed`).
- **Admission and routing policy** (via Kernel invariants I3, I7): verdicts are
  inputs to policy, never constraints on the Kernel's authority. The Kernel
  records verdicts in its internal Ledger (KERNEL/04-request-state.md) as
  read-only artifacts it consumes, not state it produces.

### 3.3 Capability Planning's Replan Path

From ARCHITECTURE.md line 216: `verify.failed` routes back to Capability
Planning to replan the failed step.

The structure is:

```
VER -->|verify.failed| SCH
SCH -->|replan(step, failure)| CP
CP -->|plan.revised| SCH
```

VAE provides the failure verdict and its structured reasons. Capability
Planning decides *whether* to replan (it may decide to give up and propagate
the failure to the Kernel instead). Capability Planning may use the failure
reasons as context ("what was wrong about the first plan?") when designing a
revised plan, but it is not obligated to — the decision to replan is CP's
policy, not VAE's.

---

## 4. Verdict Consumption Contract

What the Kernel, Scheduler, and other consumers can rely on regarding verdicts
they receive from VAE.

### 4.1 Definiteness

**Guarantee:** Every verdict is a definite terminal judgment (VAE-I5, VAE-I6).
There are two possible values — `verify.passed` or `verify.failed` — and once
one is emitted, no other verdict for the same artifact will be emitted (though
evidence may accumulate after the fact, which updates assurance level but not
the verdict itself).

**What this means for enforcers:** The gate needs only to check "did a
`verify.passed` arrive?" If not, the gate is closed. There is no "waiting for a
verdict" state once a reasonable time for delegated checks has passed; a hung
check becomes a timeout failure routed back through the replan path (VAE/01 §9
"Never retries" — VAE does not wait and retry itself; it enforces a deadline
and treats timeout as failure).

### 4.2 Determinism

**Guarantee:** Identical artifact + identical rules version + identical
recorded delegated-check results → identical verdict and evidence record
(VAE-I6, Law 6).

**What this means for enforcers:** A `verify.passed` on a given artifact is
deterministically replayable. If the same artifact is judged again against the
same rules with the same evidence, the verdict will be identical. This enables
audit ("was that verdict correct?") and debugging ("why did this artifact
pass?") without re-running anything live.

### 4.3 Independence

**Guarantee:** VAE's verdict on an artifact is independent of who produced it,
when it was produced, and whether the Kernel or Scheduler exerts pressure to
accept it. The verdict is a judgment of the *artifact*, not an opinion on the
*producer* (VAE/00 §2 "Trust nothing," Principle 2).

**What this means for enforcers:** A `verify.passed` is a genuine assertion
about the artifact's conformance to its declared rules. It is not inflated by
urgency, shortened by cost pressure, or modified by producer reputation. The
Kernel and Scheduler can trust that the gate is reliable precisely because VAE
is not moved by enforcement's incentives.

### 4.4 Explainability

**Guarantee:** The reasons attached to every verdict, combined with the
referenced evidence record, make the verdict explainable without access to VAE's
internal state or re-running any checks (VAE-I8, VAE-A10).

**What this means for enforcers:** The Kernel and Scheduler can defend
themselves and explain to users why a request moved forward or was stopped:
"this step's verification passed because [reasons]" or "failed because [failure
cause + reasons]." No internal VAE debugging required.

---

## 5. Assurance Level Consumption

Assurance levels (VAE/02 §7) are evidence summaries, not gate outputs. This
section defines what components may do with them and what they may not.

### 5.1 Observability and Reporting

Assurance levels are observable data for reporting:

- **Frontend display:** The Frontend may present "Verified — Moderate Assurance"
  to a user as a status indicator of how well an artifact was checked, *given*
  that the verdict is already a pass. The level is an honest statement of
  evidence strength.
- **Learning/benchmarking:** The Learning component may analyze assurance
  levels across completed requests to calibrate confidence representation
  (VAE/02 §9 "Confidence Benchmarking").
- **Observability recording:** Assurance levels are observable; they appear in
  Request State (§8) and in Observability's telemetry (VAE-I12).

### 5.2 What Assurance Levels Must NOT Do

**Never gate authority:** No assurance level, under any interpretation, carries
or implies a gate decision. A verdict of `verify.passed` opens the gate
regardless of whether assurance is High or Low (both are still passes under
VAE-I5). A verdict of `verify.failed` closes the gate regardless of assurance
nuance (VAE-A7).

**Never become retry policy:** Scheduling and the Kernel never retry an
artifact because assurance is low — that conflates evidence strength with
permission to rerun, the "run it again until it passes" failure Law 6 forbids
(VAE/00 §9). Low assurance is a reportable state; it is not a work order to
improve the number.

**Never substitute for verdict:** A "Verified — High Assurance" never becomes
an implicit pass if the verdict is not yet arrived. A "Verification Failed"
never becomes acceptable if assurance language suggests the artifact was
substantially checked. The level is descriptive of the evidence; it carries no
gate override (VAE-A8).

### 5.3 Presence in Enforcement Decisions

The only place an assurance level may inform an enforcement decision is as
*context* for a policy the Kernel or Scheduler authors and documents:

Example (not a binding rule, but illustrative):
- "Scheduling may defer a task if a prior-step artifact carries 'Verified —
  Low Assurance' and budget is constrained, pending collection of additional
  evidence." This is the *Kernel's policy* (not VAE's), documented, versioned,
  and auditable. It uses the assurance level as a data point, not as a mandate.

Such policies belong to VAE/04+ (operational behavior) and Phase 3 names only
the boundary: assurance informs policy but does not encode it.

---

## 6. Failure-Mode Contract: Limbo Prevention

VAE-I5 and VAE/00 §9 establish: "Definite terminal verdicts; every failure
mode of VAE itself must degrade to a definite fail or a loud absence the
enforcers treat as fail — never to an implicit pass."

This section defines how the system eliminates limbo.

### 6.1 Verdict Timeouts

If a delegated check (running in Execution) does not complete within a declared
deadline:

- **VAE's action:** VAE treats the timeout as a delegated-check failure (VAE/01
  §11 "Execution failure"). The artifact moves to `verify.failed` with reasons
  that attribute the failure to check timeout, not to artifact defect.
- **Scheduler's action:** The Scheduler sees `verify.failed` and routes the
  artifact to the replan path, just as it does for any other failure.

No verdict waits indefinitely. The deadline is fixed by the rules (VAE/00 §4
responsibility 1, rules-as-data), not dynamically negotiated.

### 6.2 VAE Failure

If VAE itself crashes, hangs, or produces an invalid verdict:

- **Structure:** VAE's verdicts are first-class events on the bus. If VAE
  crashes, no verdict is emitted, and Scheduling's gate remains closed (not
  passed by absence).
- **Observability:** The hung VAE is observed as a missing verdict (a fault-
  tolerance concern for VAE/04). The system does not treat a silent VAE as a
  pass.
- **Recovery:** This is handled at the operational level (VAE/04, §4 "Delegation
  lifecycle with Execution"), not at the architectural level.

### 6.3 Ambiguous Evidence

If delegated checks return contradictory results or inconclusive findings
(VAE/01 §11):

- **VAE's action:** VAE issues a definite verdict based on the deterministic
  rules (VAE-I6). Contradictory evidence (VAE-A5) reduces confidence but does
  not leave the verdict ambiguous. Inconclusive evidence (VAE/01 §11) results
  in a fail verdict and reasons that explain the inconclusiveness.
- **Scheduler's action:** The Scheduler sees a definite verdict (pass or fail)
  and acts accordingly. Ambiguity is never left unresolved for the enforcer to
  guess about.

### 6.4 Missing or Insufficient Checks

If the rules declare that certain checks should have run but did not (evidence
insufficiency, VAE/01 §11):

- **VAE's action:** Evidence insufficiency is recorded in the evidence body
  (VAE-M2) and in the failure reasons. VAE issues a `verify.failed` verdict with
  reasons explaining which required checks did not run.
- **Scheduler's action:** The Scheduler sees failure and routes to replan. The
  evidence record's detail about *why* (missing checks, not artifact defect)
  allows Capability Planning to decide whether to try a different plan that
  might satisfy the checks, request additional delegated checks, or give up.

### 6.5 Enforcement is Unreachable

If Scheduling or Kernel is not running or not reachable when a verdict arrives:

- **Communication guarantee:** This is the bus's at-least-once delivery
  guarantee (ARCHITECTURE.md §Communication model). A verdict event is persisted
  before ack and delivered to all durable subscribers (Scheduler, Kernel,
  Observability) at least once.
- **VAE's role:** VAE has no role; it publishes once and expects the bus to
  deliver.

---

## 7. Retry and Rollback Recommendations

VAE provides structured failure information that Kernel/Scheduler use to decide
whether to retry and rollback. This section defines the boundary.

### 7.1 What VAE Provides

From VAE/01 §11 (Failure Philosophy), VAE distinguishes five failure causes:

| Cause | What VAE records | What it implies for retry |
|---|---|---|
| **Execution failure** | The artifact-producing process crashed, timed out, or reported failure | Potentially retriable: execution may have been unlucky; the artifact was never produced for VAE to judge. |
| **Verification failure** | The artifact satisfies rules, Execution checks passed. | Not directly retriable by VAE's definition: the artifact was correctly judged deficient. If replan produces a different artifact, that is a new attempt, not a retry of the same artifact. |
| **Evidence insufficiency** | Required checks did not run or were not delivered. | Potentially retriable: evidence may yet arrive if the check is re-requested in a different form or timing. |
| **Inconclusive verification** | Applicable checks ran, but results do not settle the question. | Potentially retriable: check implementation may be flaky or need refinement; domain logic may benefit from clarification. |
| **Contradictory evidence** | Independent sources gave conflicting answers. | Potentially retriable: one source may be wrong; additional independent evidence may clarify. |

Each cause is recorded in the failure reasons on the `verify.failed` event,
allowing the downstream component to distinguish them.

### 7.2 What the Kernel and Scheduler Decide

Decisions about whether to retry, how many times, what to change between
retries, and when to give up are the Kernel's and Scheduler's exclusive
authority (VAE-I1):

- **Retry policy** (whether to attempt the same step again): Scheduler or Kernel
  policy, versioned, auditable, not VAE's.
- **Rollback policy** (whether to undo committed work): Kernel policy, not VAE's.
- **Replan policy** (whether to ask Capability Planning for a different plan):
  Scheduler policy, informed by the failure cause but not determined by VAE.
- **Escalation** (whether to ask a human or operator): Kernel or Frontend
  policy, not VAE's.

VAE's role is **describing** the failure, not **recommending** an action. This
keeps the boundary between evidence and policy clean (VAE-I1).

### 7.3 Architectural Boundary

VAE/00 §5 ("Execution policy decisions") is binding and refined here:

> **VAE never encodes, recommends, or implies a retry, rollback, escalation, or
> termination decision. The failure cause is part of the verdict record; what
> to do about that cause is the Kernel's exclusive authority.**

This prevents the evidence service from becoming a soft policy engine.

---

## 8. Request State Manager Integration

The Request State Manager (RSM/01–02) owns the runtime state record for every
active request. This section defines where assurance lives in that record.

### 8.1 Verification Block in Request State

From RSM/02 §1, the Request State record has a **Verification block** containing:

> **Verification** | verdict refs per gate | Reference into Verification's owned verdict content.

This means:

- **Per-artifact verdict reference:** When VAE emits `verify.passed` or
  `verify.failed` for an artifact (e.g., a plan, a step's output), RSM records
  a reference to that verdict in the Verification block keyed by the artifact's
  gate or step identifier.
- **Evidence record reference:** The verdict reference points to the verdict
  event or to the Storage-backed evidence record the verdict references
  (RSM/02 ADR-RSM-3: "ref over duplication"), allowing any query to fetch the
  full evidence and reason set.
- **Assurance level attachment:** The assurance level from the verdict event
  (§2.3) is stored alongside the verdict reference in the Verification block
  for observability.

### 8.2 Request State Evolution as Verdicts Arrive

As a request progresses:

1. **Step scheduled:** Scheduling emits `task.scheduled`, captured in Request
   State's Work block.
2. **Step execution completes:** Execution emits `exec.completed`, captured in
   Work block.
3. **Verification begins:** Scheduling emits `verify.requested`, captured as a
   pending gate in Verification block (optional tracking; state not yet
   terminal).
4. **Verdict arrives:** VAE emits `verify.passed` or `verify.failed`, captured
   in Verification block with verdict_ref, assurance_level, and reasons.
5. **Next action:** Scheduler consumes the verdict and either marks the step
   `task.completed` (if pass) or routes to replan (if fail). Request State's
   Work block is updated accordingly.

Request State remains the queryable view of "where is this request, what has
been verified, what was the evidence strength."

### 8.3 Failure State Materialization

RSM/02 §1 also defines a **Failure block** in the Request State record:

> **Failure** | materialized failure entries | Assembled from `*.failed` families and `fault.recorded`; content, not just a pointer, since failure entries are themselves small and terminal.

Verdicts that are `verify.failed` are represented here alongside other failure
points (execution failures, task failures). The Request State record makes it
observable what failed, when, and with what verdict.

### 8.4 Audit and Replay

RSM/02 §2 establishes: "Deterministic replay — a completed request's journal
can be replayed to reproduce a byte-identical materialization."

For assurance:

- **Historical confidence:** Replaying the per-request journal from the bus
  reconstructs every verdict that arrived during the request's life, in
  order. Because assurance is deterministically derived from the evidence body
  (VAE-A1), the historical assurance level at any point is reconstructible.
- **Audit trail:** The Verification block in the materialized Request State,
  combined with the journal, creates an auditable record: "at time T, with
  these checks run and these results, this artifact received this verdict and
  this assurance level, which the rules version V say is correct."

---

## 9. Integration Boundaries

This section names what Phase 3 does not cover; those are VAE/04–05 territory.

### Out of Scope for Phase 3

- **Operational event choreography:** The precise timing of when verdicts are
  emitted relative to other events, buffering, and in-flight artifact state
  management — VAE/04 (Operational Architecture).
- **Delegation lifecycle detail:** How VAE requests checks from Execution,
  tracks pending results, timeouts, and retries on the delegation side —
  VAE/04.
- **Evidence persistence mechanics:** How evidence records are structured,
  stored, indexed, and retrieved via Storage; what is persisted when; what
  Storage's transactional guarantees are — VAE/04.
- **Telemetry shape and collection:** How VAE's activity (verdicts issued,
  checks run, evidence produced) is telemetered to Observability and exposed
  for benchmarking — VAE/04.
- **Performance envelope:** Latency bounds for verdict emission, evidence
  persistence, verdict availability to enforcers — VAE/04.
- **Full event canon:** Complete list of all events VAE emits beyond the two
  terminal verdicts (e.g., delegated-check requests to Execution, evidence
  records written to Storage) — VAE/05.
- **Experience integration detail:** How Learning consumes verdicts and evidence
  to update planning priors and plugin reliability; the full trusted-knowledge
  membrane rules — VAE/05.
- **Invariant cross-phase scan:** System-wide invariant audit across VAE and
  all consuming systems — VAE/05.

### In Scope for Phase 3

- Verdict form and flow to enforcers (§2, §4)
- Gate topology at Scheduler and Kernel (§3)
- Assurance level semantics for consumers (§5)
- Limbo prevention architecture (§6)
- Retry/rollback boundary (§7)
- Request State Manager integration (§8)
- New invariants binding all later phases (§10)

---

## 10. Integration Invariants (VAE-K)

New Phase 3 invariants, extending VAE-I1–I12, VAE-M1–M7, and VAE-A1–A10
without duplication; binding on all later VAE phases.

1. **VAE-K1** — Every verdict is emitted as a first-class event on the
   Communication bus (`verify.passed` or `verify.failed`), with structured
   reasons and a reference to the stored evidence record. *Prevents:* verdicts
   that exist only in VAE's memory or are delivered by side channels.

2. **VAE-K2** — Every verdict references the rules version used to reach it,
   enabling deterministic replay (VAE-I6, Law 6). The same artifact against
   the same rules with the same recorded evidence always yields the same
   verdict. *Prevents:* verdicts whose source is opaque or unreplayable.

3. **VAE-K3** — The Scheduler has no architectural path that marks a step
   `task.completed` without a `verify.passed` verdict on its artifact (Law 4,
   ARCHITECTURE.md §Request lifecycle). The only route from step to completion
   passes through the verification gate. *Prevents:* unverified artifacts
   becoming durable state.

4. **VAE-K4** — A `verify.failed` verdict routes the Scheduler to replan
   (Capability Planning), never to commit or forward to the next step. The
   Scheduler has no path that accepts a failed artifact. *Prevents:* deficient
   artifacts being committed even when the Scheduler observes the failure.

5. **VAE-K5** — Absence of a verdict is enforced as not-passed by the
   Scheduler and Kernel. If a verdict deadline passes without arrival, the gate
   is closed and the artifact routes to failure/replan paths, never to
   acceptance. *Prevents:* limbo — an artifact left gated but not judged.

6. **VAE-K6** — Verdict absence never becomes a default pass due to timeout,
   urgency, budget pressure, or any enforcement incentive. The structural
   closure (VAE-K3, VAE-K4, VAE-K5) is enforced at the gate level independent
   of any policy component. *Prevents:* policy leakage backwards into verdicts
   or gate opening.

7. **VAE-K7** — Assurance levels are always attached to verdicts as evidence
   summaries (VAE-A1–A10). They are observable, reportable, and usable for
   informing enforcement policy — but no assurance level overrides a verdict
   at the gate, and no level carries implicit permission to retry or accept a
   failed artifact. *Prevents:* levels becoming soft gate policies.

8. **VAE-K8** — Every `verify.failed` includes structured reasons attributing
   the failure to one of VAE/01 §11's five causes: execution failure,
   verification failure, evidence insufficiency, inconclusive verification,
   or contradictory evidence. The Scheduler and Kernel can distinguish failure
   kinds without parsing prose. *Prevents:* opaque failures that leave enforcers
   guessing about retry or replan viability.

9. **VAE-K9** — Retry policy (whether to attempt the same step again), rollback
   policy (whether to undo durable state), and replan policy (whether to ask
   Capability Planning for a different plan) are the exclusive authority of the
   Kernel and Scheduler, versioned, auditable, and never encoded or implied by
   VAE's verdict, assurance level, or structured reasons. VAE provides evidence;
   enforcers decide. *Prevents:* policy leaking into VAE through the guise of
   failure classification (VAE-I1 restatement).

10. **VAE-K10** — The Request State Manager's Verification block records every
    verdict as it arrives (`verify.passed` or `verify.failed`), capturing the
    verdict reference, assurance level, and evidence record reference. Request
    State is the system-wide queryable view of what has been verified and how
    well. *Prevents:* assurance being invisible to request status queries;
    enables audit of "what was this request's assurance state when it completed."

11. **VAE-K11** — Per-request journal replay deterministically reconstructs the
    materialized Request State record, including all verdicts in order
    (RSM/02, deterministic-replay guarantee). Historical assurance at any point
    in a request's life is reconstructible from the journal and the rules
    versions cited in verdicts. *Prevents:* assurance being lost once a request
    completes; enables post-mortem audit.

12. **VAE-K12** — The Kernel's internal Ledger (KERNEL/04-request-state.md)
    records verdicts it receives from VAE as read-only artifacts, never as state
    it produces or mutates. The Kernel consumes verdicts for routing and gate
    decisions; it does not grade them. *Prevents:* Kernel policy influencing
    verdict formation through backward coupling (VAE-I1, VAE-I2 enforcement at
    the Kernel boundary).

---

## 11. Phase Summary

**Now fully defined by this document:**

- Verdict emission form as two first-class bus events (`verify.passed`,
  `verify.failed`) with structured reasons, evidence references, and assurance
  levels (§2.1–2.4).
- Evidence record attachment by reference, enabling deterministic replay and
  audit without recomputation (§2.2).
- Assurance level attachment as an evidence summary accompanying every verdict
  (§2.3, §5).
- Scheduler's gate topology: no path from step to `task.completed` without
  `verify.passed`; `verify.failed` routes to replan (§3.1).
- Kernel's role as routing authority, consuming verdicts as decision input but
  never producing them (§3.2).
- Capability Planning's replan path as the response to `verify.failed` (§3.3).
- Verdict consumption contract: definiteness, determinism, independence, and
  explainability (§4).
- Assurance level consumption boundaries: observable, reportable, and usable
  for policy context — but never gate authority, never implicit retry mandate,
  never verdict override (§5).
- Limbo prevention through structural unskippability, verdict deadlines,
  timeout degradation, and enforcement-independent gate closure (§6).
- Failure-mode taxonomy distinction in verdicts, enabling informed retry/
  rollback policy (§7.1) while keeping policy authority exclusive to Kernel/
  Scheduler (§7.2, §7.3).
- Request State Manager integration: Verification block materializing verdicts,
  assurance levels, and evidence references; Failure block for observability;
  journal replay for historical auditability (§8).
- Twelve new Phase 3 invariants (VAE-K1–K12) binding all later phases (§10).

**Intentionally deferred**, per the VAE/00 §11 roadmap:

- Operational event choreography, delegation lifecycle, pending-verdict state
  management, timeout handling, and retry signaling — **Phase 4 (Operational
  Architecture)**.
- Evidence persistence structure, Storage's transactional model for evidence
  records, and access patterns — **Phase 4**.
- Telemetry shape for verdict issuance, evidence production rate, bottleneck
  identification, and benchmarking feedback — **Phase 4**.
- Performance latency bounds for verdict emission, evidence availability to
  enforcers, and gate-opening latency — **Phase 4**.
- Complete event canon beyond the two terminal verdicts (e.g., `check.started`,
  `check.completed`, evidence-appended events) — **Phase 5 (System
  Integration)**.
- Learning integration: how verdicts and evidence records feed back into
  planning priors, plugin reliability, and rules-as-data versioning — **Phase
  5**.
- Experience's trusted-knowledge membrane rules and VAE's role in certifying
  what may be learned from — **Phase 5**.
- Full cross-phase invariant audit and ARCHITECTURE.md errata if any — **Phase
  5**.

This document introduces no algorithm, no schema, no formula, no threshold, and
settles no question VAE/00, VAE/01, or VAE/02 already settled. Every structural
decision traces to a responsibility, principle, invariant, or architectural law
it refines.

---

## 12. Glossary (Phase 3 additions)

| Term | Definition |
|---|---|
| **Verdict event** | A `verify.passed` or `verify.failed` event published on the Communication bus, containing verdict_id, artifact_id, rules_version, evidence_record_ref, assurance_level, and structured reasons. |
| **Limbo** | The forbidden state of a gated artifact with no terminal verdict — not passed, not failed, awaiting judgment indefinitely. Architecturally impossible per VAE-K3–K5. |
| **Gate closure** | The state of a Scheduler or Kernel gate when no `verify.passed` verdict has been received; no artifact may pass through a closed gate. |
| **Evidence record reference** | A Storage-backed identifier pointing to the immutable evidence record for a verdict, allowing audit and replay without the record existing in the event payload. |
| **Rules version** | The versioned rules-as-data (VAE/00 §4 responsibility 1) against which an artifact was judged, enabling deterministic replay and "was this verdict correct?" audits. |
| **Failure cause** | One of the five distinctions from VAE/01 §11 (execution failure, verification failure, evidence insufficiency, inconclusive verification, contradictory evidence), recorded in verdict reasons. |
| **Request State Verification block** | The section of a request's materialized state record (RSM/02) that holds references to all verdicts emitted for that request, in arrival order. |
