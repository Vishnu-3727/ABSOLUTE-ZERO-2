# SGPE/01 — Policy Store: Architecture Blueprint

Phase 1 output. Architecture only. Extends SGPE/00 (canon); no Phase 0
redesign — no defect found that would warrant one. Everything here refines
SGPE/00 §3.1 (Policy Store), §4 (lifecycle), §5 (scopes), §9 (domains)
without contradicting an invariant.

---

## 1. Nature

The Policy Store is the passive, deterministic repository of all authored
governance data. It is a library, not a librarian with opinions: it keeps
documents, their complete history, and a catalog of what exists — and does
nothing else.

**Owns:**

- authored policy documents, every version, forever
- the domain vocabulary registry (as documents — §6)
- snapshot manifests (records of which document versions a compiled snapshot
  was built from — §9)
- the catalog: what exists, in which scope, touching which domains

**Never owns** (each already homed by SGPE/00):

| Not the Store's | Owner |
|---|---|
| Evaluation, answering any policy question | Evaluator |
| Semantic validation, conflict detection | Admission Compiler |
| Compiled decision indexes | Compiler (regenerable artifact, not stored data) |
| Effective Policies | Resolver |
| Grants | Grant Ledger |
| Caches of any kind | consumers / Evaluator memoization |
| Enforcement, metering, approval workflows | consuming subsystems / IVS |
| Physical persistence machinery | Storage (Law 3 — the Store writes *via* Storage, single logical writer for its own data) |

The Store answers exactly two kinds of request: "give me these document
versions" and "what documents exist (in scope X / domain Y / as of catalog
position P)". Both are reads of recorded fact. It never answers "what is
allowed" — that question does not parse here.

---

## 2. Policy representation

Policies are declarative data. The unit of authoring, versioning, and
storage is the **Policy Document**. A document contains:

- **Header** — identity (§3), scope (one of SGPE/00 §5's four), declared
  domain references, provenance (author principal, authoring timestamp,
  reason-for-change text), and the vocabulary version the document was
  authored against.
- **Rules** — an ordered list. Each rule is a data record:
  - `rule id` — unique within the document
  - `target` — domain + operation + resource selector, in vocabulary terms
  - `effect` — one of ALLOW / DENY / REQUIRE_APPROVAL / LIMIT(value), the
    SGPE/00 §3.3 decision alphabet
  - `condition` (optional) — a declarative predicate over declared Question
    facts, drawn from a closed, versioned condition grammar (comparisons,
    set membership, boolean composition — nothing Turing-complete, no
    escape hatch to code)
  - `final` (optional) — SGPE/00 §6's only modifier; legal at system scope
    only, and the Store records it as data like any field

What a rule *means* is the Evaluator's business; whether a rule set is
*coherent* is the Compiler's. The Store records shape, not meaning — but the
shape is fixed and versioned (§7), so "policies are data, not code" is a
checkable structural property, not a convention.

---

## 3. Identity and versioning

Three-level identity, all deterministic:

1. **Document id** — stable: `(scope, name)`. Never reused, never renamed
   (a rename is a new document plus deprecation of the old).
2. **Document version** — monotonic integer per document id, assigned by
   the Store on append. Version N+1 supersedes N. No branches, no forks —
   policy history is a straight line per document.
3. **Content hash** — hash of the canonical serialized document. Integrity
   check and replay anchor; two identical contents at different versions
   are legal (rollback re-issues old content as a new version, SGPE/00 §4).

**Global rule reference** = `(document id, document version, rule id)`.
This triple is what Evaluator citation chains (SGPE/00 §3.3) and audit
events point at, which is why all three parts are immutable once written.

**Append-only evolution.** A document version, once written, never changes
— not its rules, not its metadata, not its provenance. Every mutation in
the human sense (edit, deprecate, rollback, rename) is a new version or a
new document. Deletion does not exist.

---

## 4. Lifecycle of a policy document

States are recorded facts in the catalog, not behaviors:

```
authored → admitted → in-force → superseded → deprecated → archived
```

- **Authored** — appended to the Store; exists, addressable, not yet part
  of any snapshot. The Store's structural gate (§7) has passed.
- **Admitted** — a compile (Phase 2's act) accepted it into a snapshot
  manifest. The Store merely records the manifest (§9).
- **In-force** — the snapshot referencing it is the active one. "Active" is
  a single catalog fact written atomically at activation (SGPE/00 §4); the
  Store holds the fact, the Compiler's activation act writes it.
- **Superseded** — a newer version of the same document is in a newer
  active snapshot. Old version remains addressable forever.
- **Deprecated** — an explicit authored marker version stating the document
  should no longer be included in future compiles. Deprecation is itself an
  append (provenance and reason recorded); the Compiler honors it, the
  Store just records it.
- **Archived** — a cold-storage placement hint for versions no active or
  recent snapshot references. Purely operational: archival never removes
  addressability, never alters content, never drops history. An archived
  version resolves identically, just slower.

No state transition is performed *by* the Store on its own initiative — the
Store has no clock, no triggers, no daemon behavior. Every transition is an
externally caused append (an authoring act, a compile, an activation), which
is what keeps the Store deterministic: its entire state is a pure function
of the append sequence.

---

## 5. Organization and discovery

The **catalog** is the Store's index: an append-only record with a monotonic
**catalog position** (same discipline as LIE's ledger position and the Grant
Ledger). Each append (new document version, deprecation marker, manifest,
activation fact) advances the position.

Organization axes — exactly the ones evaluation will need, nothing
speculative:

- **by scope** — system / project / user (request-grants live in the Grant
  Ledger, not here)
- **by domain** — via the header's declared domain references
- **by state** — the §4 lifecycle facts

Discovery is deterministic enumeration: "all document versions applicable to
scope S, as of catalog position P" always returns the same list. Position-
stamped reads are what lets the Compiler build reproducible snapshots and
lets audit replay reconstruct exactly what the Store contained at any past
moment. There is no search ranking, no relevance, no fuzziness — discovery
is a database question with one right answer.

---

## 6. Domain vocabulary registry

SGPE/00 §9's controlled vocabulary lives in the Store as documents of a
distinguished kind (`vocabulary` documents, system scope), because it must
share every property policy documents already have: versioned, append-only,
provenance-carrying, position-stamped.

- Additive-only: a vocabulary version may add domains, operations, and fact
  names; it may never remove or redefine them (LIE/01 precedent).
- Policy documents record the vocabulary version they were authored against
  (§2); the Compiler checks the terms — the Store only guarantees the
  referenced vocabulary version exists.
- A **new policy domain is one vocabulary append plus new rule documents.**
  Zero change to the Store's model — INV-11 is discharged structurally,
  because the Store never enumerates domains in its own design.

---

## 7. Validation boundary

The Store validates **structure only** — the line is sharp:

| Store rejects (structural) | Store accepts, Compiler judges (semantic) |
|---|---|
| Unparseable / schema-invalid documents | Rules referencing unknown vocabulary terms |
| Duplicate rule ids within a document | Conflicting rules (SGPE/00 §6 procedure) |
| Non-monotonic or duplicate version append | `final` contradictions across scopes |
| Identity collision (existing id, different document) | Scope-inappropriate rule content |
| Unknown schema version | Whether a deprecation should be honored |
| Reference to a nonexistent vocabulary *version* | Whether the terms used mean anything |

The document **schema itself is versioned** (`schema version` in the
header), evolved additively like the vocabulary. Old documents remain valid
under their recorded schema version forever — a schema change never
invalidates history, because history is never re-validated.

Rationale for the split: structural validation is decidable without meaning
and belongs at the write boundary (garbage never enters); semantic
validation requires the whole rule population and belongs to the compile.
Putting any semantics in the Store would smuggle Phase 2 in.

---

## 8. Persistence philosophy

- All durable writes go through **Storage** (Law 3). The Store is SGPE's
  single logical writer for governance data; Storage is the system's single
  physical writer.
- Two-part shape: **immutable content** (document versions, manifests —
  content-hashed, written once) plus the **append-only catalog** (the one
  growing record, atomic appends, monotonic position). No third kind of
  state exists.
- The catalog is the sole serialization point. That is deliberate: one
  atomic append stream is trivially consistent and trivially replayable;
  distributing it would buy write throughput the Store will never need
  (policy authoring is human-paced).
- Recovery = replay: catalog position P plus the content it references
  fully reconstructs the Store. No repair logic, no reconciliation — the
  append log *is* the truth.

---

## 9. Interactions with future SGPE phases

| Phase | Reads from Store | Writes to Store (as externally caused appends) |
|---|---|---|
| Admission Compiler (2) | Position-stamped document sets; vocabulary versions | Snapshot **manifests** — `(snapshot version, catalog position, list of (document id, version))`; activation facts |
| Evaluator (3) | Nothing directly — it reads compiled snapshots | Nothing |
| Resolver + Grant Ledger (4) | Nothing — Effective Policy stamps reference snapshot versions, resolvable via manifests | Nothing (grants live in the Ledger) |
| Integration (5) | Audit replay resolves citation triples via the Store | Nothing |

The manifest is data *about* a compile, so it belongs here (it is part of
governance history); the compiled index is a *derived artifact*, regenerable
from manifest + documents, so it does not (LIE's regenerable-intelligence
precedent — derived things are never system-of-record).

Store appends emit catalog events on the bus (`policy.authored`,
`policy.deprecated`; `policy.activated` already exists per SGPE/00 §4) —
Observability persists them (INV-8), the Store keeps no event history of its
own beyond the catalog itself.

---

## 10. Scalability

- Volume is human-paced: documents grow with authoring acts, versions with
  changes, the catalog with both. All linear, all small by database
  standards. No design pressure exists for sharding, and none is built.
- Reads dominate and are position-stamped, hence immutable, hence freely
  replicable/cacheable by callers without any coherence protocol — the
  position is the coherence protocol.
- Archival (§4) bounds the hot set to versions reachable from recent
  snapshots; history depth affects cold storage cost only, never read-path
  complexity.
- The only growth risk worth naming is **catalog scan cost** for "as of
  position P" queries as history deepens; the mitigation is ordinary
  indexing by (scope, domain, state) — an implementation concern, flagged
  here only so Phase 2+ never works around it by caching semantics.

---

## 11. Architectural risks

| Risk | Disposition |
|---|---|
| Store accretes semantics (term checking, conflict hints, "helpful" validation) | Hard boundary at §7; any semantic check in the Store is an architecture violation, review-gated by PS-6 |
| Catalog head as single mutable point | Accepted deliberately (§8): single atomic append stream, human-paced writes; the alternative buys nothing and costs determinism |
| Version sprawl / unbounded history | By design — history is the product. Archival manages cost; addressability is never sacrificed |
| Vocabulary drift (documents authored against stale vocabulary) | Recorded vocabulary version per document makes staleness a visible, compile-time-checkable fact, not silent rot |
| Schema evolution invalidating old documents | Versioned schema, additive evolution, history never re-validated (§7) |
| Rename/reuse of document ids corrupting citations | Ids never reused (§3); rename = new document + deprecation |

---

## 12. Invariants (PS-1…10, review gate)

| # | Invariant |
|---|---|
| PS-1 | The Store stores, catalogs, and returns policy data; it never evaluates, compiles, resolves, enforces, or caches |
| PS-2 | Document versions, once written, are immutable — content, metadata, and provenance alike; deletion does not exist |
| PS-3 | Document versions are monotonic per document id; ids are never reused or renamed |
| PS-4 | Every stored artifact is addressable forever; archival changes placement, never addressability or content |
| PS-5 | The catalog is append-only with a monotonic position; the Store's entire state is a pure function of the append sequence |
| PS-6 | The Store validates structure only; no semantic judgment exists in the Store |
| PS-7 | Every state transition is an externally caused append; the Store has no clock, no triggers, no self-initiated behavior |
| PS-8 | Vocabulary and document schema evolve additively; no version ever removes or redefines an existing term or field |
| PS-9 | Position-stamped reads are deterministic: identical (query, position) returns identical results, byte-for-byte |
| PS-10 | Compiled artifacts are never system-of-record; only authored documents, markers, manifests, and activation facts are stored |

---

## 13. Assumption challenges (Phase 1 due diligence)

- **"Policy activation" as a Store responsibility (brief's list)** —
  narrowed: the activation *act* is the Compiler's atomic publication
  (SGPE/00 §4); the Store holds the activation *fact*. A store that
  activates is a store that decides what is in force — semantic, rejected.
- **Should the Store store compiled snapshots?** — No; manifests only
  (§9). Storing derived artifacts as records invites drift between source
  and compilation; regenerability is the integrity guarantee.
- **Branching / draft workspaces for policy authoring** — rejected (YAGNI +
  determinism): straight-line history per document. Drafts are documents
  not yet referenced by any manifest — the `authored` state already covers
  the need without a branching model.
- **Soft delete** — rejected; deprecation markers give the human meaning
  ("stop using this") without the historical damage.
- **Missing and added** — the catalog position (§5) was implicit in Phase 0
  and is now first-class: without it, reproducible compiles and audit
  replay would depend on wall-clock timestamps, violating the no-clock
  discipline the rest of the system already follows.
