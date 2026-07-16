# SGPE/02 — Admission Compiler: Architecture Blueprint

Phase 2 output. Architecture only. Extends SGPE/00 (§3.2, §4, §6) and
SGPE/01 (canon); no defect found in either — no redesign. The Compiler is
the gate between "authored" and "in force": it is where ambiguity dies so
that runtime never meets it.

---

## 1. Nature

The Admission Compiler transforms a position-stamped set of policy documents
into a validated, totally-decided, immutable **Policy Snapshot** — or a
rejection that changes nothing. It is a build step, not a runtime component:
it runs off the request path, at human authoring pace, before anything it
produces can affect a request.

**Owns:**

- the compilation pipeline (§4) and its stage order
- all semantic validation of policy (the right-hand column of SGPE/01 §7)
- conflict detection and the *application* of the SGPE/00 §6 decision
  procedure at compile time
- snapshot construction: canonical form, compiled indexes, manifest content
- compile diagnostics and the activation-readiness verdict
- the atomic activation act (SGPE/00 §4 — publish + `policy.activated`
  event; the Store records the fact)

**Never owns:**

| Not the Compiler's | Owner |
|---|---|
| Policy storage, history, catalog | Policy Store |
| Answering runtime policy questions | Evaluator |
| Effective Policies, grants | Resolver, Grant Ledger |
| The conflict procedure's *definition* | SGPE/00 §6 (canon; closed 3-rule procedure — the Compiler applies it, never extends it) |
| Structural validation | Store write boundary (PS-6) |
| Enforcement, execution of policies | consuming subsystems |
| Runtime caching | Evaluator memoization / consumers |
| Deciding *when* to compile | Humans / authoring tooling (the Compiler is invoked, never self-triggering — same no-daemon discipline as PS-7) |

The Compiler never evaluates a Question. The distinction: the Evaluator
answers "what does the active snapshot say about these facts"; the Compiler
answers "can this document set become a snapshot at all."

---

## 2. Input contract

A compile takes exactly three inputs, all versioned data:

1. **Catalog position P** — fixes the document set: all in-scope document
   versions applicable at P, honoring deprecation markers recorded at or
   before P (SGPE/01 §5).
2. **Vocabulary version** — the newest vocabulary at P (additive lineage
   makes this safe for documents authored against older versions).
3. **Compiler ruleset version** — the version of the compilation semantics
   themselves (§8). Compilation behavior is versioned like everything else;
   "the compiler changed" is a recorded fact, never a silent drift.

Nothing else enters. No clock, no environment, no live lookups beyond the
position-stamped Store read (PS-9 makes that read deterministic). Therefore:

> **Snapshot = f(P, vocabulary version, compiler ruleset version)** — a pure
> function, byte-reproducible at any later time.

---

## 3. Validation philosophy

Three principles:

1. **Whole-population judgment.** Semantic validity is a property of the
   *set*, not the document — a rule is only conflicting, shadowed, or
   redundant relative to every other rule. This is why semantics could not
   live at the Store's write boundary and why the Compiler sees the entire
   position-stamped set at once, never incremental deltas.
2. **Reject, don't repair.** The Compiler never rewrites, reorders,
   prioritizes, or "fixes" policy to make it compile. Every repair is a
   hidden authoring act with no provenance. Humans repair; the Compiler
   reports precisely what to repair (§6).
3. **All-or-nothing.** A compile either yields a complete, totally-decided
   snapshot or a rejection. No partial snapshots, no quarantined-document
   modes, no "compiled with errors." SGPE/00 §4: failure changes nothing
   in force.

---

## 4. Compilation pipeline

Fixed stage order; each stage consumes the previous stage's output; failure
at any stage aborts with diagnostics (later stages don't run — their
judgments could be artifacts of the earlier defect):

```
P ──> [1 Assembly] ─> [2 Vocabulary] ─> [3 Scope & modifier] ─> [4 Dependency]
        ─> [5 Totality] ─> [6 Conflict] ─> [7 Construction] ─> [8 Readiness]
```

1. **Assembly** — position-stamped read at P; select latest non-deprecated
   version per document id, per scope; record the exact input set (this
   list becomes the manifest core). Structural validity is *assumed* from
   PS-6, not re-litigated — one validation boundary, owned once.
2. **Vocabulary validation** — every target term (domain, operation,
   resource selector) and every condition fact name resolves in the compile
   vocabulary version. Documents authored against older vocabulary versions
   pass by additivity; a term that no longer resolves is impossible by
   PS-8, so any failure here indicates data corruption, not authoring error
   — flagged as such.
3. **Scope & modifier legality** — `final` at system scope only (SGPE/00
   §6); rule content appropriate to its document's scope; no higher-scope
   rule contradicting a `final` rule (the `final` check is here, before
   conflict detection, because it is a legality question, not a precedence
   question).
4. **Dependency validation** — the referenced vocabulary versions and
   schema versions exist (Store guarantees existence; the Compiler checks
   *coherence*: no document may reference a vocabulary version newer than
   the compile vocabulary). Policy documents do not reference each other by
   design (SGPE/01 straight-line history, no imports) — so "dependency" is
   deliberately this thin. A cross-document reference mechanism is a
   rejected feature, not an omission: imports would make document meaning
   context-dependent and history non-local.
5. **Totality check** — INV-12: the system-default scope answers every
   (domain, operation) pair in the compile vocabulary. A vocabulary append
   without a corresponding system-default rule is caught here — the moment
   a domain exists, silence is illegal.
6. **Conflict detection** — the heart. For every overlapping rule pair
   (same domain/operation, intersecting resource selectors, non-disjoint
   conditions), apply the SGPE/00 §6 procedure: scope precedence, then
   deny-overrides, then minimum-limit. Every overlap must be *decided* by
   exactly those three rules. Anything else — incomparable limits of
   different shapes, effect clashes the procedure doesn't order,
   condition overlaps whose intersection is not statically decidable in
   the closed condition grammar — is a rejection citing the pair. The
   closed grammar (SGPE/01 §2) is what makes overlap decidable at all;
   this stage is the reason the grammar must stay closed.
7. **Snapshot construction** — canonicalize (deterministic ordering of
   documents, rules, and index entries — no hash-map iteration order, no
   authoring-time ordering leaks), then build the compiled decision indexes
   (by domain/operation/scope) that the Evaluator will read. Every compiled
   entry carries its citation triple `(document id, version, rule id)` —
   traceability is embedded in the artifact, not looked up later.
8. **Readiness verdict** — the candidate snapshot plus manifest plus
   diagnostics report. Activation (§7) is a separate act.

Stages 2–6 emit *all* findings of their stage before aborting (a rejected
compile reports every vocabulary failure, not the first), but stage order is
still fail-stop across stages — conflict analysis over a non-total rule set
would report phantom conflicts.

---

## 5. Conflict detection philosophy

- **Static, exhaustive, pairwise.** All overlaps are found at compile time
  by analysis of targets and conditions in the closed grammar. Exhaustive
  is affordable because policy volume is human-paced (SGPE/01 §10) and
  compilation is off the request path — correctness buys are worth
  quadratic cost here.
- **Decided ≠ deleted.** An overlap the 3-rule procedure decides is *kept*,
  with the decided winner recorded in the index and the losing rule still
  cited in the snapshot's shadowing report (§6) — humans should see what
  their precedence bought them.
- **The procedure is canon, closed, and elsewhere.** SGPE/00 §6 defines it;
  the Compiler applies it verbatim. No weights, no tie-breakers, no
  compiler-local heuristics — adding a fourth resolution rule is an
  SGPE/00 architecture change (INV-4), not a compiler feature.
- **Undecidable = authoring error.** The rejection names the rule pair, the
  overlap witness (a concrete domain/operation/selector instance both rules
  cover), and which of the three rules failed to separate them. The fix is
  always an authoring act.

---

## 6. Compile diagnostics

One deterministic **Compile Report** per compile, canon-ordered (same inputs
⇒ byte-identical report — diagnostics obey the same reproducibility law as
snapshots):

- **Errors** (any ⇒ rejection): vocabulary failures, legality violations,
  totality gaps, undecidable conflicts. Each carries citation triples and,
  for conflicts, the overlap witness.
- **Warnings** (never block): decided-overlap shadowing (a rule fully
  eclipsed by precedence), rules referencing deprecated documents' terms,
  documents authored against old vocabulary versions. Warnings exist for
  humans and LIE-mediated advice; they have zero runtime meaning.
- **Manifest echo**: the exact input set (P, versions) so the report alone
  identifies what was judged.

The report is emitted as a bus event (`policy.compiled` on success,
`policy.rejected` on failure) and persisted by Observability (INV-8). The
Compiler keeps no report archive of its own.

---

## 7. Snapshot, versioning, activation

- **Manifest** — `(snapshot version, catalog position P, vocabulary
  version, compiler ruleset version, list of (document id, version))` —
  appended to the Store (SGPE/01 §9). System of record.
- **Compiled index** — the Evaluator-facing artifact. Derived, regenerable
  from the manifest (byte-identically, by §2), therefore *never* system of
  record (PS-10). Its integrity anchor is a content hash recorded in the
  manifest: any stored copy is verifiable against, and replaceable by,
  regeneration.
- **Snapshot version** — monotonic, assigned at activation, not at compile.
  A compile produces a *candidate*; candidates may be built, inspected, and
  discarded freely (dry-run compiles are just compiles whose candidates are
  never activated — no special mode exists). Version numbers belong to the
  activation sequence because "which snapshot is active" is the only fact
  runtime cares about (D6).
- **Activation** — atomic: one Store append recording (snapshot version,
  manifest) as the new active fact, plus the `policy.activated` event
  carrying old/new versions. Precondition: a readiness verdict with zero
  errors. In-flight requests keep their frozen Effective Policy (D5);
  activation is invisible to them.
- **Rollback** — recompile at the old manifest's inputs (byte-identical by
  reproducibility), activate as a new version. No "reactivate v3" primitive
  — versions only move forward (SGPE/00 §4).

---

## 8. Determinism and reproducibility guarantees

| # | Guarantee |
|---|---|
| R1 | Compilation is a pure function of (P, vocabulary version, compiler ruleset version) — no clock, no environment, no non-positional reads |
| R2 | Identical inputs produce byte-identical candidate snapshots *and* byte-identical Compile Reports |
| R3 | Canonical ordering everywhere — no data structure iteration order, authoring order, or filesystem order leaks into the artifact |
| R4 | The compiler ruleset version is recorded in every manifest; a semantics change is a new version, and old manifests recompile under their recorded version (the regeneration oracle stays honest across compiler evolution) |
| R5 | Standing equivalence obligation (LIE precedent): regenerating any manifest's snapshot must reproduce its recorded content hash — a permanent, testable oracle for both compiler correctness and artifact integrity |

R4 is the subtle one: reproducibility is a *versioned* promise. Without it,
the first compiler bug fix silently breaks every historical replay; with it,
"recompile under the recorded ruleset version" keeps history honest while
letting the compiler evolve.

---

## 9. Failure handling

- Rejection is the designed outcome, not an exception path: nothing in
  force changes, the report says exactly why, the authoring loop iterates.
- A *crashed* compile (as opposed to a rejecting one) leaves no partial
  state by construction: candidates are not registered anywhere until the
  single atomic activation append; a crash means the append never happened
  and the world is exactly as before. Recovery = rerun; purity makes reruns
  free.
- Corruption-class findings (stage 2's "impossible" vocabulary failures)
  are surfaced as a distinct error class — they indicate Store-integrity
  problems, and mislabeling them as authoring errors would send humans to
  fix the wrong thing.

---

## 10. Interactions

| Neighbor | Relation |
|---|---|
| Policy Store | Position-stamped reads (PS-9); appends manifests and activation facts as externally caused catalog appends (SGPE/01 §4, §9). The Compiler is the *only* writer of manifests and activation facts |
| Evaluator (Phase 3) | Consumes compiled indexes keyed by snapshot version; trusts total-decidedness (D3) — the Evaluator's simplicity is purchased entirely here |
| Resolver + Grant Ledger (Phase 4) | Effective Policy stamps reference snapshot versions the Compiler activated. Grants are *not* compiled — they are runtime-scope data evaluated per SGPE/00 §3.5; the Compiler never sees the Grant Ledger |
| Integration (Phase 5) | `policy.compiled` / `policy.rejected` / `policy.activated` events; Observability persists; audit replay uses R4/R5 to re-derive any historical snapshot |
| IVS / humans | Compile Reports are the authoring feedback loop (rendered by IVS; advised on by LIE → humans; SGPE/00 §10) |

Grants deliberately bypass compilation: they are narrow, request-scoped,
append-only facts whose "conflicts" are already decided by scope precedence
(grant scope is highest) plus deny-overrides within the ledger — the 3-rule
procedure decides them at evaluation without whole-population analysis.
Compiling per-grant would put the Compiler on the request path, breaking §1.

---

## 11. Extensibility

- **New domain** — vocabulary append + system-default rules; the pipeline
  is domain-blind (stage 5 reads the vocabulary, not a domain list). Zero
  compiler change — INV-11 holds through this phase.
- **Condition grammar growth** — additive grammar versions, each new form
  arriving *with* its static overlap-decidability rule (a form stage 6
  cannot decide is inadmissible by definition). Grammar version rides the
  compiler ruleset version.
- **New diagnostics** — warnings are freely extensible (no runtime
  meaning); new *error* classes change what can compile and therefore ride
  the compiler ruleset version like semantics changes.
- **Closed by intent**: the 3-rule procedure, the all-or-nothing law, and
  the reject-don't-repair stance. These are the architecture; extending
  them is an SGPE/00 errata event, not a compiler version bump.

---

## 12. Invariants (AC-1…10, review gate)

| # | Invariant |
|---|---|
| AC-1 | The Compiler compiles and activates; it never stores (beyond manifest/activation appends), evaluates, resolves, enforces, or answers runtime questions |
| AC-2 | Compilation is a pure function of (catalog position, vocabulary version, compiler ruleset version); byte-reproducible, clock-free |
| AC-3 | Compiles are all-or-nothing: a complete totally-decided snapshot or a rejection that changes nothing in force |
| AC-4 | The Compiler applies the SGPE/00 §6 procedure verbatim; it never repairs, reorders, or prioritizes policy, and never adds resolution rules |
| AC-5 | Every undecidable overlap is a rejection citing the rule pair and an overlap witness |
| AC-6 | Every compiled index entry carries its citation triple; traceability is embedded in the artifact |
| AC-7 | Candidate snapshots are unregistered until activation; activation is a single atomic append with a zero-error readiness precondition |
| AC-8 | Snapshot versions are monotonic and assigned at activation; rollback is recompile + forward activation |
| AC-9 | Compiled artifacts are regenerable from their manifest under the recorded compiler ruleset version, byte-identically (standing oracle) |
| AC-10 | The Compiler is invoked, never self-triggering, and never on the request path |

---

## 13. Assumption challenges (Phase 2 due diligence)

- **"Incremental compilation" for scale** — rejected. Whole-population
  analysis at human-paced volume is cheap; incrementality would trade the
  simplest correctness argument in the system (recompile everything, byte-
  compare) for speed nobody needs. If volume ever demands it, LIE's
  Equivalence Obligation pattern (incremental ≡ full regeneration, standing
  oracle) is the named upgrade path — R5 already lays its foundation.
- **"Compiler validates structure too, defense in depth"** — rejected;
  PS-6 owns structure. Two owners of one boundary means drift between two
  validators and ambiguity about which rejection is authoritative.
- **Snapshot version at compile time** — rejected in favor of at-activation
  (§7): it makes dry-run compiles a non-feature (just don't activate) and
  keeps the version sequence identical to the activation sequence runtime
  observes.
- **Grant compilation** — rejected (§10): would put compilation on the
  request path and make approval latency a compile latency.
- **Missing and added** — the **compiler ruleset version** (§2, R4). Phase
  0 versioned policies and snapshots but left compilation semantics
  implicitly eternal; making them a versioned input is what keeps replay
  honest across compiler evolution. Also added: the **overlap witness** in
  conflict rejections (§5) — a rejection without a concrete witness makes
  humans guess what the compiler saw.
