# Request State Manager — Phase 4: Validation & Integration Review

This document is Phase 4 of the RSM's 5-phase spec. It does not design
anything new. It validates what Phases 1–3 already designed:
`RSM/01-problem-definition.md` (problem, scope, non-responsibilities),
`RSM/02-architectural-blueprint.md` (record shape, ADR-RSM-1/2/3, ownership
matrix, invariants RSM-I1..I14), and `RSM/03-internal-design.md` (runtime
lifecycle, transition table, reducer pipeline, budget/failure representation,
concurrency, performance). The method is an integration review against
`ARCHITECTURE.md` — Part A walks every subsystem RSM touches (or pointedly
does not) and renders a verdict; Part B runs five mandated weakness checks
against the full design and records findings F1–F6; Part C is the final
verdict. Two findings (F2, F3) require amendments to Phase 2 — one new ADR
(ADR-RSM-4) and two new invariants (RSM-I15, RSM-I16) — applied in this same
commit. No code, no APIs, no classes — review and verdicts only.

---

## Part A — Per-subsystem integration review

For each subsystem: what flows into RSM from it, what (if anything) flows
back out to it, the verdict, and the reasoning. Verdicts are one of **SOUND**
(no issue, no change), **SOUND WITH RULE** (no issue, but a rule must be
stated explicitly to keep it that way), or **REVISED** (Phases 1–3 need an
amendment, applied here).

### Kernel

| | |
|---|---|
| In | `request.received`, `request.admitted`, `request.rejected`, `request.completed`, `request.failed` |
| Out | Nothing. Kernel reads nothing from RSM. |
| Verdict | **SOUND** |

ADR-RSM-2 holds under review: both the Kernel's internal Ledger and RSM's
Request State record are deterministic folds of the *same* event stream. They
cannot diverge except by a reducer bug — a defect, not a design tension, per
Phase 2 §3 ADR-RSM-2's own consequences section. Delivery-level exactly-once
semantics align too: Communication is at-least-once, and both projections
dedup independently — Kernel by its own mechanism (`KERNEL/04-request-state.md`
D6a), RSM by RSM-I4 (event-id dedup). Neither projection can apply an event
twice, so neither can drift from the other through duplicate application.

Zero direct edges exist between Kernel and RSM. Kernel publishes to
Communication for its own reasons (per `ARCHITECTURE.md`'s publish/consume
matrix); RSM subscribes as an additional consumer (Phase 2 §2, §6). Kernel
invariant I19 ("zero direct edges with components outside its declared set")
is untouched — RSM was never in Kernel's declared set and nothing in this
review adds it. Kernel neither reads RSM nor knows RSM exists; this was true
at the end of Phase 2 (ADR-RSM-2 "Alternatives rejected") and remains true
after Phase 3's internal-design detail. No amendment.

### Repository Memory (UMS)

| | |
|---|---|
| In | Nothing. |
| Out | Nothing. |
| Verdict | **SOUND, trivially** |

There is no interaction. RSM never queries repository knowledge — doing so
would violate the Phase 1 §5 exclusion table ("Semantic understanding /
retrieval" is owned by Repository Memory, explicitly not RSM) and the Phase 2
§7 runtime-boundary list ("RSM never... retrieves repository knowledge").
Repository Memory never reads runtime request state — it has no reason to;
its index is repo-scoped, not request-scoped, and nothing in its own spec
gives it a request-state need. The verdict here is not "no problems found
after inspection" — it is stronger: the absence of an edge between these two
subsystems *is* the verdict. A finding here would only be possible if some
document introduced a query in either direction, and none does. No amendment.

### Capability Planning

| | |
|---|---|
| In | `classify.completed`, `plan.created`, `plan.revised` (contributes to the Plan block, Phase 2 §4) |
| Out | Prior request state on replan, read-only (Phase 1 §7) |
| Verdict | **SOUND** |

### Verification

| | |
|---|---|
| In | `verify.requested`, `verify.passed`, `verify.failed`, `plan.validated`, `plan.rejected` |
| Out | Nothing — verdicts are one-shot (Phase 1 §7) |
| Verdict | **SOUND** |

### Execution

| | |
|---|---|
| In | `exec.started`, `exec.completed`, `exec.timeout`, `exec.failed` |
| Out | Nothing — Execution is stateless per dispatch (Phase 1 §7) |
| Verdict | **SOUND** |

### Plugin Runtime

| | |
|---|---|
| In | `plugin.*` events, only when tied to a specific request's steps |
| Out | Nothing |
| Verdict | **SOUND** |

### Context Management (incl. prompt compilation)

| | |
|---|---|
| In | `context.assembled` |
| Out | Nothing — Context Management is per-call, ephemeral (Phase 1 §7) |
| Verdict | **SOUND** |

These five — Capability Planning, Verification, Execution, Plugin Runtime,
Context Management — share one shape and one verdict, so the reasoning is
given once. Each is a **pure event contributor**: RSM stores only their
event-derived ids and refs (plan id, verdict ref, exec-outcome ref, context-
package id — Phase 2 §1, §4), never their owned content. Each *may* read RSM
for status (Capability Planning does, for replan strategy; the others
currently don't, but nothing forbids it — Phase 1 §7's "Reads" column is a
statement of what's useful today, not a closed permission list). Critically,
**nothing in any of their own control loops requires RSM to function.**
Capability Planning classifies and plans without consulting RSM first;
Verification computes verdicts without consulting RSM; Execution dispatches
without consulting RSM; Plugin Runtime loads without consulting RSM; Context
Management assembles without consulting RSM. Their control flow stays exactly
where it is today — on the bus, plus whatever direct queries their own specs
already define (e.g. Capability Planning → Plugin Runtime capability
matching, Context Management → Repository Memory retrieval). RSM is a
downstream mirror of their outputs, never an upstream dependency of their
decisions. No amendment for any of the five.

### Scheduling

| | |
|---|---|
| In | `task.scheduled`, `task.started`, `task.preempted`, `task.completed`, `task.failed`; budget-grant fields carried in `task.scheduled`/`task.started` payloads |
| Out | Full request materialization, read-only, for replan decisions (Phase 1 §7); RSM's Budget-block view |
| Verdict | **SOUND WITH RULE** |

**The risk.** Phase 3 §7 fixes that RSM's Budget block computes `remaining`
at read time: `remaining = granted - consumed`, derived, not stored (Phase 3
§7: "a stored value would be a second place that arithmetic could drift").
That derivation is deliberately close to what an enforcement decision looks
like — "does this request have budget left" is exactly Scheduling's own
backpressure question (Phase 1 §5: "Scheduling, budgets, preemption, work
ordering" owned by Scheduling; `ARCHITECTURE.md` state-ownership table: "Work
order, priorities, budgets, preemption state" → Scheduling). If Scheduling,
or anything acting as an enforcement path, ever reads RSM's `remaining` and
gates a preemption or admission decision on it, RSM becomes a second budget
authority through the back door — the exact drift Phase 1 §2's "Duplicated
budget arithmetic" row exists to close, reopened by the very feature meant to
surface it.

**The rule (no amendment — this is a restatement of an existing boundary,
already implied by Phase 1 §5 and Phase 3 §7, made explicit here because the
review process requires it to be stated, not left implicit).** RSM's Budget
block is a *view*. Scheduling remains the sole enforcement authority for
budget decisions and must not read RSM's derivation as an input to an
enforcement decision — Scheduling has, and keeps, its own arithmetic,
computed from its own in-memory work-order state (`ARCHITECTURE.md` state
ownership: "Work order, priorities, budgets, preemption state | Scheduling |
(in-memory)"). RSM's Budget-block view exists for Frontend display and for
audit — "what has this request cost so far" (Phase 1 §1) — never as an input
Scheduling consults to decide whether to admit, preempt, or block. This
mirrors ADR-RSM-2's Kernel Ledger precedent exactly: two deterministic
projections of the same facts are fine as long as only one of them is ever
consulted for the decision that matters.

### Context Management — see above (grouped with the five pure contributors).

### Observability

| | |
|---|---|
| In | `cost.recorded` (feeds the Budget-block aggregation) |
| Out | RSM's live view and journal, as an additional signal alongside Observability's own episodic store (Phase 1 §7); RSM's journal replay fetches event bodies from Observability's episodic store (ADR-RSM-3) |
| Verdict | **SOUND WITH RULE** |

Two touchpoints, reviewed separately.

**(a) Replay reads the episodic store.** ADR-RSM-3 (Phase 2 §3) makes RSM's
journal an index of event ids, not a copy of payloads; replay means "fetching
each event body from the episodic store via the standard read path" (Phase 2
§3, consequences). `ARCHITECTURE.md`'s memory hierarchy states Episodic
memory is "committed for audit/replay; never retrieved by similarity" — the
word "retrieved" there means Repository Memory's similarity-search retrieval
path (Law 2, fix H2: "only Repository and Semantic tiers are queryable by
similarity"). RSM's access to the episodic store is not that: it is a
**direct keyed read by event id, in journal order** — no similarity, no
ranking, no query — functionally identical in shape to any other component
fetching a record it already knows the id of. State the boundary precisely so
it stays a boundary and not a slow drift toward a second retrieval path: RSM
may fetch episodic event bodies by id for replay; RSM may never search,
filter by content, or rank episodic events. The moment a "find all events
matching X" capability were added against the episodic store, that would be
retrieval and would violate Law 2 — nothing in Phases 1–3 asks for that, and
this review closes the door on it explicitly rather than leaving it
implicit. No amendment; the boundary was already implied by ADR-RSM-3 and is
restated here because F2's schema-coupling finding (Part B) made "restate the
boundary, don't just imply it" the right posture for every touchpoint in this
review.

**(b) RSM is not a second Observability.** Phase 1 §8 already states this
("RSM is not a second Observability") and Phase 2 §7 places RSM in the Core
tier specifically so it isn't mistaken for a Substrate service alongside
Observability. Restated for this review: Observability owns the durable
history — the permanent, append-only, audit-and-metrics episodic trace, plus
telemetry/cost accounting authority (`ARCHITECTURE.md` state ownership:
"Telemetry, metrics, token/cost accounting, audit log, episodic traces" →
Observability). RSM owns the live now-view of active requests plus a bounded,
evictable per-request journal index (Phase 1 §6, Phase 3 §2). They read the
same bus and, per (a), RSM reads Observability's store for replay — but they
answer different questions for different audiences, and RSM's bounded
lifetime (§2 materialization states: terminal → persisted → retained →
evicted) is precisely what keeps it from becoming a second, competing
episodic store. No amendment.

### Learning

| | |
|---|---|
| In | Nothing |
| Out | Completed request states and journals, read-only, for distilling lessons/faults/priors (Phase 1 §7, Phase 2 §6) |
| Verdict | **SOUND** |

Learning is a pure reader against RSM — RSM contributes nothing to Learning's
inputs beyond what Learning already reads. No cycle exists: Learning's own
outputs (`lesson.learned`, `reliability.updated`, updated priors) go to
Repository Memory, Plugin Runtime, and Storage (`ARCHITECTURE.md` publish/
consume matrix; Phase 1 §7's exclusion table: "Long-term learning, lessons,
faults, priors" owned by Learning) — never back into RSM's Request State
record. A request state, once terminal, never gets rewritten by anything
downstream of it, including Learning's distillation. No amendment.

### Storage

| | |
|---|---|
| In | `storage.committed`, `storage.rejected` (reflected into Work/Failure blocks) |
| Out | RSM's own durable writes — journal index + terminal snapshot + periodic checkpoints (Phase 3 §11) — flow *through* Storage as a writer, not *from* Storage as a consumer |
| Verdict | **SOUND** |

RSM writes durably only via Storage, and only three things: the journal
index, the terminal snapshot (ADR-RSM-3, RSM-I8), and periodic checkpoints
for long-running requests (Phase 3 §11, config-gated). Every one of those
writes goes through Storage's single write path like every other component's
durable write (`ARCHITECTURE.md` state ownership: "All durable writes
converge on Storage (single writer, Law 3)"). RSM never writes to disk, to a
vault, or to any store directly. The single-writer law is intact with RSM's
introduction exactly as it was without it. No amendment.

### Communication

| | |
|---|---|
| In | Delivery substrate — every event RSM reduces arrives via Communication |
| Out | n/a |
| Verdict | **REVISED — see Finding F2, Part B** |

Communication is not a data contributor in the same sense as the other
thirteen subsystems; it is the transport all of them share. The review's
finding here is not about the transport-level contract (per-topic FIFO,
at-least-once delivery — RSM already handles this correctly per RSM-I4,
RSM-I5) but about a **payload-level coupling** the transport-level review
didn't originally surface: RSM's reducers read fields out of event payloads
(a budget-grant field inside `task.scheduled`, a cost field inside
`cost.recorded`), and nothing in Phases 1–3 said explicitly whose schema
those fields belong to. Finding F2 (Part B) resolves this: reducers bind only
to Communication's owned, versioned message schema — the same schema
`ARCHITECTURE.md`'s state-ownership table already assigns Communication
("Event schema, topic/subscription registry" → Communication) — never to a
publisher's internal payload layout. This is encoded as new **ADR-RSM-4** and
new invariant **RSM-I16**, both applied to Phase 2 in this commit (see Part
B, Part C).

### Lifecycle

| | |
|---|---|
| In | Request-scoped session/repo events only where a request's own state machine is opened/closed (Phase 1 §7) |
| Out | Nothing |
| Verdict | **SOUND** |

Request state-machine transition legality stays exactly where
`ARCHITECTURE.md`'s state-ownership table puts it: "Request / repo / plugin /
session state machines" → Lifecycle, with Kernel driving the request-scoped
transitions specifically (`ARCHITECTURE.md` component diagram: `K -->|open/
advance state machines| LIF`). RSM's Lifecycle block (Phase 2 §1) *mirrors*
these states — it never rules on whether a transition is legal, never blocks
one, never originates one. Phase 2 §5 already states this ("RSM never
computes lifecycle transitions itself") and Phase 3's transition table (§3)
never gives RSM a vote — every row that touches the Lifecycle block is
triggered by an event Kernel or Lifecycle already published, applied
passively. Session and repository state machines are out of RSM's scope
entirely (Phase 1 §7: "out of scope otherwise — repo/plugin/session lifecycle
is not request lifecycle") and nothing in Phase 3's internal design widens
that scope. No amendment.

### Frontend

| | |
|---|---|
| In | Nothing |
| Out | All materialized Request State fields, for any active or recently-terminal request — Frontend's primary state read surface (Phase 1 §7, Phase 2 §6) |
| Verdict | **SOUND WITH FOLLOW-UP** |

This is the edge RSM exists to add (Phase 1 §1: "The Frontend has no real
state read surface"). It is architecturally sound — Frontend is read-only
against RSM as it is against everything (`ARCHITECTURE.md` state ownership:
"Presented (read-only) view state | Frontend | never (reads only)") — but it
is a **new** edge that `ARCHITECTURE.md`'s component diagram does not yet
draw. Today the diagram shows `FE -->|admit request / read state| K` as
Frontend's only state-read path; RSM's introduction means rich per-request
status (step, plan ref, cost-to-date, verdicts, failure state) is read from
RSM instead of reconstructed through Kernel's black-box lifecycle phase
(Phase 1 §1). Phase 2 §7 already flagged this class of gap once, for the new
`state.updated`/`state.evicted` telemetry events, and deferred the diagram
edit to Phase 5. This review extends the same deferral to the Frontend→RSM
read edge: no amendment in this document, no new decision required — it is a
diagram-currency fix, not an architectural question, and it is folded into
the Phase 5 follow-up list alongside the telemetry-event catalog edit. No
amendment here.

---

## Part B — Weakness hunt

Five mandated checks, run against Phases 1–3 in full. Findings are numbered
F1–F6; each carries a Finding, a Severity, a Resolution, and a Where-encoded
pointer.

### Check 1 — Duplicated ownership

**F1 — Kernel Ledger vs. RSM Request State record.**

| | |
|---|---|
| Finding | Two components — Kernel and RSM — each hold a materialized view of a request's state. On its face this looks like duplicated ownership, the exact pattern Phase 1 §1 opens by describing as the root problem. |
| Severity | Would be Critical if unresolved — this is the central tension the whole RSM design has to survive. |
| Resolution | Examined in full during Phase 2 and re-examined in Part A of this review (Kernel subsection). ADR-RSM-2 reclassifies the Kernel Ledger as a kernel-internal control-plane projection, not a second system-wide authority. Both the Ledger and RSM's record are deterministic folds of the same event stream (RSM-I3), so they cannot hold conflicting truths — only a reducer bug could cause divergence, which is a defect, not a design property. "No subsystem maintains private runtime state" is restated precisely (Phase 2 ADR-RSM-2 consequences) to mean no *authoritative* private state; a discardable, rebuildable-from-the-bus projection kept for a subsystem's own fast decisions is expressly permitted. |
| Where encoded | ADR-RSM-2 (`02-architectural-blueprint.md` §3); Part A, Kernel subsection (this document). |
| Status | Closed. |

### Check 2 — Hidden coupling

**F2 — Payload-schema coupling (the substantive finding of this review).**

| | |
|---|---|
| Finding | RSM's reducers do not just consume event *names* — they read specific *fields out of event payloads*. Phase 3 §7 names two concretely: the budget-grant value carried inside `task.scheduled`/`task.started` payloads, and the cost value carried inside `cost.recorded`. Every other reducer in Phase 3 §4's registry does the same thing implicitly (a reducer cannot fold `plan.created` into the Plan block without reading the plan-id field out of that event's payload). Phases 1–3 establish *which events* RSM subscribes to (Phase 2 §4's ownership matrix) but never state *whose schema* a reducer is allowed to assume when it reads a field. Left unstated, a reducer could easily come to depend on a specific publisher's internal payload shape — the plan id field happening to sit at a particular path because that's how Capability Planning's internal plan object currently serializes, say — rather than on a payload contract anyone owns and versions. That is hidden coupling: RSM would silently couple to every publisher's internal representation, and a publisher refactoring its own internals (with no intention of breaking any contract, because it owns no contract that says otherwise) could silently break RSM's reducers with no build-time or contract-level signal. |
| Severity | High. This is exactly the shape of coupling `ARCHITECTURE.md` Law 1 and the state-ownership table exist to prevent, and it was invisible until reducers were specified concretely enough (Phase 3) to see it. |
| Resolution | Reducers bind **only** to Communication's owned, versioned message schema — `ARCHITECTURE.md`'s state-ownership table already assigns "Event schema, topic/subscription registry" solely to Communication — never to a publisher's internal payload layout. A publisher may restructure its own internal plan/task/cost representations freely, as long as the *published event*, which Communication's schema governs, is unchanged. A schema version change to a payload a reducer depends on is not silently absorbed: it is an explicit migration event for that reducer (paired with the existing `reducer_version` mechanism, Phase 3 §12), not a compatibility guess. |
| Where encoded | New **ADR-RSM-4** (amendment to `02-architectural-blueprint.md` §3, this commit); new invariant **RSM-I16** (amendment to `02-architectural-blueprint.md` §9, this commit). |
| Status | Resolved by amendment. See Part C. |

### Check 3 — Responsibility leakage

**F3 — `state.updated` as a covert control channel.**

| | |
|---|---|
| Finding | RSM publishes `state.updated` and `state.evicted` telemetry (Phase 2 §7, Phase 3 §8). These are ordinary bus events, indistinguishable in mechanism from any command-carrying event. Nothing in Phases 1–3 stops a future subsystem from subscribing to `state.updated` and *gating a decision* on it — "when RSM says this request's Work block changed, do X." If that happened, RSM would become a de-facto coordinator: a second control path running alongside Kernel's own admission/routing/gating authority, built entirely out of a side channel meant only for observability. This is the responsibility-leakage failure mode named in Phase 1 §8 ("no subsystem maintains private runtime state") turned inside-out — instead of a subsystem hoarding state, a subsystem would be *reacting* to RSM's state in a way that makes RSM load-bearing for control flow it was never designed to carry (Phase 2 §2: "RSM publishes exactly one thing back to the bus: its own telemetry... it never publishes a command"). |
| Severity | Medium — not exploitable by anything in the current 14-component design (nothing today subscribes to `state.*` for control purposes), but nothing before this review said it couldn't happen, and the failure mode is severe if it ever does (a hidden second coordinator). |
| Resolution | `state.updated` and `state.evicted` are declared telemetry-only. No subsystem may gate a control decision on either event. Their only legitimate consumers are Observability (as with any telemetry, Law 7) and Frontend (as a refresh signal — "a new state is available to query," never "do X because state changed"). Any component that wants to *act* on a request's state must query RSM's synchronous read surface directly and make its own decision from the materialized record, exactly as Phase 2 §6's query fan-out already describes — never infer intent from the fact that a telemetry event fired. |
| Where encoded | New invariant **RSM-I15** (amendment to `02-architectural-blueprint.md` §9, this commit). |
| Status | Resolved by amendment. See Part C. |

### Check 4 — Cross-topic ordering skew

**F4 — reviewed, no defect found, no amendment.**

| | |
|---|---|
| Finding | `ARCHITECTURE.md`'s delivery semantics guarantee per-topic FIFO only — "total order not guaranteed across topics." A concrete risk: `verify.passed` (topic: verification) could in principle be delivered before its corresponding `task.started` (topic: scheduling) for the same request, since they're on different topics with no cross-topic ordering guarantee. |
| Severity | Would be High if any reducer's correctness depended on cross-family arrival order. |
| Resolution | Reviewed against Phase 3 §3's transition table and Phase 2 §4's ownership matrix. Each block in the Phase 2 §1 record is fed by contributing events that are either (a) family-independent of every other block — Plan fed only by Capability Planning/Verification events, Context fed only by `context.assembled`, Verification fed only by Verification's own events — so no reducer for one block ever needs to have already seen an event belonging to a different block's family to apply correctly; or (b) explicitly append/aggregate and therefore commutative — the Failure block is append-only (Phase 3 §6: "a failure entry, once recorded, is never edited or removed"), and the Budget block's Consumed field is a running sum (Phase 3 §7), and neither an append nor a sum depends on the arrival order of the entries being appended or summed. The Lifecycle block is the one place true ordering matters (birth must precede any contributing event, terminal must be recognized correctly), and it is driven exclusively by Kernel's own `request.*` family, which is single-topic and therefore FIFO-guaranteed by Communication's own delivery semantics — no reducer anywhere depends on order *between* two different topics. Separately, RSM-I5 (journal order is applied order, never re-merged topic order) means that whatever order events actually arrive in, replay reproduces that exact applied order — so even in the hypothetical case of two families racing, the journal captures whichever order actually happened and replay is exact regardless of the skew, per RSM-I3/RSM-I12. |
| Where encoded | No amendment needed. The reasoning above is the record of this check; Phase 3 §3's transition table and §12's Invariant Refinements section already contain the pieces this check assembles (particularly RSM-I5's applied-order-is-truth framing). |
| Status | Closed, no change. |

### Check 5 — Circular dependencies

**F5 — full dependency check, no cycle found.**

| | |
|---|---|
| Finding | A circular dependency would exist if RSM's outputs fed back into RSM's own inputs through some other component, or if RSM's authority chain looped back on itself. |
| Severity | Would be Critical if found — a cycle in an event-sourced system breaks the "record = fold(reducer_version, journal order)" guarantee (RSM-I3) outright. |
| Resolution | Full trace: RSM subscribes to the bus (in-edge). RSM publishes only `state.*` telemetry, consumed by Observability and Frontend, neither of which publishes anything back that RSM subscribes to as a *contributing* family (Observability's own emissions like `telemetry.emitted` are not in RSM's reducer registry, Phase 3 §4). RSM reads the episodic store for replay (Part A, Observability subsection) — a read, not a subscription, and Observability doesn't consume RSM's replay reads as an input to anything it publishes. RSM writes via Storage — Storage's `storage.committed`/`storage.rejected` outcomes *do* feed back into RSM (they're in the reducer registry, Phase 3 §4), but that is Storage confirming RSM's own write, not RSM's output being re-injected as new domain state; it closes a single write's loop, it does not create an authority cycle. Learning reads RSM (Part A) but Learning's outputs (lessons, priors, reliability updates) go to Repository Memory, Plugin Runtime, and Storage — never to RSM (Part A, Learning subsection: "no cycle exists"). The authority graph: |
| Where encoded | This document, Part A (per-subsystem detail) and the ASCII graph below. |
| Status | Closed. |

```
        every publisher (Kernel, Capability Planning, Scheduling,
        Execution, Context Mgmt, Verification, Storage, Observability)
                              │
                              │  publish (their own reasons)
                              ▼
                     Communication bus
                              │
                              │  durable subscribe
                              ▼
                            RSM  ─────────► Storage (journal index,
                              │               terminal snapshot,
                              │               checkpoints — writer)
                              │
                              │  read-only query
                              ▼
              Frontend, Scheduling (replan), Capability Planning
              (replan), Learning (completed states + journals)
                              │
                              │  (Learning's own outputs)
                              ▼
              Repository Memory, Plugin Runtime, Storage
                    (never back to RSM)

        RSM's only out-edges: state.* telemetry → Observability/
        Frontend (terminal — consumed, never re-published toward RSM);
        journal/snapshot writes → Storage (terminal — confirmed via
        storage.committed, not re-expanded into new domain events).
```

No path returns to RSM's own inputs except the single-write confirmation
loop through Storage, which is bounded (one write, one ack) and identical in
shape to every other component's write-confirmation loop
(`ARCHITECTURE.md` write-path diagram: "Any component... → Storage →
storage.committed → Observability"). The graph is acyclic.

### Check 6 — Unnecessary complexity audit

**F6 — four candidate complexity items, each justified or already deferred.**

| Item | Justification / disposition |
|---|---|
| Checkpoints (Phase 3 §11) | Scoped narrowly: only long-running requests accumulate journals long enough to need one, and the mechanism is config-gated (interval `N` from config) — a request with a short journal never triggers a checkpoint write at all. Exists to bound recovery replay cost independent of request lifetime length (Phase 3 §1 recovery, §11). Not speculative: Phase 1 §6 already committed to bounded memory and Phase 3 §1 already committed to a recovery path that replays from persisted state; checkpoints are the mechanism that makes both promises hold for the one case (long-running requests) where naive full replay would be expensive. Justified, kept. |
| Coalescing (Phase 3 §8) | Config-gated, and defaults to the simple case: Lifecycle-block changes are never coalesced (immediate, one per change); only Work/Context/Budget-block changes coalesce, and only because Phase 2 §7 already flagged high-frequency telemetry as needing a throttling mechanism before Phase 3 existed. The default behavior for a system that never configures a coalescing interval is indistinguishable from "no coalescing" for the events that matter most (Lifecycle). Justified, kept. |
| Retention (Phase 1 §6, Phase 3 §2) | A single configuration value (the retention window). Not a subsystem, not a policy engine — one number that gates the `retained → evicted` transition. Directly required by Phase 1 design goal 6 (bounded memory) and mirrors the Kernel Ledger's own eviction discipline (Phase 1 §6). Justified, kept. |
| Sharding (Phase 2 §10, Phase 3 §9, §11) | Explicitly **not built** in any phase so far — every mention is "reserved... not built until measured," the same house rule the Kernel's own Ledger already follows (Phase 3 §9: "This is not built until measured — house rule, same as Kernel's own deferred sharding"). This is the correct disposition for a complexity item that has no present justification: it is named as a future option with a clear trigger (measured event-throughput saturation) and a clear mechanism (consistent-hash on request id), but zero of it exists yet. Deferred, correctly. |

Nothing in Phases 1–3 is removed by this check — every item was already
either justified by a design goal traced to Phase 1, or already explicitly
deferred rather than built. The audit confirms the existing discipline, it
does not find waste to cut.

---

## Part C — Verdict

**The architecture stands.** Thirteen of fourteen subsystem integrations
reviewed in Part A are SOUND or SOUND WITH RULE with no change required;
Communication's review surfaces the one substantive gap (F2), and one
cross-cutting weakness-hunt finding (F3) surfaces a second. Both are closed
by amendment in this same commit, applied to `RSM/02-architectural-
blueprint.md`:

1. **ADR-RSM-4 — Reducers bind to Communication-owned versioned schemas**
   (new ADR, appended after ADR-RSM-3 in §3). Resolves F2.
2. **RSM-I15** — `state.*` events are telemetry only; no subsystem gates a
   control decision on them (new invariant, appended to §9). Resolves F3.
3. **RSM-I16** — Reducers bind only to Communication-owned versioned event
   schemas; a schema version bump requires an explicit reducer migration
   (new invariant, appended to §9, paired with ADR-RSM-4). Resolves F2.

The invariant count moves from RSM-I1..I14 (Phase 2, refined but not
extended by Phase 3) to **RSM-I1..I16** as of this phase. No existing
invariant, ADR, or design decision from Phases 1–3 is reversed, weakened, or
contradicted — every amendment in this document is additive, in the same
sense Phase 3 §12 already established for schema evolution generally: new
constraints tighten a boundary that was previously implicit, none of them
undo a boundary that was previously explicit.

**The five mandated checks, final status:**

| Check | Result |
|---|---|
| Duplicated ownership | Pass (F1, closed by ADR-RSM-2, re-confirmed) |
| Hidden coupling | Pass, after amendment (F2, closed by ADR-RSM-4 + RSM-I16) |
| Responsibility leakage | Pass, after amendment (F3, closed by RSM-I15) |
| Cross-topic ordering skew | Pass (F4, closed, no change needed) |
| Circular dependencies | Pass (F5, acyclic authority graph confirmed) |

Unnecessary-complexity audit (F6, not one of the five mandated checks but run
alongside them per this review's scope) found nothing to remove — every
complexity item already carried its own justification or its own explicit
deferral from Phases 1–3.

**Phase 5 preview:** the final phase specifies the query/read surface — the
exact shapes callers can ask for, filtering and fan-out semantics, how the
read surface answers for `evicted` records — and closes out the two
follow-ups this review flagged but did not itself resolve: the
`ARCHITECTURE.md` component-diagram edit (Frontend→RSM read edge, Part A) and
the `ARCHITECTURE.md` event-catalog edit (`state.updated`/`state.evicted`,
already flagged once in Phase 2 §7).
