# Capability Planner (CP) — Phase 3: System Integration

CP's position in the OS and every neighbor contract. Conceptual only — no APIs, algorithms, schemas, storage, code. Builds on CP/00 (foundation), CP/01 (capability model), CP/02 (graph planning); nothing here restates them beyond citation. Built neighbors (Kernel, UMS, RSM, CM) are bound to as-built reality (`src/`); future neighbors (Scheduler, Plugin Runtime, Prompt Compiler, Reasoning Engine, Verification Engine, Experience Store) are bound only on CP's side — this document states what CP requires of them, never how they work.

---

## 1. Architectural position

CP exists because **intent is not executable**. Something must translate a goal into the OS's ability vocabulary (CP/01) before anything can be ordered or run — that translation is CP's entire reason to exist (CP/00 §1).

**Why after CM.** Planning consumes constructed knowledge, never raw repository. Request Memory must be assembled before CP can even ask "what abilities does this need" — CP/00 §13 fixed CM as the sole context assembler; planning is a *consumer* of that assembly, structurally incapable of running before it exists.

**Why before Scheduler.** Order presupposes an object to order. Scheduler cannot sequence what CP has not yet named. CP therefore sits strictly upstream of the first component that touches WHEN.

**Why isolated at all.** Planning, scheduling, implementation, and execution are four different questions with four different change cadences: what's needed changes with intent and registry content; when things run changes with load and resources; how a capability is fulfilled changes with every plugin release; the work itself changes with every model call. Coupling any two re-creates V1-H1's cascade at system scale — one authority quietly answering two questions, drift accumulating until a single bad classification breaks everything downstream. Four owners, four cadences, one fence each.

**Two distinct CM engagements — stated honestly.** Per `ARCHITECTURE.md`'s lifecycle, context assembly happens twice: once at planning time (CP requests Request Memory to build the graph) and again per-step at scheduling time (Scheduler's loop calls `CTX.assemble(step, budget)` for execution). These are architecturally distinct engagements with the same CM, not one shared artifact. **CP does not pre-assemble execution contexts** — the Request Memory CP consumes is scoped to planning; it has no bearing on, and imposes no shape on, the per-step context CM assembles later for Execution. Conflating the two would make CP responsible for execution-time context quality, a fence violation of CP/00 invariant 1.

| Question | Owner | Relative to CP |
|---|---|---|
| What does the system know? | CM | Immediately upstream |
| What abilities are required? | **CP** | — |
| In what order do abilities execute? | Scheduler | Immediately downstream |

---

## 2. Kernel

| | |
|---|---|
| Purpose of the boundary | Kernel admits and routes; CP plans only admitted work |
| CP assumes | `request.admitted` is a validated, routable unit — admission legality is decided before CP ever sees the event |
| CP guarantees | A `plan.created` or `plan.rejected` eventually follows every admitted request CP consumes; no silent drop |
| Never crosses | CP owns nothing lifecycle — no state-machine transitions, no admission authority, no routing decision |

**Invocation is event-driven.** CP consumes `request.admitted`, routed by Kernel's static router (CP/00 §4). CP does not poll, does not pull work, does not decide what to plan next — Kernel decides what CP sees.

**Failure is an event, not a crash.** `plan.rejected` is an ordinary declared outcome the Kernel/routing layer treats as a lifecycle input, exactly like `plan.created` — never a silent halt, never a process failure. Rejection is data flowing forward, not an exception flowing up.

**Retry philosophy.** At-least-once delivery (`ARCHITECTURE.md` communication model) means CP must be idempotent by `event_id`: a redelivered `request.admitted` replays to the *identical* plan. Determinism (CP/00 §9) is the entire retry safety net — CP carries no retry-specific logic, no dedup table beyond the standard idempotency discipline every consumer already owes the bus. Re-running the same inputs through the same deterministic pipeline is itself the correct redelivery behavior.

**Publish discipline.** CP publishes only its declared set (CP/00 §4); log-before-publish, same as every bus participant (`ARCHITECTURE.md` communication model).

---

## 3. RSM (Request State Manager)

| | |
|---|---|
| Purpose of the boundary | Read-only visibility of runtime request state into CP; downstream mirror of CP's output out of CP |
| CP assumes | Identity/plan/budget blocks are current-as-of-query, never stale-by-design |
| CP guarantees | Every published plan artifact is mirrored into RSM's plan block via CP's declared events — CP never writes state directly |
| Never crosses | RSM is never an upstream decision authority for CP (same doctrine as CM↔RSM, RSM/04) — CP never treats RSM content as license to change a planning decision already made from Request Memory + registry |

**Direction of authority.** CP reads request state (identity, plan, budget blocks) as read-only INPUT via RSM's query surface. RSM's plan block is populated by reducers consuming `plan.*` events — CP is upstream of that block, never a consumer racing its own writes.

**Planning state is CP-internal.** In-flight, unpublished graph construction (CP/02 §2 staged refinement) is ephemeral and lives nowhere RSM can see it. RSM records only *published* artifacts' references — never drafts, never partial graphs, never content mid-construction.

**Revision, not mutation.** `plan.revised` produces a new immutable artifact (CP/02 §4 immutability). RSM tracks the succession — replan lineage — as a chain of references; there is no in-place state edit on either side of this boundary.

---

## 4. UMS (Unified Memory System)

**Phase-3 refinement — stated explicitly, not a contradiction.** CP/00 §13's UMS row left a narrow door open: "CP touches UMS only where the frozen spec permits registry-independent knowledge lookups... never scanning, never similarity." This phase closes that door. **Binding decision: CP never queries UMS directly. CM is CP's sole knowledge gateway.**

**Rationale.** This extends upward a discipline already fixed at Core Runtime layer: the future Reasoning Engine never sees the repository (CM's blueprint) — by the same logic, no Execution Service, and no planning component, gets a second knowledge path. Retrieval stays behind CM's single door (Law 2) at every layer, not just the layer where it was first stated. Two knowledge paths into CP — Request Memory plus an ad hoc UMS lookup — would make planning knowledge non-reproducible: Request Memory is hashed and auditable (CP/00 §8 explainability bar); a direct UMS query bypassing CM's budget/provenance annotations is neither. Determinism (CP/00 §9) requires exactly one knowledge channel, or replay cannot be guaranteed byte-for-byte.

| | |
|---|---|
| CP assumes | All repository/historical knowledge arrives inside Request Memory or not at all |
| CP guarantees | Zero direct UMS calls, zero private knowledge shortcuts, at any confidence level |
| Never crosses | No CP code path holds a UMS query handle |

---

## 5. CM (Context Manager)

| | |
|---|---|
| Purpose of the boundary | CP requests planning context by objective + token budget; CM assembles and returns Request Memory |
| CP assumes | CM's budget/provenance/staleness annotations on Request Memory are authoritative and trustworthy as given |
| CP guarantees | Consumes without re-filtering, re-ranking, or re-assembling — trusting the artifact is the entire contract |
| Never crosses | CP never queries the repository itself (§4); CM never sees raw user intent — only the objective + budget CP hands it |

**Insufficiency is not an error.** If Request Memory lacks what a requirement needs, that is not a CM failure or a CP crash — it surfaces as the *information-incompleteness* confidence source (CP/02 §8), which may drive `reject-for-clarification` (CP/02 §8 disposition table). The insufficiency is data flowing into CP's own deterministic confidence aggregation, not an exception.

**Clarification routes upstream, never sideways.** A clarification need is CP *output* — carried as the rejection reason on `plan.rejected` — never CP interrogating the user directly. Talking to the user is Frontend/Kernel territory; CP has no user-facing surface at all.

**No re-work of context.** CP never assembles, filters, or re-ranks context. Consuming Request Memory means trusting CM's annotations as given — CP re-deriving what CM already decided would be a second, unaudited context assembler, the exact drift CM was built to prevent.

---

## 6. Scheduler (Workflow Scheduler)

The largest contract, because the CP/Scheduler seam is where V2's single-owner law is most load-bearing: two interpreters of one intent recreate V1-H1's cascade at system scale.

| | |
|---|---|
| Purpose of the boundary | Scheduler *consumes* the sealed graph; CP produces it. Nothing about the graph's meaning is renegotiated after publication |
| CP assumes | Scheduler treats the published graph as ground truth for WHAT and dependency structure; Scheduler supplies its own truth for WHEN |
| CP guarantees | A `plan.created`/`plan.revised` graph is self-describing: every dependency, priority band, alternative group, and gap the Scheduler needs is already on the artifact (CP/00 §13: "the plan artifact is the entire interface") |
| Never crosses | Scheduler never reaches into CP internals; CP never receives or reacts to scheduling telemetry as a planning input |

**Ownership split, stated as a table.**

| Concern | Owner | Visible to the other side? |
|---|---|---|
| Graph content (nodes, edges, gaps) | CP, forever immutable | Scheduler reads it, never edits it |
| Execution order, timing, resource allocation, preemption | Scheduler | Invisible to CP — CP never learns the chosen order |

**Priority is input, not mandate.** Priority bands (CP/02 §7) are one factor among Scheduler's own concerns — resources, budgets, backpressure (`ARCHITECTURE.md` state ownership: "work order, priorities, budgets, preemption state" owned by Scheduling). CP assigning CRITICAL never forces Scheduler to run that node first; it only tells Scheduler what fails outright without it.

**Dependency truth has one source.** Scheduler never rediscovers capabilities, never re-derives dependencies from the registry — the graph's `requires` edges (CP/02 §4, §5) are the dependency truth, full stop. This resolves the tension CP/02 flagged only implicitly: Scheduler consuming the registry a second time to "double-check" ordering would be a second interpreter of the same dependency data, capable of drifting from CP's expansion (different registry snapshot, different tie-break) — exactly the two-authority failure mode the single-owner law forbids.

**Alternative branches — selection is Scheduler's, never CP's.** CP records that alternatives exist and their relative rank (CP/02 §4, §7); it never picks one. Scheduler, in cooperation with Plugin Runtime's fulfillment data, selects among ranked alternatives *at execution time* using runtime information CP structurally cannot have — provider health, current load, live reliability scores. Selection never alters the graph: chosen-vs-not-chosen is execution telemetry, recorded downstream, not a plan mutation. The published artifact still shows every alternative that was available, unchanged.

**Failure propagation is replanning, never local patching.** Step or verification failures route to a new CP invocation producing `plan.revised` — a new artifact, through the full CP pipeline (CP/02 §2 stages, §10 gates), never a Scheduler-side patch to the existing graph. `ARCHITECTURE.md`'s lifecycle diagram shows exactly this: `verify.failed → SCH->>CP: replan(step, failure) → CP-->>OBS: plan.revised`. Scheduler requests; CP replans; the graph before the failure is untouched (CP/02 §4 immutability).

**Why never rediscover, never reinterpret.** Two interpreters of one intent is divergent authority by construction — the V1-H1 cascade re-created at system scale, just moved from "one bad classifier" to "one bad re-derivation downstream of a good plan." Single-owner law: CP is the only place intent becomes a graph; Scheduler is the only place a graph becomes an order. Crossing either direction breaks both guarantees at once.

---

## 7. Plugin Runtime

| | |
|---|---|
| Purpose of the boundary | Late binding — CP binds steps to abstract capability IDs; Plugin Runtime binds IDs to concrete providers, strictly later |
| CP assumes | The registry is a read-only catalog of declared capabilities plus health/reliability events; nothing more |
| CP guarantees | Zero implementation awareness in any published plan — plans reference vocabulary (CP/01 §1), never providers |
| Never crosses | CP never mutates the registry (CP/00 invariant 5, CP/01 §9); CP never names a plugin, MCP server, or tool anywhere in a plan |

**Late binding, operationalized.** CP/01 §1's stability argument — "a plugin can be replaced, upgraded, or removed and every plan, prior, and binding that referenced the capability stays valid" — is what this contract exists to guarantee mechanically. Provider replacement, upgrade, or outage is invisible to every published plan by construction, because plans never encode a provider in the first place.

**CP's registry interaction is narrow.** Read-only catalog access (declared capability ids, metadata per CP/01 §7) plus `plugin.registered` / `plugin.health.changed` as matching inputs — events that refresh CP's view of what's currently declared and currently healthy, consumed the same way as any other declared-input event (CP/00 §4).

**Why CP stays implementation-unaware.** Awareness would couple planning validity to provider churn: every plugin release would risk invalidating existing plans, defeating the entire point of a stable capability vocabulary. Not knowing is the feature.

---

## 8. Prompt Compiler (future)

No direct contract exists — CP and Prompt Compiler interact only indirectly, both consuming plan-derived artifacts further downstream (bound provider, step context) that neither owns.

| | |
|---|---|
| CP requires of the future component | Never receive raw user intent |
| Why | Intent has exactly one interpreter — CP. A prompt built directly from raw intent is a second, unaudited planner, running in parallel to CP with no gate, no confidence, no graph |
| What it may consume instead | Execution strategy prepared downstream of CP's plan: step + bound provider + step context — assembled and handed to it by later components, never by CP |
| What it may never consume | Capability semantics. Capabilities are OS vocabulary (CP/01 §1); they are not prompt material, and CP never hands them over for that purpose |

---

## 9. Reasoning Engine (future)

| | |
|---|---|
| CP requires of the future component | Absorb all system nondeterminism — CP/00 §9 names Reasoning as the only place nondeterminism is permitted; the quarantine is total |
| What travels back to CP | Nothing live. Reasoning outcomes influence *future* planning solely via the Experience → priors loop (§11) — never a direct signal into an in-flight or existing graph |
| Model neutrality | Nothing in a plan names, assumes, or optimizes for any model or reasoning method (CP/00 §7, invariant 6) |

CP is fully upstream and fully insulated: whatever Reasoning does with a bound step, CP's artifact for that step was already sealed before Reasoning ever ran.

---

## 10. Verification Engine (future)

Two different questions, cleanly split — the split is the entire contract.

| Question | Owner | When | Checks |
|---|---|---|---|
| Is this a well-formed plan? | CP | Pre-publication | CP/02 §10 structural gates (existence, closure, cycle-free, dedup, provenance, confidence, determinism) |
| Did the work satisfy the capability's verification expectation? | Verification | Post-execution | Outcome against the capability's declared verification expectation (CP/01 §7) |

**The bridge.** Verification expectations are authored once, in registry metadata (CP/01 §7 — "first-class, mandatory"), and travel unchanged from there through graph nodes (CP/02 §4 node fields carry the cited capability id, which carries its metadata by reference) into Verification's gate inputs. **CP is the carrier of this data, never the checker of outcomes** — CP states what would count as done; only Verification decides whether it happened.

**A third, distinct gate.** `ARCHITECTURE.md`'s "plans verified by Verification before scheduling" (CP/00 invariant 10) names a *structural pre-check* on the published artifact — visible in the lifecycle sequence as `CP->>VER: pre-check plan / VER-->>CP: verify.passed (plan admissible)`. This is a third gate, distinct from both CP's internal §10 gates and post-execution outcome verification. Three gates, three purposes: CP's own gates ask "is this graph internally valid," Verification's pre-check asks "is this graph admissible to schedule," Verification's post-execution check asks "did the work satisfy the outcome."

**No edits, only replans.** Verification never edits a published graph. A failed verification triggers a new CP invocation and a new artifact (§6), never plan surgery — consistent with graph immutability (CP/02 §4, invariant 6).

---

## 11. Experience & Knowledge Store (future)

| | |
|---|---|
| CP requires of the future component | Consume CP's event stream as learning fuel — plans, rejections, gaps, confidence — without ever mutating what it consumes |
| What CP consumes back | `prior.updated` — versioned prior data, treated strictly as CP input (CP/00 §13: "Priors arrive as versioned data via events; CP treats them as input, never produces them") |
| Never crosses | Experience never mutates historical plans or graphs; history is append-only audit substrate, same discipline as Episodic memory (`ARCHITECTURE.md` memory hierarchy) |

**What flows out of CP toward Experience.** Gap statistics become capability-evolution signals routed toward registry curation (CP/02 §9: "Gaps feed the Experience layer as future-capability signals"). Failure/rejection analytics become prior-refinement fuel. Neither is a live control signal — both are historical fuel for a future prior version.

**Determinism preserved across updates.** Priors are versioned, declared inputs. Plan determinism is conditioned on the full input tuple: (request, registry version, priors version, Request Memory hash, config version) — CP/00 §9's determinism bar, made precise. A prior update changes the *inputs* a future plan sees; it never changes the *rules* CP applies to any input tuple, including a tuple already planned. Replaying an old tuple with an old priors version still reproduces the old plan exactly.

---

## 12. Observability

| | |
|---|---|
| CP guarantees | Every planning decision is traceable from the artifact + event stream alone — no hidden state, no side channel (CP/00 §8 explainability bar) |
| Mechanism | Graph lineage — request → intent classification → graph → revision chain — is reconstructable purely from the declared event set (CP/00 §4) and the artifacts they carry |
| Failure visibility | Rejections and gaps are first-class reasons on the artifact/event, never logs-only diagnostics requiring internal access |

The explainability bar from CP/00 §8 is restated here as an integration guarantee, not a new rule: "a plan explains itself without access to CP internals" is only true if every fact needed for that explanation actually crosses the bus. Observability's role is to be the place that guarantee is checkable from outside CP.

---

## 13. Failure taxonomy & recovery

| Failure | Belongs to |
|---|---|
| Admission failure | Kernel (upstream — never reaches CP) |
| Context assembly failure | CM (upstream — surfaces to CP as information-incompleteness, §5) |
| State absence / staleness | RSM (upstream — CP reads what's there; absence is data, not a CP defect) |
| Rejection with reason, gap publication, low-confidence clarification request | **CP** |
| Scheduling failure (unfulfillable ordering, resource exhaustion) | Scheduler (downstream) |
| Fulfillment failure (no healthy provider at execution time) | Plugin Runtime (downstream) |
| Execution / reasoning failure | Execution / Reasoning Engine (downstream) |
| Outcome failure (work done, didn't satisfy verification expectation) | Verification Engine (downstream) |

**Recovery philosophy.** Recovery from a planning failure is **replan with better inputs** — clarified intent, updated registry, a new priors version — never retry-the-same-and-hope. Determinism makes blind retry pointless by construction: identical inputs produce the identical rejection, every time (CP/00 §9). The only way out of a rejection is a changed input.

**Replanning triggers, enumerated.**

1. Verification (post-execution) reports outcome failure on a step.
2. Scheduler reports an unfulfillable binding (no viable provider found at execution time).
3. A registry change invalidates capabilities a published plan referenced (deprecation/retirement with no compatible replacement).
4. Upstream intent clarification resolves a prior `reject-for-clarification`.
5. A `prior.updated` is material to a previously rejected or marginal plan.

Each trigger produces a new CP invocation through the full pipeline (CP/02 §2), never a shortcut, never a patch.

---

## 14. Contract summary matrix

| Neighbor | CP promises | CP expects | Crosses the boundary | Never crosses |
|---|---|---|---|---|
| Kernel | `plan.created`/`plan.rejected` per admitted request; idempotent replay | Valid, routed `request.admitted` events only | Events only | Lifecycle ownership, admission authority |
| RSM | Published artifacts mirrored via events | Read-only, current request state | Query (read) + events (write, indirect via reducers) | In-flight plan state, direct state writes |
| UMS | Zero direct queries | N/A — door closed | Nothing, ever | Any direct query surface |
| CM | Objective + budget request; trust the artifact as given | Request Memory with provenance/budget/staleness annotations | Query (request) + artifact (return) | Re-filtering/re-ranking context, seeing raw repository |
| Scheduler | Self-describing, immutable, sealed graph | Zero rediscovery, zero re-derivation, zero graph mutation | Artifact (`plan.created`/`plan.revised`) + replan requests | Order, timing, resource decisions, alternative selection |
| Plugin Runtime | No implementation-aware plans, ever | Read-only registry + health/reliability events | Registry read + events | Registry mutation, provider naming |
| Prompt Compiler | Nothing direct | N/A (indirect only) | Nothing | Raw intent, capability semantics |
| Reasoning Engine | Nothing direct; model-neutral plans | N/A (fully downstream) | Nothing live | Any live signal back into CP |
| Verification Engine | Verification expectations carried in nodes | Structural pre-check on published artifacts | Metadata carry-through + pre-check events | Outcome checking (CP), graph edits (Verification) |
| Experience Store | Event stream (plans, rejections, gaps, confidence) as fuel | `prior.updated` as versioned input | Events (out) + prior artifact (in) | History mutation, live prior injection mid-plan |
| Observability | Full decision traceability from artifact + events alone | N/A (passive consumer) | Telemetry via the bus | — |

---

## 15. Integration invariants

Immutable for all later CP phases and for every neighbor's own design.

1. Planning never schedules — CP never encodes execution order (CP/02 invariant 9).
2. Scheduling never replans — it requests replanning; only CP produces a new plan artifact.
3. Scheduler never re-derives dependencies — the graph's `requires` edges are the sole dependency truth.
4. Plugins never redefine capabilities — capability meaning is fixed by CP/01 §3, §6; providers only fulfill.
5. Reasoning never touches capability semantics — model/method neutrality is absolute (CP/00 invariant 6).
6. Verification never edits a published graph — a failed verification triggers replanning, never surgery.
7. Experience never mutates history — plans, rejections, gaps are append-only audit substrate.
8. CM is CP's sole knowledge gateway — CP never queries UMS directly (§4, refining CP/00 §13).
9. Intent has exactly one interpreter — CP. No neighbor independently reinterprets raw intent.
10. Prompt Compiler never sees raw intent — only plan-derived execution strategy.
11. Late binding — plans reference capabilities, never providers; provider churn never invalidates a plan.
12. Published artifacts are immutable everywhere they are read — CP, RSM, Scheduler, Verification, Experience all treat a sealed graph as fixed.
13. Determinism is conditioned on declared, versioned inputs — (request, registry version, priors version, Request Memory hash, config version) — never on hidden state.
14. All cross-component influence flows through declared events or artifacts, never a side channel, direct internal call, or shared mutable state.
15. Every rejection and gap carries a machine-readable reason — silence at any boundary is a defect, not an edge case.

---

Status: Phase 3 system integration frozen. CP's contracts with every neighbor are fixed; later phases (if any) operate within this integration surface and do not renegotiate it.
