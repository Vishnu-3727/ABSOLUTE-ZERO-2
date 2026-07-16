"""LIE provenance envelope (LIE/01 §3, LIE/04 §6 "every stored record
carries the full provenance envelope. An envelope that cannot be completed
is a rejection, not a partial admit"). Five sections, every one required:

- **Identity** -- a stable identifier, unique forever, never reused.
- **Attestation** -- for experience records, the VAE-verdict/closed-trace
  reference that admitted the record, plus the facet-vocabulary version in
  force at admission (R2, LIE/04 §2 friction resolution: "the vocabulary
  version in force at admission is part of that provenance"). For derived
  records (Phase 2, LIE/01 §3: "for derived records, the derivation
  process version and the ledger state it was computed from"), the
  attestation is a `DerivationAttestation` wrapping the `DerivationState`
  triple -- which already names exactly those two things (ruleset version
  + ledger/overlay positions), so no new provenance concept is invented.
  Which attestation flavor a record kind requires is enforced by that
  record kind's own builder (episode/decision demand `Attestation`;
  derived.py demands `DerivationAttestation`), not here.
- **Origin** -- project, environment, and *when* (an opaque, caller-
  supplied value -- this module reads no clock, INV-8); contributor is
  recorded as provenance metadata only, never authority (LIE/01 §8).
- **Facets** -- the record's controlled-vocabulary coordinates (checked
  against the current `FacetVocabulary` by the Gate, not here -- this
  module only enforces structural shape).
- **Relations** -- typed, identifier-only links (LIE/01 §6's closed seven:
  `enacts`, `recovers`, `follows`, `evidenced-by`, `instead-of`,
  `supersedes`, `about`). `about` carries a UMS identifier string only,
  never copied content (INV-9) -- enforced structurally the same way every
  relation target is: `target_id` is always a bare string.

`Envelope` and its parts are `dataclass(frozen=True)`; every `build_*`
factory validates completeness and raises loud (`EnvelopeIncompleteError`)
rather than admitting a partial envelope -- LIE/04 §6's "rejection, not
partial admit" rule enforced at construction, one layer below the Gate."""
from dataclasses import dataclass
import json

from .derivation_state import DerivationState, from_dict as derivation_state_from_dict, \
    to_dict as derivation_state_to_dict

RELATION_TYPES = ("enacts", "recovers", "follows", "evidenced-by", "instead-of", "supersedes", "about")


class EnvelopeRefusal(Exception):
    """Base for envelope.py refusals."""


class EnvelopeIncompleteError(EnvelopeRefusal):
    """A required envelope section is missing or structurally invalid --
    LIE/04 §6: 'an envelope that cannot be completed is a rejection, not a
    partial admit.'"""


class UnknownRelationTypeError(EnvelopeRefusal):
    """A relation type outside LIE/01 §6's closed seven."""


def _require_nonempty_str(label, value):
    if not isinstance(value, str) or not value:
        raise EnvelopeIncompleteError("envelope.bad_" + label + ":" + repr(value))
    return value


@dataclass(frozen=True)
class Attestation:
    attestation_ref: str      # VAE verdict / closed-trace reference
    trace_closed: bool
    vocabulary_version: int   # facet-vocabulary version in force at admission (R2)


def build_attestation(attestation_ref, trace_closed, vocabulary_version):
    _require_nonempty_str("attestation_ref", attestation_ref)
    if not isinstance(trace_closed, bool):
        raise EnvelopeIncompleteError("envelope.bad_trace_closed:" + repr(trace_closed))
    if not isinstance(vocabulary_version, int) or isinstance(vocabulary_version, bool) \
            or vocabulary_version < 1:
        raise EnvelopeIncompleteError("envelope.bad_vocabulary_version:" + repr(vocabulary_version))
    return Attestation(attestation_ref=attestation_ref, trace_closed=trace_closed,
                        vocabulary_version=vocabulary_version)


@dataclass(frozen=True)
class DerivationAttestation:
    """The attestation flavor for derived (intelligence-layer) records
    (LIE/01 §3): the derivation process version and the ledger state the
    artifact was computed from -- both already named completely by the
    `DerivationState` triple (derivation_state.py), so this wraps it
    rather than restating its components."""
    derivation_state: DerivationState


def build_derivation_attestation(derivation_state):
    if not isinstance(derivation_state, DerivationState):
        raise EnvelopeIncompleteError(
            "envelope.bad_derivation_state:" + repr(derivation_state))
    return DerivationAttestation(derivation_state=derivation_state)


@dataclass(frozen=True)
class Origin:
    project: str          # identifiability check target (Gate provenance check)
    environment: str
    contributor: object   # provenance metadata only, never authority; None allowed
    occurred_at: object    # opaque, caller-supplied; never clock-read here


def build_origin(project, environment, contributor, occurred_at):
    _require_nonempty_str("project", project)
    _require_nonempty_str("environment", environment)
    if contributor is not None and not isinstance(contributor, str):
        raise EnvelopeIncompleteError("envelope.bad_contributor:" + repr(contributor))
    if occurred_at is None:
        raise EnvelopeIncompleteError("envelope.missing_occurred_at")
    return Origin(project=project, environment=environment, contributor=contributor,
                  occurred_at=occurred_at)


@dataclass(frozen=True)
class Relation:
    relation_type: str
    target_id: str  # identifier only, never copied content (INV-9)


def build_relation(relation_type, target_id):
    if relation_type not in RELATION_TYPES:
        raise UnknownRelationTypeError("envelope.unknown_relation_type:" + repr(relation_type))
    _require_nonempty_str("relation_target_id", target_id)
    return Relation(relation_type=relation_type, target_id=target_id)


@dataclass(frozen=True)
class Envelope:
    identity: str
    attestation: object  # Attestation (experience) or DerivationAttestation (derived)
    origin: Origin
    facets: tuple      # tuple of str
    relations: tuple   # tuple of Relation


def build_envelope(identity, attestation, origin, facets, relations):
    _require_nonempty_str("identity", identity)
    if not isinstance(attestation, (Attestation, DerivationAttestation)):
        raise EnvelopeIncompleteError("envelope.attestation_not_built:" + repr(attestation))
    if not isinstance(origin, Origin):
        raise EnvelopeIncompleteError("envelope.origin_not_built:" + repr(origin))
    if not isinstance(facets, (tuple, list)) or not facets:
        raise EnvelopeIncompleteError("envelope.empty_or_bad_facets:" + repr(facets))
    facet_tuple = tuple(facets)
    for f in facet_tuple:
        if not isinstance(f, str) or not f:
            raise EnvelopeIncompleteError("envelope.bad_facet:" + repr(f))
    if not isinstance(relations, (tuple, list)):
        raise EnvelopeIncompleteError("envelope.bad_relations:" + repr(relations))
    relation_tuple = tuple(relations)
    for r in relation_tuple:
        if not isinstance(r, Relation):
            raise EnvelopeIncompleteError("envelope.relation_not_built:" + repr(r))
        if r.relation_type not in RELATION_TYPES:
            raise UnknownRelationTypeError("envelope.unknown_relation_type:" + repr(r.relation_type))
    return Envelope(identity=identity, attestation=attestation, origin=origin,
                     facets=facet_tuple, relations=relation_tuple)


# -- human-readable serialization (INV-7) ------------------------------------

def _attestation_to_dict(attestation):
    if isinstance(attestation, DerivationAttestation):
        return {"derivation_state": derivation_state_to_dict(attestation.derivation_state)}
    return {
        "attestation_ref": attestation.attestation_ref,
        "trace_closed": attestation.trace_closed,
        "vocabulary_version": attestation.vocabulary_version,
    }


def to_dict(envelope):
    return {
        "identity": envelope.identity,
        "attestation": _attestation_to_dict(envelope.attestation),
        "origin": {
            "project": envelope.origin.project,
            "environment": envelope.origin.environment,
            "contributor": envelope.origin.contributor,
            "occurred_at": envelope.origin.occurred_at,
        },
        "facets": list(envelope.facets),
        "relations": [{"relation_type": r.relation_type, "target_id": r.target_id}
                       for r in envelope.relations],
    }


def from_dict(data):
    att_data = data["attestation"]
    if "derivation_state" in att_data:
        attestation = build_derivation_attestation(
            derivation_state_from_dict(att_data["derivation_state"]))
    else:
        attestation = build_attestation(att_data["attestation_ref"], att_data["trace_closed"],
                                         att_data["vocabulary_version"])
    origin = build_origin(data["origin"]["project"], data["origin"]["environment"],
                           data["origin"]["contributor"], data["origin"]["occurred_at"])
    relations = tuple(build_relation(r["relation_type"], r["target_id"]) for r in data["relations"])
    return build_envelope(data["identity"], attestation, origin, tuple(data["facets"]), relations)


def canonical(envelope):
    return json.dumps(to_dict(envelope), sort_keys=True, separators=(",", ":")).encode()


if __name__ == "__main__":
    att = build_attestation("trace:t1", True, 1)
    origin = build_origin("asunama", "isaac-sim", "vishnu", "ledger-epoch-0")
    rel = build_relation("about", "ums:repo/asunama")
    env = build_envelope("episode:e1", att, origin, ("ros2", "cuda"), (rel,))
    assert env.identity == "episode:e1"
    assert env.facets == ("ros2", "cuda")
    assert env.relations == (rel,)

    # frozen: no in-place field reassignment
    try:
        env.identity = "other"
        raise SystemExit("envelope field reassignment allowed")
    except AttributeError:
        pass

    # completeness: every required section refuses loud when missing/malformed
    try:
        build_attestation("", True, 1)
        raise SystemExit("empty attestation_ref accepted")
    except EnvelopeIncompleteError:
        pass
    try:
        build_attestation("t1", "not-a-bool", 1)
        raise SystemExit("non-bool trace_closed accepted")
    except EnvelopeIncompleteError:
        pass
    try:
        build_origin("", "env", None, "t0")
        raise SystemExit("unidentifiable origin (empty project) accepted")
    except EnvelopeIncompleteError:
        pass
    try:
        build_origin("proj", "env", None, None)
        raise SystemExit("missing occurred_at accepted")
    except EnvelopeIncompleteError:
        pass
    try:
        build_envelope("e1", att, origin, (), (rel,))
        raise SystemExit("empty facets accepted")
    except EnvelopeIncompleteError:
        pass
    try:
        build_envelope("e1", att, origin, ("ros2",), (Relation("not-built", "x"),))
        raise SystemExit("relation object with an invented type accepted")
    except UnknownRelationTypeError:
        pass
    try:
        build_envelope("e1", att, origin, ("ros2",), ({"relation_type": "about", "target_id": "x"},))
        raise SystemExit("dict standing in for a Relation accepted")
    except EnvelopeIncompleteError:
        pass

    # closed relation-type set (INV-9's carrier)
    try:
        build_relation("mentions", "ums:x")
        raise SystemExit("invented relation type accepted")
    except UnknownRelationTypeError:
        pass
    about = build_relation("about", "ums:repo/x")
    assert about.target_id == "ums:repo/x"
    assert isinstance(about.target_id, str)  # identifier only, never content (INV-9)

    # round-trip, deterministic serialization (INV-7)
    d1 = to_dict(env)
    d2 = to_dict(env)
    assert d1 == d2
    restored = from_dict(d1)
    assert restored == env
    assert canonical(env) == canonical(restored)

    # derivation-flavored attestation (Phase 2, LIE/01 §3) ------------------
    from .derivation_state import build_derivation_state

    der_att = build_derivation_attestation(build_derivation_state(3, 1, 1))
    ev_rel = build_relation("evidenced-by", "episode:e1")
    der_env = build_envelope("lesson:l1", der_att, origin, ("ros2",), (ev_rel,))
    assert der_env.attestation.derivation_state.ledger_position == 3

    # unbuilt derivation state refused
    try:
        build_derivation_attestation({"ledger_position": 3})
        raise SystemExit("unbuilt derivation state accepted")
    except EnvelopeIncompleteError:
        pass

    # derived envelope round-trips through the same to_dict/from_dict
    der_restored = from_dict(to_dict(der_env))
    assert der_restored == der_env
    assert canonical(der_env) == canonical(der_restored)

    print("envelope selftest ok")
