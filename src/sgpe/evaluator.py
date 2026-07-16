"""SGPE Evaluator (SGPE/03; SGPE/05 §8 implementation contract). Runtime
policy evaluation as a pure, deterministic, clock-free, I/O-free function:

    Decision = f(snapshot version, grant-slice position,
                 evaluation ruleset version, canonical Question)

The Evaluator retrieves decisions already made -- at compile time by the
Compiler (totally-decided snapshot, AC-3/AC-5), at authoring time by
humans, at approval time by grantors. It never resolves conflicts, weighs
rules, or exercises judgment (EV-3).

**Never implements (EV-2):** reading the Policy Store (no Store reference
exists anywhere in this module), invoking the Compiler, fetching grants
(the slice arrives as a stamped input value), enforcement, approval
collection, or persistence (EV-10: the caller-owned memo dict is the only
state, and it is semantically invisible, EV-8).

**Two outcome classes, never confused (EV-6):** `Decision` (ALLOW / DENY /
REQUIRE_APPROVAL / LIMIT -- policy answers) and `IllPosedVerdict` (the
Question itself is defective -- a protocol error indicting the caller,
emitted as `policy.illposed`, never recorded as a DENY). Bad *stamps* or
slice objects, by contrast, are caller contract bugs and raise
`MalformedEvaluationInputError` (mirroring the Compiler's input checks).

**Implementation-forced decisions, per SGPE/03's demand for precision at
point of use (all four are additive refinements inside the frozen
architecture, not redesigns):**

1. Ask signature (SGPE/03 §4/§6) = sha256 of the canonical JSON of
   {principal, domain, operation, resource}. Facts are excluded (they
   change between the REQUIRE_APPROVAL and the re-ask under the same
   frozen Effective Policy -- including them would void every grant on
   any usage tick); request id is excluded (scope binding is the Grant
   Ledger's Phase 4 axis, not the signature's).
2. Required facts for a well-formed Question (SGPE/03 §3 "completeness is
   checkable before evaluation begins") = the union of the snapshot's
   declared fact names over EVERY (domain, question.operation) key --
   the question's own domain plus each sibling domain declaring the same
   operation. Static and checkable upfront: constraint attachment (§4)
   evaluates those sibling domains' conditions, so their facts must be
   present regardless of which effect ultimately wins. Exact set
   equality: an undeclared extra fact is non-canonical (two byte
   representations of one logical Question) and ill-posed.
3. Binding-constraint attachment (SGPE/03 §4) is domain-blind: for each
   sibling domain sharing the question's operation, the same retrieval
   runs, and the sibling's winning entry is attached iff its effect kind
   is LIMIT. No hardcoded limit-domain list -- a new limit-shaped domain
   attaches with zero Evaluator change (INV-11). A sibling domain whose
   entries all fail to match binds nothing and is skipped.
4. Range comparisons (lt/lte/gt/gte) require both sides numeric
   (bool excluded, mirroring the Compiler's `_is_numeric`); any other
   pairing is an ill-posed `incomparable_condition` -- never a silent
   False, which would be a determinism-preserving but honesty-violating
   guess about what the author meant.

**Trust boundary:** the snapshot's total-decidedness is trusted absolutely
(SGPE/03 §11). Where that trust is *checkable for free* it is checked:
a matched set with no undominated winner, or divergent-effect co-winners,
raises `SnapshotIntegrityError` -- a Compiler-regression signal, never
silently ordered."""
from dataclasses import dataclass
import hashlib
import json

from . import events as events_mod
from .compiler import CompiledSnapshot
from .condition import BooleanComposition, Comparison, SetMembership

CURRENT_EVALUATION_RULESET_VERSION = 1
SUPPORTED_EVALUATION_RULESET_VERSIONS = (1,)

GRANT = "grant"
REVOCATION = "revocation"

# ill-posed codes (SGPE/03 §9's enumeration, made concrete)
ILLPOSED_NOT_A_QUESTION = "not_a_question"
ILLPOSED_NON_CANONICAL = "non_canonical_facts"
ILLPOSED_UNKNOWN_ACTION = "unknown_action"
ILLPOSED_MISSING_FACTS = "missing_declared_facts"
ILLPOSED_UNDECLARED_FACTS = "undeclared_facts"
ILLPOSED_INCOMPARABLE = "incomparable_condition"

_SCALAR_TYPES = (str, int, float, type(None))  # bool checked separately


class EvaluatorRefusal(Exception):
    """Base for evaluator.py refusals."""


class MalformedEvaluationInputError(EvaluatorRefusal):
    """A stamp, snapshot, grant slice, or memo argument failed a basic
    caller-contract check -- a caller bug, never an ill-posed Question
    (those are the Question's own defects and get a verdict, not a
    raise)."""


class UnsupportedEvaluationRulesetVersionError(EvaluatorRefusal):
    """Asked to evaluate under an evaluation ruleset version this build
    does not implement (EV-9: replays run under the RECORDED version,
    which must be one this code knows how to run)."""


class SnapshotIntegrityError(EvaluatorRefusal):
    """The trusted total-decidedness of the snapshot failed a free
    runtime check: no undominated winner among matched entries, divergent
    co-winner effects, or a totality hole (no entry matched at all for a
    declared operation). A Compiler-regression or artifact-corruption
    signal -- never guessed around (SGPE/03 §9: every lenient path is a
    determinism leak)."""


class MalformedGrantRecordError(EvaluatorRefusal):
    """A grant-slice record failed structural validation."""


class MalformedQuestionError(EvaluatorRefusal):
    """`build_question()` was given structurally invalid parts. Note the
    boundary: build-time garbage raises (the caller never HAD a Question);
    a built-but-defective Question handed to `evaluate()` yields an
    ill-posed verdict (the protocol error class, EV-6)."""


# -- the canonical Question (SGPE/03 §3) --------------------------------------

@dataclass(frozen=True)
class Question:
    subsystem: str
    request_id: str
    principal: str
    domain: str
    operation: str
    resource: str
    facts: tuple  # ((name, value), ...) sorted by name -- canonical by construction


def _validate_scalar(label, value):
    if isinstance(value, bool):
        return
    if not isinstance(value, _SCALAR_TYPES):
        raise MalformedQuestionError("evaluator.fact_value_not_scalar:" + label + ":" + repr(value))


def build_question(subsystem, request_id, principal, domain, operation, resource, facts):
    """The only constructor that yields a canonical Question: sorted
    unique fact names, scalar values, non-empty identity strings. One
    byte representation per logical Question (SGPE/03 §3)."""
    for label, value in (("subsystem", subsystem), ("request_id", request_id), ("principal", principal),
                          ("domain", domain), ("operation", operation), ("resource", resource)):
        if not isinstance(value, str) or not value:
            raise MalformedQuestionError("evaluator.bad_" + label + ":" + repr(value))
    if not isinstance(facts, dict):
        raise MalformedQuestionError("evaluator.facts_not_a_mapping:" + repr(facts))
    fact_items = []
    for name in sorted(facts):
        if not isinstance(name, str) or not name:
            raise MalformedQuestionError("evaluator.bad_fact_name:" + repr(name))
        _validate_scalar(name, facts[name])
        fact_items.append((name, facts[name]))
    return Question(subsystem=subsystem, request_id=request_id, principal=principal, domain=domain,
                     operation=operation, resource=resource, facts=tuple(fact_items))


def question_to_dict(question):
    return {
        "subsystem": question.subsystem, "request_id": question.request_id,
        "principal": question.principal, "domain": question.domain, "operation": question.operation,
        "resource": question.resource, "facts": [[name, value] for name, value in question.facts],
    }


def question_from_dict(data):
    return build_question(data["subsystem"], data["request_id"], data["principal"], data["domain"],
                           data["operation"], data["resource"], dict((n, v) for n, v in data["facts"]))


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def question_hash(question):
    return hashlib.sha256(_canonical_json(question_to_dict(question)).encode()).hexdigest()


def ask_signature(question):
    """Forced decision 1 (module docstring): the canonical identity a
    grant must cover -- principal + action + resource, no facts, no
    request id."""
    return hashlib.sha256(_canonical_json({
        "principal": question.principal, "domain": question.domain,
        "operation": question.operation, "resource": question.resource,
    }).encode()).hexdigest()


# -- the grant slice (SGPE/03 §6; records arrive Resolver-supplied) ------------

@dataclass(frozen=True)
class GrantRecord:
    kind: str            # GRANT or REVOCATION
    grant_id: str
    ask_signature: str   # for a revocation: the signature of the grant it revokes


def build_grant_record(kind, grant_id, signature):
    if kind not in (GRANT, REVOCATION):
        raise MalformedGrantRecordError("evaluator.unknown_grant_record_kind:" + repr(kind))
    for label, value in (("grant_id", grant_id), ("ask_signature", signature)):
        if not isinstance(value, str) or not value:
            raise MalformedGrantRecordError("evaluator.bad_" + label + ":" + repr(value))
    return GrantRecord(kind=kind, grant_id=grant_id, ask_signature=signature)


# -- outcomes (SGPE/03 §4, §9) --------------------------------------------------

@dataclass(frozen=True)
class Decision:
    effect_kind: str          # ALLOW / DENY / REQUIRE_APPROVAL / LIMIT
    effect_value: object      # None except LIMIT
    ask_signature: object     # str for REQUIRE_APPROVAL, else None
    constraints: tuple        # ((domain, value, citation), ...) -- binding ceilings, ALLOW only
    explanation: tuple        # canonical-ordered trace steps (JSON-shaped dicts)
    snapshot_version: int
    grant_slice_position: int
    evaluation_ruleset_version: int
    question_hash: str


@dataclass(frozen=True)
class IllPosedVerdict:
    code: str
    detail: str
    snapshot_version: int
    grant_slice_position: int
    evaluation_ruleset_version: int


def _citation_to_list(citation):
    return [list(citation[0]), citation[1], citation[2]]


def decision_to_dict(decision):
    return {
        "effect_kind": decision.effect_kind, "effect_value": decision.effect_value,
        "ask_signature": decision.ask_signature,
        "constraints": [[domain, value, _citation_to_list(citation)]
                        for domain, value, citation in decision.constraints],
        "explanation": [dict(step) for step in decision.explanation],
        "snapshot_version": decision.snapshot_version,
        "grant_slice_position": decision.grant_slice_position,
        "evaluation_ruleset_version": decision.evaluation_ruleset_version,
        "question_hash": decision.question_hash,
    }


def decision_bytes(decision):
    """The Decision's canonical byte form -- what EV-1/EV-7's
    "byte-identical" means, concretely."""
    return _canonical_json(decision_to_dict(decision)).encode()


def illposed_to_dict(verdict):
    return {
        "code": verdict.code, "detail": verdict.detail,
        "snapshot_version": verdict.snapshot_version,
        "grant_slice_position": verdict.grant_slice_position,
        "evaluation_ruleset_version": verdict.evaluation_ruleset_version,
    }


# -- condition evaluation (meaning of condition.py's closed grammar) ------------

def _is_numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _IncomparableCondition(Exception):
    """Internal: converted to an ill-posed verdict by evaluate()."""


def _condition_satisfied(node, fact_map):
    if isinstance(node, Comparison):
        fact_value = fact_map[node.fact]
        if node.op == "eq":
            return fact_value == node.value
        if node.op == "ne":
            return fact_value != node.value
        # forced decision 4: range ops require both sides numeric
        if not _is_numeric(fact_value) or not _is_numeric(node.value):
            raise _IncomparableCondition(
                "fact " + repr(node.fact) + " op " + node.op + ": non-numeric operand "
                + repr(fact_value) + " vs " + repr(node.value))
        if node.op == "lt":
            return fact_value < node.value
        if node.op == "lte":
            return fact_value <= node.value
        if node.op == "gt":
            return fact_value > node.value
        return fact_value >= node.value  # "gte" -- condition.py's grammar is closed
    if isinstance(node, SetMembership):
        contained = fact_map[node.fact] in node.values
        return contained if node.op == "in" else not contained
    # BooleanComposition -- evaluate EVERY operand (no short-circuit) so an
    # incomparable operand surfaces deterministically regardless of position.
    results = [_condition_satisfied(operand, fact_map) for operand in node.operands]
    if node.op == "and":
        return all(results)
    if node.op == "or":
        return any(results)
    return not results[0]  # "not"


# -- retrieval (SGPE/03 §7 steps 3-4: index match + winner) ----------------------

def _selector_matches(entry_selector, resource):
    return entry_selector == resource or entry_selector == "*"


def _match_and_win(snapshot, domain, operation, resource, fact_map):
    """Retrieve the winning entry for one (domain, operation) against a
    concrete resource + facts. Returns (winner, matched_citations,
    totality_fallback) -- retrieval only: precedence was decided at
    compile time and lives in the entries' `shadows` edges (EV-3)."""
    matched = [entry for entry in snapshot.entries
               if entry.domain == domain and entry.operation == operation
               and _selector_matches(entry.resource_selector, resource)
               and (entry.condition is None or _condition_satisfied(entry.condition, fact_map))]
    if not matched:
        raise SnapshotIntegrityError(
            "evaluator.totality_hole:" + domain + "." + operation + ":" + resource)

    shadowed = set()
    for entry in matched:
        shadowed.update(entry.shadows)
    winners = [entry for entry in matched if entry.citation not in shadowed]
    if not winners:
        raise SnapshotIntegrityError(
            "evaluator.no_undominated_winner:" + domain + "." + operation + ":" + resource)
    for entry in winners[1:]:
        if entry.effect_kind != winners[0].effect_kind or entry.effect_value != winners[0].effect_value:
            raise SnapshotIntegrityError(
                "evaluator.divergent_cowinners:" + repr(winners[0].citation) + ":" + repr(entry.citation))
    winner = winners[0]  # snapshot entries are canonical-ordered; co-winners agree on effect
    fallback = (winner.scope == "system" and winner.resource_selector == "*" and len(matched) == 1)
    return winner, tuple(entry.citation for entry in matched), fallback


# -- the Evaluator (SGPE/03 §7's 7-step lifecycle) --------------------------------

def _required_fact_names(snapshot, operation):
    """Forced decision 2: union of declared fact names over every
    (domain, operation) key sharing this operation."""
    required = set()
    for (domain, op), names in snapshot.declared_facts:
        if op == operation:
            required.update(names)
    return required


def _operation_domains(snapshot, operation):
    return sorted(domain for (domain, op), _ in snapshot.declared_facts if op == operation)


def _check_inputs(snapshot_version, snapshot, grant_slice_position, grant_slice,
                   evaluation_ruleset_version, memo):
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise MalformedEvaluationInputError("evaluator.bad_snapshot_version:" + repr(snapshot_version))
    if not isinstance(snapshot, CompiledSnapshot):
        raise MalformedEvaluationInputError("evaluator.snapshot_not_compiled:" + repr(snapshot))
    if (not isinstance(grant_slice_position, int) or isinstance(grant_slice_position, bool)
            or grant_slice_position < 0):
        raise MalformedEvaluationInputError(
            "evaluator.bad_grant_slice_position:" + repr(grant_slice_position))
    if not isinstance(grant_slice, tuple):
        raise MalformedEvaluationInputError("evaluator.grant_slice_not_a_tuple:" + repr(grant_slice))
    for record in grant_slice:
        if not isinstance(record, GrantRecord):
            raise MalformedEvaluationInputError("evaluator.grant_record_not_built:" + repr(record))
    if evaluation_ruleset_version not in SUPPORTED_EVALUATION_RULESET_VERSIONS:
        raise UnsupportedEvaluationRulesetVersionError(
            "evaluator.unsupported_ruleset_version:" + repr(evaluation_ruleset_version))
    if memo is not None and not isinstance(memo, dict):
        raise MalformedEvaluationInputError("evaluator.memo_not_a_dict:" + repr(memo))


def _ill_posed(code, detail, snapshot_version, grant_slice_position, ruleset_version, bus):
    verdict = IllPosedVerdict(code=code, detail=detail, snapshot_version=snapshot_version,
                               grant_slice_position=grant_slice_position,
                               evaluation_ruleset_version=ruleset_version)
    if bus is not None:
        events_mod.emit(bus, "policy.illposed",
                         "illposed:" + code + ":" + str(snapshot_version) + ":" + str(grant_slice_position),
                         "sgpe/evaluate", illposed_to_dict(verdict))
    return verdict


def evaluate(snapshot_version, snapshot, grant_slice_position, grant_slice, question,
              evaluation_ruleset_version=CURRENT_EVALUATION_RULESET_VERSION, bus=None, memo=None):
    """SGPE/03 §7's fixed lifecycle: [1 well-formedness] -> [2 memo probe]
    -> [3 index match] -> [4 final check] -> [5 grant overlay] ->
    [6 constraint attachment] -> [7 Decision + trace]. Returns a
    `Decision` or an `IllPosedVerdict` -- two outcome classes, never
    confused (EV-6). Pure in its stamped inputs (EV-1): no clock, no I/O
    reads, no randomness; the optional caller-owned `memo` dict is
    semantically invisible (EV-8) and stores Decisions only."""
    _check_inputs(snapshot_version, snapshot, grant_slice_position, grant_slice,
                   evaluation_ruleset_version, memo)

    def ill_posed(code, detail):
        return _ill_posed(code, detail, snapshot_version, grant_slice_position,
                           evaluation_ruleset_version, bus)

    # -- step 1: well-formedness (canonical form + completeness) ---------
    if not isinstance(question, Question):
        return ill_posed(ILLPOSED_NOT_A_QUESTION, repr(question))
    try:
        rebuilt = build_question(question.subsystem, question.request_id, question.principal,
                                  question.domain, question.operation, question.resource,
                                  dict(question.facts))
    except (MalformedQuestionError, TypeError, ValueError) as exc:
        return ill_posed(ILLPOSED_NON_CANONICAL, repr(exc))
    if rebuilt != question:
        # hand-built Question bypassing build_question's canonical order --
        # rejected, never silently normalized (SGPE/03 §3: silent
        # normalization would fork the memo key from the audit record)
        return ill_posed(ILLPOSED_NON_CANONICAL, "facts_not_in_canonical_order")

    declared_keys = {key for key, _ in snapshot.declared_facts}
    if (question.domain, question.operation) not in declared_keys:
        return ill_posed(ILLPOSED_UNKNOWN_ACTION, question.domain + "." + question.operation)

    supplied = {name for name, _ in question.facts}
    required = _required_fact_names(snapshot, question.operation)
    if required - supplied:
        return ill_posed(ILLPOSED_MISSING_FACTS, repr(sorted(required - supplied)))
    if supplied - required:
        return ill_posed(ILLPOSED_UNDECLARED_FACTS, repr(sorted(supplied - required)))

    # -- step 2: memo probe (EV-7's key: every answer-changing input) -----
    q_hash = question_hash(question)
    memo_key = (snapshot_version, grant_slice_position, evaluation_ruleset_version, q_hash)
    if memo is not None and memo_key in memo:
        decision = memo[memo_key]
        _emit_decided(bus, decision)
        return decision

    fact_map = dict(question.facts)
    try:
        # -- step 3: index match + decided-precedence winner ---------------
        winner, matched_citations, fallback = _match_and_win(
            snapshot, question.domain, question.operation, question.resource, fact_map)

        effect_kind, effect_value = winner.effect_kind, winner.effect_value
        explanation = [{
            "step": "index",
            "matched": [_citation_to_list(c) for c in matched_citations],
            "winner": _citation_to_list(winner.citation),
            "decided_by": list(winner.decided_by),
            "final": winner.final,
            "totality_fallback": fallback,
        }]

        # -- steps 4-5: final check, then exact-signature grant overlay ----
        signature = ask_signature(question) if effect_kind == "REQUIRE_APPROVAL" else None
        if not winner.final and effect_kind == "REQUIRE_APPROVAL":
            revoked = {record.grant_id for record in grant_slice if record.kind == REVOCATION}
            applicable = [record for record in grant_slice
                          if record.kind == GRANT and record.ask_signature == signature
                          and record.grant_id not in revoked]
            if applicable:
                grant = applicable[0]  # slice is ledger-ordered; first covering unrevoked grant
                effect_kind, effect_value, signature = "ALLOW", None, None
                explanation.append({
                    "step": "grant",
                    "grant_id": grant.grant_id,
                    "ledger_position": grant_slice_position,
                    "overrode": _citation_to_list(winner.citation),
                })

        # -- step 6: binding-constraint attachment (ALLOW only, §4) --------
        constraints = []
        if effect_kind == "ALLOW":
            for domain in _operation_domains(snapshot, question.operation):
                if domain == question.domain:
                    continue
                try:
                    ceiling, _, _ = _match_and_win(snapshot, domain, question.operation,
                                                    question.resource, fact_map)
                except SnapshotIntegrityError:
                    continue  # forced decision 3: an unmatched sibling domain binds nothing
                if ceiling.effect_kind != "LIMIT":
                    continue
                constraints.append((domain, ceiling.effect_value, ceiling.citation))
                explanation.append({
                    "step": "constraint", "domain": domain, "value": ceiling.effect_value,
                    "citation": _citation_to_list(ceiling.citation),
                })
    except _IncomparableCondition as exc:
        return ill_posed(ILLPOSED_INCOMPARABLE, str(exc))

    # -- step 7: assemble, emit, memoize, return ---------------------------
    decision = Decision(
        effect_kind=effect_kind, effect_value=effect_value, ask_signature=signature,
        constraints=tuple(constraints), explanation=tuple(explanation),
        snapshot_version=snapshot_version, grant_slice_position=grant_slice_position,
        evaluation_ruleset_version=evaluation_ruleset_version, question_hash=q_hash)
    _emit_decided(bus, decision)
    if memo is not None:
        memo[memo_key] = decision
    return decision


def _emit_decided(bus, decision):
    # emitted on memo hits too: each ask IS an evaluation, and eviction
    # must be invisible on the event stream as well (EV-8/EV-10);
    # duplicate delivery is the bus's at-least-once problem (SGPE/03 §9)
    if bus is not None:
        events_mod.emit(bus, "policy.decided",
                         "decided:" + str(decision.snapshot_version) + ":"
                         + str(decision.grant_slice_position) + ":" + decision.question_hash,
                         "sgpe/evaluate", decision_to_dict(decision))


if __name__ == "__main__":
    from . import document as doc_mod
    from . import rule as rule_mod
    from . import vocabulary as vocabulary_mod
    from .bus_double import BusDouble
    from .compiler import activate, compile_snapshot
    from .storage_double import StorageDouble
    from .store import PolicyStore

    store = PolicyStore(StorageDouble())
    v1 = vocabulary_mod.default_v1()
    v2 = vocabulary_mod.evolve(v1, operations=("execution.run", "token-budget.run"))
    store.append_vocabulary(v1)
    store.append_vocabulary(v2)

    prov = doc_mod.build_provenance("alice", "epoch-0", "authoring")
    header = doc_mod.build_header("system", "baseline", ("execution",), prov, 2, 1)
    rules = (
        rule_mod.build_rule("r1", rule_mod.build_target("execution", "run", "*"),
                             rule_mod.build_effect("REQUIRE_APPROVAL")),
        rule_mod.build_rule("r2", rule_mod.build_target("token-budget", "run", "*"),
                             rule_mod.build_effect("LIMIT", 1000)),
    )
    store.append_document(doc_mod.build_document(header, rules))

    result = compile_snapshot(store, store.catalog_position())
    assert result.outcome == "compiled"
    activate(store, result)
    snapshot = result.snapshot

    question = build_question("kernel", "req-1", "alice", "execution", "run", "repo-x", {})
    bus = BusDouble()

    # REQUIRE_APPROVAL with ask signature
    d1 = evaluate(1, snapshot, 0, (), question, bus=bus)
    assert d1.effect_kind == "REQUIRE_APPROVAL" and d1.ask_signature == ask_signature(question)
    assert bus.messages("policy.decided")[0]["payload"]["effect_kind"] == "REQUIRE_APPROVAL"

    # grant overlay flips it to ALLOW, with the token-budget ceiling attached
    grant = build_grant_record(GRANT, "g1", ask_signature(question))
    d2 = evaluate(1, snapshot, 1, (grant,), question)
    assert d2.effect_kind == "ALLOW" and d2.constraints[0][:2] == ("token-budget", 1000)

    # revocation beats grant
    revocation = build_grant_record(REVOCATION, "g1", ask_signature(question))
    d3 = evaluate(1, snapshot, 2, (grant, revocation), question)
    assert d3.effect_kind == "REQUIRE_APPROVAL"

    # determinism + memo byte-identity
    memo = {}
    a = evaluate(1, snapshot, 0, (), question, memo=memo)
    b = evaluate(1, snapshot, 0, (), question, memo=memo)
    assert a is b and decision_bytes(a) == decision_bytes(d1)

    # ill-posed is a distinct class, never a DENY
    bad = build_question("kernel", "req-1", "alice", "execution", "fly", "repo-x", {})
    verdict = evaluate(1, snapshot, 0, (), bad)
    assert isinstance(verdict, IllPosedVerdict) and verdict.code == ILLPOSED_UNKNOWN_ACTION

    print("evaluator selftest ok")
