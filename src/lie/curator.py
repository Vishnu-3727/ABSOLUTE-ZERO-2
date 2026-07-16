"""LIE Curator (LIE/00 §4.5, LIE/03 §4, LIE/04 §6 Curator contract). The
deliberate-governance subsystem -- "judge standing: rulings, vocabulary,
ruleset governance":

- **Required:** append-only rulings (deprecation, supersession,
  contradiction resolution) with reasons and cited evidence; vocabulary
  ownership (additive evolution, merges by ruling); ruleset version
  governance; process the Contested queue deliberately.
- **Forbidden:** mutating or deleting any record anywhere; automatic or
  event-triggered rulings; admitting experience; compiling intelligence.
- **Guarantees:** every ruling is itself a citable, versioned record (its
  `OverlayEntry` position is its version); overlay position advances
  monotonically.

Structural enforcement of the Forbidden list:

- **Never mutates:** the Curator holds the overlay (append-only by
  construction, overlay.py) and immutable value objects (FacetVocabulary,
  DerivationRuleset) -- there is no mutation surface to misuse. Vocabulary
  and ruleset "changes" are new versions; prior versions are retained
  forever (`vocabulary_version()`, `ruleset_version()` lookups keep every
  historical layer state reconstructible, LIE/03 §6).
- **Never automatic:** no method here subscribes to anything, takes a bus,
  or is wired to any trigger -- every method is a deliberate call by a
  human-accountable caller (LIE/03 §4: "a triggered ruling is a
  contradiction in terms"). The RUNTIME trigger `on_curation_ruling` is
  fired by the Curator's caller AFTER `rule()` returns, exactly as the
  Gate's caller fires `on_ledger_appended` -- the Curator itself never
  touches the Distillery ("compiling intelligence" is forbidden).
- **Never admits experience:** no method takes an Episode/Decision and no
  path reaches `ledger.append` -- the Curator is not even handed the
  ledger.

`contested_queue(layer)` is the read side of LIE/03 §4's "the Contested
queue the Distillery flags for ruling": the Distillery flags conflicts by
setting `contested=True` on both artifacts of a same-signature/
same-approach/opposite-valence pair (LIE/02 §7 -- NOTE the granularity:
same signature with DIFFERENT approaches is the instead-of shape, never
contested); this function lists those flagged pairs from a published
layer so a human can rule. Processing the queue = calling `rule()` with a
`contradiction_resolution` annotation whose `target_ids` name the
ruled-AGAINST artifact identities (the side fresh derivation drops --
distillery.py's established semantics, LIE/02 §8 "derivation follows the
ruling"). The queue is computed, never stored -- it IS the contested flags
of the current layer, so it needs no lifecycle of its own."""
from . import derived
from .curation import Annotation
from .distillery import Layer
from .overlay import CurationOverlay
from .ruleset import DerivationRuleset
from .vocabulary import FacetVocabulary, evolve as evolve_vocabulary


class CuratorRefusal(Exception):
    """Base for curator.py refusals."""


class MalformedCuratorInputError(CuratorRefusal):
    """Curator was constructed with, or handed, something other than the
    built value shapes it governs."""


class RulesetVersionNotAdvancingError(CuratorRefusal):
    """adopt_ruleset() was handed a version that does not advance past the
    current one -- versions are deliberate, monotonic governance acts
    (LIE/03 §6); re-adopting or rolling back a version number would make
    the Derivation State triple ambiguous."""


class Curator:
    def __init__(self, overlay, vocabulary, ruleset):
        if not isinstance(overlay, CurationOverlay):
            raise MalformedCuratorInputError("curator.overlay_not_built:" + repr(overlay))
        if not isinstance(vocabulary, FacetVocabulary):
            raise MalformedCuratorInputError("curator.vocabulary_not_built:" + repr(vocabulary))
        if not isinstance(ruleset, DerivationRuleset):
            raise MalformedCuratorInputError("curator.ruleset_not_built:" + repr(ruleset))
        self._overlay = overlay
        # old versions are never deleted (LIE/03 §6) -- both histories are
        # append-only dicts keyed by version.
        self._vocabularies = {vocabulary.version: vocabulary}
        self._rulesets = {ruleset.version: ruleset}
        self._current_vocabulary = vocabulary
        self._current_ruleset = ruleset

    # -- rulings (CuratorPort.rule) --------------------------------------------

    def rule(self, annotation):
        """One deliberate governance act: append `annotation` to the
        overlay and return its new overlay position -- the ruling's own
        citable version number. The caller fires the runtime's
        `on_curation_ruling` trigger afterward; this method never compiles
        anything."""
        if not isinstance(annotation, Annotation):
            raise MalformedCuratorInputError("curator.ruling_not_built:" + repr(annotation))
        return self._overlay.append(annotation).position

    # -- vocabulary ownership (LIE/01 §7: versioned, additive, Curator-owned) ---

    def current_vocabulary(self):
        return self._current_vocabulary

    def vocabulary_version(self, version):
        return self._vocabularies.get(version)

    def evolve_vocabulary(self, new_terms):
        """Additive evolution only -- vocabulary.evolve() refuses removal/
        renaming loud; term merges are expressed as rulings plus additive
        terms (LIE/01 §7: "rulings map terms forward"), never as edits."""
        new = evolve_vocabulary(self._current_vocabulary, new_terms)
        self._vocabularies[new.version] = new
        self._current_vocabulary = new
        return new

    # -- ruleset version governance (LIE/03 §6) ----------------------------------

    def current_ruleset(self):
        return self._current_ruleset

    def ruleset_version(self, version):
        return self._rulesets.get(version)

    def adopt_ruleset(self, ruleset):
        """Adopt a new Derivation Ruleset version -- "changing how the
        system learns is a curation-class judgment" (LIE/03 §6). The
        caller fires the runtime's `on_ruleset_changed` trigger afterward;
        OPS-6 (effect only via full regeneration) is enforced there."""
        if not isinstance(ruleset, DerivationRuleset):
            raise MalformedCuratorInputError("curator.ruleset_not_built:" + repr(ruleset))
        if ruleset.version <= self._current_ruleset.version:
            raise RulesetVersionNotAdvancingError(
                "curator.ruleset_version_not_advancing:current=" +
                str(self._current_ruleset.version) + ":proposed=" + str(ruleset.version))
        self._rulesets[ruleset.version] = ruleset
        self._current_ruleset = ruleset
        return ruleset

    # -- the Contested queue (LIE/03 §4, LIE/02 §7) --------------------------------

    def contested_queue(self, layer):
        """The artifacts a published layer flags for deliberate ruling:
        every Pattern/AntiPattern with contested=True, in identity order
        (layer.artifacts is already identity-sorted). Computed from the
        layer, never stored -- processing it is calling `rule()` with a
        contradiction_resolution whose target_ids name the ruled-AGAINST
        identities."""
        if not isinstance(layer, Layer):
            raise MalformedCuratorInputError("curator.not_a_layer:" + repr(layer))
        return tuple(
            a for a in layer.artifacts
            if isinstance(a, (derived.Pattern, derived.AntiPattern)) and a.contested)


if __name__ == "__main__":
    from . import distillery
    from . import envelope as envelope_mod
    from .admission_receipt import AdmissionReceipt
    from .curation import build_annotation
    from .episode import build_episode
    from .ledger import ExperienceLedger
    from .ruleset import default_ruleset
    from .storage_double import StorageDouble
    from .vocabulary import build_vocabulary, VocabularyNotAdditiveError

    overlay = CurationOverlay(StorageDouble())
    v1 = build_vocabulary(1, {"cuda", "jetson"})
    rs1 = default_ruleset()
    curator = Curator(overlay, v1, rs1)

    # -- rulings: append-only, versioned by overlay position ------------------
    pos = curator.rule(build_annotation("deprecation", ("episode:e1",), "bad sensor",
                                          ("episode:e2",)))
    assert pos == 1
    assert overlay.by_position(1).annotation.kind == "deprecation"
    pos2 = curator.rule(build_annotation("supersession", ("episode:e1",), "redone",
                                           ("episode:e3",)))
    assert pos2 == 2  # monotonic

    try:
        curator.rule({"kind": "deprecation"})
        raise SystemExit("unbuilt ruling accepted")
    except MalformedCuratorInputError:
        pass

    # -- vocabulary ownership: additive evolution, history retained ------------
    v2 = curator.evolve_vocabulary({"cuda", "jetson", "ros2"})
    assert v2.version == 2
    assert curator.current_vocabulary() is v2
    assert curator.vocabulary_version(1) is v1  # never deleted
    try:
        curator.evolve_vocabulary({"cuda"})  # drops jetson/ros2
        raise SystemExit("non-additive evolution accepted")
    except VocabularyNotAdditiveError:
        pass
    assert curator.current_vocabulary() is v2  # refusal changed nothing

    # -- ruleset governance: monotonic versions, history retained ---------------
    rs2 = default_ruleset(version=2)
    assert curator.adopt_ruleset(rs2) is rs2
    assert curator.current_ruleset() is rs2
    assert curator.ruleset_version(1) is rs1  # reconstructible forever
    for bad_version in (1, 2):
        try:
            curator.adopt_ruleset(default_ruleset(version=bad_version))
            raise SystemExit("non-advancing ruleset version accepted")
        except RulesetVersionNotAdvancingError:
            pass

    # -- contested queue: computed from a published layer -----------------------
    ledger = ExperienceLedger(StorageDouble())
    queue_overlay = CurationOverlay(StorageDouble())
    for i, verdict in enumerate(("passed", "passed", "failed", "failed")):
        env = envelope_mod.build_envelope(
            "episode:c" + str(i), envelope_mod.build_attestation("trace:c" + str(i), True, 1),
            envelope_mod.build_origin("p" + str(i % 2), "sim", None, "epoch-0"), ("cuda",), ())
        ledger.append(AdmissionReceipt(build_episode(
            env, situation={"s": 1}, approach={"a": "same"},
            outcome={"verdict": verdict}, cost={"c": 1})))
    layer = distillery.regenerate(ledger, queue_overlay, rs1)
    queue = curator.contested_queue(layer)
    assert len(queue) == 2  # the contested pair, both sides
    assert all(a.contested for a in queue)

    # processing the queue: rule against one side, re-derive, queue empties
    queue_curator = Curator(queue_overlay, v1, rs1)
    anti_id = next(a.envelope.identity for a in queue
                    if isinstance(a, derived.AntiPattern))
    queue_curator.rule(build_annotation("contradiction_resolution", (anti_id,),
                                          "failures traced to bad sensor batch",
                                          ("episode:c0", "episode:c1")))
    layer2 = distillery.regenerate(ledger, queue_overlay, rs1)
    assert queue_curator.contested_queue(layer2) == ()
    assert layer2.by_identity(anti_id) is None  # ruled-against side dropped

    try:
        curator.contested_queue("not a layer")
        raise SystemExit("non-layer accepted by contested_queue")
    except MalformedCuratorInputError:
        pass

    # -- forbidden surfaces do not exist at all ----------------------------------
    for name in ("admit", "append", "regenerate", "absorb", "consult", "delete",
                  "update", "edit", "remove"):
        assert not hasattr(curator, name)

    print("curator selftest ok")
