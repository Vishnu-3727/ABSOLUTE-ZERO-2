# Errata

Pre-ruled canon corrections against earlier phase documents. Where a later
audit finds a naming conflict, the correction below is canon; the document
named "overridden" is wrong on that point only, nothing else in it changes.

## C1 — event name is `lesson.recorded`

**Audit: 2026-07-16.** VAE/05's cross-subsystem event matrix lists LIE's
lesson-published event as `lesson.learned`. That name is wrong. LIE's own
canon (`LIE/00-architectural-foundation.md` §4.4, carried into
`src/lie/events.py`) names it `lesson.recorded`. LIE naming wins: LIE is the
publisher of this event, VAE/05 is a downstream reference that drifted.
`lesson.learned` does not exist anywhere in this codebase and must be
treated as an invented name if it is ever proposed again.

## C2 — the Advisory Interface (LIE), not UMS, serves lessons

**Audit: 2026-07-16.** `learning.md` and `memory.md` describe UMS as the
component that serves learned lessons to consumers. That is wrong. Per
`LIE/00-architectural-foundation.md` and `LIE/03-operational-lifecycle.md`
§7, the Advisory Interface is the sole component that answers consultations
and serves recommendation objects; UMS is a peer with strict separation
(identifiers cross, content never does — INV-9). LIE naming wins: `learning.md`
and `memory.md` are wrong on this point and should be read as if they named
the Advisory Interface (LIE) instead of UMS.

## C3 — reading of SGPE INV-6 ("Effective Policy frozen") vs mid-request grants

**Phase 4 design: 2026-07-16.** `SGPE/00-architecture-blueprint.md` INV-6
freezes a request's Effective Policy at admission; SGPE/00 §3.5's approval
loop lets a running request obtain grants after a REQUIRE_APPROVAL. Both are
canon and reconcile per `SGPE/04-resolver-grant-ledger.md` §2.3: what is
frozen is the *binding rule* — `(snapshot version, admission ledger position
P₀, request id)` — not the slice's row count. The slice grows in exactly one
way: Ledger appends scope-bound to *this request id* (answers to asks the
request itself raised, and their revocations). No snapshot activation and no
principal/project-width append after P₀ ever enters a running request's
world. Every consultation stamps the ledger position it used, so replay is
exact. INV-6 should be read with this refinement; SGPE/04 §2.3 is the
authoritative wording.

## C4 — request lifecycle state: Kernel is the authority, RSM is the derived read surface, Lifecycle never advances

**ARB ruling B1: 2026-07-17.** Three documents assign request-state authority
in conflicting directions. This ruling reconciles them; it changes labels and
charters only — no shipped behavior changes, and ADR-RSM-2's structural
consequences (`RSM/02-architectural-blueprint.md` §3) all stand.

1. **The Kernel Ledger is the sole runtime authority for request lifecycle
   state.** The Coordinator is its sole mutator (kernel I1); its transition
   log is the durable causal record (I16); admission, routing, and gate
   decisions are made from it synchronously. ADR-RSM-2's *label* for the
   Ledger — "a derived decision cache … projection of the same event
   stream" — is overridden: the Ledger cannot be a projection of a stream it
   *produces*. The Kernel emits the lifecycle transitions RSM folds;
   causality points one way. Everything else in ADR-RSM-2 is unchanged and
   binding: the Ledger stays kernel-internal, is never queried by another
   subsystem, and the Kernel never reads RSM (the rejected alternative stays
   rejected).

2. **RSM is the sole system-wide *derived* read surface for request runtime
   state — never a control-decision input.** RSM/01's "single source of
   truth" and RSM/02 §8's "authoritative Request State record" must be read
   as "single system-wide read surface": authoritative *for cross-component
   reads*, always reconstructible from the event stream, and on any
   divergence the Kernel Ledger wins by definition. No component may consult
   RSM to decide an admission, transition, gate, or budget enforcement.

3. **Lifecycle defines the request state graph; it never advances request
   state and never publishes `request.completed`.** `lifecycle.md`'s
   "define **and advance** the request state machine" and its listing of
   `request.completed` under Events Published are wrong on those points.
   `request.completed` is published by the Kernel (per `ARCHITECTURE.md`'s
   event matrix and the shipped transition table) as the terminal Ledger
   transition. Lifecycle's request-side responsibility is authorship of the
   legal-transition table, delivered to the Kernel as governed config data
   via the existing `config.changed` path. Its repo/plugin/session state
   machines are untouched by this ruling.

4. **Interim table custody.** Until Lifecycle is implemented, the request
   transition table in `src/kernel/default_config.py` is provisionally
   Lifecycle-owned *content* hosted in the Kernel's tree. Extending it is a
   Lifecycle-policy change, not a Kernel change.

## C5 — verification gates are layered by object, not owned twice; the Kernel is the gate authority

**ARB ruling B2: 2026-07-17.** The B2 audit finding read `ARCHITECTURE.md`'s
component summary ("Kernel … mediates lifecycle gates"; "Scheduling …
enforces gates") as two components enforcing the *same* gate. That reading
is rejected. `VAE/03-kernel-integration.md` §3.1/§3.2 — the most specific
canon on enforcement topology — already assigns two *different* gates to two
*different* objects, and that assignment is ratified here:

1. **Two gates, two objects, by design.** The Scheduler's gate guards **task
   dispatch**: no step is released downstream without the `verify.passed`
   verdict its plan requires (verdict absence is not-passed — VAE-I5). The
   Kernel's gate guards **request lifecycle transitions**: admission,
   routing, cancellation, and completion; no request reaches `completed`
   without its recorded verdicts satisfying the completion gate. This is
   layered fail-closed composition, not duplicated responsibility: a permit
   requires both layers, so any disagreement between them degrades to
   refusal or a stalled request — never to a bypass. Law 4 holds at both
   granularities independently.

2. **The Kernel is the gate authority.** Gate *definitions* live in the
   governed config snapshot the Kernel evaluates (`gates` section of the
   Config View), and the Kernel is the **sole emitter of `gate.enforced`
   audit records** — the authoritative gate audit trail. This matches the
   shipped implementation exactly.

3. **The Scheduler is a dispatch-time guard, never a gate authority.** It
   consumes verdict events and refuses to dispatch ungated work; its refusal
   is a *scheduling hold* (task held in queue), not a gate verdict, and it
   never emits `gate.enforced`, never defines gates, and never dispatches
   around a Kernel block. `scheduling.md`'s "enforces gates" must be read as
   "enforces the dispatch gate"; `ARCHITECTURE.md`'s summary rows are
   clarified accordingly.

## C6 — budget ownership is layered, one authority per concept; no component owns another's layer

**ARB ruling B6: 2026-07-17.** The B6 audit finding claimed budget authority
is fragmented five ways with "no canonical counter." The fragmentation claim
is **rejected**: the layering already exists in canon and is consistent —
SGPE/00 §"Boundary refinements" rules it explicitly ("the *limit* is
SGPE's; the *meter* is Observability's; the *comparison* is the
consumer's"), `observability.md` disclaims enforcement, `WS/00` sources
measurements from Observability, `RSM/01` disclaims accounting authority,
and the CM/UMS fitters and RO's `BudgetEnvelope` hold no mutable budget
state. What the audit correctly detected is that this matrix was scattered
across six documents and stated nowhere whole. This erratum is that single
statement; every document below is to be read against it.

**Budget ownership matrix (canon):**

| Concept | Authority (sole mutator) | Everyone else |
|---|---|---|
| Budget policy & limits (authored ceilings, LIMIT decisions) | SGPE | Consumers read via frozen Effective Policy; never modified downstream. |
| Budget allocation (request/step allocations, reservations) | Scheduling (WS) | CM/UMS/RO receive ceilings as call parameters; RSM materializes a view. |
| Request budget / step budget | Scheduling (WS), carved from SGPE limits | Read-only downstream. |
| Context budget / retrieval budget | Not state — a ceiling *parameter* handed down (WS → CM → UMS) | CM/UMS *fit* under it (pure functions); fitting never modifies an allocation. |
| Reasoning budget envelope | RO — derived, immutable (`BudgetEnvelope`, frozen), allocated from the WS allocation under SGPE limits | Child envelopes draw from parent remaining; no mutable ledger exists in RO's budget module. |
| Actual token spend / monetary cost (the meter) | Observability — sole durable spend record (`cost.recorded`) | RO's per-invocation `consumed_total` is transient local enforcement of one envelope, discarded at invocation end — never the spend record. |
| Remaining budget | Nobody — always derived (allocation − metered spend), computed at the point of comparison | Any component persisting "remaining" as state violates this ruling. |
| Budget violations (detection) | Observability — measures and emits `budget.exceeded` | Scheduling *acts* on it (preempt/hold); response is not detection. |
| Budget audit events | Observability | Sink for all budget telemetry, one schema. |

**Laws restated as prohibitions:** SGPE never meters and never sees raw
spend (purity, D2). Observability never allocates and never enforces.
Scheduling never authors limits and never meters. CM/UMS/RO fitting never
mutates an allocation — over-ceiling is always a loud refusal or a reported
drop, never a renegotiation. `RSM`'s budget block is a materialized view,
never an accounting authority (RSM/01 §2, ERRATA C4 applies).

## C7 — Storage serves bytes only to the state's owner; cross-component reads are owner-mediated

**ARB ruling B5: 2026-07-17.** Two claims examined, opposite verdicts.

**Write-bypass claim: rejected.** Every implemented component persists only
its own state, through its injected Storage port, under a disjoint key
namespace (`ums/…`, `rsm/…`, `sgpe/…`, `prt/…`, `ro/…`). No component
writes another owner's keys; Law 3 (single durable writer) plus
owner-scoped namespaces hold in the shipped code. Storage remains custody,
never authority (persistence follows authority — it does not confer it).

**Read-backdoor claim: confirmed — in the architecture document, not the
implementation.** `ARCHITECTURE.md`'s component diagram carried
`CTX -->|read other memories| STO`, and the context-assembly flow read
semantic memory ("lessons/priors") and episodic memory ("prior decisions")
"via Storage". Those arrows licensed Context Management to fetch and
interpret *other owners' bytes* directly — contradicting ERRATA C2 (the
Advisory Interface is the sole server of lessons) and the ownership model
itself. The implementation never took the license: `src/cm` contains zero
Storage usage, and its only cross-component reads are `ums.query` and
`rsm.query` — owner query surfaces. The arrows are corrected to match.

**The rule, stated generally:** Storage serves raw bytes only to the
component that owns the state being read. Every cross-component read goes
through the owning component's query/advisory surface: repository knowledge
via UMS query, runtime request state via RSM query, lessons/priors via the
Advisory Interface (LIE), episodic traces via Observability's query API.
Views, caches, snapshots, and indexes remain derived and non-authoritative
(ERRATA C4's RSM ruling is the reference case); a derived surface answering
a read is not ownership — bypassing the owner to read its bytes is.

## C8 — "experience" decomposes into layered concepts, each single-owner; RO's PriorsStore is a versioned representation, not a second experience authority

**ARB ruling B3: 2026-07-17.** The B3 audit finding claimed RO's
`PriorsStore` + `experience_feed` constitute "a second experience-derived
store … outside the curator's jurisdiction." **Overturned on all three
counts**, on canon already in force:

1. **RO never computes experience.** `RO/05` §5 assigns "priors
   computation, lesson distillation" exclusively to Experience/Learning
   (LIE). `experience_feed` is the *Out* flow only: reference-shaped
   batches (content hashes, never content — the same identifiers-cross-
   content-never discipline as LIE INV-9) shipping RO's decision/outcome
   stream to Learning as raw material. Observation is not learning; RO
   supplies observations.

2. **RO's `PriorsStore` is a derived, versioned representation.** Priors
   are authored by Learning and arrive only as `prior.updated` events
   (publisher: Learning — LIE/00 §4.4, LIE/03 §4, `ARCHITECTURE.md` event
   matrix). The store is append-only with strictly monotonic versions;
   stale or duplicate versions are refused loud; a decision replays
   against the priors version it recorded (`at_version`), never current
   priors (RO-S6). Representation, not ownership — and the audit's "no
   ruling on which wins when they disagree" is moot: disagreement is
   impossible by construction, since only one component ever computes.

3. **Curation jurisdiction is intact.** Because RO holds only
   Learning-authored artifacts keyed by version, LIE's curation/forgetting
   machinery governs the *content* of every prior RO will ever cite; RO's
   history is a replay ledger, not a live belief store.

**Experience concept decomposition (canon, one owner each):** observation
and episodic history — Observability; execution outcomes and reasoning
decision records — RO (sealed records, producer's own audit state);
lessons, faults, priors, plugin-reliability knowledge — Learning (LIE),
authored via distillation and curation only; advisory responses — LIE's
Advisory Interface (sole consultation surface, ERRATA C2); semantic
repository knowledge — UMS; request memory (context assembly) — CM,
ephemeral, never persisted; skills/plugin capability records — PRT.
Observations never become lessons directly: the only path is
LIE-consumed events → ledger → distillation → curated publication.

## C9 — plugin "reliability" is two concepts with one seam; PRT owns live health, Learning owns learned reliability, PRT owns the composition

**ARB ruling B4: 2026-07-17.** The B4 audit finding claimed PRT's health
scores and Learning's plugin reliability are "two writers to one effective
signal" with the merge policy silently pushed into consumers. **Overturned**
— `PRT/04-health-reliability.md` §5 is a locked, dedicated "Reliability vs
health" ruling that decomposes the concept exactly as the audit demanded,
and the shipped code obeys it:

1. **Live operational health** — PRT's. One current health state per
   provider, a pure deterministic fold over the ordered evidence journal
   (PRT-H1); replayable — same ordered evidence + same priors version +
   same admin acts → same state (PRT-I8). Not a registry entry; RETIRED is
   a registry fact the health lifecycle never owns.

2. **Learned reliability** — Learning's. Healed priors distilled from
   *closed* traces across requests (semantic-memory-tier knowledge),
   published as `reliability.updated`.

3. **One seam, one direction each way.** `reliability.updated` folds into
   PRT's health computation as ONE versioned, declared input — so the
   *composition* into the selection-facing signal has exactly one owner:
   PRT. PRT never writes reliability (its own law enforcer pins the event
   as consumed-only); Learning never reads live health (src/lie contains
   zero PRT references). Operational health is not learned trust; the two
   never collapse into one number anywhere but PRT's governed fold.

4. **Neither is governance.** Grants/revocations are SGPE's (C3 approval
   loop); quarantine and admin overrides are admin acts recorded as
   evidence in PRT's journal — learning never authorizes a plugin, and
   governance never fabricates observations. Audit history of health
   changes is events + journal, replayable.

The audit's recommended fix — "PRT owns the composition into a single
selection-facing score" — is precisely what PRT/04 §4–6 already specifies
and `src/prt/health.py` implements. No correction to code or canon;
this erratum records the decomposition so the claim is not re-litigated.

## C10 — configuration decomposes into schema / instance / activation / view; Storage holds custody, never config authority

**ARB ruling B9: 2026-07-17.** The B9 audit finding claimed configuration
ownership is fragmented across Storage ("config source of truth"), five
per-component `config_view` validators, and SGPE. **Partially confirmed.**
The fragmentation claim is rejected: the five config views are
component-local schemas over *disjoint* key namespaces (the only shared key
is `version`), each the "policy as data" pattern — read-only, validated at
construction, replaced wholesale, never mutated in place. Five schemas for
five components is correct decentralization, not five authorities over one
thing. What the audit correctly caught is `ARCHITECTURE.md` calling Storage
the config "source of truth" — custody conflated with authority, the same
label error C4 corrected for request state and C7 for reads.

**Configuration concept decomposition (canon, one owner each):**

1. **Schema** (which keys exist, their types and meaning, per component) —
   owned by that component; its `config_view` REQUIRED/OPTIONAL_KEYS is the
   schema authority for its namespace. Key namespaces are disjoint across
   components; a key needed by two components must instead be authored once
   and delivered to both through activation (rule 3) — never declared twice.

2. **Defaults** — bootstrap fallback only (`default_config.snapshot()`
   deep-copies; deployments replace via `config.changed`). Defaults are
   never authority and never merge *over* an activated snapshot.

3. **Authored instance + activation** — the values are an operator/
   deployment act, governed; **custody** of the authored bytes is Storage
   (C7 discipline); **activation** is an explicit versioned event
   (`config.changed`), validated by the consumer's schema, last-good
   retained on rejection (fail closed). Policy configuration is the special
   case with a full owner already: SGPE's authored documents, admission
   compiler, and hash-verified snapshot activation. Content ownership of a
   section can differ from its carrier (C4's TRANSITIONS custody note is
   the precedent).

4. **Effective configuration (the view)** — derived, immutable, versioned;
   consumers are read-only; validation is pure (never mutates its input);
   in-flight requests stay pinned to the snapshot version they were
   admitted under (kernel I18), which is what keeps replay deterministic.

5. **Runtime state is not configuration** — ledgers, journals, health
   folds, and priors are C4/C8/C9 territory and never travel in a config
   snapshot.

## C11 — session concepts decompose; the Kernel's sleep-time eviction is own-ledger housekeeping, not session ownership; event names are `session.wake` / `session.sleep`

**ARB ruling B8: 2026-07-17.** The B8 audit finding claimed the Kernel
"performs Lifecycle's session work" by handling `session.wake`/`session.sleep`
and evicting requests at sleep. **Overturned**, with one genuine naming
erratum found in the process:

1. **Session identity and lifecycle are Lifecycle's.** Lifecycle is the
   sole publisher of session boundary events (`ARCHITECTURE.md` event
   matrix); no implemented component mints them (verified: the Kernel only
   *consumes* — `_SESSION_EVENTS` appears in its inbound set, and no
   `publish("session.…")` exists anywhere in src). Observers cannot
   terminate sessions; nothing but Lifecycle ever will.

2. **The Kernel's sleep-time eviction is housekeeping of its own state.**
   At `session.sleep` the Coordinator evicts only *terminal*
   (completed/failed/cancelled) entries from the Ledger it owns (ERRATA
   C4), logging each as a `__cleanup__` record first — eviction is not
   deletion; `recover()` replays `__cleanup__` records deterministically,
   so the post-eviction Ledger is a replay-reconstructible state, not a
   loss. Reacting to a published boundary by cleaning one's own memory is
   consumption, not session ownership. The same pattern holds elsewhere:
   RSM's retention/eviction gates its *own* materialization (RSM-I11,
   persist-gated, not even session-coupled), and CM's Request Memory is
   request-scoped and ephemeral — no component touches another's state at
   a session boundary.

3. **Event names: `session.wake` and `session.sleep` are canon.**
   `lifecycle.md` lists `session.woke` / `session.slept` under Events
   Published. Those names are wrong (same class as ERRATA C1): the shipped
   Kernel inbound set and the `ARCHITECTURE.md` matrix both say
   `session.wake` / `session.sleep`, and the consumer's inbound contract +
   matrix win over a publisher spec that drifted. `session.woke` and
   `session.slept` do not exist in this codebase and must be treated as
   invented names if proposed again. `lifecycle.md` is corrected directly.

4. **Retention policy residue, named honestly:** *which* entries evict
   (terminal only) and *when* (session boundary) is currently hardcoded in
   the Coordinator rather than carried as config data — contrast RSM,
   whose retention window is a config_view scalar (C10 pattern). Ownership
   is unambiguous (Kernel, own state), so this is a policy-as-data style
   gap, not a B8 defect; if it moves, it moves into the Kernel's own
   config snapshot, never to another component.

## C12 — conformance decomposes: local invariants stay with their component; global invariants have one authority — the repo conformance layer (tests/), with two global checks provisionally hosted in peer modules

**ARB ruling B7: 2026-07-17.** The B7 audit finding called the five
`law_enforcer` modules "a shadow governance engine … quintuplicated," and
recommended consolidation under SGPE or one harness. **Partially
confirmed** — the decomposition rejects most of it and confirms a hosting
defect:

1. **Law enforcers are static verification, not governance.** They run at
   CI time through the phase-5 test suites, verify source structure, and
   fail closed. SGPE governs *runtime* boundary crossings of *requests*;
   it must never own build-time source conformance (validation is not
   governance; static verification is not runtime enforcement). The
   audit's "move it into SGPE" is rejected outright.

2. **Local invariants correctly live with their component.** CM's closed
   event set and licensed-door rule, PRT's closed CONSUMED set, RO's and
   VAE's seam checks — each verifies its *own* contract. Component
   contracts are not system contracts; consolidating them would create
   exactly the cross-component knowledge coupling the laws forbid. The
   five modules are five *local* verifiers, not five copies of one thing —
   "quintuplicated" was wrong.

3. **Global invariants have one authority: the repo conformance layer** —
   the repo-level guard tests (`tests/test_b*_*.py` and now
   `tests/test_b7_conformance.py`), run in CI, fail closed. This layer
   already exists implicitly; this erratum names it. Two global checks are
   currently *hosted* inside peer modules and are hereby reclassified as
   repo-conformance content provisionally hosted there (C4 custody
   precedent): `ums/law_enforcer.py`'s all-of-src Law-2 scan +
   single-similarity-owner check, and `cm/law_enforcer.py`'s system-wide
   single-Assembler check. UMS and CM are custodians of that code, not
   owners of the jurisdiction; the repo layer invokes both directly so the
   global checks run even if a phase suite is refactored away.

4. **Overlapping detection is layered, not dual authority.** CM's local
   no-similarity check and UMS's global scan can both catch the same
   violation in src/cm; both fail closed, so disagreement degrades to
   refusal (the B2/C5 AND-composition argument). The known cost of hosting
   global content inside scanned peers is the token-splitting the modules
   use to avoid matching each other — tolerated, documented here, and the
   first thing to delete when the checks physically move to the repo layer
   (H6 harness work, out of B7's scope).

## C13 — Storage's events are `storage.committed` / `storage.rejected`; `write.committed`, `write.failed` are drift; git integration deferred until Execution exists

**Implementation ruling C1B: 2026-07-17.** `storage.md` listed
`write.committed` / `write.failed` under Events Published. Those names are
wrong (C11's rule: the ARCHITECTURE.md matrix + the consumer contract win
over a publisher spec that drifted): the matrix — and the now-executable
Communication vocabulary — name them **`storage.committed`** and
**`storage.rejected`**, and no consumer anywhere references the `write.*`
forms. `storage.md` is corrected directly. `commit.created` (git
integration) is not drift but *deferred scope*: storage.md itself rules
that git runs as a process via Execution and Storage spawns nothing —
until Execution exists there is nothing architecture-compliant to
implement, so the shipped Storage substrate carries no git machinery and
publishes no `commit.created`. The event stays chartered for the git
integration phase.

## C14 — Execution's events are `exec.*` (PRT/05 §4 D2 already ruled it); its dispatch trigger is `task.scheduled`; declared-but-unenforceable sandbox caps are refused, not faked

**Implementation ruling C1C: 2026-07-17.** Three decisions, two of them
already made elsewhere and ratified here:

1. **Event names: `exec.started` / `exec.completed` / `exec.failed` /
   `exec.timeout`.** `execution.md` (and downstream mentions in
   `learning.md`, `lifecycle.md`, `observability.md`, `scheduling.md`,
   `verification.md`, `plugin-runtime.md`) carried the draft `process.*`
   family. PRT/05 §4 D2 ruled this long ago — "`process.failed` /
   `process.timeout` … never published by anyone, dead draft vocabulary,
   canon is `exec.*`" — and the ruling is encoded in shipped
   `src/prt/events.py`. All COMPONENTS references are corrected directly;
   the `process.*` event names are banned invented names from here on.

2. **Dispatch trigger: `task.scheduled`.** `execution.md` said
   `task.dispatched`; the ARCHITECTURE.md matrix routes `task.scheduled →
   Execution, Observability` (C11's rule: matrix wins). `task.dispatched`
   remains a Scheduling-published release event whose consumer set will be
   settled when the Workflow Scheduler is built — it is not Execution's
   trigger.

3. **Caps are fail-closed, not decorative.** The spec requires resource
   caps enforced "on every process without exception"; portable stdlib
   enforcement does not exist on this platform. The shipped substrate
   therefore *refuses* an execution spec that declares resource caps
   (loud `CapsUnsupportedError`) rather than accepting-and-ignoring them —
   a declared cap that is not enforced would be a silent security hole.
   Timeouts are enforced unconditionally. Cap enforcement arrives with a
   sandbox backend (execution.md Future Expansion), behind the same spec
   fields.

## C15 — Workflow Scheduler event canon: `task.started` is the dispatch announcement, `task.dispatched` is a dead draft name, `workflow.created` announces the artifact; deferred policy is refused, not improvised

**Implementation ruling C2A: 2026-07-17.** WS/00 §6 and WS/01 §9a-b named
the drift and chartered the implementation phase to settle it. Settled, by
the C11 rule (matrix + consumer contract win):

1. **Dispatch canon = the matrix's `task.*` family.** `task.scheduled`
   (unit enqueued at workflow activation), `task.started` (unit released
   to Execution — this IS the dispatch announcement), `task.completed` /
   `task.failed` (unit terminal), `verify.requested` (WS asking VAE for
   the per-unit verdict). **`task.dispatched` is a dead draft name**
   (same class as `process.*`, C14) — never published by anyone, banned;
   `scheduling.md` is corrected. `backpressure.engaged` is *deferred
   scope*, not drift: backpressure is dispatcher policy, and that phase
   is unwritten — the name stays chartered, unregistered, unpublished.

2. **`workflow.created`** (WS/01 §9b's recommended row) enters the matrix
   and the Communication vocabulary: published by Scheduling when a
   compiled workflow reaches Published; consumed by Observability and
   VAE (gate 2, plan-admissibility inspection surface).

3. **Deferred policy is refused, not improvised.** The shipped WS
   implements exactly what WS/01-02 lock: compilation (WS-W1..W12),
   readiness/completion semantics (WS-E1..E10), and dispatch in the
   artifact's canonical total order — WS/02 §5's own default "when policy
   expresses no preference." Priority/budget/aging/backpressure policy
   and workflow-level retry (WS/02 §7: "a later resilience phase") are
   NOT implemented; unit failure makes downstream permanently unready
   (WS-E9) and resolution is branch selection or replan, exactly as
   specified. Execution-attempt retries remain Execution's
   (`max_retries`, C14).

4. **Branch-selection default, minus servability:** WS/02 §10a's locked
   principle is "highest-ranked branch whose capability is currently
   servable." Servability comes from PRT health, which is not wired into
   this flow yet; the shipped default selects CP's highest-ranked branch
   unconditionally, and the servability filter arrives with PRT wiring.
   Documented here so nobody mistakes the interim rule for canon.

## C16 — the classification event is `intent.classified`; `classify.completed` was the stale matrix name (CP/05 pre-ruled; reconciliation executed early because the matrix is now code)

**Implementation ruling C2B: 2026-07-17.** CP/05's "Global laws" table
ruled it: *"`intent.classified` (per COMPONENTS spec + CP/00 §4) is
canonical; ARCHITECTURE.md matrix row `classify.completed` is stale —
matrix fixed in Phase 5."* The component spec
(`COMPONENTS/capability-planning.md`, authority above ARCHITECTURE.md)
agrees. The reconciliation was scheduled for CP Phase 5, but the matrix
became executable when the Communication vocabulary shipped, so leaving
the stale name registered would have had CP Phase 1's closed event set
refusing its own canonical name. Executed now: matrix row, Communication
vocabulary, the request-lifecycle diagram, and RSM's consumer surface
(`reducers.py`, `transitions.py` — a mechanical rename, identical
behavior; RSM/01-04's `classify.completed` mentions are covered by this
erratum, frozen docs untouched). `classify.completed` is a banned stale
name from here on. The same sweep fixed the two remaining `lesson.learned`
diagram references (C1 enforcement, missed in the C1-era sweep).


## C17 — SGPE's nine-event canon is registered in the executable vocabulary as RECORD topics; the matrix gains Governance rows

**Implementation ruling C3 (System Integration): 2026-07-18.** The first
real boot of SGPE over the real Bus was refused with
`schema.unknown_topic:'policy.authored'` — correct fail-closed behavior:
SGPE's event canon (SGPE/05 §4, closed set of nine) predates the
executable vocabulary and was never registered, and the ARCHITECTURE
matrix carried no Governance rows at all. Ruling:

1. **The nine SGPE names join the vocabulary as RECORD topics** —
   `policy.authored/.deprecated/.compiled/.rejected/.activated/.decided/
   .illposed`, `grant.recorded`, `grant.revoked`. RECORD, not ENVELOPE:
   SGPE's envelopes are its own reference shape (`event_name, event_id,
   subject_ref, payload`) with no `request_id` — policy authorship and
   grants are not request-scoped, and the shape belongs to the
   publisher's closed canon (SGPE/05 §4), which Communication does not
   restate.
2. **The matrix gains one row per name**, publisher Governance
   (per-subsystem attribution as SGPE/05 §4 assigns it), consumer
   Observability — matching EV-10/GL-7: the bus event IS the audit
   trail; no runtime consumer reacts to policy events.
3. **Registration stays an explicit act.** Nothing auto-registers on
   first publish; the next component that brings its own canon (VAE's
   verdict shape) goes through the same door.

Discovered by C3's System composition root — the first code anywhere
that boots SGPE against the real Communication component instead of its
`bus_double`.
