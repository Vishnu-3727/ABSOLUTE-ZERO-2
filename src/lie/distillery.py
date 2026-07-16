"""LIE Distillery (LIE/02, LIE/04 §6 Distillery contract) -- the
deterministic intelligence compiler: `regenerate(ledger, overlay,
ruleset) -> Layer`. "The intelligence layer is a build artifact. The
Experience Ledger is the source. The Derivation Ruleset is the compiler"
(LIE/02 §1). Pure function of the Derivation State triple; no clocks, no
randomness, no admission-order sensitivity (evidence members, groupings,
and the layer itself are always sorted by content identity, never by
ledger position).

Regeneration is the ONLY compiler this phase ships (LIE/03 §6:
"regeneration is the reference semantics"); incremental absorption is a
latency optimization a later phase may add, at which point
`layer_canonical` is the Equivalence Obligation seam (LIE/02 §9): run
both, compare bytes.

Derivation shapes (LIE/02 §3), all compiled over Evidence Sets:

- **Signature** -- the sorted unique facet tuple of a record. (LIE/02 §2
  defines the signature as a facet-AND-relation profile the ruleset
  defines; ponytail: facets only, relations join the profile when a
  ruleset version needs them -- the seam is `signature_of`.)
- **Evidence Set** -- ledger episodes grouped by signature, partitioned
  by outcome polarity (the VAE verdict in `outcome["verdict"]`, closed
  two: "passed"/"failed", anything else refused loud). Computed, never
  stored; membership sorted by identity, monotonic by construction (the
  ledger only appends).
- **Lesson** -- one per non-empty (signature, polarity) partition, even a
  single episode; statement deterministic from scope + polarity + count.
- **Pattern** -- a positive sub-group sharing signature AND approach
  (canonical-JSON grouping) that recurred past
  `ruleset.pattern_min_episodes`.
- **AntiPattern** -- the same over a negative sub-group, plus the
  automatic `instead-of` link when the same signature holds positive
  evidence for a DIFFERENT approach (LIE/02 §3: "don't do X, do Y is
  compiled, not authored"): a surviving Pattern/Recipe there if one
  compiled, else the positive Lesson.
- **Contested** (LIE/02 §7) -- same signature, SAME approach, opposite
  valence: both artifacts get contested=True. No automatic resolution
  ever -- no recency, no count, no tie-break. A `contradiction_resolution`
  ruling in the overlay (its target_ids naming the ruled-AGAINST artifact
  identities -- identities are deterministic, so rulable in advance) drops
  that side from the fresh layer and un-contests the survivor: "derivation
  follows the ruling" (LIE/02 §8). NOTE the granularity: same signature
  with DIFFERENT approaches and opposite valence is not a conflict -- it
  is exactly the failure/recovery shape whose compiled form is the
  `instead-of` link (LIE/04 §1 walkthrough).
- **Recipe** -- a positive sub-group whose episodes agree on an ordered
  step sequence (`approach["steps"]`, the in-episode thread of significant
  actions) past `ruleset.recipe_min_episodes`.
- **ProjectDossier** -- per project with >=1 episode: its decisions,
  episodes, originated lessons (lessons citing >=1 of its episodes), and
  relationship statements from Project Signature overlap -- always citing
  the shared facets, never a bare scalar (LIE/02 §5).
- **DomainKnowledgePack** -- per declared scope in `ruleset.pack_scopes`:
  the compiled lessons/patterns/anti-patterns/recipes whose facets fall
  within the scope, plus benchmark-bearing episodes (outcome carries
  "measurements") -- a view over already-derived knowledge + ledger,
  no new derivation (LIE/02 §3).
- **Maturity Grade** (LIE/02 §4) -- recomputed per artifact as a pure
  function of its evidence set + ruleset thresholds: Established when
  evidence spans `established_min_projects` projects, Corroborated at
  `corroborated_min_episodes` episodes, else Provisional. No one promotes
  knowledge; evidence does.

Curation overlay as weighting input (LIE/02 §8): records targeted by
deprecation or supersession rulings are excluded from fresh evidence sets
(they remain in the ledger; superseded records contribute only through
their superseding records, which sit in the ledger as ordinary records);
contradiction_resolution rulings direct which side fresh derivation
follows, as above.

`citation_chain` constructs INV-4's walkable chain from the envelope
graph: artifact -> evidence members -> ledger records -> attestation
refs; a chain that cannot be walked end-to-end raises loud."""
from dataclasses import dataclass
import hashlib
import json

from . import derived
from .decision import Decision
from .derivation_state import DerivationState, build_derivation_state, \
    to_dict as derivation_state_to_dict
from .envelope import build_derivation_attestation, build_envelope, build_origin, build_relation
from .episode import Episode
from .ruleset import DerivationRuleset

POSITIVE = "positive"
NEGATIVE = "negative"
POLARITIES = (POSITIVE, NEGATIVE)


class DistilleryRefusal(Exception):
    """Base for distillery.py refusals."""


class UnknownVerdictError(DistilleryRefusal):
    """An episode's outcome verdict is outside the closed two
    ("passed"/"failed") -- polarity cannot be derived, and guessing would
    be interpretation, which the compiler never does."""


class UnwalkableChainError(DistilleryRefusal):
    """A citation chain link could not be resolved in the ledger --
    INV-4: a recommendation whose chain cannot be walked end-to-end is a
    defect."""


class MalformedCompilerInputError(DistilleryRefusal):
    """regenerate() was handed something other than (ledger, overlay,
    ruleset)-shaped inputs."""


# -- Situation Signature (LIE/02 §2) ------------------------------------------

@dataclass(frozen=True)
class Signature:
    facets: tuple  # sorted, unique


def signature_of(record):
    """The deterministic facet profile of a record. Comparable strings,
    not judgments (LIE/02 §7)."""
    return Signature(facets=tuple(sorted(set(record.envelope.facets))))


def polarity_of(episode):
    verdict = episode.outcome.get("verdict")
    if verdict == "passed":
        return POSITIVE
    if verdict == "failed":
        return NEGATIVE
    raise UnknownVerdictError(
        "distillery.unknown_verdict:" + episode.envelope.identity + ":" + repr(verdict))


def evidence_sets(episodes):
    """Deterministic grouping (LIE/02 §2): {Signature: {polarity: tuple of
    episodes, sorted by identity}}. Membership order is content order,
    never admission order."""
    sets = {}
    for ep in episodes:
        parts = sets.setdefault(signature_of(ep), {POSITIVE: [], NEGATIVE: []})
        parts[polarity_of(ep)].append(ep)
    return {
        sig: {pol: tuple(sorted(members, key=lambda e: e.envelope.identity))
               for pol, members in parts.items()}
        for sig, parts in sets.items()
    }


# -- shared derivation helpers --------------------------------------------------

def _canonical_hash(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def _grade(episodes, ruleset):
    """Maturity as a pure function of the evidence set + ruleset
    thresholds (LIE/02 §4)."""
    projects = {e.envelope.origin.project for e in episodes}
    if len(projects) >= ruleset.established_min_projects:
        return derived.MATURITY_ESTABLISHED
    if len(episodes) >= ruleset.corroborated_min_episodes:
        return derived.MATURITY_CORROBORATED
    return derived.MATURITY_PROVISIONAL


def _derived_envelope(identity, facets, evidence_ids, projects, state, extra_relations=()):
    relations = tuple(build_relation("evidenced-by", i) for i in sorted(evidence_ids))
    relations += tuple(extra_relations)
    origin = build_origin(
        ",".join(sorted(projects)), "distillery", None,
        "derived@L{0}:O{1}:R{2}".format(state.ledger_position, state.overlay_position,
                                          state.ruleset_version))
    return build_envelope(identity, build_derivation_attestation(state), origin,
                           tuple(facets), relations)


def _facets_key(facets):
    return "+".join(facets)


# -- the layer -------------------------------------------------------------------

@dataclass(frozen=True)
class Layer:
    derivation_state: DerivationState
    artifacts: tuple  # sorted by envelope identity

    def by_identity(self, identity):
        for a in self.artifacts:
            if a.envelope.identity == identity:
                return a
        return None

    def by_kind(self, kind_type):
        return tuple(a for a in self.artifacts if isinstance(a, kind_type))


def layer_to_dict(layer):
    return {
        "derivation_state": derivation_state_to_dict(layer.derivation_state),
        "artifacts": [derived.to_dict(a) for a in layer.artifacts],
    }


def layer_canonical(layer):
    """The Equivalence Obligation seam (LIE/02 §9): two compilations of
    the same Derivation State must produce byte-identical canonical
    forms -- this is the comparison."""
    return json.dumps(layer_to_dict(layer), sort_keys=True, separators=(",", ":")).encode()


# -- the compiler -----------------------------------------------------------------

def regenerate(ledger, overlay, ruleset):
    """Full regeneration (LIE/03 §6): empty layer, full ledger, full
    overlay, one ruleset version. The only whole-corpus operation, and
    the reference semantics for any future incremental path."""
    if not isinstance(ruleset, DerivationRuleset):
        raise MalformedCompilerInputError("distillery.ruleset_not_built:" + repr(ruleset))

    state = build_derivation_state(ledger.current_position(), overlay.current_position(),
                                    ruleset.version)

    # curation overlay as weighting input (LIE/02 §8)
    excluded_ids = set()
    ruled_against = set()
    for entry in overlay.all():
        ann = entry.annotation
        if ann.kind in ("deprecation", "supersession"):
            excluded_ids.update(ann.target_ids)
        elif ann.kind == "contradiction_resolution":
            ruled_against.update(ann.target_ids)

    episodes = []
    decisions = []
    for entry in ledger.all():
        record = entry.record
        if record.envelope.identity in excluded_ids:
            continue
        if isinstance(record, Episode):
            episodes.append(record)
        elif isinstance(record, Decision):
            decisions.append(record)

    sets = evidence_sets(episodes)
    signatures = sorted(sets, key=lambda s: s.facets)

    lessons = {}    # (facets, polarity) -> Lesson
    patterns = {}   # (facets, approach_hash) -> Pattern spec then artifact
    antis = {}      # (facets, approach_hash) -> AntiPattern parts
    recipes = []

    # -- lessons: one per non-empty partition, minimal derivation ------------
    for sig in signatures:
        for polarity in POLARITIES:
            members = sets[sig][polarity]
            if not members:
                continue
            identity = "lesson:" + _facets_key(sig.facets) + ":" + polarity
            if identity in ruled_against:
                continue
            evidence_ids = [m.envelope.identity for m in members]
            statement = "in scope [{0}]: verified {1} outcome across {2} episode(s)".format(
                ", ".join(sig.facets), polarity, len(members))
            env = _derived_envelope(identity, sig.facets, evidence_ids,
                                     {m.envelope.origin.project for m in members}, state)
            lessons[(sig.facets, polarity)] = derived.build_lesson(
                env, statement, maturity=_grade(members, ruleset))

    # -- pattern / anti-pattern specs: sub-group by identical approach ----------
    def _approach_groups(members):
        groups = {}
        for m in members:
            key = _canonical_hash(dict(m.approach))
            groups.setdefault(key, []).append(m)
        return groups

    pattern_specs = {}  # (facets, approach_hash) -> (sig, members)
    anti_specs = {}
    for sig in signatures:
        for key, members in sorted(_approach_groups(sets[sig][POSITIVE]).items()):
            if len(members) >= ruleset.pattern_min_episodes:
                pattern_specs[(sig.facets, key)] = (sig, tuple(members))
        for key, members in sorted(_approach_groups(sets[sig][NEGATIVE]).items()):
            if len(members) >= ruleset.pattern_min_episodes:
                anti_specs[(sig.facets, key)] = (sig, tuple(members))

    # Contested (LIE/02 §7): same signature, same approach, opposite valence.
    # No automatic tie-break; a contradiction_resolution ruling drops the
    # ruled-against side and un-contests the survivor.
    def _pattern_identity(facets, key):
        return "pattern:" + _facets_key(facets) + ":" + key

    def _anti_identity(facets, key):
        return "anti_pattern:" + _facets_key(facets) + ":" + key

    contested_keys = set(pattern_specs) & set(anti_specs)
    dropped = set()
    contested_flags = {}
    for spec_key in contested_keys:
        facets, key = spec_key
        pid, aid = _pattern_identity(facets, key), _anti_identity(facets, key)
        p_ruled, a_ruled = pid in ruled_against, aid in ruled_against
        if p_ruled:
            dropped.add(pid)
        if a_ruled:
            dropped.add(aid)
        if not p_ruled and not a_ruled:
            contested_flags[pid] = True
            contested_flags[aid] = True

    for (facets, key), (sig, members) in sorted(pattern_specs.items()):
        identity = _pattern_identity(facets, key)
        if identity in ruled_against or identity in dropped:
            continue
        evidence_ids = [m.envelope.identity for m in members]
        env = _derived_envelope(identity, facets, evidence_ids,
                                 {m.envelope.origin.project for m in members}, state)
        patterns[(facets, key)] = derived.build_pattern(
            env, dict(members[0].approach), maturity=_grade(members, ruleset),
            contested=contested_flags.get(identity, False))

    # -- recipes: positive sub-groups agreeing on an ordered step sequence ------
    recipe_identities_by_sig = {}
    for sig in signatures:
        step_groups = {}
        for m in sets[sig][POSITIVE]:
            steps = m.approach.get("steps")
            if not isinstance(steps, (list, tuple)) or not steps \
                    or not all(isinstance(s, str) and s for s in steps):
                continue  # no step thread to agree on
            step_groups.setdefault(tuple(steps), []).append(m)
        for steps, members in sorted(step_groups.items()):
            if len(members) < ruleset.recipe_min_episodes:
                continue
            identity = "recipe:" + _facets_key(sig.facets) + ":" + _canonical_hash(list(steps))
            if identity in ruled_against:
                continue
            members = tuple(sorted(members, key=lambda e: e.envelope.identity))
            evidence_ids = [m.envelope.identity for m in members]
            env = _derived_envelope(identity, sig.facets, evidence_ids,
                                     {m.envelope.origin.project for m in members}, state)
            recipes.append(derived.build_recipe(env, steps, maturity=_grade(members, ruleset)))
            recipe_identities_by_sig.setdefault(sig.facets, []).append(identity)

    # -- anti-patterns, with the automatic instead-of link ------------------------
    for (facets, key), (sig, members) in sorted(anti_specs.items()):
        identity = _anti_identity(facets, key)
        if identity in ruled_against or identity in dropped:
            continue
        # instead-of: a positive-backed artifact at the same signature with a
        # DIFFERENT approach -- surviving Pattern first, then Recipe, then the
        # positive Lesson when the positive evidence includes a different
        # approach (LIE/01 §5.3, LIE/04 §1 walkthrough). Same-approach positive
        # evidence is the Contested case, never an alternative.
        alternatives = sorted(
            p.envelope.identity for (p_facets, p_key), p in patterns.items()
            if p_facets == facets and p_key != key)
        alternatives += sorted(recipe_identities_by_sig.get(facets, []))
        positive_lesson = lessons.get((facets, POSITIVE))
        other_approach_exists = any(
            _canonical_hash(dict(m.approach)) != key for m in sets[sig][POSITIVE])
        if not alternatives and positive_lesson is not None and other_approach_exists:
            alternatives = [positive_lesson.envelope.identity]
        extra = (build_relation("instead-of", alternatives[0]),) if alternatives else ()

        evidence_ids = [m.envelope.identity for m in members]
        consequence = "verified failure across {0} episode(s)".format(len(members))
        env = _derived_envelope(identity, facets, evidence_ids,
                                 {m.envelope.origin.project for m in members}, state,
                                 extra_relations=extra)
        antis[(facets, key)] = derived.build_anti_pattern(
            env, dict(members[0].approach), consequence, maturity=_grade(members, ruleset),
            contested=contested_flags.get(identity, False))

    core_artifacts = list(lessons.values()) + list(patterns.values()) \
        + list(antis.values()) + recipes

    # -- project dossiers (LIE/02 §3, §5) -------------------------------------------
    dossiers = []
    project_episodes = {}
    for ep in episodes:
        project_episodes.setdefault(ep.envelope.origin.project, []).append(ep)
    project_decisions = {}
    for dec in decisions:
        project_decisions.setdefault(dec.envelope.origin.project, []).append(dec)
    # Project Signature: the aggregate facet profile of a project's records
    project_signatures = {}
    for project, eps in project_episodes.items():
        facets = set()
        for record in eps + project_decisions.get(project, []):
            facets.update(record.envelope.facets)
        project_signatures[project] = facets

    for project in sorted(project_episodes):
        identity = "dossier:" + project
        if identity in ruled_against:
            continue
        eps = sorted(project_episodes[project], key=lambda e: e.envelope.identity)
        episode_ids = [e.envelope.identity for e in eps]
        decision_ids = sorted(d.envelope.identity
                               for d in project_decisions.get(project, []))
        episode_id_set = set(episode_ids)
        lesson_ids = sorted(
            l.envelope.identity for l in lessons.values()
            if episode_id_set & {r.target_id for r in l.envelope.relations
                                  if r.relation_type == "evidenced-by"})
        relationships = tuple(
            derived.build_project_relationship(
                other, tuple(sorted(project_signatures[project] & project_signatures[other])))
            for other in sorted(project_signatures)
            if other != project and project_signatures[project] & project_signatures[other])
        env = _derived_envelope(identity, tuple(sorted(project_signatures[project])),
                                 episode_ids, {project}, state)
        dossiers.append(derived.build_project_dossier(
            env, project, tuple(decision_ids), tuple(episode_ids), tuple(lesson_ids),
            relationships, maturity=_grade(eps, ruleset)))

    # -- domain knowledge packs: views over the layer + ledger (LIE/02 §3) ------------
    packs = []
    episode_by_id = {e.envelope.identity: e for e in episodes}
    for name in sorted(ruleset.pack_scopes):
        identity = "pack:" + name
        if identity in ruled_against:
            continue
        scope = set(ruleset.pack_scopes[name])
        member_ids = []
        evidence_ids = set()
        for artifact in core_artifacts:
            if set(artifact.envelope.facets) <= scope:
                member_ids.append(artifact.envelope.identity)
                evidence_ids.update(r.target_id for r in artifact.envelope.relations
                                     if r.relation_type == "evidenced-by")
        # benchmark-bearing episodes within scope (LIE/01 §5.6)
        # ponytail: "benchmark-bearing" detected by a "measurements" key in
        # the outcome; a declared benchmark facet replaces this when the
        # vocabulary grows one.
        for ep in sorted(episodes, key=lambda e: e.envelope.identity):
            if "measurements" in ep.outcome and set(ep.envelope.facets) <= scope:
                member_ids.append(ep.envelope.identity)
                evidence_ids.add(ep.envelope.identity)
        if not member_ids:
            continue
        evidence_episodes = [episode_by_id[i] for i in evidence_ids if i in episode_by_id]
        env = _derived_envelope(identity, tuple(sorted(scope)), sorted(evidence_ids),
                                 {e.envelope.origin.project for e in evidence_episodes},
                                 state)
        packs.append(derived.build_domain_knowledge_pack(
            env, tuple(sorted(member_ids)), maturity=_grade(evidence_episodes, ruleset)))

    artifacts = tuple(sorted(core_artifacts + dossiers + packs,
                              key=lambda a: a.envelope.identity))
    return Layer(derivation_state=state, artifacts=artifacts)


# -- citation chain (INV-4's mechanism, LIE/02 §6 step 4) --------------------------

def citation_chain(artifact, ledger):
    """The walkable chain: artifact -> evidence members -> ledger records
    -> attestation refs. Every link is an identifier resolvable in the
    ledger; an unresolvable link raises loud."""
    links = []
    for relation in artifact.envelope.relations:
        if relation.relation_type != "evidenced-by":
            continue
        entry = ledger.by_identity(relation.target_id)
        if entry is None:
            raise UnwalkableChainError(
                "distillery.unresolvable_citation:" + artifact.envelope.identity +
                "->" + relation.target_id)
        links.append({
            "artifact": artifact.envelope.identity,
            "evidence": relation.target_id,
            "attestation_ref": entry.record.envelope.attestation.attestation_ref,
        })
    if not links:
        raise UnwalkableChainError(
            "distillery.no_citations:" + artifact.envelope.identity)
    return tuple(links)


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .admission_receipt import AdmissionReceipt
    from .curation import build_annotation
    from .episode import build_episode
    from .ledger import ExperienceLedger
    from .overlay import CurationOverlay
    from .ruleset import default_ruleset
    from .storage_double import StorageDouble

    def make_episode(identity, project, facets, verdict, approach, outcome_extra=None):
        env = envelope_mod.build_envelope(
            identity, envelope_mod.build_attestation("trace:" + identity, True, 1),
            envelope_mod.build_origin(project, "sim", None, "epoch-0"), facets, ())
        outcome = {"verdict": verdict}
        outcome.update(outcome_extra or {})
        return build_episode(env, situation={"s": 1}, approach=approach,
                              outcome=outcome, cost={"c": 1})

    def fresh():
        return ExperienceLedger(StorageDouble()), CurationOverlay(StorageDouble())

    # two failures with approach A, one recovery with approach B, same signature
    ledger, overlay = fresh()
    for ep in (
        make_episode("episode:f1", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:f2", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:r1", "p1", ("jetson",), "passed", {"a": "flash-new"}),
    ):
        ledger.append(AdmissionReceipt(ep))

    layer = regenerate(ledger, overlay, default_ruleset())
    anti = layer.by_identity("anti_pattern:jetson:" + _canonical_hash({"a": "flash-old"}))
    assert anti is not None
    assert anti.contested is False  # different approaches -> instead-of, NOT contested
    instead = [r for r in anti.envelope.relations if r.relation_type == "instead-of"]
    assert len(instead) == 1  # automatic, compiled not authored
    assert instead[0].target_id == "lesson:jetson:positive"  # no pattern at threshold; lesson backs it
    assert anti.maturity == derived.MATURITY_CORROBORATED  # 2 episodes, 1 project

    # citation chain walkable end-to-end
    chain = citation_chain(anti, ledger)
    assert [l["evidence"] for l in chain] == ["episode:f1", "episode:f2"]
    assert chain[0]["attestation_ref"] == "trace:episode:f1"

    # determinism + order-insensitivity: same records, reversed admission order
    ledger2, overlay2 = fresh()
    for ep in (
        make_episode("episode:r1", "p1", ("jetson",), "passed", {"a": "flash-new"}),
        make_episode("episode:f2", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:f1", "p1", ("jetson",), "failed", {"a": "flash-old"}),
    ):
        ledger2.append(AdmissionReceipt(ep))
    assert layer_canonical(regenerate(ledger2, overlay2, default_ruleset())) \
        == layer_canonical(layer)

    # contested: same signature, SAME approach, both polarities at threshold
    ledger3, overlay3 = fresh()
    for i, verdict in enumerate(("passed", "passed", "failed", "failed")):
        ledger3.append(AdmissionReceipt(make_episode(
            "episode:c{0}".format(i), "p{0}".format(i % 2), ("cuda",), verdict, {"a": "same"})))
    layer3 = regenerate(ledger3, overlay3, default_ruleset())
    key = _canonical_hash({"a": "same"})
    pat = layer3.by_identity("pattern:cuda:" + key)
    ant = layer3.by_identity("anti_pattern:cuda:" + key)
    assert pat.contested and ant.contested  # both sides presented, no tie-break
    assert not [r for r in ant.envelope.relations if r.relation_type == "instead-of"]
    assert pat.maturity == derived.MATURITY_ESTABLISHED  # spans 2 projects

    # resolution ruling: anti side ruled against -> dropped, pattern un-contested
    overlay3.append(build_annotation("contradiction_resolution",
                                      ("anti_pattern:cuda:" + key,),
                                      "approach verified sound; failures were env-specific",
                                      ("episode:c0", "episode:c1")))
    layer3b = regenerate(ledger3, overlay3, default_ruleset())
    assert layer3b.by_identity("anti_pattern:cuda:" + key) is None
    assert layer3b.by_identity("pattern:cuda:" + key).contested is False

    # deprecation excludes from fresh sets: drop one failure -> anti loses recurrence
    ledger4, overlay4 = fresh()
    for ep in (
        make_episode("episode:f1", "p1", ("jetson",), "failed", {"a": "flash-old"}),
        make_episode("episode:f2", "p1", ("jetson",), "failed", {"a": "flash-old"}),
    ):
        ledger4.append(AdmissionReceipt(ep))
    overlay4.append(build_annotation("deprecation", ("episode:f2",), "bad sensor data",
                                      ("episode:f1",)))
    layer4 = regenerate(ledger4, overlay4, default_ruleset())
    assert layer4.by_identity("anti_pattern:jetson:" + _canonical_hash({"a": "flash-old"})) is None
    negative_lesson = layer4.by_identity("lesson:jetson:negative")
    assert negative_lesson.maturity == derived.MATURITY_PROVISIONAL  # one episode left

    # recipe: two positive episodes agreeing on an ordered step thread
    ledger5, overlay5 = fresh()
    steps = {"steps": ["flash", "install", "build"]}
    for i in ("1", "2"):
        ledger5.append(AdmissionReceipt(make_episode(
            "episode:s" + i, "p1", ("ros2",), "passed", steps)))
    layer5 = regenerate(ledger5, overlay5, default_ruleset())
    recipes5 = layer5.by_kind(derived.Recipe)
    assert len(recipes5) == 1
    assert recipes5[0].steps == ("flash", "install", "build")

    # dossier + pack + benchmark episode
    ledger6, overlay6 = fresh()
    ledger6.append(AdmissionReceipt(make_episode(
        "episode:b1", "p1", ("ros2",), "passed", {"a": 1}, {"measurements": {"fps": 30}})))
    ledger6.append(AdmissionReceipt(make_episode(
        "episode:b2", "p2", ("ros2", "cuda"), "passed", {"a": 1})))
    layer6 = regenerate(ledger6, overlay6, default_ruleset(
        pack_scopes={"ros2-pack": ("ros2", "cuda")}))
    dossier = layer6.by_identity("dossier:p1")
    assert dossier.episode_refs == ("episode:b1",)
    assert dossier.relationships[0].other_project == "p2"
    assert dossier.relationships[0].shared_facets == ("ros2",)  # cites shared facets
    pack = layer6.by_identity("pack:ros2-pack")
    assert "episode:b1" in pack.member_refs  # benchmark-bearing episode in scope
    assert "lesson:ros2:positive" in pack.member_refs

    # unknown verdict refused loud
    try:
        polarity_of(make_episode("episode:x", "p", ("f",), "maybe", {"a": 1}))
        raise SystemExit("unknown verdict accepted")
    except UnknownVerdictError:
        pass

    # unwalkable chain refused loud
    try:
        citation_chain(anti, ledger5)  # anti's evidence lives in `ledger`, not ledger5
        raise SystemExit("unwalkable chain accepted")
    except UnwalkableChainError:
        pass

    print("distillery selftest ok")
