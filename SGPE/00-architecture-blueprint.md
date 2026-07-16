# SGPE/00 — System Governance & Policy Engine: Architecture Blueprint

Phase 0 output. Architecture only — no implementation, no APIs-as-code.
Canon status: same discipline as VAE/LIE docs — extend, never replace;
changes require errata.

---

## 1. Mission and nature

SGPE is the single source of truth for every operating policy in
ABSOLUTE-ZERO V2. It answers exactly one kind of question:

> Given this policy snapshot and these facts, is this action **allowed**,
> **forbidden**, **approval-gated**, or **limited** — and by which rules?

SGPE is a pure **Policy Decision Point**. Every consulting subsystem is its
own **Policy Enforcement Point**. This split is the load-bearing decision of
the whole architecture:

- SGPE never executes, blocks, kills, meters, throttles, retries, plans,
  reasons, verifies, learns, or stores usage. It computes decisions from
  declared data and returns them.
- Consumers must enforce what SGPE decides (Law 4 — unskippable gates — makes
  the consultation itself mandatory; the Kernel's gating makes bypass a
  protocol violation, not an SGPE concern).

This kills the god-component risk by construction: SGPE holds all *policy*,
and nothing else. A component that only evaluates rules over data cannot
accrete execution responsibilities without violating its own type.

**Alignment with existing canon.** RO/02 §7 already consumes "governance
policy as data (config version), Storage-sourced declared data" and treats
budget availability as a governance *fact passed in*. SGPE is the named owner
of exactly that contract, generalized to all eleven other subsystems. Nothing
in RO changes; RO's input #7 becomes "an SGPE decision" instead of an
anonymous config read.

---

## 2. What SGPE is not (non-responsibilities)

Named refusals, each with its rightful owner:

| Not SGPE's job | Owner | Boundary rule |
|---|---|---|
| Enforcement (blocking, killing, denying I/O) | Each consuming subsystem | SGPE returns decisions; consumers act |
| Usage metering / accounting (tokens, cost, counts) | Observability | Usage is a *fact supplied inside the Question*; SGPE owns only the *limit* |
| Approval collection (asking a human, UI, timeout of the ask) | Interaction & Visualization System | SGPE returns REQUIRE_APPROVAL; the collected grant returns to SGPE as data |
| Plugin registry stewardship | Plugin Runtime (CP/01 §9) | SGPE holds plugin *permissions*, not plugin identity/lifecycle |
| Retry execution / backoff | Workflow Scheduler & consumers | SGPE holds retry *limits* only |
| Persistence | Storage (Law 3, single writer) | SGPE persists its documents *via* Storage like everyone else |
| Audit storage | Observability (single sink) | SGPE emits decision events; it keeps no audit store of its own |
| Reasoning about what a policy *should* be | Humans + LIE advice to humans | SGPE evaluates authored policy; it never synthesizes policy |

---

## 3. Internal structure — five parts

```
authored policy docs ──> [1 Policy Store] ──> [2 Admission Compiler] ──> Policy Snapshot vN (immutable)
                                                                              │
grants ──> [5 Grant Ledger] ──────────────────────────────────────────────────┤
                                                                              ▼
consumer Question ──────────────────────────> [3 Evaluator] ──> Decision + explanation
                                                                              │
request admission ──> [4 Effective Policy Resolver] ──> frozen Effective Policy (per request)
```

### 3.1 Policy Store

Declarative policy documents — rules as data, never procedural logic.
Persisted via Storage (Law 3). Append-only version history: a policy document
is never edited in place; a change is a new version superseding the old.
Every document carries scope (§5), domain vocabulary terms (§9), and
authorship provenance.

### 3.2 Admission Compiler

The gate between "authored" and "in force." It:

1. **Validates** — schema, vocabulary terms, scope legality.
2. **Detects conflicts** — any pair of rules whose interaction is not
   decidable by the fixed precedence order (§6) is a *compile error*.
   Ambiguity is rejected at admission, never resolved at runtime. This is
   the determinism cornerstone: runtime never encounters a judgment call.
3. **Compiles** — produces an immutable, indexed **Policy Snapshot** with a
   monotonically increasing version. The snapshot is the only thing the
   Evaluator ever reads.

A snapshot that compiles is *totally decided*: every well-formed Question has
exactly one answer.

### 3.3 Evaluator

A pure function:

```
(snapshot version, canonical Question) → Decision
```

- **Question** — canonical, self-contained fact bundle: subject (which
  subsystem, which request, which principal), action (domain + operation),
  resource, and every environmental fact needed (including current usage
  numbers, supplied by the caller from Observability data). No fact is ever
  fetched by the Evaluator itself.
- **Decision** — one of `ALLOW`, `DENY`, `REQUIRE_APPROVAL`,
  `LIMIT(values)`; plus an **explanation**: the ordered citation chain of
  rule ids (with document versions) that produced the outcome, including
  which precedence step decided any overlap. Every decision is explainable
  by construction — the explanation is the evaluation trace, not a
  reconstruction.
- **Purity** — no clocks, no I/O, no randomness, no external lookups. Time,
  if a rule needs it, is a fact in the Question. Same inputs, same bytes out
  (aligns RO-I3 byte-replayability).

`LIMIT` is a decision *about* a ceiling, not a meter: "the token budget for
this scope is N." Whether N is exhausted is the caller comparing its
Observability-sourced usage fact against N — or asking a new Question with
that fact included and getting `DENY`.

### 3.4 Effective Policy Resolver

At request admission (Kernel/RSM boundary), SGPE derives the **Effective
Policy** for the request: the resolved subset of the active snapshot plus any
applicable grants, stamped with `(snapshot version, grant-ledger position)`.
It is **immutable for the request's lifetime**:

- All consultations for that request evaluate against the frozen Effective
  Policy, not "whatever is active now."
- A snapshot activation mid-request changes nothing for in-flight requests;
  new requests get the new snapshot. This mirrors LIE's Derivation State
  stamping and makes every request's governance replayable from its stamp.

The Effective Policy is a *view*, not a copy with independent life — it is
fully determined by its stamp, so persisting the stamp (RSM owns request
state) is sufficient for replay.

### 3.5 Grant Ledger

Approvals are data, not workflow. When a Decision is `REQUIRE_APPROVAL`:

1. The consumer surfaces the need (via IVS for humans, or Kernel policy for
   automated principals). SGPE is not involved in the asking.
2. The outcome, if granted, is appended to the Grant Ledger as a **grant**:
   scoped (which request/project/principal), bounded (expiry expressed as a
   condition — request end, event, or timestamp fact), and append-only
   (revocation is a new entry, never a deletion).
3. Grants participate in evaluation as the highest-precedence scope (§5) —
   ordinary rules as data, no special path through the Evaluator.

The ledger is SGPE's only mutable runtime state, and it is append-only with
a monotonic position counter — the same discipline as LIE's curation overlay.

---

## 4. Policy lifecycle

```
author → validate+compile → activate (atomic) → supersede
```

- **Author** — humans (or tooling acting for humans) write declarative
  documents. LIE may *advise* policy changes; only an authoring act creates
  one. SGPE never self-modifies.
- **Compile** — §3.2. Failure returns rejection with the conflicting rule
  pairs cited; nothing changes in force.
- **Activate** — atomic publication of the new snapshot (single Storage
  write + `policy.activated` event on the bus carrying old/new versions).
  There is never a moment when "which snapshot is active" is ambiguous.
- **Supersede** — activation of vN+1 supersedes vN. History is never
  destroyed; every prior snapshot remains addressable for replay and audit.
- **Rollback** — re-activation of an old document set as a *new* version
  (vN+2 with vN's content). Versions only move forward; no in-place revert.

---

## 5. Policy hierarchy

Four scopes, fixed total precedence order (most-specific wins):

```
system defaults  <  project  <  user  <  request-grant
```

- **System defaults** — the OS baseline; the only scope that must be total
  (every domain has a default answer, so no Question is ever unanswerable).
- **Project** — per-repository/per-project policy documents.
- **User** — per-principal policy documents.
- **Request-grant** — Grant Ledger entries (§3.5); narrowest, wins over all.

Inheritance is implicit in precedence: a scope that says nothing about a
domain inherits the answer from the scope below. No copy-down, no merge
step — resolution is evaluation-order, which keeps snapshots small and
inheritance impossible to get out of sync.

---

## 6. Conflict resolution philosophy

Exactly three rules, applied in order, and nothing else:

1. **Scope precedence** — higher scope (§5) wins over lower.
2. **Deny-overrides within a scope** — if two same-scope rules disagree on
   permission, DENY wins; REQUIRE_APPROVAL beats ALLOW.
3. **Minimum-limit within a scope** — overlapping limits combine by taking
   the most restrictive value.

Any conflict these three rules cannot decide is a **compile-time rejection**
(§3.2). The philosophy: a small closed decision procedure that a human can
hold in their head beats an extensible priority system that becomes policy
about policy. No rule weights, no "importance" fields, no last-writer-wins.

Note the asymmetry with grants: a grant (scope 4) can override a project/user
DENY — that is its purpose — but *within* the grant scope, deny-overrides
still applies (a revocation entry beats the grant it revokes). A grant can
never *loosen* a system-default structural prohibition marked
non-overridable; documents at the system scope may flag rules as `final`,
which the compiler enforces by rejecting any higher-scope rule that contradicts
them. `final` is the only rule modifier in the model.

---

## 7. Determinism guarantees

| # | Guarantee |
|---|---|
| D1 | Evaluation is a pure function of (snapshot version, canonical Question) — byte-replayable |
| D2 | Every fact enters via the Question; the Evaluator performs no lookups, reads no clock |
| D3 | Compiled snapshots are totally decided — every well-formed Question has exactly one answer |
| D4 | Conflict resolution is the closed 3-rule procedure of §6; undecidable = compile rejection |
| D5 | Effective Policy is frozen per request; mid-flight activations affect only new requests |
| D6 | Snapshot activation is atomic; active-version ambiguity cannot exist |
| D7 | Grant Ledger is append-only with monotonic positions; any (snapshot, ledger position) pair fully reconstructs past decisions |

---

## 8. Caching and audit

**Caching.** Because of D1, a decision cache is pure memoization keyed by
`(snapshot version, canonical Question hash)`. Consequences:

- No TTLs, no staleness class, no invalidation protocol. A new snapshot
  version is simply a new key space; old entries die by disuse.
- Consumers may cache locally with the same key — correctness is guaranteed
  by the key, not by coordination.
- The Effective Policy per request is itself the coarsest cache: most
  per-request consultations resolve against it without touching SGPE again.
- Grant-sensitive Questions include the ledger position in the key.

**Audit.** Every Decision is emitted as a `policy.decided` event on the
Communication bus: Question hash, Decision, citation chain, snapshot version,
ledger position, request id. Observability persists it (single sink). Audit
replay = re-evaluating the recorded Question against the recorded stamp and
comparing bytes. SGPE stores no audit trail of its own; the event canon *is*
the audit strategy. Lifecycle events (`policy.activated`, `grant.recorded`)
complete the trail: the full governance history of the system is
reconstructible from the bus record plus Storage's document history.

---

## 9. Policy domains and vocabulary

Domains are a **controlled vocabulary** (LIE/01 precedent), versioned with
the schema, additive-only. Initial set:

execution, plugin, filesystem, repository, network, shell, model,
token-budget, context-limit, resource-limit, retry-limit, persistence,
approval.

Each domain declares its operations and its answer shape (permission vs.
limit). Adding a domain = vocabulary entry + rules — **no code change** in
Store, Compiler, Evaluator, Resolver, or Ledger. That is the extensibility
claim, and it is testable: the five parts are domain-blind.

---

## 10. Interaction with every subsystem

One uniform contract for all consumers: pull-only consult (LIE Advisory
precedent). No subsystem-specific APIs, no push, no subscriptions to SGPE
(subsystems may observe `policy.activated` on the bus like any event).

| Subsystem | Consults SGPE for | Direction notes |
|---|---|---|
| Execution Kernel | Admission-time Effective Policy resolution; structural gates | The only caller of the Resolver (§3.4) |
| Request State Manager | Persists the Effective Policy stamp with request state | Stores the stamp; never evaluates |
| Unified Memory System | Persistence permissions, retention limits | |
| Context Manager | Context limits, token budgets for assembly | |
| Capability Planner | Capability/plugin permissions while planning (plan against what is allowed) | Advisory during planning; enforcement still at execution time |
| Workflow Scheduler | Concurrency/resource/retry limits | |
| Plugin Runtime | Plugin permissions, sandbox/filesystem/network scopes for a binding | PRT owns the registry; SGPE owns what a plugin *may do* |
| Reasoning Orchestrator | Model permissions, reasoning budgets (RO/02 input #7/#8 — now sourced from SGPE) | GOVERNANCE-REFUSED = enforced SGPE DENY |
| Verification & Assurance | Verification-resource limits; whether a gate may be waived (almost always `final`: no) | VAE outcomes are never policy inputs at runtime — only humans turn lessons into policy |
| Learning & Intelligence | Persistence permissions for its ledger; LIE *advises* humans on policy, never writes it | Advice → human authoring → §4 lifecycle |
| Interaction & Visualization | Renders REQUIRE_APPROVAL asks; returns grant outcomes for ledger append; displays explanations | The only path by which approvals become grants |

Two deliberate exclusions:

- **No learning loop into SGPE.** LIE-derived lessons do not auto-tune
  policy. Auto-adjusting governance from observed behavior would make policy
  nondeterministic-by-drift and unauditable-by-intent. The loop closes
  through humans.
- **No SGPE-to-SGPE recursion.** Policy about changing policy (who may
  author/activate) is itself just rules in the `approval`/`persistence`
  domains, evaluated the ordinary way.

---

## 11. Scalability

- Snapshots compile to indexed decision structures; evaluation is index
  lookup + the 3-rule procedure — no rule-list scans at runtime.
- Memoization (§8) makes repeated Questions O(1); the per-request Effective
  Policy absorbs most consultation volume without any SGPE round-trip.
- Policy volume grows with scopes and domains, both bounded and additive;
  compile cost is paid once per activation, off the request path.
- The Grant Ledger grows with approvals only; its evaluation-relevant slice
  per request is the handful of grants in scope.

---

## 12. Invariants (review gate)

Per repo convention (CP/04 §9), this list is the architecture governance
gate: any change touching an invariant is an architecture change requiring
review + errata.

| # | Invariant |
|---|---|
| INV-1 | SGPE decides; it never enforces, executes, meters, reasons, verifies, learns, or stores usage |
| INV-2 | All policy is declarative data; no procedural policy logic exists anywhere in SGPE |
| INV-3 | Evaluation is a pure function of (snapshot version, canonical Question) |
| INV-4 | Conflicts undecidable by the 3-rule procedure (§6) are compile-time rejections; runtime never resolves ambiguity |
| INV-5 | Snapshots are immutable and versioned; activation is atomic; history is never destroyed |
| INV-6 | A request's Effective Policy is frozen at admission and immutable for the request lifetime |
| INV-7 | Every Decision carries a rule-citation explanation produced by the evaluation itself |
| INV-8 | Every Decision, activation, and grant is a bus event; Observability is the sole audit sink |
| INV-9 | Grants are append-only, scoped, bounded; revocation is a new entry |
| INV-10 | Policy changes originate from authoring acts only — no self-modification, no learning loop |
| INV-11 | Domains are a versioned additive vocabulary; new domains require no SGPE code change |
| INV-12 | System-default scope is total: every well-formed Question has an answer |

---

## 13. Assumption challenges (Phase 0 due diligence)

Assumptions from the brief that were examined and where they landed:

- **"SGPE evaluates every boundary crossing at runtime"** — refined: the
  Resolver + frozen Effective Policy means most per-request checks are local
  to the consumer against the frozen view. SGPE the component is consulted
  at admission and on grant events; SGPE the *policy* governs every crossing.
  Same guarantee, no central-bottleneck topology.
- **"Token budgets are SGPE's"** — split: the *limit* is SGPE's; the *meter*
  is Observability's; the *comparison* is the consumer's (or a Question with
  usage facts). Keeping meters out preserves purity (D2).
- **"Approval workflows"** — moved: the workflow is IVS + Kernel; SGPE holds
  only the REQUIRE_APPROVAL decision and the resulting grant data. A policy
  engine that runs approval workflows is executing — INV-1 violation.
- **"Audit strategy"** — delegated: the bus/Observability event canon is the
  audit mechanism; SGPE contributes complete, replayable events rather than
  a parallel audit store (Law 3 respected).
- **Missing and added** — the `final` modifier (§6): without it, a grant
  could loosen structural safety prohibitions, which no reviewed design
  should permit; and INV-12 totality, without which "deny by default" would
  be an unstated convention instead of a checkable property.

---

## 14. Implementation shape (forward pointer, not commitment)

Five parts (§3) map naturally onto five implementation phases:
Store + vocabulary/schema → Compiler → Evaluator → Resolver + Ledger →
integration (events, consult contract, doubles for consumers). Contracts per
part follow the LIE/04 required/forbidden/guarantees pattern at freeze time.
Phase boundaries are the user's to set; this section is orientation only.
