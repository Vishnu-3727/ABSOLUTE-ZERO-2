"""RO Phase 3 suite — RO/03-request-preparation.md, request preparation +
resolution/rendering (RO/05 §10 blueprint groups G3+G4). Covers: schema
registry append-only/duplicate/unknown; budget parent inheritance, sibling
accounting, exhaustion, infeasible-content, no-fresh-grants; context
selection/reduction table paths, content-hash dedup, relevance threshold,
size-class cap, empty-context floor for knowledge-demanding capabilities,
low-dependency empty-OK, stale/malformed RQM; capability matching + provider
selection candidate/eligible sets, exclusions, tie-break order, size-class
derivation boundaries; end-to-end `prepare()` from REASONING_APPROVED,
RO-P1/P2/P3/P8/P11/§12-tuple checks, budget-infeasible propagation;
renderer unknown-form/determinism/losslessness/provider-absence/mutated-
constraints; static AST scan of the five Phase 3 modules + renderer for
time/random/datetime imports.
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ro.decision_gate import DecisionRecord
from ro.records import build_capability, build_descriptor_row
from ro.schemas import (
    SchemaRegistry,
    DuplicateSchemaVersionError,
    UnknownSchemaError,
)
from ro.budget import (
    allocate_budget,
    require_fits,
    BudgetInvalidError,
    BudgetExhaustedError,
    BudgetInfeasibleError,
)
from ro.context_prep import (
    select_and_reduce,
    validate_rqm,
    rqm_content_hash,
    check_freshness,
    MalformedRQMError,
    StaleRQMError,
    EmptyContextError,
)
from ro.matching_selection import (
    build_candidate_set,
    select_provider,
    derive_size_class,
    EmptyCandidateSetError,
    EmptyEligibleSetError,
)
from ro.request import (
    prepare,
    canonical as canonical_request,
    content_hash as request_content_hash,
    UnapprovedDecisionError,
    UnconstrainedRequestError,
)
from ro.renderer import (
    render,
    assert_lossless,
    UnknownRequestFormError,
)


_CHARS = {
    "inference_depth": "moderate", "context_sensitivity": "medium",
    "determinism_tolerance": "medium", "knowledge_dependency": "medium",
    "creativity_requirement": "low", "reasoning_complexity": "C1",
    "verification_difficulty": "low", "expected_output_structure": "bounded",
}

_CHARS_LOW = dict(_CHARS, knowledge_dependency="low", context_sensitivity="low")


def _capability(chars=None, cap_id="ro.cap.summarize"):
    return build_capability(cap_id, "INTERPRETIVE", chars or _CHARS, lifecycle="active")


def _approved_decision(cap_id="ro.cap.summarize", rung="C1"):
    return DecisionRecord(
        outcome="REASONING_APPROVED",
        justification=MappingProxyType({"passed": ("x",)}),
        decided_from=MappingProxyType({}),
        approved_capability_id=cap_id, approved_required_rung=rung,
        approved_scope=MappingProxyType({
            "description": "summarize", "granularity": "single_demand", "narrowing": None,
        }),
    )


def _rejected_decision():
    return DecisionRecord(
        outcome="REASONING_REJECTED", justification=MappingProxyType({}),
        decided_from=MappingProxyType({}), approved_capability_id=None,
        approved_required_rung=None, approved_scope=None,
    )


def _rqm():
    return {
        "core": ({"id": "c1", "content": "alpha fact", "provenance": "doc:1"},),
        "supporting": ({"id": "s1", "content": "beta detail", "provenance": "doc:2"},),
    }


def _row(provider_id="ro.provider.x", cap_id="ro.cap.summarize", rung="C1", **kw):
    defaults = dict(
        context_capacity_class="large", cost_class="low", latency_class="fast",
        determinism_class="low_variance", deployment_locality="local",
        privacy_domain="internal",
    )
    defaults.update(kw)
    return build_descriptor_row(provider_id, {cap_id: (rung,)}, **defaults)


class _Policy:
    policy_version = 1


def _registry():
    reg = SchemaRegistry()
    reg.register("ro.schema.summary", 1, ("summary",))
    return reg


def _prepare(**overrides):
    kwargs = dict(
        decision_record=_approved_decision(), rqm=_rqm(), capability_record=_capability(),
        descriptor_rows=[_row()], descriptor_space_version=5, policy_view=_Policy(),
        priors_version=2, schema_registry=_registry(), schema_id="ro.schema.summary",
        schema_version=1, budget_ceiling=10_000, budget_source_policy_version=1,
        verification_expectations={"must_cite": True},
    )
    kwargs.update(overrides)
    return prepare(**kwargs)


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

class SchemaRegistryTests(unittest.TestCase):
    def test_append_only_register_returns_record(self):
        reg = SchemaRegistry()
        rec = reg.register("ro.schema.x", 1, ("a", "b"))
        self.assertEqual(rec.required_fields, ("a", "b"))
        self.assertIs(reg.get("ro.schema.x", 1), rec)

    def test_duplicate_version_refused(self):
        reg = SchemaRegistry()
        reg.register("ro.schema.x", 1, ("a",))
        with self.assertRaises(DuplicateSchemaVersionError):
            reg.register("ro.schema.x", 1, ("a", "b"))

    def test_unknown_version_loud(self):
        reg = SchemaRegistry()
        reg.register("ro.schema.x", 1, ("a",))
        with self.assertRaises(UnknownSchemaError):
            reg.require("ro.schema.x", 2)

    def test_new_version_of_same_id_allowed(self):
        reg = SchemaRegistry()
        reg.register("ro.schema.x", 1, ("a",))
        rec2 = reg.register("ro.schema.x", 2, ("a", "b"))
        self.assertEqual(rec2.version, 2)


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------

class BudgetTests(unittest.TestCase):
    def test_parent_inheritance_sets_parent_ref(self):
        parent = allocate_budget(1000, source_policy_version=1)
        child = allocate_budget(400, source_policy_version=1, parent=parent)
        self.assertIsNotNone(child.parent_ref)

    def test_sibling_accounting(self):
        parent = allocate_budget(1000, source_policy_version=1)
        allocate_budget(400, source_policy_version=1, parent=parent, already_allocated_from_parent=0)
        sibling = allocate_budget(500, source_policy_version=1, parent=parent,
                                   already_allocated_from_parent=400)
        self.assertEqual(sibling.ceiling, 500)

    def test_exhaustion_loud(self):
        parent = allocate_budget(1000, source_policy_version=1)
        with self.assertRaises(BudgetExhaustedError):
            allocate_budget(700, source_policy_version=1, parent=parent,
                             already_allocated_from_parent=400)

    def test_infeasible_content_loud(self):
        env = allocate_budget(100, source_policy_version=1)
        require_fits(env, 100)
        with self.assertRaises(BudgetInfeasibleError):
            require_fits(env, 101)

    def test_no_fresh_grant_child_cannot_exceed_parent_ceiling(self):
        parent = allocate_budget(500, source_policy_version=1)
        with self.assertRaises(BudgetExhaustedError):
            allocate_budget(501, source_policy_version=1, parent=parent,
                             already_allocated_from_parent=0)

    def test_bad_ceiling_refused(self):
        with self.assertRaises(BudgetInvalidError):
            allocate_budget(0, source_policy_version=1)
        with self.assertRaises(BudgetInvalidError):
            allocate_budget(-5, source_policy_version=1)


# ---------------------------------------------------------------------------
# context_prep
# ---------------------------------------------------------------------------

class ContextPrepTests(unittest.TestCase):
    def test_selection_table_low_low_yields_nothing(self):
        cap = _capability(_CHARS_LOW)
        included, _, _ = select_and_reduce(_rqm(), cap)
        self.assertEqual(included, ())

    def test_selection_table_medium_medium_pulls_core_and_supporting(self):
        cap = _capability(_CHARS)
        included, _, _ = select_and_reduce(_rqm(), cap)
        sections = {item["provenance"] for item in included}
        self.assertEqual(sections, {"doc:1", "doc:2"})

    def test_dedup_by_content_hash_collapses_different_id_and_provenance(self):
        rqm = {
            "core": (
                {"id": "c1", "content": "same fact", "provenance": "doc:1"},
                {"id": "c2-different-id", "content": "same fact", "provenance": "doc:99-different"},
            ),
        }
        cap = _capability(dict(_CHARS, knowledge_dependency="low", context_sensitivity="medium"))
        included, _, reduction = select_and_reduce(rqm, cap)
        self.assertEqual(len(included), 1)
        self.assertTrue(any(r["reason"] == "duplicate_content" for r in reduction))

    def test_relevance_threshold_drop(self):
        rqm = {"core": ({"id": "c1", "content": "low score", "provenance": "doc:1", "score": 0.1},)}
        cap = _capability(dict(_CHARS, knowledge_dependency="low", context_sensitivity="medium"))
        included, _, reduction = select_and_reduce(rqm, cap, relevance_threshold=0.5)
        self.assertEqual(included, ())
        self.assertTrue(any(r["reason"] == "below_relevance_threshold" for r in reduction))

    def test_size_class_cap(self):
        rqm = {"core": tuple(
            {"id": "c%d" % i, "content": "fact %d" % i, "provenance": "doc:%d" % i}
            for i in range(10)
        )}
        cap = _capability(dict(_CHARS, knowledge_dependency="low", context_sensitivity="medium"))
        included, _, reduction = select_and_reduce(rqm, cap)  # -> minimal, cap=2
        self.assertEqual(len(included), 2)
        self.assertTrue(any(r["reason"] == "size_class_cap_reached" for r in reduction))

    def test_empty_context_floor_for_knowledge_demanding_capability(self):
        cap = _capability(dict(_CHARS, knowledge_dependency="high", context_sensitivity="high"))
        with self.assertRaises(EmptyContextError):
            select_and_reduce({}, cap)

    def test_low_dependency_empty_context_ok(self):
        cap = _capability(_CHARS_LOW)
        included, _, _ = select_and_reduce({}, cap)
        self.assertEqual(included, ())

    def test_stale_rqm_flag_loud(self):
        with self.assertRaises(StaleRQMError):
            check_freshness(_rqm(), rqm_stale=True)

    def test_stale_rqm_hash_mismatch_loud(self):
        with self.assertRaises(StaleRQMError):
            check_freshness(_rqm(), expected_rqm_hash="not-the-real-hash")

    def test_malformed_rqm_loud(self):
        with self.assertRaises(MalformedRQMError):
            validate_rqm({"core": [{"id": "x", "content": "y", "provenance": "z"}]})
        with self.assertRaises(MalformedRQMError):
            validate_rqm("not a dict")
        with self.assertRaises(MalformedRQMError):
            validate_rqm({"core": ({"id": "x", "content": "y"},)})  # missing provenance

    def test_determinism(self):
        cap = _capability(_CHARS)
        r1 = select_and_reduce(_rqm(), cap)
        r2 = select_and_reduce(dict(_rqm()), cap)
        self.assertEqual(r1, r2)
        self.assertEqual(rqm_content_hash(_rqm()), rqm_content_hash(dict(_rqm())))


# ---------------------------------------------------------------------------
# matching_selection
# ---------------------------------------------------------------------------

class MatchingSelectionTests(unittest.TestCase):
    def test_candidate_set_is_claim_and_rung_only(self):
        row_ok = _row("ro.provider.a")
        row_wrong_rung = _row("ro.provider.b", rung="C2")
        row_wrong_cap = _row("ro.provider.c", cap_id="ro.cap.other")
        candidates = build_candidate_set([row_ok, row_wrong_rung, row_wrong_cap],
                                          "ro.cap.summarize", "C1")
        self.assertEqual([r.provider_id for r in candidates], ["ro.provider.a"])

    def test_empty_candidate_set_loud(self):
        with self.assertRaises(EmptyCandidateSetError):
            build_candidate_set([_row("ro.provider.a")], "ro.cap.nope", "C1")

    def test_eligibility_exclusions_recorded_per_provider_with_reasons(self):
        row_a = _row("ro.provider.a", privacy_domain="public")
        row_b = _row("ro.provider.b", privacy_domain="restricted")
        candidates = build_candidate_set([row_a, row_b], "ro.cap.summarize", "C1")
        winner, exclusions, _ = select_provider(candidates, privacy_domain_required="restricted")
        self.assertEqual(winner.provider_id, "ro.provider.b")
        self.assertEqual(len(exclusions), 1)
        self.assertEqual(exclusions[0]["provider_id"], "ro.provider.a")
        self.assertIn("privacy_domain_insufficient", exclusions[0]["reasons"])

    def test_empty_eligible_set_loud_carries_exclusions(self):
        row_a = _row("ro.provider.a", context_capacity_class="small")
        candidates = build_candidate_set([row_a], "ro.cap.summarize", "C1")
        with self.assertRaises(EmptyEligibleSetError) as ctx:
            select_provider(candidates, request_size_class="xlarge")
        self.assertEqual(len(ctx.exception.exclusions), 1)

    def test_tie_break_order_cost_then_preference_then_provider_id(self):
        row_cheap = _row("ro.provider.cheap", cost_class="low")
        row_pricey = _row("ro.provider.pricey", cost_class="high")
        candidates = build_candidate_set([row_cheap, row_pricey], "ro.cap.summarize", "C1")
        winner, _, _ = select_provider(candidates)
        self.assertEqual(winner.provider_id, "ro.provider.cheap")  # cost wins first

        row_z = _row("ro.provider.z", cost_class="low")
        row_a = _row("ro.provider.a", cost_class="low")
        tied = build_candidate_set([row_z, row_a], "ro.cap.summarize", "C1")
        winner_pref, _, _ = select_provider(
            tied, declared_preference=("ro.provider.z", "ro.provider.a"))
        self.assertEqual(winner_pref.provider_id, "ro.provider.z")  # preference wins tie

        winner_alpha, _, _ = select_provider(tied)
        self.assertEqual(winner_alpha.provider_id, "ro.provider.a")  # alphabetical fallback

    def test_size_class_derivation_boundaries(self):
        self.assertEqual(derive_size_class(0), "small")
        self.assertEqual(derive_size_class(2_000), "small")
        self.assertEqual(derive_size_class(2_001), "medium")
        self.assertEqual(derive_size_class(8_000), "medium")
        self.assertEqual(derive_size_class(8_001), "large")
        self.assertEqual(derive_size_class(32_000), "large")
        self.assertEqual(derive_size_class(32_001), "xlarge")


# ---------------------------------------------------------------------------
# request / prepare
# ---------------------------------------------------------------------------

class PrepareTests(unittest.TestCase):
    def test_end_to_end_pair_from_approved(self):
        req, res = _prepare()
        self.assertEqual(req.capability_id, "ro.cap.summarize")
        self.assertEqual(res.provider_id, "ro.provider.x")

    def test_non_approved_outcome_refused(self):
        with self.assertRaises(UnapprovedDecisionError):
            _prepare(decision_record=_rejected_decision())

    def test_missing_verification_expectations_refused(self):
        with self.assertRaises(UnconstrainedRequestError):
            _prepare(verification_expectations=None)

    def test_provider_id_absent_from_request_present_in_resolution(self):
        req, res = _prepare()
        self.assertNotIn("ro.provider.x", canonical_request(req).decode())
        self.assertEqual(res.provider_id, "ro.provider.x")

    def test_resolved_for_request_hash_linkage(self):
        req, res = _prepare()
        self.assertEqual(res.resolved_for_request_hash, request_content_hash(req))

    def test_determinism_byte_identical_from_independently_rebuilt_inputs(self):
        req1, res1 = _prepare(rqm=_rqm(), descriptor_rows=[_row()])
        req2, res2 = _prepare(rqm=_rqm(), descriptor_rows=[_row()])
        self.assertEqual(request_content_hash(req1), request_content_hash(req2))
        self.assertEqual(request_content_hash(res1), request_content_hash(res2))

    def test_preparation_coordinates_carry_all_six_tuple_members(self):
        req, _ = _prepare()
        coords = req.preparation_coordinates
        for key in ("decision_record_content_hash", "rqm_content_hash",
                    "descriptor_space_version", "policy_version",
                    "priors_version", "schema_version"):
            self.assertIn(key, coords)

    def test_budget_infeasible_propagates_loud(self):
        with self.assertRaises(BudgetInfeasibleError):
            _prepare(budget_ceiling=1)

    def test_constraints_carry_all_six_categories(self):
        req, _ = _prepare()
        for category in ("allowed_scope", "output_form", "forbidden_behaviors",
                          "determinism_expectations", "policy_constraints",
                          "verification_expectations"):
            self.assertIn(category, req.constraints)


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------

class RendererTests(unittest.TestCase):
    def test_unknown_form_loud(self):
        req, _ = _prepare()
        with self.assertRaises(UnknownRequestFormError):
            render(req, "carrier_pigeon")

    def test_determinism_byte_identical(self):
        req, _ = _prepare()
        self.assertEqual(render(req, "prompt_text"), render(req, "prompt_text"))

    def test_losslessness_all_six_categories_present(self):
        req, _ = _prepare(forbidden_behaviors=("no_pii", "no_speculation"))
        rendered = render(req, "prompt_text")
        assert_lossless(req, rendered)  # raises AssertionError on failure
        text = rendered.decode("utf-8")
        self.assertIn("no_pii", text)
        self.assertIn("must_cite", text)
        self.assertIn("summarize", text)  # allowed_scope description
        self.assertIn("ro.schema.summary", text)  # output_form
        self.assertIn("medium", text)  # determinism_expectations band value

    def test_provider_id_absent_from_rendering(self):
        req, res = _prepare()
        rendered = render(req, "prompt_text")
        self.assertNotIn(res.provider_id, rendered.decode("utf-8"))

    def test_mutated_constraints_render_differently(self):
        req1, _ = _prepare(forbidden_behaviors=("no_pii",))
        req2, _ = _prepare(forbidden_behaviors=("no_pii", "no_speculation"))
        self.assertNotEqual(render(req1, "prompt_text"), render(req2, "prompt_text"))

    def test_context_items_and_capability_present(self):
        req, _ = _prepare()
        rendered = render(req, "prompt_text").decode("utf-8")
        for item in req.context:
            self.assertIn(item["id"], rendered)
            self.assertIn(item["content"], rendered)
            self.assertIn(item["provenance"], rendered)
        self.assertIn(req.capability_id, rendered)
        self.assertIn(req.required_rung, rendered)


# ---------------------------------------------------------------------------
# static invariants
# ---------------------------------------------------------------------------

class StaticInvariantTests(unittest.TestCase):
    """Mirrors decision_gate's AST-scan style (RO-D2/D6 pattern extended to
    Phase 3: no wall-clock, no randomness anywhere in preparation/rendering).
    The Phase 2 no-DescriptorRow rule is decision_gate-specific (RO-D3) and
    is NOT extended here — matching_selection/request legitimately reference
    DescriptorRow."""

    _MODULES = ("schemas.py", "budget.py", "context_prep.py",
                "matching_selection.py", "request.py", "renderer.py")

    def _src_dir(self):
        return Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "ro"))

    def test_no_time_or_random_import_in_phase3_modules(self):
        for name in self._MODULES:
            tree = ast.parse((self._src_dir() / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(imported & {"time", "random", "datetime"}, name)


if __name__ == "__main__":
    unittest.main()
