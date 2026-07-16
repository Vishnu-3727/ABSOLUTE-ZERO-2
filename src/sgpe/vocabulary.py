"""SGPE domain vocabulary registry (SGPE/00 §9, SGPE/01 §6). Lives in the
Store as a distinguished-kind document set: system scope, versioned,
append-only, additive-only. A vocabulary version may add domains,
operations, and fact names -- it may never remove or redefine an existing
one (LIE/01 precedent, carried into PS-8).

Additivity is enforced structurally here (`evolve()`'s only path to a new
version) AND again by the Store on append (defense in depth against a
hand-built, non-evolved `Vocabulary` object bypassing `evolve()`) -- see
store.py's `_apply_vocabulary_version`."""
from dataclasses import dataclass

# SGPE/00 §9's initial domain set.
INITIAL_DOMAINS = (
    "execution", "plugin", "filesystem", "repository", "network", "shell", "model",
    "token-budget", "context-limit", "resource-limit", "retry-limit", "persistence", "approval",
)


class VocabularyRefusal(Exception):
    """Base for vocabulary.py refusals."""


class MalformedVocabularyError(VocabularyRefusal):
    """A vocabulary version or term set failed structural validation."""


class VocabularyNotAdditiveError(VocabularyRefusal):
    """`evolve()` was asked to produce a term set that drops or renames an
    existing domain/operation/fact-name on any axis -- refused loud, never
    silently accepted (PS-8)."""


class VocabularyNoNewTermsError(VocabularyRefusal):
    """`evolve()` was asked to produce a version identical to the current
    one on every axis -- a version bump must add something."""


def _term_set(label, terms):
    if not isinstance(terms, (frozenset, set, tuple, list)):
        raise MalformedVocabularyError("vocabulary.bad_" + label + ":" + repr(terms))
    frozen = frozenset(terms)
    for t in frozen:
        if not isinstance(t, str) or not t:
            raise MalformedVocabularyError("vocabulary.bad_" + label + "_term:" + repr(t))
    return frozen


@dataclass(frozen=True)
class Vocabulary:
    version: int
    domains: frozenset
    operations: frozenset
    fact_names: frozenset


def build_vocabulary(version, domains, operations=(), fact_names=()):
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MalformedVocabularyError("vocabulary.bad_version:" + repr(version))
    domain_set = _term_set("domains", domains)
    if not domain_set:
        raise MalformedVocabularyError("vocabulary.empty_domains")
    return Vocabulary(version=version, domains=domain_set, operations=_term_set("operations", operations),
                       fact_names=_term_set("fact_names", fact_names))


def default_v1():
    """The Phase 1 seed vocabulary: SGPE/00 §9's initial domain set, no
    operations/fact-names declared yet (later versions add them additively)."""
    return build_vocabulary(1, INITIAL_DOMAINS)


def evolve(vocabulary, domains=None, operations=None, fact_names=None):
    """The only path to a new vocabulary version. Each of `domains` /
    `operations` / `fact_names`, when given, is the COMPLETE proposed term
    set for that axis (not just the delta) and must be a strict superset
    of the current one; an axis left as `None` carries the current set
    forward unchanged. Returns a NEW `Vocabulary` at `version + 1`; never
    mutates the argument."""
    if not isinstance(vocabulary, Vocabulary):
        raise MalformedVocabularyError("vocabulary.evolve_target_not_built:" + repr(vocabulary))
    new_domains = _term_set("domains", domains) if domains is not None else vocabulary.domains
    new_operations = _term_set("operations", operations) if operations is not None else vocabulary.operations
    new_fact_names = _term_set("fact_names", fact_names) if fact_names is not None else vocabulary.fact_names

    for label, current, proposed in (("domains", vocabulary.domains, new_domains),
                                      ("operations", vocabulary.operations, new_operations),
                                      ("fact_names", vocabulary.fact_names, new_fact_names)):
        if not proposed.issuperset(current):
            missing = current - proposed
            raise VocabularyNotAdditiveError(
                "vocabulary.not_additive:" + label + ":removed_or_renamed=" + repr(sorted(missing)))

    if (new_domains == vocabulary.domains and new_operations == vocabulary.operations
            and new_fact_names == vocabulary.fact_names):
        raise VocabularyNoNewTermsError("vocabulary.no_new_terms:version=" + str(vocabulary.version))

    return Vocabulary(version=vocabulary.version + 1, domains=new_domains, operations=new_operations,
                       fact_names=new_fact_names)


def to_dict(vocabulary):
    return {"version": vocabulary.version, "domains": sorted(vocabulary.domains),
            "operations": sorted(vocabulary.operations), "fact_names": sorted(vocabulary.fact_names)}


def from_dict(data):
    return build_vocabulary(data["version"], tuple(data["domains"]), tuple(data["operations"]),
                             tuple(data["fact_names"]))


if __name__ == "__main__":
    v1 = default_v1()
    assert v1.version == 1
    assert v1.domains == frozenset(INITIAL_DOMAINS)

    v2 = evolve(v1, operations=("read", "write"))
    assert v2.version == 2
    assert v2.domains == v1.domains  # untouched axis carried forward
    assert v2.operations == frozenset({"read", "write"})
    assert v1.operations == frozenset()  # original untouched

    v3 = evolve(v2, domains=tuple(INITIAL_DOMAINS) + ("audit",))
    assert "audit" in v3.domains
    assert v3.operations == v2.operations  # untouched axis carried forward

    # additive-only per axis
    try:
        evolve(v2, operations=("read",))  # dropped "write"
        raise SystemExit("operation removal accepted")
    except VocabularyNotAdditiveError:
        pass
    try:
        evolve(v1, domains=tuple(d for d in INITIAL_DOMAINS if d != "shell"))
        raise SystemExit("domain removal accepted")
    except VocabularyNotAdditiveError:
        pass
    try:
        evolve(v1, domains=tuple(d if d != "shell" else "sh" for d in INITIAL_DOMAINS))
        raise SystemExit("domain rename accepted")
    except VocabularyNotAdditiveError:
        pass

    # no-op evolve refused
    try:
        evolve(v1)
        raise SystemExit("no-new-terms evolve accepted")
    except VocabularyNoNewTermsError:
        pass

    # round trip
    restored = from_dict(to_dict(v3))
    assert restored == v3

    # no edit/remove/rename API exists at all
    assert not hasattr(v1, "remove_domain")
    assert not hasattr(v1, "rename_domain")

    # malformed inputs
    try:
        build_vocabulary(0, INITIAL_DOMAINS)
        raise SystemExit("non-positive version accepted")
    except MalformedVocabularyError:
        pass
    try:
        build_vocabulary(1, ())
        raise SystemExit("empty domain set accepted")
    except MalformedVocabularyError:
        pass

    print("vocabulary selftest ok")
