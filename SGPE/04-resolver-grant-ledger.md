# SGPE/04 — Effective Policy Resolver & Grant Ledger: Architecture Blueprint

Phase 4 output. Architecture only. Extends SGPE/00 (§3.4, §3.5, §5, §6) with
SGPE/01–03 as canon. One precision pass on Phase 0 (§3 below — the
mid-request grant question); no defect, no redesign.

Together these two parts define the **runtime policy context** of a request:
the Resolver binds a request to its governance world at admission; the
Ledger is the only governance data that can lawfully come into existence
while the system runs.

---

## 1. The Grant Ledger

### 1.1 Nature

The append-only record of approval outcomes — SGPE's only runtime-mutable
state (SGPE/00 §3.5), under the same discipline as the Store's catalog:
monotonic position, externally caused appends, no clock, no self-initiated
behavior (PS-5/PS-7 mirrored).

**Owns:** grant records, their complete history, the monotonic ledger
position, deterministic slice reads.

**Never owns:**

| Not the Ledger's | Owner |
|---|---|
| Deciding whether approval is needed | Evaluator (REQUIRE_APPROVAL) |
| Collecting the approval | IVS + Kernel (SGPE/00 §3.5) |
| Judging whether a grant *should* exist | grantor (human/Kernel principal) |
| Applying grants to Questions | Evaluator (exact-signature overlay, EV-5) |
| Compiled policy — reading or touching it | Compiler/Evaluator; the Ledger never modifies, references, or even parses snapshots |
| Persistence machinery | Storage (Law 3) |
| Audit history | Observability via `grant.recorded` / `grant.revoked` events (INV-8) |

### 1.2 Grant representation and identity

A grant is a small immutable record:

- **Grant id** — unique, never reused; assigned at append.
- **Kind** — `grant` or `revocation` (a revocation names the grant id it
  revokes; it is a new record, never an edit — INV-9).
- **Ask signature** — the canonical identity emitted by the
  REQUIRE_APPROVAL Decision it answers (EV §4/§6). The signature is the
  *entire* matching surface: grants have no selectors, patterns, or
  conditions of their own beyond it. This is what keeps grant matching
  exact and runtime judgment-free (EV-5).
- **Scope binding** — which subject the grant covers: one request id, one
  principal, or one project (SGPE/00 §5 scope 4 in its three widths; §1.4).
- **Bounds** — expiry as a declared condition, never a background timer:
  request end, a named event, or a timestamp *fact* compared inside
  evaluation (the Ledger never expires anything itself — a lapsed grant is
  one whose bound-condition evaluates false against the Question's facts).
- **Provenance** — grantor principal, the Decision (stamps + Question hash)
  that raised the ask, grant-time reason text.
- **Position** — the monotonic ledger position of the append.

Identity is the grant id; the signature is deliberately *not* unique —
several grants may cover the same signature (re-approval after lapse,
overlapping scopes). Duplicates are harmless by construction: matching
grants all say "granted," and any revocation among them wins by
deny-overrides (SGPE/00 §6 rule 2). No supersession machinery exists —
a newer grant doesn't replace an older one, it coexists; a revocation
doesn't delete, it outranks. Two primitives, zero edit semantics.

### 1.3 Validity philosophy

A grant is never valid or invalid *in the Ledger* — validity is an
evaluation-time judgment made by the Evaluator from data: signature match,
scope match, bound-condition over Question facts, absence of a winning
revocation. The Ledger stores; the Evaluator applies (EV §6). This keeps
the Ledger free of any behavior that could disagree with replay: a record's
bytes never change meaning, only the facts around it change.

`final` immunity restated for completeness: no grant, at any scope width,
touches a `final` rule (SGPE/00 §6, EV-5). The Ledger doesn't enforce this
— it can't, it doesn't read policy — the Evaluator's overlay order does.

### 1.4 Organization and slices

Indexed by exactly the axes slice reads need: scope binding (request id /
principal / project) and ask signature. A **slice** is a deterministic,
position-stamped read:

```
slice(request R, principal U, project J, position P) =
    all records at ≤ P whose scope binding ∈ {R, U, J}
```

Same arguments, same slice, byte-for-byte (PS-9 discipline). Slices are
small by nature — grants accumulate at human-approval pace, and a request's
slice is the handful of records naming it or its principal/project.

### 1.5 Citation model

Grants enter Evaluator traces as `(grant id, ledger position)` (EV §5);
revocations cite `(revocation id, revoked grant id, position)`. Resolution
to full records (who granted, why) is the reader's act against the Ledger,
exactly parallel to citation-triple resolution against the Store (EV §5).
The provenance chain closes the loop: Decision → ask signature → grant →
later Decisions citing it — every approval is traceable from first refusal
to final use.

---

## 2. The Effective Policy Resolver

### 2.1 Nature

The Resolver binds a request to its governance world, once, at admission.
It is invoked by the Execution Kernel only (SGPE/00 §10) and produces one
small immutable value — the **Effective Policy binding**:

```
EP(R) = (snapshot version S, admission ledger position P₀, request id R,
         principal U, project J)
```

**Owns:** the binding rule (§2.2), its immutability and isolation
guarantees, admission-time failure behavior.

**Never owns:**

| Not the Resolver's | Owner |
|---|---|
| Evaluating anything | Evaluator — the Resolver asks no Questions and answers none |
| Compilation, snapshot selection *policy* | Compiler activates; the Resolver reads the single active-version fact (D6) |
| Persisting the binding | RSM (stores the stamp with request state, SGPE/00 §10) |
| Enforcement | consumers |
| Grant appends | Ledger (via the approval path) |
| Mid-request policy changes | nobody — that is the point |

### 2.2 Binding philosophy

At admission the Resolver performs two atomic reads and no writes:

1. **Snapshot binding** — the active snapshot version at admission. One
   fact, atomically published (AC-7/D6), read once. The request never
   observes another snapshot: activations during its lifetime bind only
   requests admitted after them (D5).
2. **Grant baseline** — the current ledger position P₀. Standing grants
   (principal- and project-scoped) existing at P₀ are in the request's
   world from the start.

The binding is a *rule*, not a copy: EP(R) plus the (immutable, replayable)
artifacts it points at fully determines every consultation's inputs. No
policy content is duplicated into the request — SGPE/00 §3.4's "a view, not
a copy" made operational.

### 2.3 The mid-request grant question (precision on Phase 0)

The one place Phase 0's words need sharpening. INV-6 freezes the Effective
Policy for the request's lifetime; yet the approval loop *exists* to let a
running request obtain a grant after a REQUIRE_APPROVAL. Both are canon.
They reconcile cleanly because Phase 0 already made grants scope-4 data
with per-consultation ledger positions (§8: grant-sensitive keys include
the position):

> **What is frozen is the binding rule, not the slice's row count.** The
> request's grant slice may grow in exactly one way: appends whose scope
> binding names *this request id* — i.e., answers to asks this request
> itself raised. Nothing admitted after P₀ at principal/project width, and
> no snapshot activation, ever enters EP(R).

So the slice for a consultation at ledger position P is:

```
slice(R) at P = standing grants at ≤ P₀  ∪  request-R-scoped grants in (P₀, P]
```

- The world *outside* the request is frozen at (S, P₀) — no external
  actor can loosen or tighten a running request's policy from the side.
- The request's *own* approvals — and their revocations, which use the
  same request-scoped door — are visible as they land. Deny-overrides
  makes a mid-request revocation of a mid-request grant effective
  immediately, which is the behavior an emergency revocation needs.
- Every Decision stamps the actual position used (EV-1/EV-4), so replay
  reconstructs each consultation exactly (§2.5) — growth is recorded,
  never ambient.

This is a reading of INV-6, not an amendment: the Effective Policy — the
resolved policy view: snapshot, baseline, and the closed rule above — is
immutable from admission. An ERRATA.md entry will record this reading
against INV-6's wording so the interpretation is canon, not lore.

### 2.4 Lifecycle, isolation, failure

- **Created** at admission (Kernel calls, Resolver binds, RSM persists the
  stamp). **Referenced** for every consultation the request makes.
  **Retired** at request end — retirement is implicit: request-scoped
  grants lapse by their request-end bound, and the binding simply stops
  being consulted. The Resolver keeps no registry of live bindings — the
  stamp lives in RSM with the rest of request state.
- **Isolation** — concurrent requests hold independent bindings; there is
  no shared mutable resolution state anywhere (the Resolver is stateless
  between calls). Two requests admitted around an activation boundary
  lawfully run under different snapshots simultaneously; audit tells them
  apart by their stamps.
- **Failure** — no active snapshot ⇒ admission refused (fail-closed; can
  only occur before the system's first activation — **bootstrap order is
  therefore canon: first activation precedes first request admission**, a
  Phase 5 integration obligation). Ledger unreachable at admission ⇒
  admission refused, same rule: a request must never start with an
  unknown governance world. Resolver crash mid-admission ⇒ nothing was
  written anywhere (it writes nothing); re-admission re-binds, possibly to
  a newer world — correct, since the request had not begun.

### 2.5 Replay

Replay of any historical consultation needs only recorded stamps:

- EP(R) from RSM (snapshot version, P₀, scope identities);
- the per-Decision position and Question from the audit record (EV-10);
- snapshot regenerable from its manifest (AC-9); slice reconstructible
  from the Ledger at the recorded position (§1.4).

Re-run under the recorded evaluation ruleset version (EV-9), byte-compare
(SGPE/00 §8). The Resolver adds no replay machinery of its own — its whole
contribution is that the stamps *exist* and are small.

---

## 3. Interactions

| Neighbor | Relation |
|---|---|
| Execution Kernel | Sole invoker of the Resolver at request admission (SGPE/00 §10); routes approval outcomes from IVS into Ledger appends |
| RSM | Persists EP(R) with request state; never evaluates it |
| Evaluator (Phase 3) | Receives (snapshot version, slice, position) per consultation; the Resolver's binding rule is what fills the Evaluator's stamped arguments |
| Compiler (Phase 2) | Supplies the active-version fact the Resolver reads; never called by it |
| Policy Store (Phase 1) | Untouched by both parts at runtime; the Ledger is a *sibling* append-only record, not a Store tenant — grants are runtime facts, not authored policy documents, and mixing the two records would blur the authored/granted provenance line |
| IVS | Renders asks (from REQUIRE_APPROVAL's signature), returns approval outcomes; the outcome's Ledger append is the Kernel-routed act |
| Observability | `grant.recorded` / `grant.revoked` events; admission refusals surface through the Kernel's existing admission events |

---

## 4. Architectural risks

| Risk | Disposition |
|---|---|
| Mid-request grant door widened later ("just let project grants in live") | The §2.3 rule is closed and review-gated (EPR-4); widening it reintroduces mid-flight policy drift, the exact thing INV-6 exists to kill |
| Ledger accretes validity logic ("expire lapsed grants", "compact duplicates") | Barred by GL-2/GL-5; lapse is evaluation-time, duplication is harmless, compaction would rewrite history |
| Grant scope widths creep (team-, org-, time-window-scoped grants) | Three widths are canon (SGPE/00 §3.5); a new width is an SGPE/00 errata event, not a Ledger feature |
| Resolver accumulates state (live-binding registry, admission queue) | Stateless by EPR-6; request state lives in RSM, period |
| Signature drift between REQUIRE_APPROVAL and grant matching | One canonical signature definition, owned by the Evaluator (EV §4); the Ledger stores it opaquely and never parses it |
| Bootstrap deadlock (no snapshot, no admission) | Named and owned: first activation precedes first admission — Phase 5 integration obligation |

---

## 5. Invariants (review gate)

**Grant Ledger (GL):**

| # | Invariant |
|---|---|
| GL-1 | The Ledger is append-only with a monotonic position; records are immutable; deletion and edit do not exist |
| GL-2 | The Ledger stores and returns; it never evaluates, expires, compacts, enforces, or reads compiled policy |
| GL-3 | Two record kinds only — grant and revocation; revocation is a new record naming a grant id; no supersession or edit semantics exist |
| GL-4 | A grant's matching surface is exactly its ask signature plus scope binding; grants carry no selectors, patterns, or conditions of their own (bounds excepted) |
| GL-5 | Grant validity is an evaluation-time judgment from data; nothing in the Ledger changes meaning after append |
| GL-6 | Position-stamped slice reads are deterministic, byte-for-byte |
| GL-7 | Every append is a bus event; the Ledger keeps no audit trail beyond itself |

**Effective Policy Resolver (EPR):**

| # | Invariant |
|---|---|
| EPR-1 | Every request binds exactly one snapshot version and one grant baseline (P₀), at admission, atomically |
| EPR-2 | The binding is immutable for the request's lifetime; no activation or external grant ever enters a running request's world |
| EPR-3 | The Resolver never evaluates, compiles, enforces, or writes; it reads two facts and emits one value |
| EPR-4 | The grant slice grows only by request-scoped appends answering the request's own asks (the §2.3 closed rule); every consultation stamps the position it used |
| EPR-5 | Admission fails closed: no active snapshot or unreachable Ledger ⇒ no admission |
| EPR-6 | The Resolver is stateless between invocations; EP(R) persistence is RSM's |
| EPR-7 | EP(R) plus recorded per-Decision stamps reconstructs every historical consultation exactly |

---

## 6. Assumption challenges (Phase 4 due diligence)

- **"Exactly one grant slice per request" (brief)** — refined to "exactly
  one *slice rule*" (§2.3). A literally frozen slice would make the
  approval loop useless to the running request that triggered it —
  REQUIRE_APPROVAL would mean "die and retry as a new request," turning
  every approval into a request restart. The closed growth rule keeps the
  determinism (every consultation's slice is position-stamped and
  replayable) while letting approvals mean something. This is the phase's
  one genuine judgment call, recorded as an INV-6 reading + errata.
- **Grants as Store documents** — rejected (§3): the Store records what
  humans *authored*; the Ledger records what grantors *approved at
  runtime*. One record with two provenance regimes would need kind-flags
  everywhere and make "policy history" ambiguous. Sibling records, same
  discipline, different doors.
- **Grant supersession machinery** — rejected (§1.2): coexistence +
  deny-overrides already yields every needed behavior (re-grant after
  lapse, emergency revoke); an "replaces grant X" primitive is edit
  semantics smuggled into an append-only record.
- **Resolver as per-consultation gatekeeper** (every Question routed
  through a live Resolver) — rejected: it would put a stateful chokepoint
  on the request path for zero semantic gain — the binding rule is data;
  consumers/Kernel carry it (SGPE/00 §11 already promised most
  consultations don't round-trip SGPE).
- **Missing and added** — the **bootstrap ordering obligation** (§2.4):
  no prior phase said which comes first, activation or admission; leaving
  it implicit invites a fail-open hack ("no policy yet, allow all") that
  EPR-5 now forbids explicitly. Also added: **admission-refusal on
  unreachable Ledger** — silence about it would have left the one
  I/O-dependent read in SGPE's runtime path with undefined failure
  semantics.
