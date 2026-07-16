"""VAE's five-part evidence record (VAE/04 §7.1, VAE/00 §12, VAE/01 §6):
artifact binding, rules binding, evidence items, identified absences, and
an explicitly-empty derivation-account slot. Follows the `ro/priors.py` /
`ro/records.py` convention: `dataclass(frozen=True)`, `MappingProxyType`-
frozen mapping fields where relevant, validating `build_*` factories,
canonical/content_hash via sorted-key JSON.

Evidence items are the fourth part; identified absences (VAE/02 §5
"Missing") are first-class within that same append-only items list rather
than a bolted-on side channel — each is an ordinary `EvidenceItem` whose
`contribution_kind` is `"missing"` and which carries no `source` (there is
nothing to attribute an absence to). Contribution kind is a closed five
(VAE/02 §5): `independent`, `corroborating`, `redundant`, `conflicting`,
`missing` — anything else is refused loud (VAE-M7's "every evidence item
attributable" carried into a hard structural check).

Append-only (VAE-M2, VAE-A6): `EvidenceRecord` is frozen; there is no
edit/remove method for an existing item at all — `append_item` is the only
way an item enters a record, and it always returns a NEW record built from
the old items tuple plus one more, never mutating the old one in place.
`derivation_account` stays `None` through every Phase 1 construction path;
passing a non-None value is refused loud (filled for real in Phase 3,
VAE-A10).

Content-hash identity is order-sensitive by construction: items are stored
and serialized as a list, in append order, never sorted — per VAE/01 §6/
VAE-M4, independently sourced evidence for the same claim must stay
distinguishable, and per-artifact ordering is itself meaningful (VAE/06
Phase 1 testing goals)."""
from dataclasses import dataclass
from types import MappingProxyType
import hashlib
import json

CONTRIBUTION_KINDS = ("independent", "corroborating", "redundant", "conflicting", "missing")


class EvidenceRefusal(Exception):
    """Base for evidence.py refusals."""


class MalformedEvidenceItemError(EvidenceRefusal):
    """An evidence item failed structural validation."""


class UnknownContributionKindError(EvidenceRefusal):
    """A contribution kind outside VAE/02 §5's closed five."""


class MalformedEvidenceRecordError(EvidenceRefusal):
    """An evidence record's binding fields failed structural validation."""


class DerivationAccountRefusedError(EvidenceRefusal):
    """Phase 1 refuses any attempt to set a non-None derivation account —
    that slot is filled for real only in Phase 3 (VAE-A10). Also raised by
    `with_derivation_account` if the target record's slot is already filled
    (the slot is filled exactly once; re-deriving produces a new account to
    compare, never a second write to the same record)."""


class DerivationAccountMalformedError(EvidenceRefusal):
    """A derivation account passed to `with_derivation_account` was not a
    mapping (Phase 3, derivation.py, is the only producer of well-formed
    accounts; this is a structural backstop, not a content check — this
    module has no opinion on account content)."""


@dataclass(frozen=True)
class EvidenceItem:
    rule: str            # the rule addressed (VAE-M7)
    artifact_ref: str     # the artifact reference this item bears on
    source: object         # own check name or delegated-result ref; None only for "missing"
    result: str            # the recorded observation/outcome
    contribution_kind: str  # one of CONTRIBUTION_KINDS (VAE/02 §5)
    level: str              # verification level this item addresses (VAE-M7)


def build_evidence_item(rule, artifact_ref, source, result, contribution_kind, level):
    if contribution_kind not in CONTRIBUTION_KINDS:
        raise UnknownContributionKindError(
            "evidence.unknown_contribution_kind:" + repr(contribution_kind))
    for label, value in (("rule", rule), ("artifact_ref", artifact_ref),
                          ("result", result), ("level", level)):
        if not isinstance(value, str) or not value:
            raise MalformedEvidenceItemError("evidence.bad_" + label + ":" + repr(value))
    if contribution_kind == "missing":
        if source is not None:
            raise MalformedEvidenceItemError(
                "evidence.missing_item_must_have_no_source:" + repr(source))
    else:
        if not isinstance(source, str) or not source:
            raise MalformedEvidenceItemError("evidence.bad_source:" + repr(source))
    return EvidenceItem(rule=rule, artifact_ref=artifact_ref, source=source, result=result,
                         contribution_kind=contribution_kind, level=level)


@dataclass(frozen=True)
class EvidenceRecord:
    artifact_ref: str        # Storage-backed reference to the judged artifact (VAE/04 §7.1)
    rules_version: int        # the rules version used (VAE-K2 replay)
    items: tuple                # tuple of EvidenceItem, append-only, in append order
    derivation_account: object  # None through Phase 1; filled Phase 3 (VAE-A10)


def _validate_binding(artifact_ref, rules_version):
    if not isinstance(artifact_ref, str) or not artifact_ref:
        raise MalformedEvidenceRecordError("evidence.bad_artifact_ref:" + repr(artifact_ref))
    if not isinstance(rules_version, int) or isinstance(rules_version, bool) or rules_version < 1:
        raise MalformedEvidenceRecordError("evidence.bad_rules_version:" + repr(rules_version))


def build_evidence_record(artifact_ref, rules_version, items=(), derivation_account=None):
    _validate_binding(artifact_ref, rules_version)
    if derivation_account is not None:
        raise DerivationAccountRefusedError(
            "evidence.derivation_account_not_available_until_phase_3")
    frozen_items = []
    for item in items:
        if not isinstance(item, EvidenceItem):
            raise MalformedEvidenceItemError("evidence.item_not_built:" + repr(item))
        frozen_items.append(item)
    return EvidenceRecord(artifact_ref=artifact_ref, rules_version=rules_version,
                           items=tuple(frozen_items), derivation_account=None)


def append_item(record, item):
    """The only mutation path: returns a NEW record with `item` appended to
    the end of the existing items tuple. There is no method that edits or
    removes an existing item — no such API surface exists (VAE-M2, VAE-A6)."""
    if not isinstance(record, EvidenceRecord):
        raise MalformedEvidenceRecordError("evidence.append_target_not_a_record:" + repr(record))
    if not isinstance(item, EvidenceItem):
        raise MalformedEvidenceItemError("evidence.append_item_not_built:" + repr(item))
    return EvidenceRecord(artifact_ref=record.artifact_ref, rules_version=record.rules_version,
                           items=record.items + (item,), derivation_account=None)


def with_derivation_account(record, account):
    """Phase 3's ONLY path into the derivation-account slot (VAE-A10):
    returns a NEW frozen `EvidenceRecord` — same artifact/rules binding,
    same items tuple, untouched — with `derivation_account` filled from a
    completed Phase 3 derivation. Additive to Phase 1: `build_evidence_record`
    and `append_item` still refuse any non-None account outright; this
    function is the one place that fills it, and only once per record (a
    record whose slot is already filled is refused — the account is not an
    editable field, VAE-A6). Never mutates `record`; `account` is stored
    as-is (derivation.py is responsible for handing over an already-frozen,
    already-immutable structure — this module has no opinion on its shape
    beyond "is a mapping")."""
    if not isinstance(record, EvidenceRecord):
        raise MalformedEvidenceRecordError(
            "evidence.with_derivation_account_target_not_a_record:" + repr(record))
    if record.derivation_account is not None:
        raise DerivationAccountRefusedError(
            "evidence.derivation_account_already_set:" + record.artifact_ref)
    if not isinstance(account, (dict, MappingProxyType)):
        raise DerivationAccountMalformedError(
            "evidence.derivation_account_not_a_mapping:" + repr(account))
    return EvidenceRecord(artifact_ref=record.artifact_ref, rules_version=record.rules_version,
                           items=record.items, derivation_account=account)


# -- canonical serialization (records.py / priors.py pattern) ---------------

def _item_to_dict(item):
    return {
        "rule": item.rule, "artifact_ref": item.artifact_ref, "source": item.source,
        "result": item.result, "contribution_kind": item.contribution_kind, "level": item.level,
    }


def to_dict(record):
    return {
        "artifact_ref": record.artifact_ref,
        "rules_version": record.rules_version,
        # list, in append order — NEVER sorted; order is meaningful (VAE-M4)
        "items": [_item_to_dict(i) for i in record.items],
        "derivation_account": record.derivation_account,
    }


def canonical(record):
    # sort_keys sorts each dict's OWN keys only; the top-level "items" list
    # itself keeps append order, which is exactly what makes content_hash
    # order-sensitive across items while still deterministic per item.
    return json.dumps(to_dict(record), sort_keys=True, separators=(",", ":")).encode()


def content_hash(record):
    return hashlib.sha256(canonical(record)).hexdigest()


def from_canonical(data):
    """Phase 5's ONLY path back from Storage-persisted bytes to an
    `EvidenceRecord` (VAE-K2, VAE/05 §8: "every verdict event re-derives
    from its persisted evidence record" -- replay reconstructs a record
    from durable bytes alone, zero live reads). Inverse of `canonical()`/
    `to_dict()`: items are rebuilt in their stored append order (order is
    meaningful, VAE-M4) and whatever derivation account was persisted is
    restored as-is -- this is deserialization, not derivation; Phase 3's
    `derive()` is the only place account content is ever computed."""
    obj = json.loads(data.decode())
    items = tuple(
        EvidenceItem(rule=i["rule"], artifact_ref=i["artifact_ref"], source=i["source"],
                     result=i["result"], contribution_kind=i["contribution_kind"], level=i["level"])
        for i in obj["items"])
    return EvidenceRecord(artifact_ref=obj["artifact_ref"], rules_version=obj["rules_version"],
                           items=items, derivation_account=obj["derivation_account"])


if __name__ == "__main__":
    rec = build_evidence_record("artifact:a1", 1)
    assert rec.items == ()
    assert rec.derivation_account is None

    item_a = build_evidence_item("rule.structural", "artifact:a1", "check.structural",
                                  "pass", "independent", "structural")
    item_b = build_evidence_item("rule.semantic", "artifact:a1", "check.semantic",
                                  "pass", "corroborating", "semantic")
    absence = build_evidence_item("rule.system", "artifact:a1", None,
                                   "not_run", "missing", "system")

    rec1 = append_item(rec, item_a)
    rec2 = append_item(rec1, item_b)
    rec3 = append_item(rec2, absence)
    assert len(rec3.items) == 3
    assert rec3.items[-1].contribution_kind == "missing"
    # original records untouched (append never mutates in place)
    assert rec.items == ()
    assert rec1.items == (item_a,)

    # frozen: no in-place field reassignment
    try:
        rec3.items = ()
        raise SystemExit("record field reassignment allowed")
    except AttributeError:
        pass
    try:
        item_a.result = "fail"
        raise SystemExit("item field reassignment allowed")
    except AttributeError:
        pass

    # no edit/remove API exists at all — append_item is the ONLY mutation path
    assert not hasattr(rec3, "edit_item")
    assert not hasattr(rec3, "remove_item")
    assert not hasattr(rec3, "set_item")

    # closed-five contribution kind refused loud
    try:
        build_evidence_item("r", "a", "s", "res", "independent", "structural")
        raise SystemExit("non-canon contribution kind accepted")
    except UnknownContributionKindError:
        pass

    # missing items must carry no source; non-missing items must carry one
    try:
        build_evidence_item("r", "a", "some.source", "not_run", "missing", "system")
        raise SystemExit("missing item with a source accepted")
    except MalformedEvidenceItemError:
        pass
    try:
        build_evidence_item("r", "a", None, "pass", "independent", "structural")
        raise SystemExit("non-missing item with no source accepted")
    except MalformedEvidenceItemError:
        pass

    # derivation account slot explicitly refused before Phase 3
    try:
        build_evidence_record("artifact:a1", 1, derivation_account={"verdict": "verify.passed"})
        raise SystemExit("derivation account accepted in Phase 1")
    except DerivationAccountRefusedError:
        pass

    # content-hash determinism: same items, same order -> same hash
    rec3b = append_item(append_item(append_item(
        build_evidence_record("artifact:a1", 1), item_a), item_b), absence)
    assert content_hash(rec3) == content_hash(rec3b)

    # order-sensitivity: same items, different order -> different hash
    rec_reordered = append_item(append_item(append_item(
        build_evidence_record("artifact:a1", 1), item_b), item_a), absence)
    assert content_hash(rec_reordered) != content_hash(rec3)

    # from_canonical: round trip, including an account-bearing record ------
    rec3_bytes = canonical(rec3)
    rec3_restored = from_canonical(rec3_bytes)
    assert rec3_restored.items == rec3.items
    assert rec3_restored.artifact_ref == rec3.artifact_ref
    assert rec3_restored.rules_version == rec3.rules_version
    assert rec3_restored.derivation_account is None
    assert content_hash(rec3_restored) == content_hash(rec3)

    accounted = with_derivation_account(build_evidence_record("artifact:a2", 1, items=(item_a,)),
                                         {"verdict": "passed", "assurance_level": "Unverified"})
    accounted_restored = from_canonical(canonical(accounted))
    assert accounted_restored.derivation_account == accounted.derivation_account
    assert content_hash(accounted_restored) == content_hash(accounted)

    print("evidence selftest ok")
