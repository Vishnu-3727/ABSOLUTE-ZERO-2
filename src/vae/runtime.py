"""VAE Phase 5 -- Verification's composition root (VAE/06 Phase 5). Mirrors
`ro/runtime.py`'s shape: every collaborator is either injected or constructed
explicitly in `__init__` (no hidden/ambient state), bus/storage/execution are
injected PORTS, and this module adds NO governance logic of its own -- every
rule already lives in Phases 1-4 (intake, delegation, judgment, static
checks, derivation, emission, pending); this file only sequences the calls
VAE/04 §2/§5 already fixed: handle demand -> judge -> persist -> publish.

`Verification.replay()` is the byte-identical golden-artifact check VAE/05
§8 requires ("every verdict event re-derives from its persisted evidence
record") and RO/05's runtime.py `replay()` pattern reused verbatim: reload
an account-bearing `EvidenceRecord` from Storage BY CONTENT-ADDRESSED KEY
ALONE (evidence.from_canonical, Phase 5), re-derive with the injected
policy (derivation.derive -- pure, VAE-I6), and assert the reconstructed
verdict envelope (emission.build_verdict_envelope, Phase 5) is byte-
identical to what was originally published. Zero live judgment state is
touched; VAE-O10's "recovery re-derives... reaches verdicts identical to
those an uninterrupted VAE would have reached" is exactly this check, run
without a crash as the trigger.

**Interpretation call, flagged (mirrors pending.py's own call 1 for the
identical reason):** `open_from_demand` needs each required check's
delegated-vs-static classification and per-check verification level to
build a `Judgment`; `rules.py`'s `ArtifactRules` only carries
`required_checks`/`depth`/`deadlines`, never that classification (Phases
1-4 never modeled it either -- every existing test supplies
`delegated_check_levels`/`static_check_levels` directly in the demand
event, exactly as `pending.rebuild`'s fixture demands do). This module
takes the SAME reading pending.py already took: classification comes from
the demand event, only each check's DEADLINE is fetched fresh from
`rules_store` (the one part of "rules-assigned" that IS durable data).
The ~8-line snippet that builds `delegated_checks`/`static_checks_spec`
from a demand + `ArtifactRules` is intentionally duplicated from
`pending.rebuild` rather than imported: `pending.py` is crash-recovery-
scoped (a batch of demand events replayed against one fresh `Intake`) and
this module is live-single-event-scoped (one shared `Intake`, sequential
handling) -- different callers, same small mapping, not worth a shared
import that would couple the two modules' otherwise-independent recovery
and live-operation concerns."""
import json

from . import delegation as delegation_mod
from . import derivation as derivation_mod
from . import emission as emission_mod
from . import events as events_mod
from . import evidence as evidence_mod
from . import intake as intake_mod
from . import judgment as judgment_mod
from . import rules as rules_mod
from . import telemetry as telemetry_mod
from .bus_double import BusDouble
from .static_checks import StaticCheckRegistry
from .storage_double import StorageDouble


def _canonical_account(account):
    return json.dumps(account, sort_keys=True, separators=(",", ":"))


class RuntimeRefusal(Exception):
    """Base for runtime.py refusals."""


class NoOpenJudgmentError(RuntimeRefusal):
    """A per-check operation (dispatch/resolve/run_static) named an
    artifact with no open judgment in this projection -- caller misuse
    (e.g. the artifact is already terminal, or demand was never opened),
    never an operational outcome the way an ordinary Storage rejection is."""


class ReplayMismatchError(RuntimeRefusal):
    """VAE/05 §8: a replayed reconstruction diverged from what was
    originally derived or published. Always loud -- this is the
    determinism-rate-100% gate, RO/05's runtime.py `replay()` precedent."""


class Verification:
    """One VAE composition root, injected collaborators, zero hidden
    state. `policy` (derivation.DerivationPolicy) is required -- no
    default, mirroring rules.py's own "never a default rule set"
    discipline; a caller must decide which versioned policy governs."""

    def __init__(self, *, policy, rules_store=None, bus=None, storage=None,
                 static_registry=None, intake=None, telemetry_sink=None):
        self.policy = policy
        self.rules_store = rules_store if rules_store is not None else rules_mod.RulesStore()
        self.bus = bus if bus is not None else BusDouble()
        self.storage = storage if storage is not None else StorageDouble()
        self.static_registry = static_registry if static_registry is not None else StaticCheckRegistry()
        self.intake = intake if intake is not None else intake_mod.Intake()
        self.telemetry_sink = telemetry_sink if telemetry_sink is not None else telemetry_mod.TelemetrySinkDouble()
        self._open = {}  # artifact_ref -> Judgment; VAE's own thin pending view (VAE-O1)

    # -- demand intake (VAE/04 §2) -------------------------------------------

    def handle_demand(self, demand):
        """One demand event -> one Intake outcome. Opens a new Judgment
        only when intake answers OPENED; every other outcome
        (already_open/answered_by_existing_verdict/deduped) is intake.py's
        own job already done -- this method adds nothing on those paths."""
        result = self.intake.receive(demand["event_name"], demand["event_id"],
                                      demand["artifact_ref"], demand["judgment_id"])
        if result.action != intake_mod.OPENED:
            return result

        artifact_rules = self.rules_store.lookup(demand["artifact_type"], demand["rules_version"])
        delegated_checks = {check: {"deadline": artifact_rules.deadlines[check], "level": level}
                             for check, level in demand.get("delegated_check_levels", {}).items()}
        static_checks_spec = {check: {"level": level}
                               for check, level in demand.get("static_check_levels", {}).items()}
        j = judgment_mod.open_judgment(demand["judgment_id"], demand["artifact_ref"],
                                        demand["rules_version"], delegated_checks, static_checks_spec)
        self._open[demand["artifact_ref"]] = j
        return result

    def _require_open(self, artifact_ref):
        j = self._open.get(artifact_ref)
        if j is None:
            raise NoOpenJudgmentError("runtime.no_open_judgment:" + artifact_ref)
        return j

    # -- per-check operations, wiring judgment.py + telemetry.py -------------

    def dispatch(self, artifact_ref, check, execution_double, request):
        j = judgment_mod.dispatch_delegation(self._require_open(artifact_ref), check,
                                              execution_double, request)
        self._open[artifact_ref] = j
        telemetry_mod.emit_check_activity(self.telemetry_sink, artifact_ref, check, "dispatched")
        return j

    def resolve(self, artifact_ref, check, execution_double, now):
        before = self._require_open(artifact_ref)
        before_state = before.delegations[check].state
        j = judgment_mod.resolve_delegation(before, check, execution_double, now)
        self._open[artifact_ref] = j
        new_state = j.delegations[check].state
        if new_state != before_state and new_state in delegation_mod.TERMINAL_STATES:
            phase = "resulted" if new_state == delegation_mod.RESULTED else "expired"
            category = j.record.items[-1].result
            telemetry_mod.emit_check_activity(self.telemetry_sink, artifact_ref, check, phase, category)
        return j

    def run_static(self, artifact_ref, check, metadata):
        j = judgment_mod.run_static_check(self._require_open(artifact_ref), check,
                                           self.static_registry, metadata)
        self._open[artifact_ref] = j
        telemetry_mod.emit_check_activity(self.telemetry_sink, artifact_ref, check,
                                           "static_run", j.record.items[-1].result)
        return j

    # -- close + emit (VAE/04 §5: derive -> persist -> publish) --------------

    def try_close_and_emit(self, artifact_ref):
        """If the open judgment has reached evidence-complete (VAE/04 §5.1
        step 1), close + derive + persist + publish -- emission.py's whole
        choreography, reused verbatim -- emit the judgment-outcome/
        coverage/agreement/derivation-consistency telemetry (VAE-O8:
        unconditional on every completed judgment), and retire the
        artifact from this projection. Returns the EmissionResult, or None
        if the judgment is not yet ready -- never forces early closure."""
        j = self._open.get(artifact_ref)
        if j is None or not judgment_mod.is_closed(j):
            return None
        closed = judgment_mod.close(j)
        result = emission_mod.emit_verdict(closed, self.policy, self.storage, self.bus, self.intake)
        if result.outcome == emission_mod.EMITTED:
            account_record = derivation_mod.attach_derivation(closed.record, self.policy)
            account = account_record.derivation_account
            record_hash = evidence_mod.content_hash(account_record)
            telemetry_mod.emit_judgment_outcome(
                self.telemetry_sink, artifact_ref, closed.rules_version,
                account["verdict"], account["failure_cause"], account["assurance_level"])
            telemetry_mod.emit_coverage_readout(self.telemetry_sink, artifact_ref, account["coverage"])
            telemetry_mod.emit_agreement_records(self.telemetry_sink, artifact_ref, closed.record.items)
            telemetry_mod.emit_derivation_consistency(
                self.telemetry_sink, artifact_ref, closed.rules_version, record_hash, account)
        self._open.pop(artifact_ref, None)
        return result

    # -- replay: byte-identical reconstruction from Storage alone (VAE/05 §8) --

    def replay(self, storage_key, originally_emitted_event):
        """Reload the persisted, account-bearing EvidenceRecord from
        Storage BY ITS CONTENT-ADDRESSED KEY ALONE, re-derive with THIS
        instance's policy, and assert the verdict envelope it reconstructs
        is byte-identical to `originally_emitted_event` (the envelope
        `emission.emit_verdict` actually published). Raises
        ReplayMismatchError loud on any divergence. Zero writes, zero
        clock reads, zero live judgment/pending state consulted -- the
        whole call is a pure function of Storage's bytes plus `policy`."""
        data = self.storage.read(storage_key)
        record = evidence_mod.from_canonical(data)

        expected_key = "vae/ev/" + evidence_mod.content_hash(record)
        if expected_key != storage_key:
            raise ReplayMismatchError("runtime.replay_key_mismatch:" + storage_key)

        # Compared via canonical JSON bytes, not raw Python equality:
        # from_canonical necessarily hands back whatever JSON round-tripping
        # gives (tuples become lists) while derive() returns its own native
        # tuples -- different Python container types, same data. VAE/05 §8's
        # actual bar is byte-identical data, not identical Python types.
        recomputed_account = derivation_mod.derive(record, self.policy)
        if _canonical_account(recomputed_account) != _canonical_account(record.derivation_account):
            raise ReplayMismatchError("runtime.replay_account_mismatch:" + storage_key)

        record_hash = evidence_mod.content_hash(record)
        event_name, event_id, payload = emission_mod.build_verdict_envelope(record_hash, record)
        envelope = events_mod.build_envelope(event_name, event_id, record.artifact_ref, payload)
        if envelope != originally_emitted_event:
            raise ReplayMismatchError("runtime.replay_event_mismatch:" + storage_key)

        return record, recomputed_account


if __name__ == "__main__":
    from .execution_double import ExecutionDouble

    def _rules_store():
        store = rules_mod.RulesStore()
        store.ingest(1, {
            "plugin_output": {
                "required_checks": ("structural", "reference_wellformed"),
                "depth": "standard",
                "deadlines": {"structural": 10, "reference_wellformed": 5},
            },
        })
        return store

    def _demand(artifact_ref, judgment_id, event_id, rules_version=1):
        return {
            "event_name": "verify.requested", "event_id": event_id,
            "artifact_ref": artifact_ref, "judgment_id": judgment_id,
            "artifact_type": "plugin_output", "rules_version": rules_version,
            "delegated_check_levels": {"structural": "structural"},
            "static_check_levels": {"reference_wellformed": "system"},
        }

    policy = derivation_mod.build_derivation_policy(1, coverage_moderate_min_fraction=0.5,
                                                     coverage_strong_min_fraction=0.9)

    # -- full demand -> verdict path, wired through the composition root ----
    vr = Verification(policy=policy, rules_store=_rules_store())
    result = vr.handle_demand(_demand("artifact:a1", "judgment:a1", "e1"))
    assert result.action == intake_mod.OPENED

    exe = ExecutionDouble()
    vr.run_static("artifact:a1", "reference_wellformed", {})
    vr.dispatch("artifact:a1", "structural", exe, {"check": "structural"})
    exe.script_result("judgment:a1:structural", arrival_time=1, outcome="success")
    vr.resolve("artifact:a1", "structural", exe, now=1)

    emission = vr.try_close_and_emit("artifact:a1")
    assert emission.outcome == emission_mod.EMITTED
    assert emission.verdict == "passed"
    assert len(vr.bus.messages("verify.passed")) == 1
    assert "artifact:a1" not in vr._open  # retired once terminal

    # telemetry fired across every family this path touches
    assert vr.telemetry_sink.by_family("check_activity")
    assert vr.telemetry_sink.by_family("judgment_outcome")[-1]["verdict"] == "passed"
    assert vr.telemetry_sink.by_family("coverage_readout")
    assert vr.telemetry_sink.by_family("derivation_consistency")

    # a later demand for the same artifact is answered by the existing
    # verdict, never re-judged (VAE/04 §2.2)
    again = vr.handle_demand(_demand("artifact:a1", "judgment:a1-again", "e-late"))
    assert again.action == intake_mod.ANSWERED_BY_EXISTING_VERDICT

    # -- replay: byte-identical reconstruction from Storage alone -----------
    originally_emitted = vr.bus.messages("verify.passed")[-1]
    replayed_record, replayed_account = vr.replay(emission.storage_key, originally_emitted)
    assert replayed_account["verdict"] == "passed"
    assert replayed_record.artifact_ref == "artifact:a1"
    # idempotent: replaying again from the same durable bytes agrees again
    vr.replay(emission.storage_key, originally_emitted)

    # tampered "originally emitted" comparison is refused loud
    tampered = dict(originally_emitted, payload=dict(originally_emitted["payload"], verdict_id="tampered"))
    try:
        vr.replay(emission.storage_key, tampered)
        raise SystemExit("tampered replay comparison accepted")
    except ReplayMismatchError:
        pass

    # -- fail path end-to-end, plus a failed judgment's own replay ----------
    vr2 = Verification(policy=policy, rules_store=_rules_store())
    vr2.handle_demand(_demand("artifact:a2", "judgment:a2", "e2"))
    exe2 = ExecutionDouble()
    vr2.run_static("artifact:a2", "reference_wellformed", {})
    vr2.dispatch("artifact:a2", "structural", exe2, {"check": "structural"})
    vr2.resolve("artifact:a2", "structural", exe2, now=10)  # no result scripted -> expiry
    emission2 = vr2.try_close_and_emit("artifact:a2")
    assert emission2.outcome == emission_mod.EMITTED and emission2.verdict == "failed"
    failed_event = vr2.bus.messages("verify.failed")[-1]
    vr2.replay(emission2.storage_key, failed_event)

    # -- persistence rejection: no open-judgment leak, no telemetry lie -----
    vr3 = Verification(policy=policy, rules_store=_rules_store(), storage=StorageDouble())
    vr3.handle_demand(_demand("artifact:a3", "judgment:a3", "e3"))
    exe3 = ExecutionDouble()
    vr3.run_static("artifact:a3", "reference_wellformed", {})
    vr3.dispatch("artifact:a3", "structural", exe3, {"check": "structural"})
    exe3.script_result("judgment:a3:structural", arrival_time=1, outcome="success")
    vr3.resolve("artifact:a3", "structural", exe3, now=1)
    j3 = vr3._open["artifact:a3"]
    closed3 = judgment_mod.close(j3)
    account_preview = derivation_mod.attach_derivation(closed3.record, policy)
    rejected_key = "vae/ev/" + evidence_mod.content_hash(account_preview)
    vr3.storage.script_reject(rejected_key)
    rejection = vr3.try_close_and_emit("artifact:a3")
    assert rejection.outcome == emission_mod.REJECTED
    assert vr3.bus.messages("verify.passed") == [] and vr3.bus.messages("verify.failed") == []
    assert len(vr3.bus.messages("fault.recorded")) == 1
    assert "artifact:a3" not in vr3._open  # still retired -- absence is loud, not left dangling open
    # no judgment_outcome telemetry for a rejected (never-emitted) verdict
    assert vr3.telemetry_sink.by_family("judgment_outcome") == []

    # -- operation on an artifact with no open judgment refused loud --------
    try:
        vr.dispatch("artifact:never-opened", "structural", ExecutionDouble(), {})
        raise SystemExit("operation on unopened artifact accepted")
    except NoOpenJudgmentError:
        pass

    print("runtime selftest ok")
