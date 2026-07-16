"""SGPE Phase 3 suite — Evaluator (SGPE/03, SGPE/05 §8 implementation
contract: "pure evaluation; 7-step lifecycle; two outcome classes; exact-
signature grants; binding-constraint attachment; memo keyed by every
answer-changing input" / forbidden: "Store reads; compilation; grant
fetching; conflict resolution; enforcement; persistence" / guarantees
EV-1..EV-10).

Every invariant EV-1..EV-10 gets one or more explicit tests, named by
invariant, plus: each lifecycle step (happy + failure), every ill-posed
code, grant overlay mechanics (exact match, revocation-beats-grant,
final immunity), constraint attachment across sibling limit domains,
condition-grammar evaluation semantics, byte-stable explanations, and
the structural no-Store / no-Compiler boundary."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sgpe import compiler as compiler_mod
from sgpe import condition as condition_mod
from sgpe import document as document_mod
from sgpe import evaluator as evaluator_mod
from sgpe import rule as rule_mod
from sgpe import vocabulary as vocabulary_mod
from sgpe.bus_double import BusDouble
from sgpe.evaluator import (
    Decision,
    GrantRecord,
    IllPosedVerdict,
    MalformedEvaluationInputError,
    MalformedGrantRecordError,
    MalformedQuestionError,
    Question,
    SnapshotIntegrityError,
    UnsupportedEvaluationRulesetVersionError,
    ask_signature,
    build_grant_record,
    build_question,
    decision_bytes,
    evaluate,
    question_from_dict,
    question_hash,
    question_to_dict,
)
from sgpe.storage_double import StorageDouble
from sgpe.store import PolicyStore


# -- shared builders ----------------------------------------------------------

def _rule(rule_id, domain, operation, selector, effect_kind, value=None, condition=None, final=False):
    target = rule_mod.build_target(domain, operation, selector)
    effect = rule_mod.build_effect(effect_kind, value)
    return rule_mod.build_rule(rule_id, target, effect, condition=condition, final=final)


def _doc(name, scope, rules, vocab_version=2, domain_refs=("execution",)):
    prov = document_mod.build_provenance("alice", "epoch-0", "authoring")
    header = document_mod.build_header(scope, name, domain_refs, prov, vocab_version, 1)
    return document_mod.build_document(header, rules)


def _compiled(docs, op_terms=("execution.run",), fact_names=()):
    """Store -> compile -> activate; returns the CompiledSnapshot. The
    Evaluator never touches the Store afterwards -- tests hand it the
    snapshot value only (EV-2)."""
    store = PolicyStore(StorageDouble())
    v1 = vocabulary_mod.default_v1()
    store.append_vocabulary(v1)
    store.append_vocabulary(vocabulary_mod.evolve(v1, operations=op_terms, fact_names=fact_names or None))
    for doc in docs:
        store.append_document(doc)
    result = compiler_mod.compile_snapshot(store, store.catalog_position())
    assert result.outcome == "compiled", result.report.errors
    compiler_mod.activate(store, result)
    return result.snapshot


def _q(domain="execution", operation="run", resource="repo-x", facts=None, principal="alice",
        request_id="req-1", subsystem="kernel"):
    return build_question(subsystem, request_id, principal, domain, operation, resource, facts or {})


def _baseline_snapshot(effect_kind="ALLOW", value=None, final=False, condition=None):
    return _compiled((_doc("baseline", "system",
                            (_rule("r1", "execution", "run", "*", effect_kind, value,
                                   condition=condition, final=final),)),))


class EvaluatorTestCase(unittest.TestCase):
    def assertDecision(self, outcome, effect_kind):
        self.assertIsInstance(outcome, Decision)
        self.assertEqual(outcome.effect_kind, effect_kind)
        return outcome

    def assertIllPosed(self, outcome, code):
        self.assertIsInstance(outcome, IllPosedVerdict)
        self.assertEqual(outcome.code, code)
        return outcome


# -- the canonical Question (SGPE/03 §3) ---------------------------------------

class QuestionModel(EvaluatorTestCase):
    def test_build_question_sorts_facts_canonically(self):
        q = _q(facts={"b": 2, "a": 1, "c": None})
        self.assertEqual(q.facts, (("a", 1), ("b", 2), ("c", None)))

    def test_round_trip(self):
        q = _q(facts={"usage.tokens": 5, "region": "eu"})
        self.assertEqual(question_from_dict(question_to_dict(q)), q)

    def test_identity_fields_must_be_nonempty_strings(self):
        for field in ("subsystem", "request_id", "principal", "domain", "operation", "resource"):
            with self.assertRaises(MalformedQuestionError):
                _q(**{field: ""})

    def test_facts_must_be_a_mapping_of_scalars(self):
        with self.assertRaises(MalformedQuestionError):
            build_question("k", "r", "p", "execution", "run", "x", [("a", 1)])
        with self.assertRaises(MalformedQuestionError):
            _q(facts={"a": [1, 2]})
        with self.assertRaises(MalformedQuestionError):
            _q(facts={"": 1})

    def test_question_hash_is_content_addressed(self):
        self.assertEqual(question_hash(_q(facts={"a": 1})), question_hash(_q(facts={"a": 1})))
        self.assertNotEqual(question_hash(_q(facts={"a": 1})), question_hash(_q(facts={"a": 2})))

    def test_ask_signature_excludes_facts_and_request_id(self):
        base = ask_signature(_q(facts={}))
        self.assertEqual(ask_signature(_q(request_id="req-2", facts={})), base)
        self.assertNotEqual(ask_signature(_q(principal="bob")), base)
        self.assertNotEqual(ask_signature(_q(resource="repo-y")), base)


# -- EV-1: pure, byte-replayable, clock-free, I/O-free --------------------------

class EV1Purity(EvaluatorTestCase):
    def test_same_inputs_same_decision_bytes(self):
        snapshot = _baseline_snapshot("DENY")
        q = _q()
        a = evaluate(1, snapshot, 0, (), q)
        b = evaluate(1, snapshot, 0, (), q)
        self.assertEqual(decision_bytes(a), decision_bytes(b))
        self.assertEqual(a, b)

    def test_no_clock_no_io_no_randomness_in_source(self):
        source = inspect.getsource(evaluator_mod)
        for token in ("import time", "import datetime", "import random", "import os",
                       "import uuid", "open("):
            self.assertNotIn(token, source)

    def test_decision_carries_full_replay_stamps(self):
        snapshot = _baseline_snapshot()
        d = evaluate(7, snapshot, 3, (), _q())
        self.assertEqual((d.snapshot_version, d.grant_slice_position, d.evaluation_ruleset_version),
                          (7, 3, evaluator_mod.CURRENT_EVALUATION_RULESET_VERSION))
        self.assertEqual(d.question_hash, question_hash(_q()))


# -- EV-2: no Store, no Compiler invocation, no grant fetching ------------------

class EV2StructuralBoundary(EvaluatorTestCase):
    def test_module_never_references_the_store_or_compiles(self):
        source = inspect.getsource(evaluator_mod)
        self.assertNotIn("PolicyStore", source.split('if __name__ == "__main__":')[0])
        self.assertNotIn("compile_snapshot", source.split('if __name__ == "__main__":')[0])

    def test_evaluate_signature_takes_only_stamped_values(self):
        params = list(inspect.signature(evaluate).parameters)
        self.assertEqual(params, ["snapshot_version", "snapshot", "grant_slice_position", "grant_slice",
                                    "question", "evaluation_ruleset_version", "bus", "memo"])


# -- EV-3: retrieval, never judgment --------------------------------------------

class EV3Retrieval(EvaluatorTestCase):
    def test_compile_decided_precedence_is_inherited_not_rederived(self):
        # user DENY shadows system ALLOW at compile time; the Evaluator
        # returns the decided winner and surfaces the decided-by marker.
        snapshot = _compiled((
            _doc("baseline", "system", (_rule("r1", "execution", "run", "*", "ALLOW"),)),
            _doc("stricter", "user", (_rule("r2", "execution", "run", "*", "DENY"),)),
        ))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q()), "DENY")
        index_step = d.explanation[0]
        self.assertEqual(index_step["winner"], [["user", "stricter"], 1, "r2"])
        self.assertIn(compiler_mod.DECIDED_BY_SCOPE, index_step["decided_by"])

    def test_condition_selects_between_disjoint_rules(self):
        low = condition_mod.build_comparison("usage.tokens", "lt", 100)
        high = condition_mod.build_comparison("usage.tokens", "gte", 100)
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r0", "execution", "run", "*", "ALLOW"),
            _rule("r1", "execution", "run", "repo-x", "ALLOW", condition=low),
            _rule("r2", "execution", "run", "repo-x", "DENY", condition=high),
        )),), fact_names=("usage.tokens",))
        self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 50})), "ALLOW")
        self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 150})), "DENY")

    def test_totality_fallback_is_marked_and_cited(self):
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r0", "execution", "run", "*", "ALLOW"),
            _rule("r1", "execution", "run", "repo-x", "DENY"),
        )),))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q(resource="repo-other")), "ALLOW")
        self.assertTrue(d.explanation[0]["totality_fallback"])
        d2 = self.assertDecision(evaluate(1, snapshot, 0, (), _q(resource="repo-x")), "DENY")
        self.assertFalse(d2.explanation[0]["totality_fallback"])

    def test_snapshot_integrity_violations_raise_never_guess(self):
        # a conditional-only "default" leaves a runtime totality hole --
        # unreachable through an honest Compiler, but never guessed around
        cond = condition_mod.build_comparison("usage.tokens", "lt", 10)
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "ALLOW", condition=cond),)),),
            fact_names=("usage.tokens",))
        with self.assertRaises(SnapshotIntegrityError):
            evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 99}))


# -- EV-4: one effect + constraints + explanation + stamps ----------------------

class EV4DecisionShape(EvaluatorTestCase):
    def test_limit_domain_question_answers_in_ceilings(self):
        snapshot = _compiled((_doc("budget", "system",
                                     (_rule("r1", "token-budget", "run", "*", "LIMIT", 1000),),
                                     domain_refs=("token-budget",)),),
                              op_terms=("token-budget.run",))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q(domain="token-budget")), "LIMIT")
        self.assertEqual(d.effect_value, 1000)
        self.assertEqual(d.constraints, ())  # constraints attach to permission ALLOWs only

    def test_allow_carries_every_binding_ceiling_with_own_citation(self):
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "ALLOW"),
            _rule("r2", "token-budget", "run", "*", "LIMIT", 1000),
            _rule("r3", "retry-limit", "run", "*", "LIMIT", 3),
        )),), op_terms=("execution.run", "token-budget.run", "retry-limit.run"))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q()), "ALLOW")
        self.assertEqual(d.constraints, (
            ("retry-limit", 3, (("system", "baseline"), 1, "r3")),
            ("token-budget", 1000, (("system", "baseline"), 1, "r2")),
        ))
        constraint_steps = [s for s in d.explanation if s["step"] == "constraint"]
        self.assertEqual(len(constraint_steps), 2)

    def test_deny_and_require_approval_attach_no_constraints(self):
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "DENY"),
            _rule("r2", "token-budget", "run", "*", "LIMIT", 1000),
        )),), op_terms=("execution.run", "token-budget.run"))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q()), "DENY")
        self.assertEqual(d.constraints, ())

    def test_sibling_permission_domain_never_attaches(self):
        # constraint attachment is by winning effect KIND, not domain name
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "ALLOW"),
            _rule("r2", "shell", "run", "*", "DENY"),
        )),), op_terms=("execution.run", "shell.run"))
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q()), "ALLOW")
        self.assertEqual(d.constraints, ())

    def test_explanation_contains_matched_entries_and_winner_citation(self):
        snapshot = _baseline_snapshot("ALLOW")
        d = evaluate(1, snapshot, 0, (), _q())
        step = d.explanation[0]
        self.assertEqual(step["step"], "index")
        self.assertEqual(step["matched"], [[["system", "baseline"], 1, "r1"]])
        self.assertEqual(step["winner"], [["system", "baseline"], 1, "r1"])


# -- EV-5: exact-signature grants, final immunity --------------------------------

class EV5Grants(EvaluatorTestCase):
    def setUp(self):
        self.snapshot = _baseline_snapshot("REQUIRE_APPROVAL")
        self.question = _q()
        self.signature = ask_signature(self.question)

    def test_require_approval_emits_ask_signature(self):
        d = self.assertDecision(evaluate(1, self.snapshot, 0, (), self.question), "REQUIRE_APPROVAL")
        self.assertEqual(d.ask_signature, self.signature)

    def test_exact_matching_grant_flips_to_allow_with_trace(self):
        grant = build_grant_record("grant", "g1", self.signature)
        d = self.assertDecision(evaluate(1, self.snapshot, 4, (grant,), self.question), "ALLOW")
        self.assertIsNone(d.ask_signature)
        grant_step = d.explanation[1]
        self.assertEqual((grant_step["step"], grant_step["grant_id"], grant_step["ledger_position"]),
                          ("grant", "g1", 4))
        self.assertEqual(grant_step["overrode"], [["system", "baseline"], 1, "r1"])

    def test_signature_mismatch_never_partially_covers(self):
        other = build_grant_record("grant", "g1", ask_signature(_q(resource="repo-other")))
        self.assertDecision(evaluate(1, self.snapshot, 1, (other,), self.question), "REQUIRE_APPROVAL")

    def test_revocation_beats_grant(self):
        grant = build_grant_record("grant", "g1", self.signature)
        revocation = build_grant_record("revocation", "g1", self.signature)
        for slice_order in ((grant, revocation), (revocation, grant)):
            self.assertDecision(evaluate(1, self.snapshot, 2, slice_order, self.question),
                                 "REQUIRE_APPROVAL")

    def test_final_rules_are_immune_to_grants(self):
        snapshot = _baseline_snapshot("REQUIRE_APPROVAL", final=True)
        grant = build_grant_record("grant", "g1", self.signature)
        d = self.assertDecision(evaluate(1, snapshot, 1, (grant,), self.question), "REQUIRE_APPROVAL")
        self.assertTrue(d.explanation[0]["final"])
        self.assertEqual(len(d.explanation), 1)  # no grant step in the trace at all

    def test_grants_never_loosen_a_deny(self):
        snapshot = _baseline_snapshot("DENY")
        grant = build_grant_record("grant", "g1", self.signature)
        self.assertDecision(evaluate(1, snapshot, 1, (grant,), self.question), "DENY")

    def test_grant_records_are_validated(self):
        with self.assertRaises(MalformedGrantRecordError):
            build_grant_record("blessing", "g1", self.signature)
        with self.assertRaises(MalformedGrantRecordError):
            build_grant_record("grant", "", self.signature)
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(1, self.snapshot, 0, ({"kind": "grant"},), self.question)


# -- EV-6: ill-posed is a distinct outcome class ---------------------------------

class EV6IllPosed(EvaluatorTestCase):
    def setUp(self):
        self.snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "ALLOW",
                  condition=condition_mod.build_comparison("usage.tokens", "lt", 100)),
            _rule("r0", "execution", "run", "*", "DENY"),
        )),), fact_names=("usage.tokens",))

    def test_not_a_question(self):
        verdict = self.assertIllPosed(evaluate(1, self.snapshot, 0, (), "run repo-x"),
                                       evaluator_mod.ILLPOSED_NOT_A_QUESTION)
        self.assertNotIsInstance(verdict, Decision)

    def test_unknown_action(self):
        self.assertIllPosed(evaluate(1, self.snapshot, 0, (), _q(operation="fly", facts={})),
                             evaluator_mod.ILLPOSED_UNKNOWN_ACTION)

    def test_missing_declared_fact(self):
        self.assertIllPosed(evaluate(1, self.snapshot, 0, (), _q(facts={})),
                             evaluator_mod.ILLPOSED_MISSING_FACTS)

    def test_undeclared_extra_fact(self):
        self.assertIllPosed(
            evaluate(1, self.snapshot, 0, (), _q(facts={"usage.tokens": 5, "mood": "good"})),
            evaluator_mod.ILLPOSED_UNDECLARED_FACTS)

    def test_non_canonical_hand_built_question_rejected_not_normalized(self):
        crooked = Question(subsystem="kernel", request_id="req-1", principal="alice",
                            domain="execution", operation="run", resource="repo-x",
                            facts=(("usage.tokens", 5), ("usage.tokens", 5)))
        self.assertIllPosed(evaluate(1, self.snapshot, 0, (), crooked),
                             evaluator_mod.ILLPOSED_NON_CANONICAL)

    def test_incomparable_condition_fact_type(self):
        self.assertIllPosed(evaluate(1, self.snapshot, 0, (), _q(facts={"usage.tokens": "many"})),
                             evaluator_mod.ILLPOSED_INCOMPARABLE)

    def test_ill_posed_never_evaluated_and_never_a_deny(self):
        verdict = evaluate(1, self.snapshot, 0, (), _q(facts={}))
        self.assertFalse(hasattr(verdict, "effect_kind"))
        self.assertEqual(illposed_stamps(verdict), (1, 0, 1))

    def test_bad_stamps_raise_they_are_caller_bugs_not_ill_posed(self):
        q = _q(facts={"usage.tokens": 5})
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(0, self.snapshot, 0, (), q)
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(1, "not a snapshot", 0, (), q)
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(1, self.snapshot, -1, (), q)
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(1, self.snapshot, 0, [], q)
        with self.assertRaises(MalformedEvaluationInputError):
            evaluate(1, self.snapshot, 0, (), q, memo="cache")


def illposed_stamps(verdict):
    return (verdict.snapshot_version, verdict.grant_slice_position,
            verdict.evaluation_ruleset_version)


# -- EV-7 / EV-8: memoization ------------------------------------------------------

class EV7EV8Memoization(EvaluatorTestCase):
    def setUp(self):
        self.snapshot = _baseline_snapshot("REQUIRE_APPROVAL")
        self.question = _q()

    def test_memo_hit_returns_byte_identical_decision(self):
        memo = {}
        a = evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        b = evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        self.assertIs(a, b)
        self.assertEqual(decision_bytes(a), decision_bytes(b))

    def test_memo_key_contains_every_answer_changing_input(self):
        memo = {}
        evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        ((key, _),) = memo.items()
        self.assertEqual(key, (1, 0, evaluator_mod.CURRENT_EVALUATION_RULESET_VERSION,
                                question_hash(self.question)))

    def test_empty_slice_position_still_keys_the_memo(self):
        memo = {}
        evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        evaluate(1, self.snapshot, 5, (), self.question, memo=memo)
        self.assertEqual(len(memo), 2)  # same empty slice, different positions, different keys

    def test_eviction_is_semantically_invisible(self):
        memo = {}
        a = evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        memo.clear()
        b = evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        self.assertEqual(decision_bytes(a), decision_bytes(b))

    def test_no_memo_at_all_is_equally_legal(self):
        a = evaluate(1, self.snapshot, 0, (), self.question, memo=None)
        b = evaluate(1, self.snapshot, 0, (), self.question, memo={})
        self.assertEqual(decision_bytes(a), decision_bytes(b))

    def test_grant_slice_changes_reach_a_different_key(self):
        memo = {}
        signature = ask_signature(self.question)
        evaluate(1, self.snapshot, 0, (), self.question, memo=memo)
        d = evaluate(1, self.snapshot, 1, (build_grant_record("grant", "g1", signature),),
                      self.question, memo=memo)
        self.assertEqual(d.effect_kind, "ALLOW")
        self.assertEqual(len(memo), 2)

    def test_ill_posed_verdicts_are_never_memoized(self):
        memo = {}
        evaluate(1, self.snapshot, 0, (), "garbage", memo=memo)
        self.assertEqual(memo, {})


# -- EV-9: versioned evaluation semantics ------------------------------------------

class EV9RulesetVersion(EvaluatorTestCase):
    def test_unsupported_version_refused(self):
        snapshot = _baseline_snapshot()
        with self.assertRaises(UnsupportedEvaluationRulesetVersionError):
            evaluate(1, snapshot, 0, (), _q(), evaluation_ruleset_version=99)

    def test_every_decision_stamps_the_ruleset_version(self):
        snapshot = _baseline_snapshot()
        d = evaluate(1, snapshot, 0, (), _q())
        self.assertEqual(d.evaluation_ruleset_version, evaluator_mod.CURRENT_EVALUATION_RULESET_VERSION)
        self.assertIn(evaluator_mod.CURRENT_EVALUATION_RULESET_VERSION,
                       evaluator_mod.SUPPORTED_EVALUATION_RULESET_VERSIONS)


# -- EV-10: events, no persistence ---------------------------------------------------

class EV10Events(EvaluatorTestCase):
    def test_every_decision_is_a_policy_decided_event(self):
        bus = BusDouble()
        snapshot = _baseline_snapshot("DENY")
        d = evaluate(1, snapshot, 0, (), _q(), bus=bus)
        (event,) = bus.messages("policy.decided")
        self.assertEqual(event["payload"], evaluator_mod.decision_to_dict(d))

    def test_every_ill_posed_verdict_is_a_policy_illposed_event(self):
        bus = BusDouble()
        snapshot = _baseline_snapshot()
        verdict = evaluate(1, snapshot, 0, (), _q(operation="fly"), bus=bus)
        (event,) = bus.messages("policy.illposed")
        self.assertEqual(event["payload"], evaluator_mod.illposed_to_dict(verdict))
        self.assertEqual(bus.messages("policy.decided"), [])

    def test_memo_hits_still_announce_each_ask(self):
        bus = BusDouble()
        memo = {}
        snapshot = _baseline_snapshot()
        evaluate(1, snapshot, 0, (), _q(), bus=bus, memo=memo)
        evaluate(1, snapshot, 0, (), _q(), bus=bus, memo=memo)
        self.assertEqual(len(bus.messages("policy.decided")), 2)

    def test_evaluator_persists_nothing(self):
        # no module-level mutable state: the caller-owned memo is the only
        # state anywhere, and it lives with the caller
        for name, value in vars(evaluator_mod).items():
            if name.startswith("_") or callable(value) or isinstance(value, type):
                continue
            self.assertNotIsInstance(value, (dict, list, set),
                                      "module-level mutable state: " + name)


# -- condition-grammar evaluation semantics -------------------------------------

class ConditionSemantics(EvaluatorTestCase):
    def _snapshot_with(self, condition, fact_names):
        return _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "repo-x", "DENY", condition=condition),
            _rule("r0", "execution", "run", "*", "ALLOW"),
        )),), fact_names=fact_names)

    def test_set_membership(self):
        cond = condition_mod.build_set_membership("region", "in", ("us", "eu"))
        snapshot = self._snapshot_with(cond, ("region",))
        self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"region": "eu"})), "DENY")
        self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"region": "apac"})), "ALLOW")

    def test_boolean_composition_and_or_not(self):
        cond = condition_mod.build_boolean("and", (
            condition_mod.build_comparison("usage.tokens", "gte", 100),
            condition_mod.build_boolean("not", (
                condition_mod.build_set_membership("region", "in", ("us",)),)),
        ))
        snapshot = self._snapshot_with(cond, ("usage.tokens", "region"))
        self.assertDecision(
            evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 150, "region": "eu"})), "DENY")
        self.assertDecision(
            evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 150, "region": "us"})), "ALLOW")
        self.assertDecision(
            evaluate(1, snapshot, 0, (), _q(facts={"usage.tokens": 50, "region": "eu"})), "ALLOW")

    def test_incomparable_operand_surfaces_regardless_of_short_circuit_position(self):
        # "or" whose first operand is already True: a short-circuiting
        # evaluator would hide the second operand's type defect --
        # determinism requires it to surface (SGPE/03 §10: no order leaks)
        cond = condition_mod.build_boolean("or", (
            condition_mod.build_comparison("region", "eq", "eu"),
            condition_mod.build_comparison("usage.tokens", "lt", 100),
        ))
        snapshot = self._snapshot_with(cond, ("usage.tokens", "region"))
        self.assertIllPosed(
            evaluate(1, snapshot, 0, (), _q(facts={"region": "eu", "usage.tokens": "many"})),
            evaluator_mod.ILLPOSED_INCOMPARABLE)


# -- required facts across sibling domains (forced decision 2) --------------------

class RequiredFactsUnion(EvaluatorTestCase):
    def test_sibling_limit_domain_facts_are_required_upfront(self):
        cond = condition_mod.build_comparison("tier", "eq", "pro")
        snapshot = _compiled((_doc("baseline", "system", (
            _rule("r1", "execution", "run", "*", "ALLOW"),
            _rule("r2", "token-budget", "run", "*", "LIMIT", 1000, condition=cond),
            _rule("r3", "token-budget", "run", "*", "LIMIT", 100,
                  condition=condition_mod.build_comparison("tier", "ne", "pro")),
        )),), op_terms=("execution.run", "token-budget.run"), fact_names=("tier",))
        self.assertIllPosed(evaluate(1, snapshot, 0, (), _q(facts={})),
                             evaluator_mod.ILLPOSED_MISSING_FACTS)
        d = self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"tier": "pro"})), "ALLOW")
        self.assertEqual(d.constraints, (("token-budget", 1000, (("system", "baseline"), 1, "r2")),))
        d2 = self.assertDecision(evaluate(1, snapshot, 0, (), _q(facts={"tier": "free"})), "ALLOW")
        self.assertEqual(d2.constraints, (("token-budget", 100, (("system", "baseline"), 1, "r3")),))


if __name__ == "__main__":
    unittest.main()
