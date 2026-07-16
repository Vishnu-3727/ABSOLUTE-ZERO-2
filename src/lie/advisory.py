"""LIE Advisory Interface (LIE/00 §4.4, LIE/03 §7, LIE/04 §6 Advisory
Interface contract). Pull-only consultation service over the currently
published `distillery.Layer`, plus the change-notification side of layer
publication (LIE/03 §4: "Advisory Interface | Triggered by ... layer
publications (to emit change notifications) | Its own initiative -- it
never pushes").

Two responsibilities, both read-only in the derivation sense (OPS-2:
"Consultations are read-only and never trigger derivation, curation, or
any state change beyond operational telemetry"):

- **`publish(layer)`** -- called once by the runtime orchestrator
  (runtime.py) immediately after `distillery.regenerate()` returns a new
  `Layer`. Atomic publication (OPS-3): swapping `self._layer` is a single
  attribute assignment, so a consultation observes either the previous
  complete layer or the new one, never a torn state -- no lock, no queue,
  no partial-write machinery needed for that guarantee in a single-process
  implementation (ponytail: multi-process atomic publish is a Storage/
  Communication-backed handoff a later phase can add if LIE ever runs
  cross-process; nothing here assumes single-process forever, but nothing
  builds for the multi-process case speculatively either). Diffs the new
  layer against the prior one and emits `lesson.recorded` for every
  recommendation-bearing artifact (Lesson, Pattern, AntiPattern, Recipe)
  that is new or changed -- LIE/03 §3 station 5: "for whatever actually
  changed."
- **`consult(situation_facets)`** -- read-only lookup against whatever
  layer is currently published; never calls the Distillery, never mutates
  anything (OPS-2). Returns the four-part recommendation object LIE/04 §6
  names (advice, scope statement, maturity and standing, walkable citation
  chain), each stamped with the Derivation State it was answered from
  (OPS-4), or the definite `NoRelevantExperience` marker when nothing
  matches (INV-4: "unmatchable situation -> definite absence").

`reliability.updated` and `prior.updated` are NOT fired by this phase.
LIE/04 §6 R3 resolves reliability signals and planning priors as "Lessons
in statistical form" -- but nothing in the frozen vocabulary or ruleset
canon (LIE/01, ruleset.py) yet distinguishes a "plugin reliability" or
"planning prior" facet scope from an ordinary Lesson's scope. Firing those
two event names would require inventing that classification, which is out
of Phase 4 scope (no new recommendation/similarity algorithms, no new
learning rules). ponytail: wire `reliability.updated` / `prior.updated`
once the vocabulary or ruleset canon names the scopes that distinguish
them from a plain Lesson; `events.py` already carries both names in its
closed PUBLISHED set, so nothing here is a structural blocker."""
from dataclasses import dataclass

from . import derived
from . import distillery
from . import events
from .derivation_state import DerivationState, to_dict as derivation_state_to_dict

# The recommendation-bearing artifact kinds (LIE/04 §6: the four-part
# recommendation object). ProjectDossier and DomainKnowledgePack are
# compiled views, not advice, and are not consultation targets here --
# no new recommendation logic invented to cover them.
_ADVICE_KINDS = (derived.Lesson, derived.Pattern, derived.AntiPattern, derived.Recipe)


class AdvisoryRefusal(Exception):
    """Base for advisory.py refusals."""


class NoLayerPublishedError(AdvisoryRefusal):
    """consult() called before any layer has ever been published --
    LIE/03 §7: any LIE outage's only consumer-visible symptom is
    consultations failing or stale; this is that failure made loud rather
    than silently guessed at."""


class MalformedConsultationError(AdvisoryRefusal):
    """consult() was handed something other than a tuple/set of facet
    strings."""


@dataclass(frozen=True)
class Recommendation:
    kind: str                    # one of derived.DERIVED_KINDS (advice-bearing subset)
    advice: str                  # the human-readable recommendation text
    scope: tuple                 # the facet scope it holds in (envelope.facets)
    maturity: str                # derived.MATURITY_GRADES value
    contested: bool              # standing: False for kinds without the flag (Lesson, Recipe)
    citation_chain: tuple        # distillery.citation_chain(...) -- walkable to VAE verdicts
    derivation_state: DerivationState  # OPS-4 stamp


@dataclass(frozen=True)
class NoRelevantExperience:
    """The definite absence response (INV-4) -- itself stamped (OPS-4:
    "every advisory response"), so a consumer knows exactly which ledger
    state was searched and found nothing."""
    derivation_state: DerivationState


def _advice_text(artifact):
    if isinstance(artifact, derived.Lesson):
        return artifact.statement
    if isinstance(artifact, derived.Pattern):
        return "recommended approach: " + repr(dict(artifact.approach))
    if isinstance(artifact, derived.AntiPattern):
        return "avoid: " + repr(dict(artifact.approach)) + " -- " + artifact.consequence
    if isinstance(artifact, derived.Recipe):
        return "steps: " + " -> ".join(artifact.steps)
    raise MalformedConsultationError("advisory.not_advice_bearing:" + repr(type(artifact)))


def _kind_name(artifact):
    for name, cls in zip(
        ("lesson", "pattern", "anti_pattern", "recipe"), _ADVICE_KINDS
    ):
        if isinstance(artifact, cls):
            return name
    raise MalformedConsultationError("advisory.not_advice_bearing:" + repr(type(artifact)))


def _matches(artifact, situation_facets):
    # LIE/04 §1 walkthrough: "its situation facets match the anti-pattern's
    # signature" -- the artifact's declared scope must be wholly contained
    # in what the consumer's situation offers.
    return set(artifact.envelope.facets) <= situation_facets


def _recommend(artifact, ledger, state):
    return Recommendation(
        kind=_kind_name(artifact),
        advice=_advice_text(artifact),
        scope=artifact.envelope.facets,
        maturity=artifact.maturity,
        contested=getattr(artifact, "contested", False),
        citation_chain=distillery.citation_chain(artifact, ledger),
        derivation_state=state,
    )


class AdvisoryInterface:
    def __init__(self, ledger, bus):
        self._ledger = ledger
        self._bus = bus
        self._layer = None  # None until the first publish() (OPS-3: "complete" layers only)
        self._event_seq = 0

    # -- publication side (LIE/03 §4: triggered by layer publications) -------

    def publish(self, layer):
        if not isinstance(layer, distillery.Layer):
            raise AdvisoryRefusal("advisory.publish_not_a_layer:" + repr(layer))
        previous = self._layer
        changed = self._changed_advice_artifacts(previous, layer)
        self._layer = layer  # single assignment == atomic swap (OPS-3)
        for artifact in changed:
            self._event_seq += 1
            events.emit(
                self._bus, "lesson.recorded", "lesson-recorded-" + str(self._event_seq),
                artifact.envelope.identity,
                {"derivation_state": derivation_state_to_dict(layer.derivation_state)})
        return layer.derivation_state

    def _changed_advice_artifacts(self, previous, layer):
        prior_by_id = {} if previous is None else {
            a.envelope.identity: a for a in previous.artifacts}
        out = []
        for artifact in layer.artifacts:
            if not isinstance(artifact, _ADVICE_KINDS):
                continue
            if prior_by_id.get(artifact.envelope.identity) != artifact:
                out.append(artifact)
        return tuple(sorted(out, key=lambda a: a.envelope.identity))

    # -- consultation side (OPS-2: passive, read-only, never triggers derivation) --

    def current_derivation_state(self):
        return None if self._layer is None else self._layer.derivation_state

    def consult(self, situation_facets):
        if self._layer is None:
            raise NoLayerPublishedError("advisory.no_layer_published")
        if not isinstance(situation_facets, (tuple, list, set, frozenset)):
            raise MalformedConsultationError(
                "advisory.bad_situation_facets:" + repr(situation_facets))
        facets = set(situation_facets)
        state = self._layer.derivation_state
        matches = sorted(
            (a for a in self._layer.artifacts
             if isinstance(a, _ADVICE_KINDS) and _matches(a, facets)),
            key=lambda a: a.envelope.identity)
        if not matches:
            return (NoRelevantExperience(derivation_state=state),)
        return tuple(_recommend(a, self._ledger, state) for a in matches)


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .admission_receipt import AdmissionReceipt
    from .episode import build_episode
    from .ledger import ExperienceLedger
    from .overlay import CurationOverlay
    from .ruleset import default_ruleset
    from .storage_double import StorageDouble
    from .bus_double import BusDouble

    def make_episode(identity, project, facets, verdict, approach):
        env = envelope_mod.build_envelope(
            identity, envelope_mod.build_attestation("trace:" + identity, True, 1),
            envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
        return build_episode(env, situation={"s": 1}, approach=approach,
                              outcome={"verdict": verdict}, cost={"c": 1})

    ledger, overlay = ExperienceLedger(StorageDouble()), CurationOverlay(StorageDouble())
    bus = BusDouble()
    advisory = AdvisoryInterface(ledger, bus)

    # -- OPS-2 / no-layer failure is loud, not a silent guess ------------------
    try:
        advisory.consult(("jetson",))
        raise SystemExit("consult before any publish accepted")
    except NoLayerPublishedError:
        pass

    for ep in (
        make_episode("episode:f1", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:f2", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:r1", "p1", ("jetson",), "passed", {"a": "flash-new"}),
    ):
        ledger.append(AdmissionReceipt(ep))

    layer1 = distillery.regenerate(ledger, overlay, default_ruleset())
    state1 = advisory.publish(layer1)
    assert state1 == layer1.derivation_state

    # publishing emits lesson.recorded once per new advice-bearing artifact,
    # never carrying advice as payload (LIE/03 §7)
    recorded = bus.messages("lesson.recorded")
    assert len(recorded) >= 1
    assert set(recorded[0]["payload"].keys()) == {"derivation_state"}

    # -- consultation: a situation whose facets are a superset of the
    # anti-pattern's scope matches; unrelated facets do not -------------------
    hits = advisory.consult(("jetson", "extra-context"))
    kinds = {h.kind for h in hits}
    assert "anti_pattern" in kinds
    for h in hits:
        assert h.derivation_state == state1                  # OPS-4 stamp
        assert h.citation_chain                                # INV-4 walkable
        assert isinstance(h.contested, bool)

    empty = advisory.consult(("cuda",))
    assert len(empty) == 1 and isinstance(empty[0], NoRelevantExperience)
    assert empty[0].derivation_state == state1                 # absence is stamped too

    # -- publish is idempotent w.r.t. notifications: re-publishing the SAME
    # layer content emits nothing new (nothing "actually changed") ------------
    before = len(bus.messages("lesson.recorded"))
    layer1b = distillery.regenerate(ledger, overlay, default_ruleset())
    advisory.publish(layer1b)
    assert len(bus.messages("lesson.recorded")) == before

    # -- a genuinely new episode changes the layer and re-fires notifications --
    ledger.append(AdmissionReceipt(
        make_episode("episode:f3", "p2", ("jetson",), "failed", {"a": "flash-old"})))
    layer2 = distillery.regenerate(ledger, overlay, default_ruleset())
    state2 = advisory.publish(layer2)
    assert state2 != state1
    assert len(bus.messages("lesson.recorded")) > before
    # answers reflect the newly published state, never a torn mix (OPS-3)
    hits2 = advisory.consult(("jetson",))
    assert all(h.derivation_state == state2 for h in hits2)

    # -- same question at same Derivation State -> same answer, forever -------
    assert advisory.consult(("jetson",)) == hits2

    print("advisory selftest ok")
