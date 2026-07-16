# Learning & Intelligence Engine (LIE) — Phase 1: Architectural Foundation

Status: authoritative foundation for all LIE design phases. Architecture only — no
storage formats, no schemas, no record structures, no algorithms, no retrieval or
ranking design, no confidence models, no APIs, no modules. Later LIE phases refine
within these boundaries; contradictions of this document require errata here, not
silent divergence.

Lineage: this document expands `COMPONENTS/learning.md` into a full design
contract. Everything the component sheet fixes remains binding: learning consumes
only closed, verdict-tagged traces; durable writes go through Storage (Law 3);
LIE never scans repositories (Law 2); identical inputs yield identical derived
knowledge (Law 6); consumers refresh via events, never polling. Where this
document says more, it refines; where it would say less, the component sheet
still holds.

Canon carried in from the session charter, restated once and never redefined:

- UMS stores repository knowledge; LIE stores verified engineering experience.
- Only verified execution may become learning.
- Learning is deterministic.
- Recommendations are advisory only; learning never changes execution directly.
- Engineering experience survives model changes and OS changes.
- Experience is stored as human-readable, version-controlled artifacts.
- LIE is an engineering experience system, not a conversational memory system.

---

## 1. Mission

The Learning & Intelligence Engine converts verified engineering work into
durable, reusable engineering intelligence, so the operating system never pays
for the same problem twice. Its input is the attested outcome of completed work
— what was attempted, what was decided, what succeeded, what failed, what it
cost. Its product is **advice with citations**: recommendations that any
execution component may consult, each traceable to the verified records that
justify it.

LIE exists separately from the Unified Memory System because the two answer
different questions with different truth conditions. UMS answers "what is true
of this repository right now" — its knowledge is refreshed by observation and
invalidated by change. LIE answers "what has verified work taught us" — its
knowledge is accumulated by attestation and never invalidated by repository
change, only superseded by newer verified experience. A fact about code rots
when the code changes; a lesson about engineering holds until better-evidenced
experience replaces it. Mixing the two stores would force one lifecycle onto
knowledge with two different decay laws. The separation is therefore structural,
not organizational.

The division of authority is permanent and one-directional:

> **VAE attests. LIE remembers and advises. Consumers decide.**

LIE never schedules, retries, blocks, gates, or modifies anything. It answers
"what does accumulated verified experience say about this situation, and here is
the evidence" — the consulting component alone answers "so what do we do."

**Flow reconciliation.** The linear pipeline places LIE after VAE. As already
ruled for CP/00 §1, WS/00, RO/00 §1, and VAE/00 §1, this is question order, not
topology: learning is the question asked after verification renders a verdict.
ARCHITECTURE.md's hub/event topology stays authoritative.

---

## 2. Design Philosophy

| Tenet | Meaning |
|---|---|
| Attestation is the only door | Nothing becomes experience unless VAE rendered a verdict on the work it came from. Prompts, conversations, raw reasoning output, aborted runs, and unverified executions have no path into LIE — not a filtered path, no path. A verified *failure* is admissible; an unverified *success* is not. |
| Experience is fact; intelligence is derivation | LIE holds two strictly separated layers. The **experience layer** records what verifiably happened — immutable, append-only, never edited. The **intelligence layer** holds everything derived from it — patterns, anti-patterns, statistics, packs. The derived layer is always a reproducible function of the experience layer plus a versioned derivation process, and can be regenerated from scratch at any time. If a derived artifact cannot be regenerated, it is a defect. |
| Cite or stay silent | Every recommendation names the experience records that justify it. A recommendation that cannot cite its evidence is not emitted. Explainability is not a report generated after the fact; it is the admission condition for advice. |
| Advice, never action | LIE has no write path into any execution component's state. It publishes signals and answers consultations. Adoption is the consumer's decision, and the consequences of adoption re-enter LIE only as new verified experience — closing the loop through VAE, never around it. |
| Nothing model-shaped | No artifact in either layer may be meaningful only to a particular language model — no embeddings-as-truth, no model-specific weights, no opaque scores without recorded derivation. Everything is a structured, human-readable engineering record. Swapping the model must change nothing LIE knows. |
| Deprecate, never delete | Experience is permanent. Records that prove wrong, stale, or superseded are marked so, with the reason and the superseding evidence recorded — because "we used to believe X and learned better" is itself engineering experience. Deletion destroys the audit trail that makes ten-year knowledge trustworthy. |
| Learning is incremental | Each newly attested outcome is absorbed as it arrives, at bounded cost. Full-corpus reprocessing exists only as the regeneration path for the derived layer, never as the routine operating mode. A system that must reread everything to learn anything cannot scale to thousands of executions. |
| Ignorance is a definite answer | When accumulated experience says nothing about a situation, LIE says exactly that. No interpolation, no plausible-sounding fill. "No relevant experience" is a first-class, honest response — and the absence itself is a signal worth recording. |

The coherent philosophy: **LIE is a refinery, not a mind.** Verified outcomes in,
curated evidence-backed advice out, every step deterministic and inspectable.
Nothing in it "learns" in the model sense; it accumulates records and derives
from them by versioned, repeatable processing.

---

## 3. Architectural Position

In the conceptual question order LIE is terminal: it sits after VAE and feeds
nothing downstream in the pipeline — its outputs travel *back up* as advice.

**Upstream — VAE (sole admission authority).** VAE is the only source whose
outputs may become experience. LIE trusts VAE's verdicts and never re-verifies;
re-verification would duplicate VAE's mission and create two authorities over
one question. Consequently LIE's knowledge quality is bounded by VAE's rigor —
an accepted and intended coupling: assurance and learning share one standard of
truth.

**Peer — UMS (strict separation).** No shared storage, no data flow of content
in either direction. Where an experience record must refer to repository
knowledge, it refers by stable identifier, never by copied content — UMS
knowledge in LIE would rot on repository change, violating the two-decay-law
separation of §1. UMS never stores behavioral learning; LIE never stores
repository semantics.

**Consumers — Kernel and the components it governs.** The Execution Kernel,
Capability Planner, Workflow Scheduler, Plugin Runtime, and Reasoning
Orchestrator consult LIE and receive advice with citations. Per the component
sheet, reliability signals flow to Plugin Runtime and planning priors to
Capability Planning — both are instances of the same advisory relationship:
LIE derives the numbers; the consumer owns the decision and its own state.
The Kernel enforces nothing on LIE's behalf, because LIE asks for nothing to
be enforced.

**Infrastructure.** Storage persists everything (Law 3); Communication carries
all events; Observability supplies closed traces and consumes LIE's published
events. LIE holds no private persistence and spawns no processes.

---

## 4. Internal Decomposition

Five subsystems. Each exists because its responsibility has a distinct trust
boundary, lifecycle, or change cadence from the others; no further subdivision
earns its existence at this phase.

### 4.1 Admission Gate

The single entry point for all experience. Receives attested outcomes (closed,
verdict-tagged work), checks provenance — is there a VAE verdict, is the trace
closed, is the origin identifiable — and normalizes admitted material into
canonical experience records. Rejections are recorded with reasons.

*Why it exists:* the "only verified execution" canon needs one enforcer. If
admission logic were distributed across capture points, every new experience
source would be a new opportunity to leak unverified material into the store.
One gate, one rule, auditable rejections.

### 4.2 Experience Ledger

The append-only system of record for the experience layer: every admitted
record, immutable from the moment of admission, version-controlled and
human-readable per canon. The component sheet's fault ledger lives here as a
category of experience, alongside successful workflows, decisions, benchmark
outcomes, and recovery episodes — categorization is a later-phase concern; this
phase fixes only that the Ledger is one store with typed contents, not a
federation of parallel stores.

*Why it exists:* the permanence guarantee needs an owner. Immutability,
append-only discipline, and survival across models and OS versions are
properties of exactly one place, or they are properties of nowhere.

### 4.3 Distillery

The derivation processor: consumes the Ledger, produces the intelligence layer
— discovered patterns, anti-patterns, cross-project generalizations, domain
knowledge packs, workflow/plugin/capability/performance statistics. Every
derivation process is versioned; every derived artifact records which process
version and which ledger state produced it. Identical ledger + identical
process version = identical derived layer, always.

*Why it exists:* raw experience does not generalize itself. The step from "these
forty records" to "this recurring pattern" is real work with its own change
cadence — derivation logic will evolve over ten years far faster than the
records it reads, and versioning it separately is what keeps old derivations
explainable after the logic improves.

### 4.4 Advisory Interface

The single consultation surface. Answers "what does experience say about this
situation" with cited recommendations drawn from both layers, publishes the
update events the component sheet canonizes (`lesson.recorded`,
`reliability.updated`, `prior.updated`), and returns the definite "no relevant
experience" answer when that is the truth. Read-only toward both layers;
writeless toward every consumer.

*Why it exists:* the advisory-only canon needs a choke point just as admission
does. If consumers read the Ledger directly, citation discipline and the
read-only boundary become conventions instead of architecture.

### 4.5 Curator

Owner of the knowledge lifecycle: marks experience deprecated or superseded
(with reasons and evidence, per the deprecate-never-delete tenet), resolves
contradictions between records by recorded ruling rather than silent overwrite,
ages derived artifacts whose evidence base has been superseded, and owns the
evolution path when record conventions must change across years — old records
are never rewritten; newer conventions must read them or the change is rejected.

*Why it exists:* ten years of append-only accumulation without curation is a
landfill, not a knowledge base. But curation authority must be separate from
admission (which only lets things in) and from derivation (which must never
edit its own inputs) — a Distillery that could deprecate inconvenient records
would be grading its own homework, the exact failure VAE exists to prevent.

### Boundary summary

- **Write path:** Admission Gate → Experience Ledger. No other subsystem writes
  experience.
- **Derive path:** Ledger → Distillery → intelligence layer. Distillery reads
  experience, writes only derived artifacts, edits nothing it reads.
- **Read path:** both layers → Advisory Interface → consumers. Strictly
  read-only.
- **Curation path:** Curator annotates (never mutates) Ledger records and ages
  derived artifacts. It is the only subsystem that may mark; even it may not
  erase.
- All durable writes on every path go through Storage (Law 3).

The required capability list from the charter maps onto this decomposition
without remainder: Experience Repository, Decision Memory, Anti-Pattern
Repository, Benchmark History → Experience Ledger (as typed content). Pattern
Discovery, Cross-Project Learning, Domain Knowledge Packs, Workflow/Plugin/
Capability/Performance Learning → Distillery. Similar Project Detection,
Recommendation Generation → Advisory Interface. Learning Lifecycle Management →
Curator. Later phases design each mapping's interior; none may move a capability
across these boundaries without errata here.

---

## 5. Lifecycle of Engineering Experience

Every unit of experience passes through the same stations, in order:

1. **Attestation** — VAE renders a verdict on completed work. Nothing before
   this point concerns LIE.
2. **Admission** — the Gate verifies provenance and normalizes; the outcome is
   an immutable Ledger record or a recorded rejection.
3. **Distillation** — the Distillery absorbs the record incrementally; derived
   artifacts that the new evidence supports are created or strengthened, with
   the derivation recorded.
4. **Advisory service** — the record and its derivations become citable; the
   Advisory Interface may now recommend on their evidence and publishes the
   corresponding update events.
5. **Reinforcement or supersession** — later verified experience either
   strengthens the record's derivations or contradicts them; contradiction is
   resolved by the Curator with a recorded ruling, producing supersession, not
   erasure.
6. **Deprecated permanence** — superseded experience remains in the Ledger,
   marked, citable as history, excluded from fresh advice. There is no station
   seven; nothing exits.

The loop closes externally: advice adopted by a consumer produces new work, new
work produces a new VAE verdict, and the verdict re-enters at station 1. Whether
LIE's advice actually improved outcomes is therefore itself measurable from the
Ledger — the engine's own effectiveness is subject to the same evidence
standard it imposes on everything else.

---

## 6. Architectural Invariants

Every later phase must preserve all of these. A phase that cannot is wrong, or
must file errata against this document first.

- **INV-1 (Single door).** Experience enters only through the Admission Gate,
  and only with VAE attestation. No bulk import, no manual insertion, no
  side-channel — a human-curated seed corpus, if ever wanted, goes through the
  Gate under the same provenance rules.
- **INV-2 (Immutable experience).** Ledger records are never edited or deleted
  after admission. Curation annotates; it does not mutate.
- **INV-3 (Reproducible intelligence).** The derived layer is a pure function
  of (Ledger state, derivation process version) and can be regenerated from
  scratch with identical results. Loss of the derived layer is an inconvenience,
  never a knowledge loss.
- **INV-4 (Citation or silence).** Every recommendation cites the records
  justifying it; absence of experience is answered as absence, never filled.
- **INV-5 (Advisory boundary).** LIE writes no consumer's state and gates no
  execution. Removal of LIE degrades advice quality and nothing else — the
  operating system remains fully functional, exactly as deterministic, merely
  unadvised.
- **INV-6 (Model and platform independence).** Both layers remain meaningful
  with no language model present at all. Nothing stored requires a specific
  model, OS installation, or execution environment to interpret.
- **INV-7 (Human-readable, version-controlled).** All experience and all
  derived knowledge live as human-readable artifacts inside the project
  repository's version control, diffable and auditable by contributors without
  tooling.
- **INV-8 (Deterministic processing).** Every LIE process — admission,
  distillation, advice, curation — yields identical outputs from identical
  inputs and process versions (Law 6). Nondeterministic advice is a defect.
- **INV-9 (UMS separation).** No repository semantics stored in LIE beyond
  stable identifiers; no behavioral learning stored in UMS. Cross-reference by
  identifier only.
- **INV-10 (Bounded incremental cost).** Absorbing one new record costs an
  amount bounded per record, not proportional to corpus size. Full reprocessing
  is a regeneration tool, not an operating mode.

---

## 7. Governing Principles for Later Phases

Where later phases face a choice this document does not settle:

1. **Extend, never replace.** Canon and this foundation grow by addition.
   Terminology defined here is fixed.
2. **Evidence over inference.** When designing any derivation or
   recommendation mechanism, prefer the design that keeps a shorter, plainer
   chain from advice back to attested records.
3. **Regenerate over migrate.** For derived knowledge, schema evolution is
   solved by re-running a new derivation version over the Ledger — never by
   migrating derived artifacts in place. For Ledger records, evolution is
   solved by readers that accept old conventions — never by rewriting records.
4. **The boring record wins.** Between a richer representation and a plainer
   one, choose the one a contributor can read in a text editor in 2036 with no
   context. Ten-year survivability outranks expressive power.
5. **Measure the engine by its own ledger.** Any claimed improvement to LIE —
   better patterns, better advice — must be demonstrable from recorded
   outcomes, per §5's closed loop. A learning mechanism whose benefit cannot
   be measured from the Ledger does not get built.
6. **No component grades its own homework.** Preserve the authority
   separations of §4: admission cannot derive, derivation cannot curate,
   curation cannot admit, advice cannot write.

---

## 8. Phase Boundary

This document fixes what LIE *is*: its mission, philosophy, position, five
subsystems, experience lifecycle, invariants, and governing principles. It
deliberately leaves open everything about interior design — record content
models, categorization taxonomies, derivation mechanics, similarity and
retrieval, recommendation construction, confidence, curation policy detail, and
all integration contracts. Those are Phases 2–5 material and must be designed
inside the boundaries drawn here.
