# SGPE/05 — System Integration & Architecture Freeze

Phase 5 output — final architectural phase. Integrates SGPE/00–04 (canon,
plus ERRATA C3) with the operating system. No new SGPE subsystems; the five
parts (Store, Compiler, Evaluator, Resolver, Grant Ledger) are complete and
this document adds only their weave into the OS, the consolidated failure
law, observability, and the closing review.

---

## 1. Consultation contract (uniform, restated once)

Every subsystem consults SGPE the same way (SGPE/00 §10): pose a canonical
Question through the request's Effective Policy binding, receive a Decision
(effect + binding constraints + explanation + stamps), enforce it. Facts the
consumer must supply come from the snapshot's declared fact names (EV §3);
usage numbers come from the consumer's own Observability-sourced accounting.
The consumer is always the enforcement point (INV-1); **no Decision = no
action** (EV §2) — uniformly, no exceptions per domain.

Per-subsystem specifics below add only *when* each asks, *what about*, and
what stays theirs.

## 2. Per-subsystem integration

| Subsystem | When consulted | Typical Questions (domains) | Decisions received | Stays outside SGPE |
|---|---|---|---|---|
| **Execution Kernel** | Request admission (invokes Resolver — sole invoker, EPR canon); before structural gate crossings; routes approval outcomes to Ledger appends | execution (may this request class run), resource-limit (global ceilings) | EP(R) binding (admission); ALLOW/DENY + ceilings (gates) | Gate mechanics, scheduling authority, kill/suspend decisions and their execution; admission *mechanics* (SGPE only supplies the binding and the fail-closed rule) |
| **Request State Manager** | Never asks policy Questions | — | — (persists EP(R) stamp and per-Decision stamps as request state) | All request-state semantics; RSM is a pure custodian here — the one consumer whose integration is storage of stamps, not consultation |
| **Unified Memory System** | Before persisting/retaining memory content; before serving content across scope boundaries | persistence (may this be stored/retained), resource-limit (retention ceilings) | ALLOW/DENY; LIMIT (retention) | What is worth remembering, memory structure, retrieval ranking — SGPE governs *may*, never *what* |
| **Context Manager** | At context assembly start (per request, via frozen EP) | context-limit, token-budget (assembly share) | LIMIT values + citations | Assembly strategy, reduction choices, what enters context — CM optimizes *within* the ceiling; exhaustion handling is CM behavior, not a new Question shape |
| **Capability Planner** | During planning, advisory pass over candidate capabilities (plan against what is allowed — SGPE/00 §10) | capability/plugin permission, model permission (planned steps) | ALLOW/DENY/REQUIRE_APPROVAL per candidate | Plan construction, capability choice among allowed options. Planning-time answers do **not** pre-authorize execution: the executing subsystem re-asks at crossing time under the same frozen EP — same stamps, same answer (D1), so the double-ask costs one memo hit and buys crossing-time facts (usage may have grown) |
| **Workflow Scheduler** | Before dispatching steps; on retry decisions | resource-limit (concurrency), retry-limit | LIMIT values; DENY when exhausted-by-facts | Scheduling order, backoff strategy, retry *execution* — SGPE owns the ceiling, WS owns the loop |
| **Plugin Runtime** | At plugin binding/load; before granting a binding its sandbox scopes | plugin permission, filesystem/network/shell scopes for the binding | ALLOW/DENY/REQUIRE_APPROVAL + scope constraints | Registry stewardship (CP/01 §9), discovery, health, sandbox *construction* — SGPE says what a plugin may touch, PRT builds the cage |
| **Reasoning Orchestrator** | RO/02 governance inputs #7/#8, now SGPE-sourced: before reasoning invocation | model permission, token-budget (reasoning ceiling, remaining-budget fact supplied by RO) | ALLOW/DENY (→ GOVERNANCE-REFUSED when enforced), LIMIT (budget) | Necessity judgment, provider selection, sizing, retry taxonomy F1–F8 — RO/04 unchanged; SGPE replaces only the anonymous config read |
| **Verification & Assurance** | Before verification runs (resource ceilings); on any gate-waiver ask | resource-limit (verification budget), approval (waiver — near-always blocked by `final`) | LIMIT; DENY (final-cited) | Verdict semantics, assurance levels, what to verify. VAE verdicts never enter Questions as policy inputs (SGPE/00 §10) — verification informs humans, humans author policy |
| **Learning & Intelligence** | Before ledger/derived persistence (persistence domain); its *advice* path is outbound to humans, not into SGPE | persistence, resource-limit | ALLOW/DENY; LIMIT | The whole learning loop. LIE may cite Compile Report warnings and policy-decided events as experience; policy *change* remains human authoring (INV-10) — the loop closes through people, never wires |
| **Interaction & Visualization** | Renders REQUIRE_APPROVAL asks (signature + explanation); displays resolved citations; returns approval outcomes (Kernel routes the append) | Own actions rarely governed (display is not a boundary crossing); asks `approval`-domain Questions only when surfacing meta-approvals | The ask payloads, not policy answers | Approval UX entirely: presentation, consent capture, timeout of the *ask* (an unanswered ask simply never becomes a grant — no SGPE state waits on it) |

Two structural notes:

- **Consultation topology.** Admission is the only synchronous SGPE
  round-trip on every request. Per-crossing Questions evaluate against the
  frozen EP with memoization (EV §8) — SGPE/00 §11's promise, now visible
  per consumer: the hot path is local evaluation over immutable stamped
  inputs, not a service hop.
- **Non-request governance.** Compile/activate (Compiler) and authoring
  (Store) run off any request path; their consumers are humans and tooling,
  their events flow to the same bus.

## 3. Runtime lifecycle (end-to-end)

```
[authoring] docs → Store appends → compile → candidate → activate (atomic)
                                                            │
[request]  Kernel admission ─ Resolver binds EP(R) = (S, P₀, R) ─ RSM persists
                │
        consultations (any subsystem, frozen EP, memoized) → Decisions enforced
                │
        REQUIRE_APPROVAL → IVS renders ask → grantor decides → Kernel routes
                │                 append (request-scoped) → grant.recorded
                │                 → re-ask (new position stamp) → ALLOW/DENY
                │
[completion] request ends → request-scoped grants lapse by bound → EP retired
                │            (implicitly; nothing to clean up — EPR §2.4)
                │
[replay]   RSM stamps + audit Questions → regenerate snapshot (AC-9) +
           slice at position (GL-6) → re-evaluate under recorded ruleset
           versions (EV-9) → byte-compare
```

Bootstrap (canon per EPR §2.4): Storage → Communication → Observability
already precede everything (ROADMAP Phase 0); within SGPE, first vocabulary
+ system-default documents → first compile → first activation → only then
first admission. The system-default scope's totality (INV-12) makes the
first snapshot the "deny-by-default constitution" — deployment readiness
begins at exactly this point, §7.

## 4. Observability

**Philosophy.** SGPE is glass-box by events and stateless by storage: every
governance act is a bus event, Observability is the sole sink (INV-8), and
nothing about SGPE's behavior is inferable only from internal state —
because there is no internal state beyond the two append-only records and
disposable memo tables.

**Event canon (consolidated — all previously defined, none new):**

| Event | Emitted by | Carries |
|---|---|---|
| `policy.authored` / `policy.deprecated` | Store | document id/version, provenance, position |
| `policy.compiled` / `policy.rejected` | Compiler | Compile Report (manifest echo, errors/warnings, witnesses) |
| `policy.activated` | Compiler (activation act) | old/new snapshot versions, manifest |
| `policy.decided` | Evaluator | Question hash, Decision, citations, stamps |
| `policy.illposed` | Evaluator | malformation diagnostic, caller identity |
| `grant.recorded` / `grant.revoked` | Ledger | grant/revocation record, position |

**Metrics** (derived by Observability from events, never counted by SGPE):
decision volume and effect mix per domain/consumer; memo hit ratio;
ill-posed rate per caller (a *consumer bug* signal, not a policy signal);
REQUIRE_APPROVAL→grant conversion and latency (human-loop health); compile
rejection rate and time-to-green (authoring friction); shadowing-warning
count (policy hygiene).

**Health signals.** SGPE health is boring by design: active-snapshot fact
present; Store/Ledger append latency within bounds; replay spot-checks
green (R5/EV-9 oracles run as standing verification — VAE-run, SGPE-blind).
An unhealthy SGPE fails closed (§5), so health monitoring protects
*availability*, never correctness.

**Benchmarking philosophy.** Two numbers matter, measured not asserted:
(1) admission overhead (Resolver's two reads) — budgeted as negligible
against Kernel admission; (2) per-consultation evaluation latency, memo-hit
and memo-miss. Benchmarks run against synthetic snapshots of realistic
shape (documents × rules × scopes at human-paced volume, SGPE/01 §10) and
are regression gates, not targets to optimize past — the architecture
already spends its performance budget on determinism, deliberately.
Compile-time cost is explicitly unbenchmarked as a gate (off request path;
quadratic conflict analysis is an accepted cost, AC canon).

**Diagnostic expectations.** Any governance surprise is answerable from
events alone: "why was this denied" = citation chain from `policy.decided`;
"why did this compile fail" = witnesses in `policy.rejected`; "who allowed
this" = grant provenance chain (GL §1.5). If a question about governance
behavior cannot be answered from the bus record plus the two appends-only
records, that is an architecture bug — file it against INV-7/INV-8, not a
logging feature request.

## 5. Failure philosophy (consolidated law)

One sentence: **SGPE fails closed, loudly, and deterministically — and
never guesses.** The cases, all previously ruled, gathered:

| Failure | Behavior | Ruled in |
|---|---|---|
| SGPE unavailable at admission | Admission refused | EPR-5 |
| No active snapshot | Admission refused (bootstrap order canon) | EPR §2.4 |
| Ledger unreachable at admission | Admission refused | EPR-5 |
| Ledger unreachable mid-request (grant append fails) | The approval simply never lands; pending ask stays unanswered; request proceeds under existing Decisions (REQUIRE_APPROVAL = still forbidden) | GL/EPR semantics — no new rule needed |
| Snapshot artifact lost/corrupt | Regenerate from manifest (AC-9, hash-verified); until regenerated, consultations cannot proceed = no action | AC-9, EV §2 |
| Malformed Question | Ill-posed verdict — not DENY, not guessed; caller must treat as no-Decision | EV-6, EV §9 |
| Invalid grant (lapsed bound, revoked, wrong scope) | Not matched at evaluation — grants are data, invalidity is just non-match; never an error | GL-5, EV §6 |
| Evaluator crash | Re-ask; pure = idempotent, free | EV §9 |
| Compile crash | No partial state; rerun | AC §9 |
| Consumer cannot reach SGPE mid-request | No Decision = no action; the consumer blocks or fails its own operation per its own fault model — it never proceeds ungoverned and never caches beyond its keys | EV §2, SGPE/00 Law 4 discipline |

**Consumer obligations** (the enforceable contract, for Phase-5-of-
implementation test doubles): supply declared facts truthfully from their
own accounting; enforce effects and *all* binding constraints; treat
ill-posed and unreachable as no-action; never re-derive, reinterpret, or
"remember" a Decision past its stamps; surface REQUIRE_APPROVAL asks rather
than swallowing them. A consumer violating these is a Law-4 violation — a
Kernel/VAE matter, not an SGPE runtime concern (SGPE cannot detect it,
by purity; the audit record can, by replay).

## 6. Final invariant review

Full-architecture verification pass across SGPE/00–04:

- **Determinism** — every runtime answer is f(stamps, Question) (EV-1);
  every build is f(P, versions) (AC-2); both rulesets versioned (R4/EV-9).
  No clock, no randomness, no iteration-order leak anywhere in canon. ✓
- **Replayability** — stamps small and total: EP(R) + per-Decision
  positions + regenerable snapshots + position-sliced ledger reconstruct
  everything byte-for-byte (EPR-7). ✓
- **Purity** — Evaluator I/O-free (EV-2); Resolver stateless, two reads
  (EPR-3/6); Store/Ledger pure functions of their append sequences
  (PS-5/GL-1). ✓
- **Separation of concerns** — five parts, each with a never-owns table;
  enforcement/metering/approval-UX/audit-storage all externally homed;
  cross-checked against CP/PRT/RO/VAE/LIE ownership claims — no overlap
  found; RO integration is a source swap, not a semantics change. ✓
- **No policy mutation during evaluation** — runtime writes are exactly
  one kind: Ledger appends via the Kernel-routed approval path; neither
  Evaluator nor Resolver can write governance data at all (EV-2, EPR-3). ✓
- **No runtime ambiguity** — totality (INV-12) + compile-time rejection of
  undecidables (AC-5) + exact grant matching (GL-4/EV-5) leave zero
  judgment at runtime; the ill-posed class catches everything else without
  guessing (EV-6). ✓
- **OS consistency** — Law 3 (Storage sole writer) honored by both
  records; Law 4 discipline restated as consumer obligation; event canon
  extends the existing bus vocabulary; no-clock/causal-trigger discipline
  matches LIE OPS canon; doc/errata governance per CP/04 §9 precedent. ✓

**Residual weaknesses, named honestly:**

1. **The Question-fact honesty boundary.** SGPE decisions are only as true
   as consumer-supplied facts (usage numbers especially). This is a
   *designed* trust boundary (purity requires it), enforced socially by
   audit-replay + VAE attestation of consumer behavior, not technically by
   SGPE. Accepted; alternatives (SGPE metering) violate INV-1 and were
   rightly rejected. Flagged so nobody later "fixes" it by breaking purity.
2. **Approval-loop liveness.** An unanswered ask blocks the asking
   operation indefinitely by design (no SGPE timeout — time is not SGPE's).
   Liveness is Kernel/WS's to manage via their own operation deadlines.
   Correct placement, but implementers will be tempted to add ask-expiry to
   SGPE; the bound-condition mechanism (GL §1.2) is the sanctioned tool if
   policy wants asks to lapse.
3. **Canonicalization ownership concentration.** Question canonical form,
   ask signatures, and memo keys all hang on one definition owned by the
   Evaluator (EV §3). Single ownership is right; the risk is implementation
   drift between the Evaluator and callers constructing Questions. The
   implementation must ship canonicalization as one shared artifact, not
   parallel implementations — recorded here as a binding implementation
   constraint (the architecture's only one).

No genuine defect found in Phases 0–4. No redesign. ERRATA C3 remains the
architecture's single interpretive ruling.

## 7. Deployment readiness

SGPE is deployable into the OS when, in order:

1. Storage/Communication/Observability live (ROADMAP Phase 0 — already
   canon-satisfied in this repo's build order);
2. vocabulary v1 + system-default document set authored (the deny-by-
   default constitution, total per INV-12);
3. first compile green, first activation done (bootstrap canon, §3);
4. standing oracles wired: R5 (regeneration ≡ recorded hash) and EV-9
   replay spot-checks running under VAE;
5. consumer contracts (§5 obligations) exercised against SGPE doubles —
   consumers integrate one at a time, RO first (it already has the
   GOVERNANCE-REFUSED seam), Kernel admission last (it flips fail-closed
   on for the whole system).

Nothing in SGPE requires other subsystems to change their canon: RO swaps a
config source; the Kernel gains the Resolver call and the append route; all
others gain consultations at boundaries they already own.

## 8. Implementation contracts (per part, LIE/04 pattern)

For the Sonnet implementation phases — required / forbidden / guarantees:

| Part | Required | Forbidden | Guarantees |
|---|---|---|---|
| Policy Store | Append/version/catalog documents; structural gate; position-stamped reads; manifests + activation facts | Any semantic judgment; edit/delete; self-initiated behavior | PS-1…10 |
| Admission Compiler | 8-stage pipeline; all-findings-per-stage; canonical artifacts; atomic activation; Compile Reports | Repair/reorder policy; partial snapshots; request-path presence; extra resolution rules | AC-1…10, R1–R5 |
| Evaluator | Canonical Question validation; index retrieval; `final`-before-grants overlay; constraint attachment; trace-as-explanation; memo by full key | Store/Ledger/Compiler access; conflict resolution; guessing; clock reads | EV-1…10, D1–D7 |
| Resolver | Two atomic reads at admission; EP(R) emission; fail-closed refusals | State between calls; evaluation; writes; per-consultation gatekeeping | EPR-1…7 |
| Grant Ledger | Append grant/revocation; position-stamped slices; opaque signatures | Validity judgment; expiry/compaction; parsing signatures or policy | GL-1…7 |

Shared: one canonicalization artifact (§6 weakness 3 — binding constraint);
events per §4 canon; all persistence through Storage doubles until Phase-0
substrate integration.

---

**SGPE architecture complete and frozen.** Five parts, five documents
(SGPE/00–05), one errata ruling (C3), invariant families INV/PS/AC/EV/EPR/GL,
two standing oracles. Implementation may begin against §8.
