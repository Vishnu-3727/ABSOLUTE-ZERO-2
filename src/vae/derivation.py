"""VAE Phase 3 — Derivation (VAE/06 Phase 3, VAE/02 §3-§7, VAE/01 §11):
a pure function from a CLOSED evidence body (evidence.py's `EvidenceRecord`,
already `judgment.close()`-sealed) plus a versioned derivation policy to a
verdict, five confidence dimensions, explicit uncertainty, a five-level
assurance classification, and (on a fail verdict) one of VAE/01 §11's five
failure causes. Nothing here emits events, persists anything, or talks to
Storage/Communication/Execution — derivation reads `record.items` and
`record.rules_version` and returns data (VAE/06 "derivation is a pure
function layer"). `attach_derivation` is the only place a derivation account
enters `evidence.py`'s Phase-1-refused slot, via `evidence.with_derivation_account`
(additive, never mutation).

**Interpretation calls flagged, most-conservative reading taken where VAE/02
defers the derivation EXPRESSION to rules-as-data (§3, §7 "the mapping's
expression is later-phase rules-as-data"):**

1. Confidence-dimension banding (`CONFIDENCE_LEVELS`, the corroborated /
   single / conflicted / absent claim-strength rules) is pure categorical
   composition straight out of VAE/02 §4-§5's prose (corroboration
   strengthens beyond a single source; conflict lands below either alone;
   redundant items are simply excluded from the count they'd otherwise
   inflate; missing items never enter a dimension's confidence, only its
   coverage) — no numeric weight is invented anywhere in this step.
2. The one place a genuine threshold is unavoidable is coverage banding
   (what fraction of identified claims counts as "substantially complete"
   vs "adequate but uneven" vs "minimal") and the assurance-level cutoffs
   built from it. Per the brief, that expression is taken as a **versioned
   derivation-policy parameter** (`DerivationPolicy`, `build_derivation_policy`)
   rather than a hardcoded magic number presented as architecture — every
   caller supplies one explicitly; there is no default policy.
3. VAE/01 §5's five verification levels are treated as a closed set here
   (`CANONICAL_LEVELS`) mapping onto VAE/02 §3's four non-coverage
   confidence dimensions (`structural`, `execution`, `semantic`,
   `consistency` — the latter merging Cross-artifact and System per §3's
   explicit "share a dimension" ruling). evidence.py's own `level` field is
   an unconstrained non-empty string (Phase 1 scope); this module adds the
   closed-set check on top, additively, only at derivation time.
4. "Claim" identity for confidence/coverage purposes is `(level, rule)` —
   the same rule addressed at two different levels is two claims, matching
   VAE-M7's per-item (rule, level) attribution rather than collapsing on
   `rule` alone.
5. Evidence-item `result` strings are classified via the CLOSED outcome
   vocabularies `execution_double.py` (`success/failure/timeout/crash`) and
   `static_checks.py` (`pass/fail`) already fix, plus `judgment.py`'s own
   literal `"execution_failure"` expiry string — not a new invented
   vocabulary. Any other result string on a non-missing item is treated as
   VAE/01 §11 "inconclusive" (the check ran and returned something, but it
   does not settle the claim) rather than silently ignored.
6. A completely empty evidence body (`record.items == ()`) is Evidence
   insufficiency, not a vacuous pass — VAE-I5/VAE/01 §11 require every
   failure mode, including "nothing was ever checked," to degrade to a
   definite fail rather than default to pass.
7. Item order does not change the verdict, confidence, or assurance level
   (derivation is a set-of-claims function of the closed body); order
   remains meaningful for `evidence.py`'s content-hash record identity,
   which this module does not touch or recompute.

Failure-cause precedence (fixed, for determinism when more than one cause
condition holds over the same body — VAE-I6): contradictory evidence >
inconclusive verification > execution failure > verification failure >
evidence insufficiency. Contradiction is checked first because a conflicting
item's mere presence is itself the fact being reported, independent of what
any result string says; inconclusive is checked before the two failure
kinds because an unclassifiable result cannot yet be read as either kind of
failure."""
from dataclasses import dataclass
from types import MappingProxyType

from . import evidence

CONFIDENCE_LEVELS = ("none", "conflicted", "weak", "moderate", "strong")

DIMENSIONS = ("structural", "execution", "semantic", "consistency")

LEVEL_TO_DIMENSION = MappingProxyType({
    "structural": "structural",
    "execution": "execution",
    "semantic": "semantic",
    "cross_artifact": "consistency",
    "system": "consistency",
})
CANONICAL_LEVELS = tuple(LEVEL_TO_DIMENSION.keys())

# VAE/01 §11 closed five, VAE-K8 — exact causes, code-identifier slugs.
EXECUTION_FAILURE = "execution_failure"
VERIFICATION_FAILURE = "verification_failure"
EVIDENCE_INSUFFICIENCY = "evidence_insufficiency"
INCONCLUSIVE_VERIFICATION = "inconclusive_verification"
CONTRADICTORY_EVIDENCE = "contradictory_evidence"
FAILURE_CAUSES = (CONTRADICTORY_EVIDENCE, INCONCLUSIVE_VERIFICATION, EXECUTION_FAILURE,
                   VERIFICATION_FAILURE, EVIDENCE_INSUFFICIENCY)

# VAE/02 §7 closed five, exact level names copied verbatim from the doc.
VERIFIED_HIGH = "Verified — High Assurance"
VERIFIED_MODERATE = "Verified — Moderate Assurance"
VERIFIED_LOW = "Verified — Low Assurance"
UNVERIFIED = "Unverified"
VERIFICATION_FAILED = "Verification Failed"
ASSURANCE_LEVELS = (VERIFIED_HIGH, VERIFIED_MODERATE, VERIFIED_LOW, UNVERIFIED, VERIFICATION_FAILED)

# Closed outcome vocabularies already fixed by execution_double.py / static_checks.py,
# plus judgment.py's own literal expiry string — not invented here (interpretation call 5).
PASSING_RESULTS = ("pass", "success")
EXECUTION_FAILURE_RESULTS = ("failure", "timeout", "crash", "execution_failure")
SEMANTIC_FAIL_RESULTS = ("fail",)

VERDICT_PASSED = "passed"
VERDICT_FAILED = "failed"


class DerivationRefusal(Exception):
    """Base for derivation.py refusals."""


class UnknownVerificationLevelError(DerivationRefusal):
    """An evidence item's `level` is outside VAE/01 §5's closed five."""


class MalformedDerivationPolicyError(DerivationRefusal):
    """A derivation policy failed structural validation."""


@dataclass(frozen=True)
class DerivationPolicy:
    policy_version: int
    coverage_moderate_min_fraction: float  # established/total >= this -> at least "moderate"
    coverage_strong_min_fraction: float    # established/total >= this -> "strong"


def build_derivation_policy(policy_version, coverage_moderate_min_fraction,
                             coverage_strong_min_fraction):
    if not isinstance(policy_version, int) or isinstance(policy_version, bool) or policy_version < 1:
        raise MalformedDerivationPolicyError(
            "derivation.bad_policy_version:" + repr(policy_version))
    for label, value in (("coverage_moderate_min_fraction", coverage_moderate_min_fraction),
                          ("coverage_strong_min_fraction", coverage_strong_min_fraction)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 < value <= 1):
            raise MalformedDerivationPolicyError(
                "derivation.bad_" + label + ":" + repr(value))
    if coverage_strong_min_fraction < coverage_moderate_min_fraction:
        raise MalformedDerivationPolicyError(
            "derivation.strong_threshold_below_moderate:" +
            repr(coverage_strong_min_fraction) + "<" + repr(coverage_moderate_min_fraction))
    return DerivationPolicy(policy_version=policy_version,
                             coverage_moderate_min_fraction=coverage_moderate_min_fraction,
                             coverage_strong_min_fraction=coverage_strong_min_fraction)


def _verdict_and_cause(items):
    """Scans the closed body once; fixed precedence (module docstring)."""
    if not items:
        return VERDICT_FAILED, EVIDENCE_INSUFFICIENCY
    has_conflicting = False
    has_unresolved = False
    has_execution_failure = False
    has_verification_failure = False
    has_missing = False
    for item in items:
        if item.contribution_kind == "conflicting":
            has_conflicting = True
        if item.contribution_kind == "missing":
            has_missing = True
            continue
        if item.result in PASSING_RESULTS:
            continue
        if item.result in EXECUTION_FAILURE_RESULTS:
            has_execution_failure = True
        elif item.result in SEMANTIC_FAIL_RESULTS:
            has_verification_failure = True
        else:
            has_unresolved = True
    if has_conflicting:
        return VERDICT_FAILED, CONTRADICTORY_EVIDENCE
    if has_unresolved:
        return VERDICT_FAILED, INCONCLUSIVE_VERIFICATION
    if has_execution_failure:
        return VERDICT_FAILED, EXECUTION_FAILURE
    if has_verification_failure:
        return VERDICT_FAILED, VERIFICATION_FAILURE
    if has_missing:
        return VERDICT_FAILED, EVIDENCE_INSUFFICIENCY
    return VERDICT_PASSED, None


def _group_claims(items):
    """(level, rule) -> list of (index, item), in append order. Also
    validates every item's level against the closed VAE/01 §5 five."""
    claims = {}
    order = []
    for idx, item in enumerate(items):
        if item.level not in CANONICAL_LEVELS:
            raise UnknownVerificationLevelError(
                "derivation.unknown_verification_level:" + repr(item.level))
        key = (item.level, item.rule)
        if key not in claims:
            claims[key] = []
            order.append(key)
        claims[key].append((idx, item))
    return order, claims


def _claim_strength(entries):
    """VAE/02 §4-§5's claim-level rule, purely categorical:
    conflicting kind present -> "conflicted" (below either item alone);
    every item "missing" -> "absent" (no evidence, caps coverage only);
    else strength is driven by independent/corroborating items only —
    redundant items are counted zero times, exactly as §5 requires."""
    kinds = [it.contribution_kind for _, it in entries]
    refs = tuple(idx for idx, _ in entries)
    if "conflicting" in kinds:
        return "conflicted", refs
    if all(k == "missing" for k in kinds):
        return "absent", refs
    substantive = [it for it in kinds if it in ("independent", "corroborating")]
    if len(substantive) >= 2:
        return "corroborated", refs
    if len(substantive) == 1:
        return "single", refs
    return "absent", refs  # only redundant ever recorded for this claim (defensive)


def _dimension_confidence(dim_claims):
    if not dim_claims:
        return "none", ()
    strengths = [s for _, s, _ in dim_claims]
    all_refs = tuple(sorted({idx for _, _, refs in dim_claims for idx in refs}))
    if "conflicted" in strengths:
        return "conflicted", all_refs
    established = [s for s in strengths if s in ("corroborated", "single")]
    if not established:
        return "none", all_refs
    if all(s == "corroborated" for s in established):
        return "strong", all_refs
    if all(s == "single" for s in established):
        return "weak", all_refs
    return "moderate", all_refs


def _coverage(claim_order, claims, policy):
    total = len(claim_order)
    if total == 0:
        return {"level": "none", "established": 0, "total": 0, "refs": ()}
    established_count = 0
    for key in claim_order:
        strength, _ = _claim_strength(claims[key])
        if strength != "absent":
            established_count += 1
    all_refs = tuple(range(sum(len(claims[k]) for k in claim_order)))
    if established_count == 0:
        return {"level": "none", "established": 0, "total": total, "refs": all_refs}
    fraction = established_count / total
    if fraction >= policy.coverage_strong_min_fraction:
        level = "strong"
    elif fraction >= policy.coverage_moderate_min_fraction:
        level = "moderate"
    else:
        level = "weak"
    return {"level": level, "established": established_count, "total": total, "refs": all_refs}


def _uncertainty(claim_order, claims):
    statements = []
    for level, rule in sorted(claim_order):
        strength, refs = _claim_strength(claims[(level, rule)])
        if strength == "absent":
            statements.append({"level": level, "rule": rule, "reason": "missing_evidence",
                                "refs": refs})
    return tuple(statements)


def _assurance_level(verdict, confidence, coverage):
    """Only reached with meaningful confidence values on a PASS: a passed
    verdict (see `_verdict_and_cause`) can never carry a "missing" or
    "conflicting" item, so every applicable dimension here is one of
    weak/moderate/strong — "none" means the dimension was never addressed
    at all (inapplicable, excluded per VAE/02 §7's own "applicable
    dimensions" qualifier) and "conflicted" cannot occur on a pass.

    High: every applicable dimension strong AND coverage substantially
    complete (§7's own wording). Low: every applicable dimension weak — the
    uniformly-minimal-evidence case §7 names ("the least the rules
    required"). Anything mixed is Moderate — §7's "some dimensions thin"
    is exactly a mix of strong and weak dimensions."""
    if verdict == VERDICT_FAILED:
        return VERIFICATION_FAILED
    applicable = [dim for dim in DIMENSIONS if confidence[dim]["level"] != "none"]
    if not applicable:
        return VERIFIED_LOW
    ranks = [CONFIDENCE_LEVELS.index(confidence[dim]["level"]) for dim in applicable]
    strong_rank = CONFIDENCE_LEVELS.index("strong")
    weak_rank = CONFIDENCE_LEVELS.index("weak")
    if all(r == strong_rank for r in ranks) and coverage["level"] == "strong":
        return VERIFIED_HIGH
    if all(r == weak_rank for r in ranks):
        return VERIFIED_LOW
    return VERIFIED_MODERATE


def derive(record, policy):
    """Pure: `(closed EvidenceRecord, DerivationPolicy) -> derivation
    account` (a nested, JSON-serializable, effectively-immutable mapping —
    dicts/tuples only, matching `evidence.py`'s `to_dict`/`canonical`
    contract so a derivation-account-bearing record still content-hashes).
    Deterministic (VAE-I6/VAE-A1): identical `record.items` +
    `record.rules_version` + `policy` -> byte-identical account, regardless
    of internal iteration order (claims are grouped by (level, rule), not by
    dict insertion order, and every list this function returns is sorted or
    built in the record's own append order)."""
    if not isinstance(record, evidence.EvidenceRecord):
        raise DerivationRefusal("derivation.target_not_a_record:" + repr(record))
    if not isinstance(policy, DerivationPolicy):
        raise DerivationRefusal("derivation.policy_not_built:" + repr(policy))

    verdict, cause = _verdict_and_cause(record.items)
    claim_order, claims = _group_claims(record.items)

    dim_claims = {dim: [] for dim in DIMENSIONS}
    for key in claim_order:
        level, rule = key
        dim = LEVEL_TO_DIMENSION[level]
        strength, refs = _claim_strength(claims[key])
        dim_claims[dim].append((rule, strength, refs))

    confidence = {}
    for dim in DIMENSIONS:
        level, refs = _dimension_confidence(dim_claims[dim])
        confidence[dim] = {"level": level, "refs": refs}

    coverage = _coverage(claim_order, claims, policy)
    uncertainty = _uncertainty(claim_order, claims)
    assurance_level = _assurance_level(verdict, confidence, coverage)

    return {
        "policy_version": policy.policy_version,
        "rules_version": record.rules_version,
        "verdict": verdict,
        "failure_cause": cause,
        "confidence": confidence,
        "coverage": coverage,
        "uncertainty": uncertainty,
        "assurance_level": assurance_level,
    }


def attach_derivation(record, policy):
    """`derive()` then hand the account to evidence.py's Phase 3 slot
    (`with_derivation_account`) — the only place a record's derivation
    account is ever filled. Returns a NEW `EvidenceRecord`; `record` is
    never mutated (VAE-A6)."""
    account = derive(record, policy)
    return evidence.with_derivation_account(record, account)


if __name__ == "__main__":
    policy = build_derivation_policy(1, coverage_moderate_min_fraction=0.5,
                                      coverage_strong_min_fraction=0.9)

    def rec(items):
        r = evidence.build_evidence_record("artifact:a1", 1)
        for it in items:
            r = evidence.append_item(r, it)
        return r

    def item(rule, source, result, kind, level="structural"):
        return evidence.build_evidence_item(rule, "artifact:a1", source, result, kind, level)

    # -- determinism: identical body -> byte-identical account -------------
    body = rec([item("r1", "s1", "pass", "independent"),
                item("r2", "s2", "pass", "independent", level="semantic")])
    acc1 = derive(body, policy)
    acc2 = derive(body, policy)
    assert acc1 == acc2
    assert acc1["verdict"] == VERDICT_PASSED
    assert acc1["failure_cause"] is None

    # item order must not change the outcome (only content-hash cares about order)
    body_reordered = rec([item("r2", "s2", "pass", "independent", level="semantic"),
                          item("r1", "s1", "pass", "independent")])
    acc_reordered = derive(body_reordered, policy)
    assert acc_reordered["verdict"] == acc1["verdict"]
    # refs are item-index-based so they legitimately differ across reorderings;
    # the confidence/coverage LEVELS (the actual outcome) must not (interpretation
    # call 7: order is meaningful for evidence.py's content-hash, not for derivation).
    for dim in DIMENSIONS:
        assert acc_reordered["confidence"][dim]["level"] == acc1["confidence"][dim]["level"]
    assert acc_reordered["coverage"]["level"] == acc1["coverage"]["level"]
    assert acc_reordered["coverage"]["established"] == acc1["coverage"]["established"]
    assert acc_reordered["coverage"]["total"] == acc1["coverage"]["total"]

    # -- contribution-kind effects (VAE/02 §5) ------------------------------
    single = rec([item("r1", "s1", "pass", "independent")])
    assert derive(single, policy)["confidence"]["structural"]["level"] == "weak"

    corroborated = rec([item("r1", "s1", "pass", "independent"),
                        item("r1", "s2", "pass", "corroborating")])
    assert derive(corroborated, policy)["confidence"]["structural"]["level"] == "strong"

    conflicted = rec([item("r1", "s1", "pass", "independent"),
                      item("r1", "s2", "fail", "conflicting")])
    conf_acc = derive(conflicted, policy)
    assert conf_acc["confidence"]["structural"]["level"] == "conflicted"
    assert conf_acc["verdict"] == VERDICT_FAILED
    assert conf_acc["failure_cause"] == CONTRADICTORY_EVIDENCE
    # conflicted is strictly below a single item alone
    assert (CONFIDENCE_LEVELS.index("conflicted") <
            CONFIDENCE_LEVELS.index(derive(single, policy)["confidence"]["structural"]["level"]))

    redundant = rec([item("r1", "s1", "pass", "independent"),
                     item("r1", "s1", "pass", "redundant")])
    assert derive(redundant, policy)["confidence"]["structural"]["level"] == "weak"  # no change

    missing_only = rec([item("r1", None, "not_run", "missing")])
    missing_acc = derive(missing_only, policy)
    assert missing_acc["confidence"]["structural"]["level"] == "none"  # caps coverage, not confidence
    assert missing_acc["coverage"]["level"] == "none"
    assert missing_acc["verdict"] == VERDICT_FAILED
    assert missing_acc["failure_cause"] == EVIDENCE_INSUFFICIENCY
    assert len(missing_acc["uncertainty"]) == 1
    assert missing_acc["uncertainty"][0]["reason"] == "missing_evidence"

    # missing alongside established evidence caps coverage but not confidence
    mixed = rec([item("r1", "s1", "pass", "independent"),
                item("r1", "s2", "pass", "corroborating"),
                item("r2", None, "not_run", "missing", level="semantic")])
    mixed_acc = derive(mixed, policy)
    assert mixed_acc["confidence"]["structural"]["level"] == "strong"
    assert mixed_acc["coverage"]["established"] == 1
    assert mixed_acc["coverage"]["total"] == 2
    assert mixed_acc["verdict"] == VERDICT_FAILED  # missing still degrades to a definite fail

    # -- all five assurance levels reachable --------------------------------
    high = rec([item("r1", "s1", "pass", "independent"),
               item("r1", "s2", "pass", "corroborating"),
               item("r2", "s3", "pass", "independent", level="execution"),
               item("r2", "s4", "pass", "corroborating", level="execution"),
               item("r3", "s5", "pass", "independent", level="semantic"),
               item("r3", "s6", "pass", "corroborating", level="semantic"),
               item("r4", "s7", "pass", "independent", level="system"),
               item("r4", "s8", "pass", "corroborating", level="system")])
    assert derive(high, policy)["assurance_level"] == VERIFIED_HIGH

    moderate = rec([item("r1", "s1", "pass", "independent"),
                   item("r1", "s2", "pass", "corroborating"),
                   item("r2", "s3", "pass", "independent", level="execution")])
    mod_acc = derive(moderate, policy)
    assert mod_acc["assurance_level"] == VERIFIED_MODERATE

    low = rec([item("r1", "s1", "pass", "independent")])
    assert derive(low, policy)["assurance_level"] == VERIFIED_LOW

    assert derive(conflicted, policy)["assurance_level"] == VERIFICATION_FAILED
    assert UNVERIFIED == "Unverified"  # pre-verdict state; not a derive() output, named for completeness
    assert set(ASSURANCE_LEVELS) == {VERIFIED_HIGH, VERIFIED_MODERATE, VERIFIED_LOW,
                                      UNVERIFIED, VERIFICATION_FAILED}

    # -- all five failure causes reachable and correctly classified ---------
    empty_body = rec([])
    assert derive(empty_body, policy)["failure_cause"] == EVIDENCE_INSUFFICIENCY
    exec_fail = rec([item("r1", "s1", "execution_failure", "independent")])
    assert derive(exec_fail, policy)["failure_cause"] == EXECUTION_FAILURE
    verif_fail = rec([item("r1", "s1", "fail", "independent")])
    assert derive(verif_fail, policy)["failure_cause"] == VERIFICATION_FAILURE
    inconclusive = rec([item("r1", "s1", "ambiguous", "independent")])
    assert derive(inconclusive, policy)["failure_cause"] == INCONCLUSIVE_VERIFICATION
    assert derive(missing_only, policy)["failure_cause"] == EVIDENCE_INSUFFICIENCY
    assert derive(conflicted, policy)["failure_cause"] == CONTRADICTORY_EVIDENCE

    # -- uncertainty explicit and separate from confidence -------------------
    assert "uncertainty" in mixed_acc and "confidence" in mixed_acc
    assert mixed_acc["uncertainty"] != mixed_acc["confidence"]
    # high dimensional confidence can coexist with uncertainty (§6)
    high_with_gap = rec([item("r1", "s1", "pass", "independent"),
                         item("r1", "s2", "pass", "corroborating"),
                         item("r2", None, "not_run", "missing", level="semantic")])
    gap_acc = derive(high_with_gap, policy)
    assert gap_acc["confidence"]["structural"]["level"] == "strong"
    assert len(gap_acc["uncertainty"]) == 1

    # -- traceability: every ref resolves to a real item index (VAE-A10) ----
    for dim in DIMENSIONS:
        for idx in mixed_acc["confidence"][dim]["refs"]:
            assert 0 <= idx < len(mixed.items)
    for stmt in mixed_acc["uncertainty"]:
        for idx in stmt["refs"]:
            assert 0 <= idx < len(mixed.items)

    # -- Phase 1+2 integration: attach_derivation fills evidence.py's slot --
    attached = attach_derivation(single, policy)
    assert attached.derivation_account == derive(single, policy)
    assert attached.items == single.items  # items untouched
    assert single.derivation_account is None  # original never mutated

    # re-derivation from an account-bearing record matches the stored account (VAE-A1)
    assert derive(attached, policy) == attached.derivation_account

    # slot already filled is refused, not silently overwritten
    try:
        attach_derivation(attached, policy)
        raise SystemExit("re-attaching a derivation account accepted")
    except evidence.DerivationAccountRefusedError:
        pass

    # unknown verification level refused loud
    bad_level = evidence.build_evidence_item("r1", "artifact:a1", "s1", "pass",
                                              "independent", "not_a_level")
    try:
        derive(rec([bad_level]), policy)
        raise SystemExit("unknown verification level accepted")
    except UnknownVerificationLevelError:
        pass

    # malformed policy refused loud
    for bad in (dict(coverage_moderate_min_fraction=0, coverage_strong_min_fraction=0.9),
                dict(coverage_moderate_min_fraction=0.9, coverage_strong_min_fraction=0.5)):
        try:
            build_derivation_policy(1, **bad)
            raise SystemExit("malformed policy accepted: " + repr(bad))
        except MalformedDerivationPolicyError:
            pass

    print("derivation selftest ok")
