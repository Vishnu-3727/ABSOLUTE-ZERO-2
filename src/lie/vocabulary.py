"""LIE controlled facet vocabulary (LIE/01 §7, LIE/00 §7 governing principle
3 "regenerate over migrate ... readers accept old"). A `FacetVocabulary` is
an immutable, versioned snapshot of every facet term ever admitted: domains,
technologies, task classes, environments.

Two rules make it durable over a decade (LIE/01 §7):

1. **Versioned, additive, Curator-owned.** New terms are added; existing
   terms are never renamed or removed. `evolve()` is the ONLY path to a new
   version and structurally enforces additivity: the proposed term set must
   be a strict superset of the current one, or the call is refused loud
   (`VocabularyNotAdditiveError`) -- there is no edit/remove/rename API at
   all (mirrors `evidence.py`'s append-only discipline: absence of a
   mutating method, not a convention).
2. **Facets are assigned from this vocabulary, never invented freely**
   (LIE/01 §7.2) -- this module fixes the term store itself; the Gate
   (gate.py) is where membership is actually checked at admission time."""
from dataclasses import dataclass


class VocabularyRefusal(Exception):
    """Base for vocabulary.py refusals."""


class MalformedVocabularyError(VocabularyRefusal):
    """A vocabulary version or term set failed structural validation."""


class VocabularyNotAdditiveError(VocabularyRefusal):
    """`evolve()` was asked to produce a term set that does not retain
    every existing term -- removal/renaming is refused loud, never
    silently accepted (LIE/01 §7 rule 1)."""


class VocabularyNoNewTermsError(VocabularyRefusal):
    """`evolve()` was asked to produce a version with no new terms at all
    -- a version bump must add something, or there is nothing to version."""


@dataclass(frozen=True)
class FacetVocabulary:
    version: int
    terms: frozenset


def _validate_terms(terms):
    if not isinstance(terms, (frozenset, set, tuple, list)) or not terms:
        raise MalformedVocabularyError("vocabulary.empty_or_bad_terms:" + repr(terms))
    frozen = frozenset(terms)
    for t in frozen:
        if not isinstance(t, str) or not t:
            raise MalformedVocabularyError("vocabulary.bad_term:" + repr(t))
    return frozen


def build_vocabulary(version, terms):
    """The Phase 1 seed: version 1 (or any explicit starting version) with
    its initial term set. Not itself additive-checked -- there is nothing
    prior to be additive against."""
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MalformedVocabularyError("vocabulary.bad_version:" + repr(version))
    return FacetVocabulary(version=version, terms=_validate_terms(terms))


def evolve(vocabulary, new_terms):
    """The only path to a new vocabulary version. `new_terms` is the
    COMPLETE proposed term set (not just the delta) -- it must be a strict
    superset of `vocabulary.terms` or the call is refused loud. Returns a
    NEW `FacetVocabulary` at `vocabulary.version + 1`; never mutates the
    argument."""
    if not isinstance(vocabulary, FacetVocabulary):
        raise MalformedVocabularyError("vocabulary.evolve_target_not_a_vocabulary:" + repr(vocabulary))
    proposed = _validate_terms(new_terms)
    if not proposed.issuperset(vocabulary.terms):
        missing = vocabulary.terms - proposed
        raise VocabularyNotAdditiveError(
            "vocabulary.not_additive:removed_or_renamed=" + repr(sorted(missing)))
    if proposed == vocabulary.terms:
        raise VocabularyNoNewTermsError("vocabulary.no_new_terms:version=" + str(vocabulary.version))
    return FacetVocabulary(version=vocabulary.version + 1, terms=proposed)


if __name__ == "__main__":
    v1 = build_vocabulary(1, {"ros2", "cuda"})
    assert v1.version == 1
    assert v1.terms == frozenset({"ros2", "cuda"})

    v2 = evolve(v1, {"ros2", "cuda", "jetson"})
    assert v2.version == 2
    assert v2.terms == frozenset({"ros2", "cuda", "jetson"})
    # v1 untouched
    assert v1.terms == frozenset({"ros2", "cuda"})

    # additive-only: removal/renaming refused loud
    try:
        evolve(v2, {"ros2", "jetson"})  # dropped "cuda"
        raise SystemExit("term removal accepted")
    except VocabularyNotAdditiveError:
        pass
    try:
        evolve(v2, {"ros_two", "cuda", "jetson"})  # "ros2" renamed away
        raise SystemExit("term rename accepted")
    except VocabularyNotAdditiveError:
        pass

    # no-op evolve (same set) refused -- a version bump must add something
    try:
        evolve(v2, v2.terms)
        raise SystemExit("no-new-terms evolve accepted")
    except VocabularyNoNewTermsError:
        pass

    # no edit/remove/rename API exists at all
    assert not hasattr(v1, "remove_term")
    assert not hasattr(v1, "rename_term")

    # malformed inputs refused loud
    try:
        build_vocabulary(0, {"a"})
        raise SystemExit("non-positive version accepted")
    except MalformedVocabularyError:
        pass
    try:
        build_vocabulary(1, set())
        raise SystemExit("empty term set accepted")
    except MalformedVocabularyError:
        pass
    try:
        build_vocabulary(1, {"", "a"})
        raise SystemExit("empty term string accepted")
    except MalformedVocabularyError:
        pass

    print("vocabulary selftest ok")
