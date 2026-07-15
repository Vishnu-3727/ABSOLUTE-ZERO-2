# VAE Implementation Blueprint

Build specification for the Verification & Assurance Engine. Architecture
frozen in VAE/00–05 — this document only translates it into an executable
roadmap. Implementation sources for coders: this file + the VAE invariant
registers (VAE-I1–12, M1–7, A1–10, K1–12, O1–10, S1–8) + VAE/04 (operational
mechanics) + VAE/05 §2 (event canon) + KERNEL/INVARIANTS.md (event
discipline). Phase prose in VAE/00–03 is rationale; invariants are law
(VAE-S8). Python 3.12+, stdlib only, `src/vae/` package beside its siblings.

Global laws binding every phase:

| Law | Meaning here |
|---|---|
| VAE-I6 / Law 6 | Same artifact + same rules version + same recorded results = identical verdict, evidence record, assurance. No clock/random reads in judgment paths; time enters only as injected data. |
| VAE-O2 | Delegation only on the direct VAE→Execution channel (injected callable); VAE publishes/consumes only its VAE/05 §2 canon rows. |
| VAE-O5 | Persist evidence via Storage, then publish verdict — always that order. |
| VAE-O7 / M2 / A6 | Evidence bodies append-only; nothing rewritten, reweighted, or pruned. |
| VAE-I11 / Law 3 | No local durable writes; all bytes via Storage (double until real). |
| Zero-seam | VAE ships its own bus/storage doubles (RO ruling: zero-seam beats DRY). No imports from src/kernel, src/ums, src/ro, src/cm, src/prt, src/rsm. |

Doubles until real: Storage, Communication, Execution (scripted delegated-check
results = deterministic nondeterminism, RO/05 §10 engine-double pattern), UMS
scoping query.

---

## Phase 1 — Foundation: rules-as-data, evidence model, event canon, doubles

| Section | Content |
|---|---|
| Objective | VAE's data substrate exists and is law-abiding: versioned rules, append-only five-part evidence records, the closed event vocabulary, and the doubles every later phase tests against. Zero judgment logic yet. |
| Modules | **rules.py** — rules-as-data: immutable `RulesVersion` snapshot mapping artifact type → required check set, depth, per-check deadline; strictly-monotonic version ingest (VAE-S5 pattern, mirrors RO priors); validation loud on malformed rules; lookup by (artifact_type, version), absent = `KeyError`-style refusal, never a default rule set. **evidence.py** — the five-part record (VAE/04 §7.1): artifact binding (reference only, never content), rules binding (version id), append-only evidence items (rule addressed, artifact ref, source, result, contribution kind per VAE/02 §5 closed five — Direct/Corroborating/Redundant/Conflicting/Missing — level/kind attribution per VAE-M7), identified absences as first-class items, derivation account slot (filled Phase 3; presence refused before then). Append is the only mutation; item edit/remove APIs do not exist. Content-hash record identity for deterministic event ids later. **events.py** — closed sets from VAE/05 §2: PUBLISHED = {verify.passed, verify.failed, plan.validated, plan.rejected, fault.recorded}, CONSUMED = {verify.requested, plan.created, exec.completed, reasoning.completed}; constructors structurally refuse invented names (UMS/RO pattern); payloads reference-shaped (record hashes + routing facts, never artifact content). **bus_double.py**, **storage_double.py** — VAE's own copies: at-least-once bus with per-topic FIFO and event-id dedup hooks; storage double with commit/reject scripting (VAE-O6 path needs scripted rejection). |
| Data produced | RulesVersion snapshots; EvidenceRecord instances; canonical event envelopes. |
| Dependencies | None (first phase). |
| Completion criteria | Malformed rules refused loud. Rules lookup deterministic; absent version/type refuses. Evidence record accepts appends, refuses every mutation of existing items (no API surface). Contribution kind outside the closed five refused. Event constructor with invented name raises. Storage double scripts both commit and reject. |
| Testing goals | `tests/test_vae_phase1.py`: rules ingest/refusal/pinning; append-only enforcement (attempt rewrite → no path exists); closed-set refusals (events, contribution kinds); record content-hash stability (same items, same order → same hash; differing order → differing hash — per-artifact ordering is meaningful); doubles behave per scripts. |
| Risks | Over-modeling the derivation account before Phase 3 — leave an explicitly-empty slot, not a speculative structure. Rules format gold-plating — smallest structure satisfying VAE/05 §8 row 1. |
| Deliverables | 5 modules + selftests + phase test file. Suite (578 baseline) stays green. |

## Phase 2 — Judgment core: intake, delegation lifecycle, static checks

Demand intake with event-id dedup + one-judgment-per-occurrence (VAE/04 §2);
delegation state machine Required→Dispatched→Resulted/Expired on injected
Execution boundary, rules-assigned deadlines as injected time data (VAE-O3,
O4); delivery-redundancy vs retry line per VAE/04 §3.4; VAE's own bounded
static checks as pluggable modules. Depends: Phase 1.

## Phase 3 — Derivation: verdict, confidence, uncertainty, assurance

Deterministic derivation from closed evidence body + rules version: verdict,
five confidence dimensions, explicit uncertainty, five assurance levels
(VAE/02 §3–§7); derivation account written into the record slot (VAE-A10
traceability); failure-cause taxonomy on fail verdicts (VAE-K8, VAE/01 §11
closed five). Depends: Phases 1–2.

## Phase 4 — Choreography: persist-then-publish, loud absence, pending state

Emission ordering (VAE-O5), storage-rejection → fault.recorded + no verdict
(VAE-O6), pending projection as rebuildable non-authority with crash-recovery
re-derivation (VAE-O1, O10, VAE/04 §6). Depends: Phases 1–3.

## Phase 5 — Integration: runtime, telemetry, law enforcer, replay

Composition root (handle demand → judge → persist → publish), six telemetry
signal families (VAE/04 §8), law_enforcer static scans (event sets == canon,
no sibling imports, no time/random in judgment paths, append-only surface,
persist-before-publish order, verdict-function takes no producer identity —
VAE-S7), golden-artifact determinism suite + byte-identical replay (VAE/05
§8). Depends: all prior.

---

Workflow per repo mandate: Fable brief/review; Sonnet high implements; one
module per commit with selftest; phase test file green + full suite green
before push.
