"""SGPE Admission Compiler (SGPE/02; SGPE/05 §4/§8 implementation
contract). The gate between "authored" and "in force": transforms a
position-stamped policy set into a validated, totally-decided, immutable
candidate Policy Snapshot, or a rejection that changes nothing (AC-3).

**Pure function of three inputs (AC-2, §2):** catalog position P, the
compile vocabulary (always `store.vocabulary_as_of(P)` -- never an
independent free parameter, since additive lineage makes "newest at P"
the only sound choice), and an explicit `compiler_ruleset_version` (this
module implements exactly one: `CURRENT_COMPILER_RULESET_VERSION`; R4
means old manifests always recompile under their OWN recorded version,
never silently upgraded).

**8-stage pipeline (§4), fail-stop across stages, all-findings-within-a-
stage:** Assembly -> Vocabulary -> Scope & modifier -> Dependency ->
Totality -> Conflict -> Construction -> Readiness. Implemented as
`compile_snapshot()`.

**Two implementation-forced decisions, both documented at point of use
below, per §5/§11's demand that closed-grammar growth arrive WITH its own
decidability rule:**

1. Resource selector overlap = exact string equality OR either side is
   the literal wildcard `"*"`. Phase 1 left selectors as opaque strings;
   this is the minimal decidable semantics that makes overlap analysis
   possible at all without a glob/path parser nobody asked for.
2. Condition overlap ("non-disjointness") is decided structurally only
   for same-fact `Comparison`/`SetMembership` pairs (eq/ne/in/not_in
   matrix, plus numeric-range lt/lte/gt/gte interval overlap) --
   `_conditions_provably_disjoint()`. Anything this cannot structurally
   prove disjoint (mismatched facts, `BooleanComposition`, an
   unrecognized op combination, or simply no condition at all) is
   conservatively treated as an OVERLAPPING pair and handed to the 3-rule
   decision below -- never silently assumed safe. Crucially, "treated as
   overlapping" is NOT "treated as decided": the 3-rule procedure
   (`_decide_pair`) still independently rejects the pair as
   `UNDECIDABLE_CONFLICT` if scope/effect precedence cannot separate it
   (AC-5). Overlap detection and conflict decision are deliberately two
   separate, independently-failing steps.

**Operation-vocabulary convention:** SGPE/00 §9 says "each domain declares
its own operations," but Phase 1's `Vocabulary.operations` is one flat
term set (never redesigned here -- extending it to a real per-domain
shape was unnecessary for Phase 1's needs and remains unnecessary now).
This module adopts the minimal convention that makes totality/vocabulary
checks meaningful without touching that shape: operation terms are
namespaced `"{domain}.{operation}"` strings within the existing flat set.
An empty `vocabulary.operations` set makes operation-membership checks
vacuous (nothing declared yet, nothing to violate) -- domains-only
vocabularies compile exactly as they did as Phase 1 test fixtures.

**Corruption vs. authoring errors (§9):** every error Finding carries an
`error_class` of `"corruption"` (stage 2 vocabulary-term failures, stage 4
vocabulary-version-ahead) or `"authoring"` (everything else) -- these are
genuinely impossible through the public Store API (PS-8 additivity, the
Store's own vocabulary-version check) and only reachable through a
corrupted append log, so mislabeling them as authoring mistakes would send
a human to fix the wrong thing.

**Never implements:** the Evaluator, Resolver, or Grant Ledger; no runtime
decisions, no enforcement, no approval workflow. Grants never reach this
module (§10) -- there is no code path here that can see the Grant Ledger
at all."""
from dataclasses import dataclass
import hashlib
import json

from . import events as events_mod
from . import manifest as manifest_mod
from .condition import BooleanComposition, Comparison, SetMembership
from .store import PolicyStore

CURRENT_COMPILER_RULESET_VERSION = 1
SUPPORTED_COMPILER_RULESET_VERSIONS = (1,)

# SGPE/00 §5's fixed total precedence order, restricted to the three
# scopes the Store holds (request-grant lives in the Grant Ledger, never
# compiled -- §10).
SCOPE_RANK = {"system": 0, "project": 1, "user": 2}

# SGPE/00 §6 rule 2: deny-overrides. Higher number wins among permission-
# shaped effects (LIMIT is a different answer shape entirely, handled by
# rule 3, never compared against these).
EFFECT_PRIORITY = {"DENY": 3, "REQUIRE_APPROVAL": 2, "ALLOW": 1}

ERROR = "error"
WARNING = "warning"

CORRUPTION = "corruption"
AUTHORING = "authoring"

STAGE_ASSEMBLY = "assembly"
STAGE_VOCABULARY = "vocabulary"
STAGE_SCOPE_MODIFIER = "scope_modifier"
STAGE_DEPENDENCY = "dependency"
STAGE_TOTALITY = "totality"
STAGE_CONFLICT = "conflict"
STAGE_CONSTRUCTION = "construction"
STAGE_READINESS = "readiness"

VOCAB_DOMAIN_UNRESOLVED = "vocabulary_domain_unresolved"
VOCAB_OPERATION_UNRESOLVED = "vocabulary_operation_unresolved"
VOCAB_FACT_UNRESOLVED = "vocabulary_fact_unresolved"
FINAL_ILLEGAL_SCOPE = "final_illegal_scope"
FINAL_CONTRADICTED = "final_contradicted"
VOCAB_VERSION_AHEAD = "vocabulary_version_ahead_of_compile"
TOTALITY_GAP = "totality_gap"
UNDECIDABLE_CONFLICT = "undecidable_conflict"

SHADOWED = "shadowed_by_precedence"
STALE_VOCABULARY = "stale_vocabulary_version"

DECIDED_BY_SCOPE = "scope-precedence"
DECIDED_BY_DENY_OVERRIDES = "deny-overrides"
DECIDED_BY_MIN_LIMIT = "minimum-limit"


class CompilerRefusal(Exception):
    """Base for compiler.py refusals."""


class MalformedCompileInputError(CompilerRefusal):
    """The (catalog position, compiler ruleset version) input to
    `compile_snapshot()` failed a basic contract check -- a caller error,
    not a policy defect (§2: these are the only two free inputs;
    vocabulary version is always derived from position, never chosen)."""


class UnsupportedCompilerRulesetVersionError(CompilerRefusal):
    """Asked to compile under a compiler ruleset version this build does
    not implement (R4: old manifests recompile under their RECORDED
    ruleset version, which must still be one this code knows how to run)."""


class ActivationRefusedError(CompilerRefusal):
    """`activate()`/`rollback()` was asked to activate a result that is
    not a zero-error "compiled" verdict (AC-7's precondition)."""


class RegenerationMismatchError(CompilerRefusal):
    """R5's standing oracle failed: regenerating a manifest's inputs did
    not reproduce its recorded content hash -- a Store-integrity or
    Compiler-regression signal, never silently ignored."""


@dataclass(frozen=True)
class Finding:
    stage: str
    severity: str        # ERROR or WARNING
    error_class: object  # CORRUPTION or AUTHORING for errors; None for warnings
    code: str
    message: str
    citations: tuple  # tuple of citation triples: ((scope, name), version, rule_id_or_None)
    witness: object    # None, or a small JSON-shaped dict describing a concrete overlap instance


def _citation(did, version, rule_id=None):
    return (did, version, rule_id)


def _finding_sort_key(finding):
    # repr(), not the raw tuples: citations mix str/int/None and dicts
    # aren't orderable -- reprs give a total, deterministic order (R3)
    # without risking a heterogeneous-type comparison at sort time.
    return (finding.stage, finding.severity, finding.code, repr(finding.citations), repr(finding.witness),
            finding.message)


@dataclass(frozen=True)
class CompileReport:
    outcome: str  # "compiled" or "rejected"
    catalog_position: int
    vocabulary_version: int
    compiler_ruleset_version: int
    manifest_echo: tuple  # ((scope, name), version) pairs, canonical order
    errors: tuple    # tuple of Finding, severity == ERROR
    warnings: tuple  # tuple of Finding, severity == WARNING
    content_hash: object  # None if rejected; else the candidate snapshot's content hash


@dataclass(frozen=True)
class IndexEntry:
    domain: str
    operation: str
    scope: str
    resource_selector: str
    effect_kind: str
    effect_value: object
    condition: object  # None or a condition.py node
    final: bool
    citation: tuple     # ((scope, name), version, rule_id) -- AC-6's embedded traceability
    decided_by: tuple   # tuple of DECIDED_BY_* markers this entry was ever judged under (empty if uncontested)
    shadows: tuple      # tuple of citation triples this entry's precedence beat


@dataclass(frozen=True)
class CompiledSnapshot:
    catalog_position: int
    vocabulary_version: int
    compiler_ruleset_version: int
    document_refs: tuple    # ((scope, name), version) pairs, canonical order
    entries: tuple          # tuple of IndexEntry, canonical order
    declared_facts: tuple   # (((domain, operation), tuple_of_fact_names), ...), canonical order -- Phase 3 input
    content_hash: str


@dataclass(frozen=True)
class CompileResult:
    outcome: str  # "compiled" or "rejected"
    report: CompileReport
    snapshot: object  # CompiledSnapshot, or None on rejection (AC-3, AC-7: unregistered until activation)


# -- serialization (deterministic; used for the content hash and for the --
# -- policy.compiled/policy.rejected event payloads) ------------------------

def _citation_to_list(citation):
    return [list(citation[0]), citation[1], citation[2]]


def finding_to_dict(finding):
    return {
        "stage": finding.stage, "severity": finding.severity, "error_class": finding.error_class,
        "code": finding.code, "message": finding.message,
        "citations": [_citation_to_list(c) for c in finding.citations], "witness": finding.witness,
    }


def report_to_dict(report):
    return {
        "outcome": report.outcome, "catalog_position": report.catalog_position,
        "vocabulary_version": report.vocabulary_version,
        "compiler_ruleset_version": report.compiler_ruleset_version,
        "manifest_echo": [[list(did), version] for did, version in report.manifest_echo],
        "errors": [finding_to_dict(f) for f in report.errors],
        "warnings": [finding_to_dict(f) for f in report.warnings],
        "content_hash": report.content_hash,
    }


def _entry_to_dict(entry):
    from . import condition as condition_mod
    return {
        "domain": entry.domain, "operation": entry.operation, "scope": entry.scope,
        "resource_selector": entry.resource_selector, "effect_kind": entry.effect_kind,
        "effect_value": entry.effect_value,
        "condition": condition_mod.to_dict(entry.condition) if entry.condition is not None else None,
        "final": entry.final, "citation": _citation_to_list(entry.citation),
        "decided_by": list(entry.decided_by), "shadows": [_citation_to_list(c) for c in entry.shadows],
    }


def snapshot_to_dict(snapshot):
    return {
        "catalog_position": snapshot.catalog_position, "vocabulary_version": snapshot.vocabulary_version,
        "compiler_ruleset_version": snapshot.compiler_ruleset_version,
        "document_refs": [[list(did), version] for did, version in snapshot.document_refs],
        "entries": [_entry_to_dict(e) for e in snapshot.entries],
        "declared_facts": [[[key[0], key[1]], list(names)] for key, names in snapshot.declared_facts],
    }


def _content_hash(position, vocabulary_version, ruleset_version, document_refs, entries, declared_facts_tuple):
    payload = {
        "catalog_position": position, "vocabulary_version": vocabulary_version,
        "compiler_ruleset_version": ruleset_version,
        "document_refs": [[list(did), version] for did, version in document_refs],
        "entries": [_entry_to_dict(e) for e in entries],
        "declared_facts": [[[key[0], key[1]], list(names)] for key, names in declared_facts_tuple],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# -- selector / condition overlap decidability (implementation-forced) -----

def _selectors_overlap(selector_a, selector_b):
    """Decision 1 (module docstring): exact match, or either side is the
    universal wildcard "*"."""
    return selector_a == selector_b or selector_a == "*" or selector_b == "*"


def _overlap_witness_selector(selector_a, selector_b):
    if selector_a == selector_b:
        return selector_a
    return selector_b if selector_a == "*" else selector_a


_RANGE_OPS = ("lt", "lte", "gt", "gte")


def _is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _interval(op, value):
    if op == "lt":
        return (float("-inf"), True, value, True)
    if op == "lte":
        return (float("-inf"), True, value, False)
    if op == "gt":
        return (value, True, float("inf"), True)
    return (value, False, float("inf"), True)  # "gte"


def _intervals_disjoint(iv_a, iv_b):
    lo_a, lo_a_open, hi_a, hi_a_open = iv_a
    lo_b, lo_b_open, hi_b, hi_b_open = iv_b
    if hi_a < lo_b or (hi_a == lo_b and (hi_a_open or lo_b_open)):
        return True
    if hi_b < lo_a or (hi_b == lo_a and (hi_b_open or lo_a_open)):
        return True
    return False


def _finite_constraint(node):
    """Reduce a Comparison(eq/ne) or SetMembership(in/not_in) node to a
    uniform ("in" | "not_in", finite value set) shape, or None if the
    node's op isn't one of these four (e.g. a range comparison)."""
    if isinstance(node, Comparison):
        if node.op == "eq":
            return ("in", {node.value})
        if node.op == "ne":
            return ("not_in", {node.value})
        return None
    if isinstance(node, SetMembership):
        return (node.op, set(node.values))
    return None


def _same_fact_disjoint(node_a, node_b):
    if (isinstance(node_a, Comparison) and node_a.op in _RANGE_OPS and _is_numeric(node_a.value)
            and isinstance(node_b, Comparison) and node_b.op in _RANGE_OPS and _is_numeric(node_b.value)):
        return _intervals_disjoint(_interval(node_a.op, node_a.value), _interval(node_b.op, node_b.value))

    constraint_a, constraint_b = _finite_constraint(node_a), _finite_constraint(node_b)
    if constraint_a is not None and constraint_b is not None:
        kind_a, values_a = constraint_a
        kind_b, values_b = constraint_b
        if kind_a == "in" and kind_b == "in":
            return values_a.isdisjoint(values_b)
        if kind_a == "in" and kind_b == "not_in":
            return values_a.issubset(values_b)
        if kind_a == "not_in" and kind_b == "in":
            return values_b.issubset(values_a)
        # not_in vs not_in: unbounded value domain -- two finite exclusion
        # sets always leave shared values outside both. Never provably disjoint.
        return False

    return False  # mixed range/finite (or any op this matrix doesn't cover) -- not provably disjoint


def _conditions_provably_disjoint(condition_a, condition_b):
    """Decision 2 (module docstring). Conservative and structural: proves
    disjointness only for same-fact Comparison/SetMembership pairs; every
    other shape (no condition, mismatched fact, BooleanComposition, or an
    unrecognized op combination) is NOT provably disjoint -- handed to the
    3-rule decision stage, never silently assumed safe."""
    if condition_a is None or condition_b is None:
        return False  # an unconditional side matches everything -- never disjoint
    single_a = condition_a if isinstance(condition_a, (Comparison, SetMembership)) else None
    single_b = condition_b if isinstance(condition_b, (Comparison, SetMembership)) else None
    if single_a is None or single_b is None or single_a.fact != single_b.fact:
        return False
    return _same_fact_disjoint(single_a, single_b)


def _walk_fact_names(condition):
    if condition is None:
        return ()
    if isinstance(condition, (Comparison, SetMembership)):
        return (condition.fact,)
    if isinstance(condition, BooleanComposition):
        names = []
        for operand in condition.operands:
            names.extend(_walk_fact_names(operand))
        return tuple(names)
    return ()


def _effects_equal(effect_a, effect_b):
    return effect_a.kind == effect_b.kind and effect_a.value == effect_b.value


def _targets_overlap(target_a, target_b):
    return (target_a.domain == target_b.domain and target_a.operation == target_b.operation
            and _selectors_overlap(target_a.resource_selector, target_b.resource_selector))


# -- stage 2: vocabulary validation -----------------------------------------

def _check_vocabulary(assembled, vocabulary):
    findings = []
    for did, version, document in assembled:
        for rule in document.rules:
            if rule.target.domain not in vocabulary.domains:
                findings.append(Finding(
                    STAGE_VOCABULARY, ERROR, CORRUPTION, VOCAB_DOMAIN_UNRESOLVED,
                    "rule targets a domain absent from the compile vocabulary -- impossible under "
                    "PS-8 additivity; indicates Store-integrity corruption, not an authoring error",
                    (_citation(did, version, rule.rule_id),), {"domain": rule.target.domain}))
                continue
            operation_term = rule.target.domain + "." + rule.target.operation
            if vocabulary.operations and operation_term not in vocabulary.operations:
                findings.append(Finding(
                    STAGE_VOCABULARY, ERROR, CORRUPTION, VOCAB_OPERATION_UNRESOLVED,
                    "rule targets an operation absent from the compile vocabulary",
                    (_citation(did, version, rule.rule_id),),
                    {"domain": rule.target.domain, "operation": rule.target.operation}))
            for fact in _walk_fact_names(rule.condition):
                if fact not in vocabulary.fact_names:
                    findings.append(Finding(
                        STAGE_VOCABULARY, ERROR, CORRUPTION, VOCAB_FACT_UNRESOLVED,
                        "rule condition references a fact name absent from the compile vocabulary",
                        (_citation(did, version, rule.rule_id),), {"fact": fact}))
    return sorted(findings, key=_finding_sort_key)


# -- stage 3: scope & modifier legality --------------------------------------

def _check_scope_and_modifier(assembled):
    legality_findings = []
    final_rules = []
    for did, version, document in assembled:
        for rule in document.rules:
            if not rule.final:
                continue
            if document.header.scope != "system":
                legality_findings.append(Finding(
                    STAGE_SCOPE_MODIFIER, ERROR, AUTHORING, FINAL_ILLEGAL_SCOPE,
                    "`final` is legal at system scope only (SGPE/00 §6)",
                    (_citation(did, version, rule.rule_id),), {"scope": document.header.scope}))
                continue
            final_rules.append((did, version, rule))
    if legality_findings:
        # a final-legality violation makes "which final rules are legitimate"
        # itself unclear -- report every legality finding, don't also run
        # the contradiction check over an already-invalid final set.
        return sorted(legality_findings, key=_finding_sort_key)

    contradiction_findings = []
    for f_did, f_version, f_rule in final_rules:
        for did, version, document in assembled:
            if document.header.scope == "system":
                continue  # only a HIGHER scope can "contradict" a system final rule
            for rule in document.rules:
                if not _targets_overlap(f_rule.target, rule.target):
                    continue
                if _effects_equal(f_rule.effect, rule.effect):
                    continue
                contradiction_findings.append(Finding(
                    STAGE_SCOPE_MODIFIER, ERROR, AUTHORING, FINAL_CONTRADICTED,
                    "a higher-scope rule contradicts a system-scope `final` rule",
                    (_citation(f_did, f_version, f_rule.rule_id), _citation(did, version, rule.rule_id)),
                    {"domain": f_rule.target.domain, "operation": f_rule.target.operation}))
    return sorted(contradiction_findings, key=_finding_sort_key)


# -- stage 4: dependency validation ------------------------------------------

def _check_dependency(assembled, vocabulary):
    findings = []
    for did, version, document in assembled:
        if document.header.vocabulary_version > vocabulary.version:
            findings.append(Finding(
                STAGE_DEPENDENCY, ERROR, CORRUPTION, VOCAB_VERSION_AHEAD,
                "document references a vocabulary version newer than the compile vocabulary -- "
                "impossible through the Store's own append checks; indicates Store-integrity corruption",
                (_citation(did, version, None),),
                {"document_vocabulary_version": document.header.vocabulary_version,
                 "compile_vocabulary_version": vocabulary.version}))
    return sorted(findings, key=_finding_sort_key)


# -- stage 5: totality (INV-12) ----------------------------------------------

def _check_totality(assembled, vocabulary):
    covered = set()
    for did, version, document in assembled:
        if document.header.scope != "system":
            continue
        for rule in document.rules:
            if rule.target.resource_selector == "*":
                covered.add((rule.target.domain, rule.target.operation))
    findings = []
    for operation_term in sorted(vocabulary.operations):
        domain, _, operation = operation_term.partition(".")
        if (domain, operation) not in covered:
            findings.append(Finding(
                STAGE_TOTALITY, ERROR, AUTHORING, TOTALITY_GAP,
                "system-default scope has no universal (resource selector '*') rule for this "
                "domain/operation -- INV-12 requires the system scope to answer every declared operation",
                (), {"domain": domain, "operation": operation}))
    return findings


# -- stage 6: conflict detection ---------------------------------------------

def _decide_pair(scope_a, effect_a, citation_a, scope_b, effect_b, citation_b):
    """Apply SGPE/00 §6's closed 3-rule procedure verbatim. Returns
    (winner_citation, loser_citation, decided_by, real_shadow) or None if
    undecidable. `real_shadow` is False when the pair is "decided" only
    because both sides already agree (nothing is actually eclipsed)."""
    rank_a, rank_b = SCOPE_RANK[scope_a], SCOPE_RANK[scope_b]
    if rank_a != rank_b:
        # rule 1: scope precedence -- always decides, regardless of effect shape
        return (citation_a, citation_b, DECIDED_BY_SCOPE, True) if rank_a > rank_b \
            else (citation_b, citation_a, DECIDED_BY_SCOPE, True)

    is_limit_a, is_limit_b = effect_a.kind == "LIMIT", effect_b.kind == "LIMIT"
    if is_limit_a != is_limit_b:
        return None  # mixed answer shapes (permission vs. limit) -- the procedure doesn't cover this

    if is_limit_a and is_limit_b:
        value_a, value_b = effect_a.value, effect_b.value
        if not _is_numeric(value_a) or not _is_numeric(value_b):
            return None  # rule 3 requires comparable numeric limits
        if value_a == value_b:
            return citation_a, citation_b, DECIDED_BY_MIN_LIMIT, False
        return (citation_a, citation_b, DECIDED_BY_MIN_LIMIT, True) if value_a < value_b \
            else (citation_b, citation_a, DECIDED_BY_MIN_LIMIT, True)

    # rule 2: deny-overrides among permission-shaped effects
    priority_a, priority_b = EFFECT_PRIORITY[effect_a.kind], EFFECT_PRIORITY[effect_b.kind]
    if priority_a == priority_b:
        return citation_a, citation_b, DECIDED_BY_DENY_OVERRIDES, False
    return (citation_a, citation_b, DECIDED_BY_DENY_OVERRIDES, True) if priority_a > priority_b \
        else (citation_b, citation_a, DECIDED_BY_DENY_OVERRIDES, True)


def _record_decision(decisions, citation, decided_by):
    decisions.setdefault(citation, {"decided_by": set(), "shadows": set()})["decided_by"].add(decided_by)


def _detect_conflicts(assembled):
    all_rules = []
    for did, version, document in assembled:
        for rule in document.rules:
            all_rules.append((did, version, document.header.scope, rule))
    all_rules.sort(key=lambda t: (t[0], t[1], t[3].rule_id))

    groups = {}
    for entry in all_rules:
        rule = entry[3]
        groups.setdefault((rule.target.domain, rule.target.operation), []).append(entry)

    errors = []
    warnings = []
    decisions = {}

    for key in sorted(groups):
        entries = groups[key]
        for i in range(len(entries)):
            did_a, ver_a, scope_a, rule_a = entries[i]
            for j in range(i + 1, len(entries)):
                did_b, ver_b, scope_b, rule_b = entries[j]
                if not _selectors_overlap(rule_a.target.resource_selector, rule_b.target.resource_selector):
                    continue
                if _conditions_provably_disjoint(rule_a.condition, rule_b.condition):
                    continue

                citation_a = _citation(did_a, ver_a, rule_a.rule_id)
                citation_b = _citation(did_b, ver_b, rule_b.rule_id)
                decision = _decide_pair(scope_a, rule_a.effect, citation_a, scope_b, rule_b.effect, citation_b)
                if decision is None:
                    errors.append(Finding(
                        STAGE_CONFLICT, ERROR, AUTHORING, UNDECIDABLE_CONFLICT,
                        "overlapping rule pair cannot be decided by the SGPE/00 §6 three-rule "
                        "procedure (scope precedence / deny-overrides / minimum-limit)",
                        (citation_a, citation_b),
                        {"domain": key[0], "operation": key[1],
                         "resource": _overlap_witness_selector(rule_a.target.resource_selector,
                                                                rule_b.target.resource_selector)}))
                    continue

                winner, loser, decided_by, real_shadow = decision
                _record_decision(decisions, winner, decided_by)
                _record_decision(decisions, loser, decided_by)
                if real_shadow:
                    decisions[winner]["shadows"].add(loser)
                    warnings.append(Finding(
                        STAGE_CONFLICT, WARNING, None, SHADOWED,
                        "rule fully eclipsed by precedence -- kept in the snapshot but never wins",
                        (winner, loser), {"decided_by": decided_by}))

    return sorted(errors, key=_finding_sort_key), decisions, sorted(warnings, key=_finding_sort_key)


# -- non-blocking diagnostics -------------------------------------------------

def _check_stale_vocabulary(assembled, vocabulary):
    findings = []
    for did, version, document in assembled:
        if document.header.vocabulary_version < vocabulary.version:
            findings.append(Finding(
                STAGE_CONSTRUCTION, WARNING, None, STALE_VOCABULARY,
                "document authored against an older vocabulary version than the compile vocabulary",
                (_citation(did, version, None),),
                {"document_vocabulary_version": document.header.vocabulary_version,
                 "compile_vocabulary_version": vocabulary.version}))
    return sorted(findings, key=_finding_sort_key)


# -- stage 7: construction ----------------------------------------------------

def _construct_snapshot(assembled, decisions, position, vocabulary, compiler_ruleset_version):
    entries = []
    declared_facts = {}
    for did, version, document in assembled:
        for rule in document.rules:
            citation = _citation(did, version, rule.rule_id)
            decision = decisions.get(citation, {})
            entries.append(IndexEntry(
                domain=rule.target.domain, operation=rule.target.operation, scope=document.header.scope,
                resource_selector=rule.target.resource_selector, effect_kind=rule.effect.kind,
                effect_value=rule.effect.value, condition=rule.condition, final=rule.final,
                citation=citation, decided_by=tuple(sorted(decision.get("decided_by", ()))),
                shadows=tuple(sorted(decision.get("shadows", ())))))
            key = (rule.target.domain, rule.target.operation)
            declared_facts.setdefault(key, set()).update(_walk_fact_names(rule.condition))

    entries.sort(key=lambda e: (e.domain, e.operation, e.scope, e.resource_selector, e.citation))
    declared_facts_tuple = tuple((key, tuple(sorted(names))) for key, names in sorted(declared_facts.items()))
    document_refs = tuple((did, version) for did, version, _ in assembled)

    content_hash = _content_hash(position, vocabulary.version, compiler_ruleset_version, document_refs,
                                  entries, declared_facts_tuple)
    return CompiledSnapshot(catalog_position=position, vocabulary_version=vocabulary.version,
                             compiler_ruleset_version=compiler_ruleset_version, document_refs=document_refs,
                             entries=tuple(entries), declared_facts=declared_facts_tuple,
                             content_hash=content_hash)


# -- top-level pipeline (stage 1, 8, and orchestration) -----------------------

def _finish(outcome, position, vocabulary, ruleset_version, manifest_echo, errors, warnings, snapshot, bus):
    report = CompileReport(
        outcome=outcome, catalog_position=position, vocabulary_version=vocabulary.version,
        compiler_ruleset_version=ruleset_version, manifest_echo=manifest_echo,
        errors=tuple(sorted(errors, key=_finding_sort_key)),
        warnings=tuple(sorted(warnings, key=_finding_sort_key)),
        content_hash=(snapshot.content_hash if snapshot is not None else None))
    if bus is not None:
        event_name = "policy.compiled" if outcome == "compiled" else "policy.rejected"
        events_mod.emit(bus, event_name, event_name + ":" + str(position) + ":" + str(ruleset_version),
                         "sgpe/compile", report_to_dict(report))
    return CompileResult(outcome=outcome, report=report, snapshot=snapshot)


def compile_snapshot(store, position, compiler_ruleset_version=CURRENT_COMPILER_RULESET_VERSION, bus=None):
    """Snapshot = f(P, vocabulary version, compiler ruleset version) --
    AC-2/R1. Returns a `CompileResult`; a rejection changes nothing (AC-3):
    no Store append happens anywhere in this function."""
    if not isinstance(store, PolicyStore):
        raise MalformedCompileInputError("compiler.store_not_a_policy_store:" + repr(store))
    if not isinstance(position, int) or isinstance(position, bool) or position < 0:
        raise MalformedCompileInputError("compiler.bad_catalog_position:" + repr(position))
    if position > store.catalog_position():
        raise MalformedCompileInputError("compiler.position_beyond_catalog:" + repr(position))
    if compiler_ruleset_version not in SUPPORTED_COMPILER_RULESET_VERSIONS:
        raise UnsupportedCompilerRulesetVersionError(
            "compiler.unsupported_ruleset_version:" + repr(compiler_ruleset_version))

    vocabulary = store.vocabulary_as_of(position)
    if vocabulary is None:
        raise MalformedCompileInputError("compiler.no_vocabulary_as_of_position:" + repr(position))

    # -- stage 1: assembly ----------------------------------------------
    assembled = []
    for did, version in store.documents_as_of(position):
        if store.is_deprecated(did, version):
            continue  # honors deprecation markers recorded at or before P (SGPE/02 §4 stage 1)
        assembled.append((did, version, store.document_version(did, version)))
    assembled.sort(key=lambda t: (t[0], t[1]))
    manifest_echo = tuple((did, version) for did, version, _ in assembled)

    def reject(errors, warnings=()):
        return _finish("rejected", position, vocabulary, compiler_ruleset_version, manifest_echo,
                        errors, warnings, None, bus)

    # -- stage 2: vocabulary validation -----------------------------------
    vocabulary_errors = _check_vocabulary(assembled, vocabulary)
    if vocabulary_errors:
        return reject(vocabulary_errors)

    # -- stage 3: scope & modifier legality --------------------------------
    scope_errors = _check_scope_and_modifier(assembled)
    if scope_errors:
        return reject(scope_errors)

    # -- stage 4: dependency validation ------------------------------------
    dependency_errors = _check_dependency(assembled, vocabulary)
    if dependency_errors:
        return reject(dependency_errors)

    # -- stage 5: totality (INV-12) ----------------------------------------
    totality_errors = _check_totality(assembled, vocabulary)
    if totality_errors:
        return reject(totality_errors)

    # -- stage 6: conflict detection ----------------------------------------
    conflict_errors, decisions, shadow_warnings = _detect_conflicts(assembled)
    if conflict_errors:
        return reject(conflict_errors, shadow_warnings)

    warnings = list(shadow_warnings)
    warnings.extend(_check_stale_vocabulary(assembled, vocabulary))

    # -- stage 7: construction ------------------------------------------------
    snapshot = _construct_snapshot(assembled, decisions, position, vocabulary, compiler_ruleset_version)

    # -- stage 8: readiness verdict ---------------------------------------------
    return _finish("compiled", position, vocabulary, compiler_ruleset_version, manifest_echo, (), warnings,
                    snapshot, bus)


# -- R5 standing regeneration oracle -----------------------------------------

def regenerate(store, recorded_manifest):
    """R5: recompiling any manifest's own recorded inputs (its catalog
    position, under its own recorded compiler ruleset version) must
    reproduce its recorded content hash byte-identically. Raises
    `RegenerationMismatchError` otherwise -- a permanent, standing oracle
    for both compiler correctness and artifact integrity (AC-9)."""
    result = compile_snapshot(store, recorded_manifest.catalog_position, recorded_manifest.compiler_ruleset_version)
    if result.outcome != "compiled":
        raise RegenerationMismatchError("compiler.regeneration_rejected:" + repr(recorded_manifest))
    if result.snapshot.content_hash != recorded_manifest.content_hash:
        raise RegenerationMismatchError(
            "compiler.regeneration_hash_mismatch:expected=" + recorded_manifest.content_hash +
            ":got=" + result.snapshot.content_hash)
    return result.snapshot


# -- activation and rollback (§7) ---------------------------------------------

def activate(store, result, bus=None):
    """The activation act (SGPE/00 §4, SGPE/02 §7). Precondition (AC-7):
    `result` must be a zero-error "compiled" verdict. Appends the
    manifest, then the activation fact (snapshot version assigned HERE,
    monotonic, next after the latest recorded activation fact -- never at
    compile time), then announces `policy.activated`.

    Implementation note on "atomic" (§7 says "one Store append"): SGPE/01
    §5 already lists manifest and activation-fact appends as two distinct
    catalog entry kinds, so this performs two sequential Store appends,
    not one physical write. Atomicity here means: nothing else runs
    between them, and if the second append fails, the first (the
    manifest) remains a fully valid "admitted, not yet in-force" record
    per SGPE/01 §4's own lifecycle -- never a corrupt or ambiguous state.
    D6 still holds: a snapshot is only "active" once its activation fact
    exists, and until then nothing observes it as such."""
    if result.outcome != "compiled" or result.report.errors:
        raise ActivationRefusedError("compiler.activation_requires_zero_error_compiled_result")
    snapshot = result.snapshot
    previous_activations = store.activations()
    previous_version = previous_activations[-1].snapshot_version if previous_activations else None
    next_version = (previous_version or 0) + 1

    manifest = manifest_mod.build_manifest(
        next_version, snapshot.catalog_position, snapshot.vocabulary_version,
        snapshot.compiler_ruleset_version, snapshot.document_refs, snapshot.content_hash)
    store.append_manifest(manifest)
    activation_fact = manifest_mod.build_activation(previous_version, next_version)
    store.append_activation(activation_fact)

    if bus is not None:
        events_mod.emit(bus, "policy.activated", "activated:" + str(next_version), "sgpe/snapshot",
                         {"previous_snapshot_version": previous_version, "snapshot_version": next_version,
                          "catalog_position": snapshot.catalog_position})
    return manifest, activation_fact


def rollback(store, old_manifest, bus=None):
    """Rollback (§7): recompile at the OLD manifest's own recorded inputs
    (position + its own compiler ruleset version -- R4), then activate
    forward as a new version. There is no "reactivate vN" primitive;
    versions only ever move forward."""
    result = compile_snapshot(store, old_manifest.catalog_position, old_manifest.compiler_ruleset_version)
    if result.outcome != "compiled" or result.report.errors:
        raise ActivationRefusedError("compiler.rollback_recompile_rejected:" + repr(old_manifest))
    return activate(store, result, bus=bus)


if __name__ == "__main__":
    from . import document as doc_mod
    from . import rule as rule_mod
    from . import vocabulary as vocabulary_mod
    from .bus_double import BusDouble
    from .storage_double import StorageDouble

    def _doc(name, scope, rules, vocab_version=2, reason="authoring"):
        prov = doc_mod.build_provenance("alice", "epoch-0", reason)
        header = doc_mod.build_header(scope, name, ("execution",), prov, vocab_version, 1)
        return doc_mod.build_document(header, rules)

    store = PolicyStore(StorageDouble())
    v1 = vocabulary_mod.default_v1()
    v2 = vocabulary_mod.evolve(v1, operations=("execution.run",))
    store.append_vocabulary(v1)
    store.append_vocabulary(v2)

    baseline_rule = rule_mod.build_rule(
        "r1", rule_mod.build_target("execution", "run", "*"), rule_mod.build_effect("ALLOW"))
    store.append_document(_doc("baseline", "system", (baseline_rule,)))

    result = compile_snapshot(store, store.catalog_position())
    assert result.outcome == "compiled", result.report.errors
    assert result.report.errors == ()
    assert len(result.snapshot.entries) == 1

    # determinism: recompiling the same position twice is byte-identical
    result2 = compile_snapshot(store, store.catalog_position())
    assert result.snapshot.content_hash == result2.snapshot.content_hash
    assert report_to_dict(result.report) == report_to_dict(result2.report)

    # activation
    bus = BusDouble()
    manifest, activation_fact = activate(store, result, bus=bus)
    assert activation_fact.snapshot_version == 1
    assert bus.messages("policy.activated")[0]["payload"]["snapshot_version"] == 1

    # R5 regeneration oracle
    regenerated = regenerate(store, manifest)
    assert regenerated.content_hash == manifest.content_hash

    print("compiler selftest ok")
