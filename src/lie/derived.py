"""LIE derived-knowledge record models (LIE/01 §5, LIE/02 §3 shapes only
-- NO derivation logic; the Distillery that compiles these is Phase 3+
material). The intelligence layer's six artifact kinds as immutable,
validated, round-trippable record types: Lesson, Pattern, AntiPattern,
Recipe, ProjectDossier, DomainKnowledgePack. Same frozen-dataclass +
envelope conventions as Episode/Decision.

Common rules, enforced by one shared envelope check:

- **Derivation-flavored attestation** (LIE/01 §3): every derived record's
  envelope must carry a `DerivationAttestation` (envelope.py) -- the
  derivation process version and the ledger state it was computed from,
  named completely by the `DerivationState` triple. An experience-flavored
  `Attestation` is refused (and episode/decision.py refuse the reverse).
- **INV-4 mechanism**: construction without at least one `evidenced-by`
  relation in the envelope raises `MissingEvidenceCitationError` -- a
  derived artifact that cannot cite its evidence does not get built,
  which is "cite or stay silent" pushed down to the type system.
- **Maturity Grade** (LIE/02 §4, Phase 3): the closed three-rung ladder
  Provisional / Corroborated / Established, orthogonal to artifact kind.
  Grades are COMPUTED at derivation (distillery.py, a pure function of
  evidence set + ruleset thresholds) and passed to builders as data;
  builders validate against the closed `MATURITY_GRADES` set and refuse
  anything outside it. No promotion logic lives here -- no one promotes
  knowledge; evidence does.
- **Contested** (LIE/02 §7, Phase 3): the orthogonal flag on the
  valence-bearing recurrence kinds (Pattern, AntiPattern) -- set by the
  Distillery's same-signature/same-approach conflict detection, never
  resolved here and never resolved automatically anywhere.

Kind-specific shapes (LIE/02 §3):

- **Lesson** -- the minimal artifact: one insight `statement`, scoped to
  exactly the facet signature of its evidence -- the scope IS the
  envelope's facets; no separate scope field exists to disagree with them.
- **Pattern** -- a recurring approach with verified good outcomes: the
  `approach` it names (frozen mapping, same shape as Episode.approach);
  situation signature = envelope facets; evidence set = `evidenced-by`
  relations.
- **AntiPattern** -- structurally Pattern with opposite valence, plus the
  observed `consequence`; MAY carry an `instead-of` relation to the
  derived artifact that works instead (LIE/01 §5.3) -- optional, ordinary
  envelope content, no extra field.
- **Recipe** -- procedural knowledge: ordered `steps` (tuple, order
  meaningful, serialized in order, never sorted); facet scope = envelope
  facets (always present -- build_envelope refuses empty facets).
- **ProjectDossier** -- the per-project compilation: `project` identifier,
  identifier-tuples for its decisions / notable episodes / originated
  lessons, and `relationships` -- `ProjectRelationship` statements naming
  the other project and the shared facets the resemblance holds in
  (LIE/02 §5: never a bare scalar). All statements are data here;
  computing them is Distillery work.
- **DomainKnowledgePack** -- declared facet scope = envelope facets;
  `member_refs` = identifier references to the artifacts within scope.
  Membership is data in Phase 2; deterministic compilation from the layer
  is later-phase work (LIE/02 §3: packs are views, no new derivation).

Knowledge-class tagging (LIE/01 §2): `knowledge_class(record)` derives
experience / intelligence / curation purely from the record's type -- no
stored tag, no mutable state."""
from dataclasses import dataclass
from types import MappingProxyType

from .curation import Annotation
from .decision import Decision
from .envelope import DerivationAttestation, Envelope, from_dict as envelope_from_dict, \
    to_dict as envelope_to_dict
from .episode import Episode

EXPERIENCE = "experience"
INTELLIGENCE = "intelligence"
CURATION = "curation"
KNOWLEDGE_CLASSES = (EXPERIENCE, INTELLIGENCE, CURATION)

# The closed Maturity Grade ladder (LIE/02 §4). Grade NAMES are canon;
# the thresholds between rungs are ruleset data (ruleset.py), and the
# computation is the Distillery's (distillery.py) -- this module only
# refuses values outside the ladder.
MATURITY_PROVISIONAL = "provisional"
MATURITY_CORROBORATED = "corroborated"
MATURITY_ESTABLISHED = "established"
MATURITY_GRADES = (MATURITY_PROVISIONAL, MATURITY_CORROBORATED, MATURITY_ESTABLISHED)

DERIVED_KINDS = ("lesson", "pattern", "anti_pattern", "recipe", "project_dossier",
                  "domain_knowledge_pack")


class DerivedRefusal(Exception):
    """Base for derived.py refusals."""


class MalformedDerivedRecordError(DerivedRefusal):
    """A derived record's fields failed structural validation."""


class MissingEvidenceCitationError(DerivedRefusal):
    """A derived record was constructed without a single `evidenced-by`
    relation -- INV-4's mechanism (LIE/01 §6): a derived artifact that
    cannot cite its evidence is not built."""


class MaturityNotAvailableError(DerivedRefusal):
    """A maturity value outside the closed LIE/02 §4 ladder
    (`MATURITY_GRADES`) -- grades come from derivation over evidence,
    never from caller invention."""


class UnknownKnowledgeRecordError(DerivedRefusal):
    """knowledge_class() was handed something that is no LIE record at
    all."""


def _require_nonempty_str(label, value):
    if not isinstance(value, str) or not value:
        raise MalformedDerivedRecordError("derived.bad_" + label + ":" + repr(value))
    return value


def _str_tuple(label, value, allow_empty=False):
    if not isinstance(value, (tuple, list)) or (not value and not allow_empty):
        raise MalformedDerivedRecordError("derived.empty_or_bad_" + label + ":" + repr(value))
    out = tuple(value)
    for v in out:
        if not isinstance(v, str) or not v:
            raise MalformedDerivedRecordError("derived.bad_" + label + "_entry:" + repr(v))
    return out


def _freeze_mapping(label, value):
    if not isinstance(value, dict) or not value:
        raise MalformedDerivedRecordError("derived.empty_or_bad_" + label + ":" + repr(value))
    return MappingProxyType(dict(value))


def _validate_derived_envelope(envelope):
    if not isinstance(envelope, Envelope):
        raise MalformedDerivedRecordError("derived.envelope_not_built:" + repr(envelope))
    if not isinstance(envelope.attestation, DerivationAttestation):
        raise MalformedDerivedRecordError(
            "derived.requires_derivation_attestation:" + repr(type(envelope.attestation)))
    if not any(r.relation_type == "evidenced-by" for r in envelope.relations):
        raise MissingEvidenceCitationError(
            "derived.no_evidence_citation:" + envelope.identity + ":INV-4")
    return envelope


def _check_maturity(value):
    if value not in MATURITY_GRADES:
        raise MaturityNotAvailableError("derived.unknown_maturity_grade:" + repr(value))
    return value


def _check_contested(value):
    if not isinstance(value, bool):
        raise MalformedDerivedRecordError("derived.bad_contested:" + repr(value))
    return value


# -- Lesson -------------------------------------------------------------------

@dataclass(frozen=True)
class Lesson:
    envelope: Envelope
    statement: str
    maturity: str  # one of MATURITY_GRADES


def build_lesson(envelope, statement, maturity=MATURITY_PROVISIONAL):
    _validate_derived_envelope(envelope)
    _require_nonempty_str("statement", statement)
    return Lesson(envelope=envelope, statement=statement, maturity=_check_maturity(maturity))


# -- Pattern / AntiPattern -----------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    envelope: Envelope
    approach: MappingProxyType
    maturity: str
    contested: bool  # LIE/02 §7 -- set by the Distillery, never resolved here


def build_pattern(envelope, approach, maturity=MATURITY_PROVISIONAL, contested=False):
    _validate_derived_envelope(envelope)
    return Pattern(envelope=envelope, approach=_freeze_mapping("approach", approach),
                    maturity=_check_maturity(maturity), contested=_check_contested(contested))


@dataclass(frozen=True)
class AntiPattern:
    envelope: Envelope
    approach: MappingProxyType
    consequence: str  # the observed consequence (LIE/01 §5.3)
    maturity: str
    contested: bool


def build_anti_pattern(envelope, approach, consequence, maturity=MATURITY_PROVISIONAL,
                        contested=False):
    _validate_derived_envelope(envelope)
    _require_nonempty_str("consequence", consequence)
    return AntiPattern(envelope=envelope, approach=_freeze_mapping("approach", approach),
                        consequence=consequence, maturity=_check_maturity(maturity),
                        contested=_check_contested(contested))


# -- Recipe ---------------------------------------------------------------------

@dataclass(frozen=True)
class Recipe:
    envelope: Envelope
    steps: tuple  # ordered, order meaningful, never sorted
    maturity: str


def build_recipe(envelope, steps, maturity=MATURITY_PROVISIONAL):
    _validate_derived_envelope(envelope)
    return Recipe(envelope=envelope, steps=_str_tuple("steps", steps),
                   maturity=_check_maturity(maturity))


# -- ProjectDossier ---------------------------------------------------------------

@dataclass(frozen=True)
class ProjectRelationship:
    """One relationship statement (LIE/02 §5): 'this project resembles
    `other_project` IN these shared facets' -- never a bare scalar."""
    other_project: str
    shared_facets: tuple


def build_project_relationship(other_project, shared_facets):
    _require_nonempty_str("other_project", other_project)
    return ProjectRelationship(other_project=other_project,
                                shared_facets=_str_tuple("shared_facets", shared_facets))


@dataclass(frozen=True)
class ProjectDossier:
    envelope: Envelope
    project: str
    decision_refs: tuple
    episode_refs: tuple
    lesson_refs: tuple
    relationships: tuple  # tuple of ProjectRelationship
    maturity: str


def build_project_dossier(envelope, project, decision_refs, episode_refs, lesson_refs,
                           relationships, maturity=MATURITY_PROVISIONAL):
    _validate_derived_envelope(envelope)
    _require_nonempty_str("project", project)
    rel_tuple = tuple(relationships) if isinstance(relationships, (tuple, list)) else None
    if rel_tuple is None:
        raise MalformedDerivedRecordError("derived.bad_relationships:" + repr(relationships))
    for r in rel_tuple:
        if not isinstance(r, ProjectRelationship):
            raise MalformedDerivedRecordError("derived.relationship_not_built:" + repr(r))
    return ProjectDossier(
        envelope=envelope, project=project,
        # a young project may legitimately have no decisions/episodes/lessons yet
        decision_refs=_str_tuple("decision_refs", decision_refs, allow_empty=True),
        episode_refs=_str_tuple("episode_refs", episode_refs, allow_empty=True),
        lesson_refs=_str_tuple("lesson_refs", lesson_refs, allow_empty=True),
        relationships=rel_tuple, maturity=_check_maturity(maturity))


# -- DomainKnowledgePack ------------------------------------------------------------

@dataclass(frozen=True)
class DomainKnowledgePack:
    envelope: Envelope  # envelope.facets IS the declared facet scope (LIE/01 §5.6)
    member_refs: tuple  # identifier references to in-scope artifacts
    maturity: str


def build_domain_knowledge_pack(envelope, member_refs, maturity=MATURITY_PROVISIONAL):
    _validate_derived_envelope(envelope)
    return DomainKnowledgePack(envelope=envelope,
                                member_refs=_str_tuple("member_refs", member_refs),
                                maturity=_check_maturity(maturity))


# -- knowledge-class tagging (LIE/01 §2) ---------------------------------------

_DERIVED_TYPES = (Lesson, Pattern, AntiPattern, Recipe, ProjectDossier, DomainKnowledgePack)


def knowledge_class(record):
    """experience / intelligence / curation, derived purely from the
    record's type (LIE/01 §2's three classes) -- no stored tag, no
    mutable state."""
    if isinstance(record, (Episode, Decision)):
        return EXPERIENCE
    if isinstance(record, _DERIVED_TYPES):
        return INTELLIGENCE
    if isinstance(record, Annotation):
        return CURATION
    raise UnknownKnowledgeRecordError("derived.unknown_knowledge_record:" + repr(type(record)))


# -- human-readable serialization (INV-7) --------------------------------------

def to_dict(record):
    envelope_dict = envelope_to_dict(record.envelope)
    if isinstance(record, Lesson):
        return {"kind": "lesson", "envelope": envelope_dict, "statement": record.statement,
                "maturity": record.maturity}
    if isinstance(record, Pattern):
        return {"kind": "pattern", "envelope": envelope_dict, "approach": dict(record.approach),
                "maturity": record.maturity, "contested": record.contested}
    if isinstance(record, AntiPattern):
        return {"kind": "anti_pattern", "envelope": envelope_dict,
                "approach": dict(record.approach), "consequence": record.consequence,
                "maturity": record.maturity, "contested": record.contested}
    if isinstance(record, Recipe):
        # list, in step order -- NEVER sorted; order is the recipe
        return {"kind": "recipe", "envelope": envelope_dict, "steps": list(record.steps),
                "maturity": record.maturity}
    if isinstance(record, ProjectDossier):
        return {"kind": "project_dossier", "envelope": envelope_dict, "project": record.project,
                "decision_refs": list(record.decision_refs),
                "episode_refs": list(record.episode_refs),
                "lesson_refs": list(record.lesson_refs),
                "relationships": [{"other_project": r.other_project,
                                    "shared_facets": list(r.shared_facets)}
                                   for r in record.relationships],
                "maturity": record.maturity}
    if isinstance(record, DomainKnowledgePack):
        return {"kind": "domain_knowledge_pack", "envelope": envelope_dict,
                "member_refs": list(record.member_refs), "maturity": record.maturity}
    raise MalformedDerivedRecordError("derived.to_dict_unknown_kind:" + repr(type(record)))


def from_dict(data):
    kind = data.get("kind")
    if kind not in DERIVED_KINDS:
        raise MalformedDerivedRecordError("derived.from_dict_unknown_kind:" + repr(kind))
    maturity = data["maturity"]
    envelope = envelope_from_dict(data["envelope"])
    if kind == "lesson":
        return build_lesson(envelope, data["statement"], maturity=maturity)
    if kind == "pattern":
        return build_pattern(envelope, data["approach"], maturity=maturity,
                              contested=data["contested"])
    if kind == "anti_pattern":
        return build_anti_pattern(envelope, data["approach"], data["consequence"],
                                   maturity=maturity, contested=data["contested"])
    if kind == "recipe":
        return build_recipe(envelope, tuple(data["steps"]), maturity=maturity)
    if kind == "project_dossier":
        relationships = tuple(build_project_relationship(r["other_project"],
                                                          tuple(r["shared_facets"]))
                               for r in data["relationships"])
        return build_project_dossier(envelope, data["project"], tuple(data["decision_refs"]),
                                      tuple(data["episode_refs"]), tuple(data["lesson_refs"]),
                                      relationships, maturity=maturity)
    return build_domain_knowledge_pack(envelope, tuple(data["member_refs"]), maturity=maturity)


if __name__ == "__main__":
    from . import envelope as envelope_mod
    from .derivation_state import build_derivation_state

    def _derived_env(identity, relations=None, facets=("ros2",)):
        if relations is None:
            relations = (envelope_mod.build_relation("evidenced-by", "episode:e1"),)
        return envelope_mod.build_envelope(
            identity,
            envelope_mod.build_derivation_attestation(build_derivation_state(3, 1, 1)),
            envelope_mod.build_origin("asunama", "isaac-sim", None, "epoch-0"),
            facets, relations)

    # -- Lesson ---------------------------------------------------------------
    lesson = build_lesson(_derived_env("lesson:l1"), "monocular SLAM drifts indoors")
    assert lesson.maturity == MATURITY_PROVISIONAL
    try:
        lesson.statement = "other"
        raise SystemExit("lesson field reassignment allowed")
    except AttributeError:
        pass

    # INV-4: no evidenced-by relation -> not built
    try:
        build_lesson(_derived_env("lesson:l2", relations=()), "s")
        raise SystemExit("derived record without evidence citation accepted")
    except MissingEvidenceCitationError:
        pass

    # experience-flavored attestation refused on a derived record
    exp_env = envelope_mod.build_envelope(
        "lesson:l3", envelope_mod.build_attestation("trace:t1", True, 1),
        envelope_mod.build_origin("p", "e", None, "t0"), ("ros2",),
        (envelope_mod.build_relation("evidenced-by", "episode:e1"),))
    try:
        build_lesson(exp_env, "s")
        raise SystemExit("experience attestation accepted on a derived record")
    except MalformedDerivedRecordError:
        pass

    # -- Pattern / AntiPattern --------------------------------------------------
    pattern = build_pattern(_derived_env("pattern:p1"), {"approach": "use orb-slam3"})
    try:
        pattern.approach["approach"] = "x"
        raise SystemExit("pattern approach mutation allowed")
    except TypeError:
        pass

    anti = build_anti_pattern(
        _derived_env("anti:a1", relations=(
            envelope_mod.build_relation("evidenced-by", "episode:e9"),
            envelope_mod.build_relation("instead-of", "pattern:p1"))),
        {"approach": "raw GPS indoors"}, "position estimate diverges")
    assert anti.consequence == "position estimate diverges"
    assert any(r.relation_type == "instead-of" for r in anti.envelope.relations)
    # instead-of is optional: an anti-pattern without one still builds
    anti_bare = build_anti_pattern(_derived_env("anti:a2"), {"a": 1}, "c")
    assert not any(r.relation_type == "instead-of" for r in anti_bare.envelope.relations)
    try:
        build_anti_pattern(_derived_env("anti:a3"), {"a": 1}, "")
        raise SystemExit("empty consequence accepted")
    except MalformedDerivedRecordError:
        pass

    # -- Recipe ------------------------------------------------------------------
    recipe = build_recipe(_derived_env("recipe:r1"), ("flash jetson", "install ros2", "build ws"))
    assert recipe.steps == ("flash jetson", "install ros2", "build ws")  # order preserved
    try:
        build_recipe(_derived_env("recipe:r2"), ())
        raise SystemExit("empty steps accepted")
    except MalformedDerivedRecordError:
        pass

    # -- ProjectDossier ------------------------------------------------------------
    rel = build_project_relationship("other-drone", ("ros2", "cuda"))
    dossier = build_project_dossier(_derived_env("dossier:d1"), "asunama",
                                     ("decision:d1",), ("episode:e1",), (), (rel,))
    assert dossier.lesson_refs == ()  # empty ref lists are legitimate
    try:
        build_project_relationship("other", ())
        raise SystemExit("relationship without shared facets accepted (bare scalar)")
    except MalformedDerivedRecordError:
        pass
    try:
        build_project_dossier(_derived_env("dossier:d2"), "p", (), (), (),
                               ({"other_project": "x"},))
        raise SystemExit("unbuilt relationship accepted")
    except MalformedDerivedRecordError:
        pass

    # -- DomainKnowledgePack ----------------------------------------------------------
    pack = build_domain_knowledge_pack(_derived_env("pack:ros2", facets=("ros2",)),
                                        ("lesson:l1", "pattern:p1"))
    assert pack.envelope.facets == ("ros2",)  # the declared scope
    try:
        build_domain_knowledge_pack(_derived_env("pack:empty"), ())
        raise SystemExit("empty pack accepted")
    except MalformedDerivedRecordError:
        pass

    # -- knowledge-class tagging -------------------------------------------------
    from .curation import build_annotation
    from .decision import build_decision
    from .episode import build_episode

    experience_env = envelope_mod.build_envelope(
        "episode:e1", envelope_mod.build_attestation("trace:t1", True, 1),
        envelope_mod.build_origin("p", "e", None, "t0"), ("ros2",), ())
    ep = build_episode(experience_env, situation={"a": 1}, approach={"a": 1},
                        outcome={"a": 1}, cost={"a": 1})
    dec = build_decision(experience_env, "q", ("a",), "a", "r", {}, {})
    ann = build_annotation("deprecation", ("episode:e1",), "r", ("episode:e2",))
    assert knowledge_class(ep) == EXPERIENCE
    assert knowledge_class(dec) == EXPERIENCE
    for artifact in (lesson, pattern, anti, recipe, dossier, pack):
        assert knowledge_class(artifact) == INTELLIGENCE
    assert knowledge_class(ann) == CURATION
    try:
        knowledge_class("not a record")
        raise SystemExit("non-record classified")
    except UnknownKnowledgeRecordError:
        pass

    # -- round-trip, deterministic serialization (INV-7) ---------------------------
    import json
    for artifact in (lesson, pattern, anti, recipe, dossier, pack):
        d = to_dict(artifact)
        json.dumps(d)  # plain data only
        assert from_dict(d) == artifact
        assert to_dict(from_dict(d)) == d

    # maturity: closed ladder -- computed grades round-trip; inventions refused
    graded = build_lesson(_derived_env("lesson:l4"), "s", maturity=MATURITY_ESTABLISHED)
    assert from_dict(to_dict(graded)).maturity == MATURITY_ESTABLISHED
    try:
        build_lesson(_derived_env("lesson:l5"), "s", maturity="legendary")
        raise SystemExit("grade outside the ladder accepted at build")
    except MaturityNotAvailableError:
        pass
    tampered = to_dict(lesson)
    tampered["maturity"] = "legendary"
    try:
        from_dict(tampered)
        raise SystemExit("grade outside the ladder accepted from dict")
    except MaturityNotAvailableError:
        pass

    # contested: bool-only, defaults False, round-trips
    contested_pat = build_pattern(_derived_env("pattern:p2"), {"a": 1}, contested=True)
    assert contested_pat.contested is True
    assert from_dict(to_dict(contested_pat)).contested is True
    assert pattern.contested is False
    try:
        build_pattern(_derived_env("pattern:p3"), {"a": 1}, contested="yes")
        raise SystemExit("non-bool contested accepted")
    except MalformedDerivedRecordError:
        pass

    print("derived selftest ok")
