"""SGPE System Integration (SGPE/05; the OS weave). Pure COMPOSITION of
the five frozen parts — no new policy logic, no new SGPE subsystem, no
responsibility moved:

- `GovernanceRuntime` — the operating system's one handle on SGPE:
  carries the Store (authored world), the Grant Ledger (runtime world),
  the bus, the shared Evaluator memo (EV §8 — semantically invisible,
  documented, not hidden), and a version-keyed registry of compiled
  snapshots whose every entry is hash-verified through the R5
  regeneration oracle (AC-9: snapshots are derived and regenerable,
  never system-of-record — losing this registry loses nothing).
- `RequestGovernance` — the frozen Effective Policy view a request
  carries (SGPE/03 §11: "the Resolver pinning one (snapshot, position)
  pair for a request's lifetime and asking through it"). Every
  consultation stamps the ledger position it used (EPR-4) and evaluates
  locally over immutable stamped inputs — admission is the only
  synchronous SGPE round-trip (SGPE/05 §2 topology note).
- `route_approval` / `route_revocation` — the Kernel-routed door from
  approval outcomes (IVS-collected) into request-scoped Ledger appends
  (SGPE/00 §3.5, SGPE/05 §3). Provenance is derived from the
  REQUIRE_APPROVAL Decision's own stamps — the traceability chain of
  GL §1.5, closed mechanically.
- `approval_ask_payload` / `resolve_citation` — IVS's integration
  surface: the render payload for an ask (signature + explanation +
  stamps) and citation-triple resolution against the Store, which is
  the READER's act (EV §5), never the Evaluator's.

**Consultation contract (SGPE/05 §1), what this module guarantees:**
pose a canonical Question through the request's frozen EP, receive a
Decision or an ill-posed verdict, enforce it yourself. No Decision = no
action — enforcement stays with the consumer (INV-1); this module never
executes, blocks, retries, or meters anything.

**Failure law (SGPE/05 §5), where each case lands here:** no active
snapshot / unreachable Ledger ⇒ `admit()` raises `AdmissionRefusedError`
(EPR-5, fail-closed); snapshot artifact lost ⇒ `snapshot_for()`
regenerates from the manifest, hash-verified, and an unknown version or
hash mismatch raises — consultations cannot proceed, so no action;
malformed Questions come back as ill-posed verdicts (EV-6), never
guessed; a failed grant append simply never lands (the ask stays
unanswered, REQUIRE_APPROVAL keeps meaning forbidden). Nothing in this
module recovers silently, guesses, or bypasses governance.

**Replay (EPR-7/EV-9):** `view_for()` rebuilds a request's view from the
RSM-persisted stamp dict; `RequestGovernance.replay()` re-evaluates a
recorded consultation from its stamps under the recorded evaluation
ruleset version, bus-silent (replay is verification, not a governance
act — re-emitting `policy.decided` would double-count the audit record).
Byte-comparison is the caller's (VAE's) oracle."""
from . import compiler as compiler_mod
from . import document as document_mod
from . import rule as rule_mod
from .evaluator import Decision, evaluate
from .ledger import GrantLedger, build_grant_provenance, build_scope_binding
from .resolver import (
    EffectivePolicy,
    admit as resolver_admit,
    consultation_slice,
    effective_policy_from_dict,
)
from .store import PolicyStore


class RuntimeRefusal(Exception):
    """Base for runtime.py refusals."""


class MalformedRuntimeInputError(RuntimeRefusal):
    """A runtime seam was handed structurally invalid arguments — a
    caller bug, never a governance outcome."""


class UnknownSnapshotVersionError(RuntimeRefusal):
    """No activated manifest records this snapshot version — the
    consultation cannot proceed, and per EV §2 no Decision means no
    action; there is no fallback snapshot, ever."""


class ApprovalRoutingError(RuntimeRefusal):
    """`route_approval`/`route_revocation` was asked to route something
    that is not a routable approval outcome (not a REQUIRE_APPROVAL
    Decision, or a Decision belonging to a different request)."""


class GovernanceRuntime:
    """The OS's handle on SGPE. Holds no governance state of its own:
    the Store and Ledger are the two append-only records (SGPE/05 §4),
    the memo is disposable (EV-8), and the snapshot registry is derived,
    hash-verified data (AC-9). Dropping this object and rebuilding it
    from the same Store + Ledger reproduces identical behavior."""

    def __init__(self, store, ledger, bus=None):
        if not isinstance(store, PolicyStore):
            raise MalformedRuntimeInputError("runtime.store_not_built:" + repr(store))
        if not isinstance(ledger, GrantLedger):
            raise MalformedRuntimeInputError("runtime.ledger_not_built:" + repr(ledger))
        self._store = store
        self._ledger = ledger
        self._bus = bus
        self._memo = {}       # EV §8: keyed by every answer-changing input; evict anytime
        self._snapshots = {}  # version -> CompiledSnapshot, each R5-verified on entry (derived, not record)

    # -- the D6 active-version fact (what the Kernel wires into admission) --

    def active_snapshot_version(self):
        """The single atomically-published activation fact (AC-7/D6);
        None before the first activation — which admission then refuses,
        enforcing the bootstrap canon (first activation precedes first
        admission, SGPE/05 §3)."""
        activations = self._store.activations()
        return activations[-1].snapshot_version if activations else None

    # -- snapshots as derived, regenerable artifacts (AC-9) ------------------

    def snapshot_for(self, snapshot_version):
        """The compiled snapshot for an activated version — regenerated
        from its manifest through the R5 oracle (recompile under the
        RECORDED compiler ruleset version, byte-compare the content
        hash). The registry entry is just the verified result kept
        warm; `compiler.regenerate` raising on hash mismatch is the
        lost/corrupt-artifact rule of SGPE/05 §5: no verified snapshot,
        no consultations, no action."""
        if snapshot_version in self._snapshots:
            return self._snapshots[snapshot_version]
        manifest = next((m for m in self._store.manifests()
                         if m.snapshot_version == snapshot_version), None)
        if manifest is None:
            raise UnknownSnapshotVersionError("runtime.unknown_snapshot_version:" + repr(snapshot_version))
        snapshot = compiler_mod.regenerate(self._store, manifest)
        self._snapshots[snapshot_version] = snapshot
        return snapshot

    # -- admission (Kernel-invoked; Resolver does the binding, EPR canon) ----

    def admit(self, request_id, principal, project):
        """Kernel admission seam: Resolver binds EP(R) fail-closed
        (EPR-1/EPR-5), and the returned view is what the Kernel hands to
        RSM (persist `view.stamp()`) and to the request's consumers."""
        ep = resolver_admit(self.active_snapshot_version, self._ledger, request_id, principal, project)
        return RequestGovernance(self, ep)

    def view_for(self, ep_stamp):
        """Rebuild a request's governance view from the RSM-persisted
        stamp (EPR-7): accepts the stamp dict or an EffectivePolicy."""
        if isinstance(ep_stamp, EffectivePolicy):
            return RequestGovernance(self, ep_stamp)
        return RequestGovernance(self, effective_policy_from_dict(ep_stamp))

    # -- the Kernel-routed approval door (SGPE/00 §3.5, SGPE/05 §3) ----------

    def route_approval(self, view, decision, grantor, reason, bound=None):
        """An approval outcome (IVS-collected, Kernel-routed) becomes a
        request-scoped grant append: signature from the REQUIRE_APPROVAL
        Decision, scope bound to the asking request (the §2.3 closed
        door), provenance from the Decision's own stamps (GL §1.5)."""
        self._check_routable(view, decision)
        if decision.effect_kind != "REQUIRE_APPROVAL" or decision.ask_signature is None:
            raise ApprovalRoutingError("runtime.not_an_approval_ask:" + repr(decision.effect_kind))
        return self._ledger.append_grant(
            decision.ask_signature,
            build_scope_binding("request", view.effective_policy.request_id),
            _provenance_from_decision(decision, grantor, reason),
            bound=bound)

    def route_revocation(self, view, decision, grant_id, grantor, reason):
        """An emergency revocation uses the same request-scoped door
        (SGPE/04 §2.3): a new Ledger record, provenance from the same
        Decision chain, visible to the running request immediately by
        deny-overrides."""
        self._check_routable(view, decision)
        return self._ledger.append_revocation(
            grant_id, _provenance_from_decision(decision, grantor, reason))

    def _check_routable(self, view, decision):
        if not isinstance(view, RequestGovernance):
            raise MalformedRuntimeInputError("runtime.view_not_built:" + repr(view))
        if not isinstance(decision, Decision):
            raise ApprovalRoutingError("runtime.not_a_decision:" + repr(decision))
        if decision.snapshot_version != view.effective_policy.snapshot_version:
            raise ApprovalRoutingError(
                "runtime.decision_from_different_world:" + repr(decision.snapshot_version))


class RequestGovernance:
    """The frozen Effective Policy view one request carries. Immutable
    binding (EPR-2); consultations are local evaluation over stamped
    inputs with shared memoization (SGPE/05 §2). This object holds no
    request state — RSM does (EPR-6); it is reconstructible any time
    from `stamp()` via `GovernanceRuntime.view_for`."""

    def __init__(self, runtime, effective_policy):
        if not isinstance(runtime, GovernanceRuntime):
            raise MalformedRuntimeInputError("runtime.runtime_not_built:" + repr(runtime))
        if not isinstance(effective_policy, EffectivePolicy):
            raise MalformedRuntimeInputError(
                "runtime.effective_policy_not_built:" + repr(effective_policy))
        self._runtime = runtime
        self.effective_policy = effective_policy

    def stamp(self):
        """The RSM persistence shape (EPR-6/EPR-7): everything needed to
        rebuild this view is this dict plus the two append-only records."""
        from .resolver import effective_policy_to_dict
        return effective_policy_to_dict(self.effective_policy)

    def consult(self, question):
        """SGPE/05 §1's uniform contract: one canonical Question in, one
        Decision (or ill-posed verdict) out, evaluated against the frozen
        EP at the CURRENT ledger position — which the Decision stamps
        (EPR-4), making this consultation replayable forever."""
        ep = self.effective_policy
        position = self._runtime._ledger.position()
        slice_records = consultation_slice(self._runtime._ledger, ep, position)
        snapshot = self._runtime.snapshot_for(ep.snapshot_version)
        return evaluate(ep.snapshot_version, snapshot, position, slice_records, question,
                         bus=self._runtime._bus, memo=self._runtime._memo)

    def replay(self, question, grant_slice_position, evaluation_ruleset_version):
        """Re-run one recorded consultation from its stamps (EPR-7):
        regenerated snapshot (AC-9), slice reconstructed at the recorded
        position (GL-6), recorded evaluation ruleset version (EV-9).
        Bus-silent and memo-free: replay is VAE's verification act, not
        a governance act — it must neither re-announce `policy.decided`
        nor depend on live-path memo state."""
        ep = self.effective_policy
        slice_records = consultation_slice(self._runtime._ledger, ep, grant_slice_position)
        snapshot = self._runtime.snapshot_for(ep.snapshot_version)
        return evaluate(ep.snapshot_version, snapshot, grant_slice_position, slice_records, question,
                         evaluation_ruleset_version=evaluation_ruleset_version, bus=None, memo=None)


# -- IVS integration surface (SGPE/05 §2 IVS row) -------------------------------

def approval_ask_payload(decision):
    """What IVS renders for a REQUIRE_APPROVAL Decision: the ask
    signature (what a grant must cover), the trace-as-explanation
    (citation triples for display), and the replay stamps. The payload
    is presentation input only — IVS receives ask payloads, never policy
    answers to enforce (SGPE/05 §2)."""
    if not isinstance(decision, Decision) or decision.effect_kind != "REQUIRE_APPROVAL":
        raise MalformedRuntimeInputError("runtime.not_an_approval_ask:" + repr(decision))
    return {
        "ask_signature": decision.ask_signature,
        "explanation": [dict(step) for step in decision.explanation],
        "snapshot_version": decision.snapshot_version,
        "grant_slice_position": decision.grant_slice_position,
        "evaluation_ruleset_version": decision.evaluation_ruleset_version,
        "question_hash": decision.question_hash,
    }


def resolve_citation(store, citation):
    """Citation-triple resolution for human display — the READER's act
    against the Store (EV §5), never the Evaluator's. Returns the cited
    document header identity and, when the citation names a rule, that
    rule's canonical dict."""
    if not isinstance(store, PolicyStore):
        raise MalformedRuntimeInputError("runtime.store_not_built:" + repr(store))
    doc_id, version, rule_id = tuple(citation[0]), citation[1], citation[2]
    document = store.document_version(doc_id, version)
    if document is None:
        raise MalformedRuntimeInputError("runtime.citation_names_unknown_document:" + repr(citation))
    resolved = {
        "doc_id": list(doc_id), "version": version, "rule_id": rule_id,
        "scope": document.header.scope,
        "provenance": document_mod.provenance_to_dict(document.header.provenance),
        "rule": None,
    }
    if rule_id is not None:
        matching = [r for r in document.rules if r.rule_id == rule_id]
        if not matching:
            raise MalformedRuntimeInputError("runtime.citation_names_unknown_rule:" + repr(citation))
        resolved["rule"] = rule_mod.to_dict(matching[0])
    return resolved


def _provenance_from_decision(decision, grantor, reason):
    return build_grant_provenance(grantor, decision.snapshot_version, decision.grant_slice_position,
                                    decision.evaluation_ruleset_version, decision.question_hash, reason)


if __name__ == "__main__":
    from . import vocabulary as vocabulary_mod
    from .bus_double import BusDouble
    from .evaluator import build_question
    from .storage_double import StorageDouble

    store = PolicyStore(StorageDouble())
    v1 = vocabulary_mod.default_v1()
    store.append_vocabulary(v1)
    store.append_vocabulary(vocabulary_mod.evolve(v1, operations=("execution.run",)))
    prov = document_mod.build_provenance("alice", "epoch-0", "constitution")
    header = document_mod.build_header("system", "baseline", ("execution",), prov, 2, 1)
    r = rule_mod.build_rule("r1", rule_mod.build_target("execution", "run", "*"),
                             rule_mod.build_effect("REQUIRE_APPROVAL"))
    store.append_document(document_mod.build_document(header, (r,)))

    bus = BusDouble()
    ledger = GrantLedger(StorageDouble(), bus=bus)
    runtime = GovernanceRuntime(store, ledger, bus=bus)

    # bootstrap canon: admission before first activation fails closed
    from .resolver import AdmissionRefusedError
    try:
        runtime.admit("req-1", "alice", "proj-x")
        raise SystemExit("pre-activation admission accepted")
    except AdmissionRefusedError:
        pass

    result = compiler_mod.compile_snapshot(store, store.catalog_position())
    compiler_mod.activate(store, result)

    view = runtime.admit("req-1", "alice", "proj-x")
    question = build_question("kernel", "req-1", "alice", "execution", "run", "repo-x", {})
    d1 = view.consult(question)
    assert d1.effect_kind == "REQUIRE_APPROVAL"

    payload = approval_ask_payload(d1)
    assert payload["ask_signature"] == d1.ask_signature
    cited = resolve_citation(store, d1.explanation[0]["winner"])
    assert cited["rule"]["rule_id"] == "r1"

    grant = runtime.route_approval(view, d1, "approver", "looks fine")
    d2 = view.consult(question)
    assert d2.effect_kind == "ALLOW"
    assert bus.messages("grant.recorded")[0]["payload"]["record_id"] == grant.record_id

    # RSM round-trip + byte-exact replay
    from .evaluator import decision_bytes
    restored = runtime.view_for(view.stamp())
    for original in (d1, d2):
        replayed = restored.replay(question, original.grant_slice_position,
                                     original.evaluation_ruleset_version)
        assert decision_bytes(replayed) == decision_bytes(original)

    # emergency revocation through the same door
    runtime.route_revocation(view, d1, grant.record_id, "approver", "emergency")
    assert view.consult(question).effect_kind == "REQUIRE_APPROVAL"

    print("runtime selftest ok")
