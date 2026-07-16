# SGPE/03 — Evaluator: Architecture Blueprint

Phase 3 output. Architecture only. Extends SGPE/00 (§3.3, §6–§8) with
SGPE/01–02 as canon; no defect found — no redesign. The Evaluator is the
smallest part of SGPE by design: everything hard was pushed into the
Compiler precisely so this component could be an index lookup with a trace.

---

## 1. Nature

The Evaluator answers policy Questions. It is a pure, deterministic,
clock-free function:

```
Decision = f(compiled snapshot, grant slice, canonical Question)
```

All three arguments are immutable values identified by stamps: the snapshot
by its version (AC-8), the grant slice by ledger position (SGPE/00 §3.5 —
supplied *to* the Evaluator by its caller, never fetched by it), the
Question by its canonical content. The function body contains no judgment:
the snapshot is totally decided (D3), grant matching is exact (§6), so
evaluation is retrieval of decisions already made — at compile time by the
Compiler, at authoring time by humans, at approval time by grantors.

**Owns:**

- the canonical Question model and its well-formedness rules (§3)
- the Decision model and its semantics (§4)
- the explanation/citation contract (§5)
- grant-overlay application (§6) — mechanical, not judgmental
- memoization correctness rules (§8)
- the ill-posed outcome class (§9)

**Never owns:**

| Not the Evaluator's | Owner |
|---|---|
| Reading the Policy Store | Compiler (the Evaluator sees only compiled indexes) |
| Compilation, conflict resolution | Compiler — every overlap inside a snapshot was decided or rejected before the Evaluator exists (AC-3/AC-5) |
| Fetching grants | Resolver/Grant Ledger (Phase 4) — grants arrive as input |
| Enforcement, execution | consuming subsystems |
| Usage metering | Observability — usage numbers are facts *inside* the Question (D2) |
| Approval collection | IVS |
| Audit persistence | Observability via bus events (INV-8) |
| Policy mutation, learning | nothing mutates here; the Evaluator has no state at all beyond its memo table (§8) |

---

## 2. Evaluation philosophy

Three commitments:

1. **Retrieval, not reasoning.** Runtime never weighs anything. If
   answering a Question would require a judgment the compiled artifacts
   don't already encode, the Question is ill-posed (§9) — by construction
   this only happens on malformed input, never on valid policy, because
   totality (INV-12) guarantees every well-formed Question has an answer.
2. **Everything in, one answer out.** The Question carries every fact;
   the Decision carries every consequence (effect *and* binding
   constraints, §4). No follow-up lookups in either direction — one
   round trip is the whole protocol.
3. **No answer means no action.** The Evaluator itself never fails open or
   closed — it returns Decisions or ill-posed verdicts. The *fail-closed*
   rule lives at the consumer: a consumer that cannot obtain a Decision
   must treat the action as forbidden (Law 4 discipline). Stated here
   because the Evaluator's contract is what makes the rule enforceable:
   Decisions are cheap, deterministic, and always available for well-formed
   asks, so "couldn't ask" is never a legitimate excuse.

---

## 3. The Question

A canonical, self-contained fact bundle (SGPE/00 §3.3, now made precise):

- **Subject** — requesting subsystem, request id, principal.
- **Action** — domain + operation, in vocabulary terms.
- **Resource** — the concrete selector instance (path, repo, host, model
  id, …) the action touches.
- **Facts** — every environmental value any potentially applicable rule's
  condition reads: usage numbers (Observability-sourced, supplied by the
  caller), time *as a declared fact* if any rule conditions on it, request
  attributes. The compiled snapshot declares which fact names its rules
  consume per (domain, operation) — so callers know exactly what to supply,
  and completeness is checkable before evaluation begins.

**Canonicalization is part of the model:** one byte representation per
logical Question (sorted fact names, normalized selectors, vocabulary-
versioned terms). The Evaluator rejects non-canonical input as ill-posed
rather than normalizing it — silent normalization would make the memo key
(§8) and the audit record disagree about what was asked.

The Question is deliberately *flat*: no nested queries, no "and also check…"
batching, no wildcard asks ("what would be allowed?"). One action instance,
one answer. Enumeration-style questions ("list everything I may do") are an
authoring/IVS concern over the Store and manifests, not a runtime decision —
admitting them would turn the Evaluator into a query engine.

---

## 4. The Decision

```
Decision = effect + binding constraints + explanation + stamps
```

- **Effect** — exactly one of the SGPE/00 alphabet:
  - `ALLOW` — the action may proceed, subject to the attached constraints.
  - `DENY` — forbidden. Terminal for this Question; carries the denying
    citation.
  - `REQUIRE_APPROVAL` — forbidden *until* a grant exists. Carries an **ask
    signature**: the canonical identity of what a grant must cover (§6).
    The consumer routes it via IVS (SGPE/00 §3.5); SGPE's involvement ends
    at returning it.
  - `LIMIT(values)` — for Questions whose domain answers in ceilings
    (token-budget, context-limit, resource-limit, retry-limit): the binding
    ceiling values.
- **Binding constraints** — constraint propagation, made explicit: an
  `ALLOW` on a permission domain also carries every limit-domain ceiling
  that binds the same action scope (e.g., ALLOW execution *with* its token
  budget and retry limit), each with its own citation. One Question about
  "may I" returns everything the consumer must respect while doing —
  without this, every ALLOW would spawn N follow-up limit Questions, and a
  consumer could act on the permission while forgetting to ask for the
  leash.
- **Explanation** — §5.
- **Stamps** — snapshot version, grant-ledger position (when a grant slice
  was in play), evaluation ruleset version (§10). The stamps are the replay
  coordinates: Decision = f(stamps, Question), reproducible forever.

Effects don't compose across Questions and Decisions carry no validity
duration — a Decision is an answer about the asked instant's facts, and
*staleness is the caller's problem by design*: facts change (usage grows),
so the Resolver/consumers decide when to re-ask. Nothing in the Decision
expires, because nothing in it is time-dependent (time, if relevant, was a
fact in the Question).

---

## 5. Explanation and citations

**The explanation is the evaluation trace, not a reconstruction** (SGPE/00
§3.3, INV-7). It contains, in evaluation order:

1. the matched compiled index entries, each with its embedded citation
   triple `(document id, document version, rule id)` (AC-6);
2. for decided overlaps baked in at compile time — the winner is in the
   index, and the index entry carries the *decided-by* marker (which of the
   3 rules ordered it) recorded by the Compiler, so the runtime trace shows
   inherited precedence without re-deriving it;
3. any grant application: grant id, ledger position, what it overrode;
4. for constraint blocks: one citation per attached ceiling;
5. the totality fallback when no specific rule matched: the system-default
   rule's citation (there is always one — INV-12).

Citations resolve through the Store (SGPE/01 §3) for human display by IVS —
resolution is the *reader's* act; the Evaluator emits triples, never
document content. Explanations are canonical-ordered and byte-stable (same
inputs, same explanation bytes) — they are part of the Decision, inside the
replay guarantee, not decoration around it.

---

## 6. Grants at evaluation

Grants are the one input that isn't compiled (AC — §10: deliberately). The
architecture keeps them judgment-free:

- A grant covers an **ask signature** — the canonical identity emitted by a
  prior REQUIRE_APPROVAL Decision (§4). Matching is *exact signature
  equality*, not selector overlap analysis. No grant can partially
  intersect a Question; it either covers this ask or it doesn't.
- Precedence is fixed by SGPE/00 §5: grant scope is highest. Within the
  slice, revocation-beats-grant is deny-overrides (SGPE/00 §6 rule 2)
  applied to at most a handful of entries — mechanical application of the
  canon procedure to an exactly-matched set, not conflict *resolution*
  (nothing undecidable can arise from exact matches plus a fixed order).
- `final` rules ignore grants entirely — the Compiler guaranteed no
  activated snapshot contradicts a `final`, and the Evaluator applies
  `final` before the grant overlay, so a grant against a `final` DENY
  changes nothing (SGPE/00 §6).
- The grant slice arrives as an input value (Resolver-supplied, position-
  stamped). An empty slice is the common case and costs nothing.

This resolves the brief's tension ("never perform conflict resolution" vs.
grants overriding rules): the Evaluator applies a decided order; it never
decides an order.

---

## 7. Evaluation lifecycle

Per Question, fixed and short:

```
[1 well-formedness] → [2 memo probe] → [3 index match] → [4 final check]
    → [5 grant overlay] → [6 constraint attachment] → [7 Decision + trace]
```

1. Canonical-form and completeness check (declared fact names present,
   §3). Failure ⇒ ill-posed (§9), evaluation never starts.
2. Memo probe (§8); hit returns the stored Decision byte-identically.
3. Compiled index lookup by (domain, operation, resource selector, facts) —
   the totally-decided snapshot yields exactly one winning entry (possibly
   the system default).
4. If the winner is `final`, done at step 7 — grants skipped by canon.
5. Exact-signature grant overlay (§6).
6. Attach binding ceilings for the action scope (permission domains only).
7. Assemble Decision, emit `policy.decided` event (INV-8), memoize, return.

No stage loops, recurses, or re-enters. Worst case is one index traversal
plus a bounded grant-slice scan — the request-path cost SGPE promised in
Phase 0 (§11).

---

## 8. Memoization

Pure memoization, exactly as SGPE/00 §8 promised — now with the key made
precise:

```
key = (snapshot version, grant-slice position, evaluation ruleset version,
       canonical Question hash)
```

- Every input that can change the answer is in the key; nothing else is.
  Correctness by key, not by coordination — no TTLs, no invalidation
  protocol, no staleness class, ever.
- Questions with an empty grant slice omit nothing: the slice position is
  part of the key even when empty (position P with no matching grants and
  position Q with one are different keys — cheap insurance against the
  subtlest cache bug available here).
- The memo table is the Evaluator's only state, and it is *semantically
  invisible*: evict any entry, all entries, at any moment — behavior is
  unchanged by D1. Sizing/eviction is an implementation concern with zero
  architectural weight, which is precisely the property that makes
  consumer-side caches equally legal (same key, same guarantee, SGPE/00
  §8).
- Memoized Decisions are byte-identical to computed ones, *including
  explanation and stamps*. A cache that strips traces would fork the audit
  record.

---

## 9. Failure behavior

Two outcome classes, never confused:

- **Decisions** — ALLOW / DENY / REQUIRE_APPROVAL / LIMIT. Policy answers.
- **Ill-posed** — the Question itself is defective: non-canonical form,
  unknown vocabulary terms, missing declared facts, stamp referencing a
  snapshot version that doesn't exist. Not a policy answer — a protocol
  error, with its own diagnostic detail (what was malformed), emitted as
  `policy.illposed` on the bus. Consumers must treat it as no-Decision (§2
  rule 3: no action) — but it is *not* recorded as a DENY, because a DENY
  cites policy and an ill-posed ask indicts the caller. Conflating them
  would poison both audit (phantom denials) and diagnostics (real bugs
  dressed as policy).
- **Crash-free by shape**: the Evaluator holds no state that can corrupt
  (memo entries are disposable), performs no I/O that can fail mid-write
  (the event emission is the bus's at-least-once problem), and a crashed
  evaluation is simply re-asked — purity makes retries free and idempotent.

The Evaluator never guesses: no default-fact substitution, no "probably
meant", no partial answers. Every lenient path is a determinism leak.

---

## 10. Determinism, replay, versioning

- **D1–D3 discharged here:** same (stamps, Question) ⇒ same Decision bytes.
  No clock (time is a fact), no I/O reads, no randomness, no iteration-
  order leaks (canonical ordering throughout, mirroring R3).
- **Replay** = re-evaluation from stamps: audit fetches the recorded
  Question and stamps, re-runs, byte-compares (SGPE/00 §8). Works forever
  because snapshots are regenerable (AC-9) and grant slices reconstruct
  from any ledger position (INV-9/PS-5 discipline).
- **Evaluation ruleset version** — mirror of the compiler ruleset version
  (R4): the Evaluator's own semantics (lifecycle order, grant-overlay
  mechanics, canonicalization rules) are versioned, stamped into every
  Decision, and historical replays run under the recorded version. Same
  rationale: the first Evaluator bug fix must not silently falsify history.

---

## 11. Interactions

| Neighbor | Relation |
|---|---|
| Compiler (Phase 2) | Sole supplier: compiled indexes keyed by snapshot version, with embedded citations, decided-by markers, per-(domain, operation) declared fact names. The Evaluator trusts total-decidedness absolutely — that trust is the whole design |
| Policy Store (Phase 1) | **None at runtime** (constraint honored structurally: the Evaluator holds no Store reference; citation resolution is the reader's act, §5) |
| Resolver (Phase 4) | Primary caller. Supplies stamps + grant slice; the frozen Effective Policy (D5) is operationally "the Resolver pinning one (snapshot, position) pair for a request's lifetime and asking through it" |
| Grant Ledger (Phase 4) | Indirect only — slices arrive via the Resolver; ask signatures emitted here are what grants get keyed to |
| Consumers (all 11) | Ask Questions (directly or via their frozen Effective Policy view); enforce Decisions; supply their own usage facts. GOVERNANCE-REFUSED (RO) = an enforced DENY from here |
| Observability | `policy.decided` / `policy.illposed` events; sole audit sink (INV-8) |

---

## 12. Extensibility

- **New domain** — new vocabulary + rules compile into snapshots; the
  Evaluator is domain-blind (indexes and fact declarations come from the
  Compiler). Zero change — INV-11 holds through this phase.
- **New effect kinds** — closed by intent. The four-effect alphabet is
  SGPE/00 canon; a fifth effect is an SGPE/00 errata event rippling through
  Compiler and every consumer, exactly as expensive as it should be.
- **New condition grammar forms** — arrive via compiler ruleset versions;
  the Evaluator needs the matching evaluation ruleset version (§10) — the
  two version lineages advance together when the grammar grows.
- **Richer explanations** — additive: new trace detail is legal anytime
  (it versions the evaluation ruleset); *removing* trace content never is.

---

## 13. Invariants (EV-1…10, review gate)

| # | Invariant |
|---|---|
| EV-1 | Evaluation is a pure function of (snapshot version, grant-slice position, evaluation ruleset version, canonical Question) — byte-replayable, clock-free, I/O-free |
| EV-2 | The Evaluator never reads the Policy Store, never invokes the Compiler, never fetches grants — all inputs arrive as stamped values |
| EV-3 | The Evaluator retrieves decided outcomes; it never resolves conflicts, weighs rules, or exercises judgment |
| EV-4 | Every Decision carries exactly one effect, its binding constraints, a trace-derived explanation with citation triples, and full replay stamps |
| EV-5 | Grant application is exact ask-signature matching under the fixed canon order; `final` rules are applied before, and are immune to, the grant overlay |
| EV-6 | Ill-posed Questions are a distinct outcome class — never a DENY, never guessed into well-formedness, never evaluated |
| EV-7 | Memoization is keyed by every answer-changing input and nothing else; memoized and computed Decisions are byte-identical including explanations |
| EV-8 | The memo table is semantically invisible: any eviction at any time changes no behavior |
| EV-9 | Evaluation semantics are versioned; every Decision stamps its evaluation ruleset version, and replay runs under the recorded version |
| EV-10 | Every Decision and every ill-posed verdict is a bus event; the Evaluator persists nothing |

---

## 14. Assumption challenges (Phase 3 due diligence)

- **"Decision = f(Snapshot, Question)" (the brief's signature)** — extended
  to include the grant slice and ruleset version. Phase 0 already committed
  grants to "ordinary rules as data, no special path" (§3.5) and put ledger
  position in the cache key (§8); a two-argument signature would force
  grants either into snapshots (rejected in AC — request-path compilation)
  or into the Question (worse: callers asserting their own grants). The
  slice as a third stamped input is the only shape consistent with prior
  canon. Not a defect in Phase 0 — a precision pass on it.
- **Wildcard / enumeration Questions** — rejected (§3): they answer "what
  is policy" (a Store/manifest reader's question) not "may I do this now"
  (the runtime question), and admitting them makes the Evaluator a query
  engine with unbounded answer shapes.
- **Decision validity windows / TTLs** — rejected (§4): nothing in a
  Decision is time-dependent, so expiry would be a fiction; re-asking on
  fact change is the Resolver/consumer's explicit job.
- **Fail-open for "low-risk" domains** — rejected (§2): one fail-open path
  anywhere makes every enforcement argument probabilistic. No-Decision =
  no-action, uniformly.
- **Missing and added** — three precision items: **binding-constraint
  attachment** (§4; without it every ALLOW under-informs its enforcer),
  the **ill-posed outcome class** (§9; without it protocol errors
  masquerade as policy denials in the audit record), and the **evaluation
  ruleset version** (§10; same replay-honesty argument as R4). All three
  are additive refinements inside Phase 0's envelope.
