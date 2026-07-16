"""LIE curation annotation record (LIE/01 §2, §9; LIE/04 §6 Curator
contract). The curation overlay's one record kind: an append-only ruling
that references ledger records by identity and changes how readers weigh
them, never what they say (LIE/01 §2's "Curator annotates, never
mutates"). Three closed kinds -- deprecation, supersession, contradiction
resolution -- matching LIE/00 §4.5's Curator responsibilities exactly; no
ruling *semantics* beyond the record shape are Phase 1 material (out of
scope per the implementation charter).

Every annotation carries `reason` and `cited_evidence` (LIE/04 §6 Curator
"Required": "rulings ... with reasons and cited evidence") -- a ruling
with no stated justification is refused loud, the same "cite or stay
silent" discipline INV-4 imposes on recommendations (LIE/00 §2)."""
from dataclasses import dataclass

ANNOTATION_KINDS = ("deprecation", "supersession", "contradiction_resolution")


class CurationRefusal(Exception):
    """Base for curation.py refusals."""


class UnknownAnnotationKindError(CurationRefusal):
    """An annotation kind outside the closed three."""


class MalformedAnnotationError(CurationRefusal):
    """An annotation's fields failed structural validation."""


def _nonempty_str_tuple(label, value):
    if not isinstance(value, (tuple, list)) or not value:
        raise MalformedAnnotationError("curation.empty_or_bad_" + label + ":" + repr(value))
    out = tuple(value)
    for v in out:
        if not isinstance(v, str) or not v:
            raise MalformedAnnotationError("curation.bad_" + label + "_entry:" + repr(v))
    return out


@dataclass(frozen=True)
class Annotation:
    kind: str
    target_ids: tuple       # ledger/overlay record identifiers this ruling concerns
    reason: str
    cited_evidence: tuple   # identifiers cited as justification


def build_annotation(kind, target_ids, reason, cited_evidence):
    if kind not in ANNOTATION_KINDS:
        raise UnknownAnnotationKindError("curation.unknown_kind:" + repr(kind))
    targets = _nonempty_str_tuple("target_ids", target_ids)
    if not isinstance(reason, str) or not reason:
        raise MalformedAnnotationError("curation.bad_reason:" + repr(reason))
    evidence = _nonempty_str_tuple("cited_evidence", cited_evidence)
    return Annotation(kind=kind, target_ids=targets, reason=reason, cited_evidence=evidence)


def to_dict(annotation):
    return {
        "kind": annotation.kind,
        "target_ids": list(annotation.target_ids),
        "reason": annotation.reason,
        "cited_evidence": list(annotation.cited_evidence),
    }


def from_dict(data):
    return build_annotation(data["kind"], tuple(data["target_ids"]), data["reason"],
                             tuple(data["cited_evidence"]))


if __name__ == "__main__":
    ann = build_annotation("supersession", ("episode:e1",), "re-attempted with better evidence",
                            ("episode:e2",))
    assert ann.kind == "supersession"

    # frozen: no in-place field reassignment
    try:
        ann.reason = "other"
        raise SystemExit("annotation field reassignment allowed")
    except AttributeError:
        pass

    # no edit/remove API exists at all -- append-only overlay discipline
    assert not hasattr(ann, "edit")
    assert not hasattr(ann, "remove")

    # closed kind set
    try:
        build_annotation("delete", ("episode:e1",), "r", ("episode:e2",))
        raise SystemExit("non-canon annotation kind accepted")
    except UnknownAnnotationKindError:
        pass

    # reason and cited_evidence are mandatory -- "cite or stay silent"
    try:
        build_annotation("deprecation", ("episode:e1",), "", ("episode:e2",))
        raise SystemExit("empty reason accepted")
    except MalformedAnnotationError:
        pass
    try:
        build_annotation("deprecation", ("episode:e1",), "reason", ())
        raise SystemExit("empty cited_evidence accepted")
    except MalformedAnnotationError:
        pass

    # round-trip, deterministic serialization (INV-7)
    assert from_dict(to_dict(ann)) == ann

    print("curation selftest ok")
