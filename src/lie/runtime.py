"""LIE Operational Lifecycle runtime (LIE/03 whole document; LIE/04 §6
Distillery contract's "incremental absorption ... full regeneration ...
atomic publication" line). This is the causal-trigger orchestrator that
wires the Gate/Ledger/Curator/Distillery/Advisory Interface subsystems
together the way LIE/03 §4's trigger table requires -- it is glue, not a
sixth subsystem: it owns no knowledge-model logic, no derivation rules, no
consultation matching. Every method here is a named, causal trigger
(OPS-7); there is no clock, no polling loop, no background thread anywhere
in this module.

LIE/03 §4 trigger table, each row realized as one method below:

| trigger | method |
|---|---|
| (a) ledger append -> incremental derivation | `on_ledger_appended` |
| (b) new curation ruling -> re-derivation | `on_curation_ruling` |
| (c) ruleset version change -> full regeneration | `on_ruleset_changed` |
| (d) explicit regeneration request | `regenerate` |

**Why every trigger is a full `distillery.regenerate()` call, never a
separate incremental compiler:** Phase 3's Distillery ships regeneration
only -- "the only compiler this phase ships" (distillery.py). LIE/03 §5 is
explicit that this is architecturally sound, not a shortcut awaiting
correction: "the incremental path may be suspended, dropped, or crashed at
any moment with no semantic loss -- the ledger holds the truth, and the
next derivation ... lands in the same place. Incremental derivation is a
latency optimization, never a source of state." Treating every trigger as
a full regeneration is therefore the reference semantics itself, not an
approximation of it -- OPS-8 (disposable derivations) holds by
construction, and the Equivalence Obligation is trivially satisfied
because there is only one compiler. ponytail: a signature-local incremental
path is a pure latency optimization for a later phase to add behind this
same seam (`_republish`); nothing here or in the Distillery assumes it
never arrives, and nothing here builds toward it speculatively either.

**Atomicity and crash safety (OPS-3, LIE/03 §8):** `distillery.regenerate`
is a pure function -- it mutates nothing shared. If it raises partway
through (or the process dies), `AdvisoryInterface.publish` is simply never
called, so the previously published layer keeps serving untouched. Recovery
after any such failure is calling the same trigger again; nothing needs to
be undone because nothing was ever half-done."""
from . import distillery
from .advisory import AdvisoryInterface
from .derivation_state import DerivationState
from .ledger import ExperienceLedger
from .overlay import CurationOverlay
from .ruleset import DerivationRuleset


class RuntimeRefusal(Exception):
    """Base for runtime.py refusals."""


class MalformedRuntimeInputError(RuntimeRefusal):
    """LieRuntime was constructed with something other than the
    ledger/overlay/ruleset/advisory shapes it requires."""


class LieRuntime:
    def __init__(self, ledger, overlay, ruleset, advisory):
        if not isinstance(ledger, ExperienceLedger):
            raise MalformedRuntimeInputError("runtime.ledger_not_built:" + repr(ledger))
        if not isinstance(overlay, CurationOverlay):
            raise MalformedRuntimeInputError("runtime.overlay_not_built:" + repr(overlay))
        if not isinstance(ruleset, DerivationRuleset):
            raise MalformedRuntimeInputError("runtime.ruleset_not_built:" + repr(ruleset))
        if not isinstance(advisory, AdvisoryInterface):
            raise MalformedRuntimeInputError("runtime.advisory_not_built:" + repr(advisory))
        self._ledger = ledger
        self._overlay = overlay
        self._ruleset = ruleset
        self._advisory = advisory

    def current_derivation_state(self):
        return self._advisory.current_derivation_state()

    def current_ruleset(self):
        return self._ruleset

    # -- causal triggers, one per LIE/03 §4 row -------------------------------

    def on_ledger_appended(self, entry):
        """Trigger (a): a Ledger append happened (the Gate calling
        `ledger.append` successfully). `entry` is accepted only for
        traceability at the call site -- the regeneration itself always
        reads the full current ledger (order-insensitive over contents,
        LIE/02 §1), never just the one new record."""
        return self._republish()

    def on_curation_ruling(self, entry):
        """Trigger (b): the Curator appended a ruling to the overlay."""
        return self._republish()

    def on_ruleset_changed(self, ruleset):
        """Trigger (c): a new Derivation Ruleset version takes effect.
        OPS-6 ("one ruleset per layer; ruleset changes take effect only
        via full regeneration") holds structurally here: this is the ONLY
        place `self._ruleset` is ever reassigned, and the very next layer
        is compiled entirely under the new version -- there is no path
        that mixes two ruleset versions in one layer, because `regenerate`
        only ever sees one `self._ruleset` value at a time."""
        if not isinstance(ruleset, DerivationRuleset):
            raise MalformedRuntimeInputError("runtime.ruleset_not_built:" + repr(ruleset))
        self._ruleset = ruleset
        return self._republish()

    def regenerate(self):
        """Trigger (d): explicit regeneration request (recovery from a
        lost/corrupted layer, an equivalence audit, or deliberate
        operator action -- LIE/03 §6, §8)."""
        return self._republish()

    def _republish(self):
        layer = distillery.regenerate(self._ledger, self._overlay, self._ruleset)
        return self._advisory.publish(layer)


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .admission_receipt import AdmissionReceipt
    from .advisory import NoRelevantExperience
    from .bus_double import BusDouble
    from .episode import build_episode
    from .ruleset import default_ruleset
    from .storage_double import StorageDouble

    def make_episode(identity, project, facets, verdict, approach):
        env = envelope_mod.build_envelope(
            identity, envelope_mod.build_attestation("trace:" + identity, True, 1),
            envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
        return build_episode(env, situation={"s": 1}, approach=approach,
                              outcome={"verdict": verdict}, cost={"c": 1})

    ledger = ExperienceLedger(StorageDouble())
    overlay = CurationOverlay(StorageDouble())
    bus = BusDouble()
    advisory = AdvisoryInterface(ledger, bus)
    runtime = LieRuntime(ledger, overlay, default_ruleset(), advisory)

    assert runtime.current_derivation_state() is None  # nothing published yet

    # -- trigger (a): ledger append -> republish, OPS-1 (nothing here waits
    # on the Gate; this is the Gate's caller invoking the trigger after its
    # own append already succeeded) -------------------------------------------
    entry = ledger.append(AdmissionReceipt(
        make_episode("episode:f1", "p1", ("jetson",), "failed", {"a": "flash-old"})))
    state1 = runtime.on_ledger_appended(entry)
    assert state1 == DerivationState(ledger_position=1, overlay_position=0, ruleset_version=1)
    assert runtime.current_derivation_state() == state1

    hit = advisory.consult(("jetson",))
    assert hit and hit[0].advice  # a Lesson exists from the one failure

    # -- trigger (b): curation ruling -> republish, overlay position advances --
    from .curation import build_annotation
    ledger.append(AdmissionReceipt(
        make_episode("episode:f2", "p1", ("jetson",), "failed", {"a": "flash-old"})))
    runtime.on_ledger_appended(None)
    overlay.append(build_annotation("deprecation", ("episode:f2",), "bad sensor data",
                                     ("episode:f1",)))
    state2 = runtime.on_curation_ruling(None)
    assert state2.overlay_position == 1
    assert state2 != state1

    # -- trigger (c): ruleset change -> OPS-6, full regeneration only, never
    # a mix of ruleset versions -------------------------------------------------
    new_ruleset = default_ruleset(version=2)
    state3 = runtime.on_ruleset_changed(new_ruleset)
    assert state3.ruleset_version == 2
    assert runtime.current_ruleset() is new_ruleset
    for artifact in advisory._layer.artifacts:  # every artifact came from ONE regenerate() call
        assert artifact.envelope.attestation.derivation_state.ruleset_version == 2

    # -- trigger (d): explicit regeneration, idempotent replay ------------------
    state4 = runtime.regenerate()
    assert state4 == state3  # same ledger/overlay/ruleset -> identical Derivation State

    # -- OPS-1: nothing here ever blocks on VAE/Observability/consumers --
    # trivially true by construction (no I/O, no wait, no consumer call in
    # any trigger method above) -- asserted structurally: no method takes a
    # callback, timeout, or consumer handle.
    import inspect
    for name in ("on_ledger_appended", "on_curation_ruling", "on_ruleset_changed", "regenerate"):
        sig = inspect.signature(getattr(runtime, name))
        assert "timeout" not in sig.parameters and "callback" not in sig.parameters

    # -- crash recovery: a Distillery that raises mid-derivation leaves the
    # previously published layer untouched (OPS-3 atomicity by construction,
    # LIE/03 §8) -----------------------------------------------------------------
    published_before = advisory._layer
    real_regenerate = distillery.regenerate
    def _boom(*a, **k):
        raise RuntimeError("simulated distillery crash")
    distillery.regenerate = _boom
    try:
        try:
            runtime.regenerate()
            raise SystemExit("crash did not propagate")
        except RuntimeError:
            pass
        assert advisory._layer is published_before  # untouched
    finally:
        distillery.regenerate = real_regenerate

    # recovery = calling the trigger again; ledger holds the truth
    state5 = runtime.regenerate()
    assert state5 == state4

    # -- malformed construction refused loud -------------------------------------
    try:
        LieRuntime("not a ledger", overlay, default_ruleset(), advisory)
        raise SystemExit("bad ledger accepted")
    except MalformedRuntimeInputError:
        pass

    print("runtime selftest ok")
