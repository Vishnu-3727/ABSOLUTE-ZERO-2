"""RO Phase 2 suite — RO/02-reasoning-decision-architecture.md, the
necessity gate (RO/05 §10 blueprint group G2). Covers: all five outcomes
reachable with correct payloads; mutual exclusivity via the fixed
evaluation order (structural -> ladder -> n1 -> governance); every
structural-defect class -> INSUFFICIENT_INFORMATION; every governance
ground -> GOVERNANCE_REFUSED; REJECTED on either false n1 claim; APPROVED
happy path payload; determinism/replay (byte-identical DecisionRecord
content hashes across independent rebuilds of equal inputs); decided_from
coordinates present on every outcome (RO-D5); static AST scan of
decision_gate.py for RO-D3 (no DescriptorRow reference) and RO-D2/D6 (no
time/random import).
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ro.demand import (
    RUNGS,
    build_demand,
    build_ladder_evidence,
    build_sealed_inputs,
)
from ro.policy_view import build_policy_view
from ro.records import build_capability
from ro.decision_gate import (
    OUTCOMES,
    DecisionRecord,
    decide,
    canonical,
    content_hash,
)

_CHARS = {
    "inference_depth": "moderate", "context_sensitivity": "medium",
    "determinism_tolerance": "medium", "knowledge_dependency": "low",
    "creativity_requirement": "low", "reasoning_complexity": "C1",
    "verification_difficulty": "low", "expected_output_structure": "bounded",
}

_SCOPE = {"description": "summarize the report", "granularity": "single_demand"}


def _capability(lifecycle="active", category="INTERPRETIVE", cap_id="ro.cap.summarize"):
    return build_capability(cap_id, category, _CHARS, lifecycle=lifecycle)


def _demand(cap_id="ro.cap.summarize", required_rung="C1", scope=None,
            underdetermined_claim=True, generalization_claim=True, demand_id="ro.demand.1"):
    scope = scope if scope is not None else _SCOPE
    return build_demand(
        demand_id, cap_id, required_rung, scope,
        underdetermined={"claim": underdetermined_claim, "justification": "u-just"},
        generalization_required={"claim": generalization_claim, "justification": "g-just"},
    )


def _ladder(statuses=None):
    statuses = statuses or {r: "exhausted" for r in RUNGS}
    return tuple(build_ladder_evidence(r, statuses[r], r + "-justification") for r in RUNGS)


def _policy(permitted=True, categories=("INTERPRETIVE",), rungs=("C0", "C1", "C2", "C3", "C4"),
            version=1):
    return build_policy_view(permitted, categories, rungs, version)


_UNSET = object()


def _sealed(demand=_UNSET, ladder=_UNSET, cap=_UNSET, policy=_UNSET, rqm="rqm.hash.1",
            wf="wf.ref.1", priors_version=1, budget_available=True):
    return build_sealed_inputs(
        demand if demand is not _UNSET else _demand(),
        rqm,
        ladder if ladder is not _UNSET else _ladder(),
        wf,
        cap if cap is not _UNSET else _capability(),
        priors_version,
        policy if policy is not _UNSET else _policy(),
        budget_available,
    )


class OutcomesReachableTests(unittest.TestCase):
    def test_approved_happy_path(self):
        record = decide(_sealed())
        self.assertEqual(record.outcome, "REASONING_APPROVED")
        self.assertEqual(record.approved_capability_id, "ro.cap.summarize")
        self.assertEqual(record.approved_required_rung, "C1")
        self.assertEqual(record.approved_scope["description"], _SCOPE["description"])
        self.assertEqual(record.approved_scope["granularity"], _SCOPE["granularity"])

    def test_rejected_when_underdetermined_false(self):
        d = _demand(underdetermined_claim=False)
        record = decide(_sealed(demand=d))
        self.assertEqual(record.outcome, "REASONING_REJECTED")
        self.assertFalse(record.justification["underdetermined_claim"])

    def test_rejected_when_generalization_false(self):
        d = _demand(generalization_claim=False)
        record = decide(_sealed(demand=d))
        self.assertEqual(record.outcome, "REASONING_REJECTED")
        self.assertFalse(record.justification["generalization_required_claim"])

    def test_rejected_when_both_false(self):
        d = _demand(underdetermined_claim=False, generalization_claim=False)
        record = decide(_sealed(demand=d))
        self.assertEqual(record.outcome, "REASONING_REJECTED")

    def test_continuation_required_single_untried(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D3"] = "untried"
        record = decide(_sealed(ladder=_ladder(statuses)))
        self.assertEqual(record.outcome, "DETERMINISTIC_CONTINUATION_REQUIRED")
        self.assertEqual(record.justification["untried_rungs"], ("D3",))

    def test_continuation_required_multiple_untried_named_in_rung_order(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D4"] = "untried"
        statuses["D2"] = "untried"
        record = decide(_sealed(ladder=_ladder(statuses)))
        self.assertEqual(record.outcome, "DETERMINISTIC_CONTINUATION_REQUIRED")
        self.assertEqual(record.justification["untried_rungs"], ("D2", "D4"))

    def test_continuation_required_inapplicable_rung_does_not_block(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D2"] = "inapplicable"
        record = decide(_sealed(ladder=_ladder(statuses)))
        self.assertEqual(record.outcome, "REASONING_APPROVED")

    def test_insufficient_information_missing_capability(self):
        record = decide(_sealed(cap=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("capability_record_missing_or_malformed", record.justification["defects"])

    def test_governance_refused_not_permitted(self):
        record = decide(_sealed(policy=_policy(permitted=False)))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "reasoning_not_permitted")

    def test_outcomes_are_exactly_the_closed_five(self):
        self.assertEqual(OUTCOMES, (
            "REASONING_APPROVED", "REASONING_REJECTED", "DETERMINISTIC_CONTINUATION_REQUIRED",
            "INSUFFICIENT_INFORMATION", "GOVERNANCE_REFUSED",
        ))


class MutualExclusivityOrderTests(unittest.TestCase):
    def test_untried_ladder_beats_false_n1_claim(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D1"] = "untried"
        d = _demand(underdetermined_claim=False)
        record = decide(_sealed(demand=d, ladder=_ladder(statuses)))
        self.assertEqual(record.outcome, "DETERMINISTIC_CONTINUATION_REQUIRED")

    def test_false_n1_claim_beats_governance_refusal(self):
        d = _demand(underdetermined_claim=False)
        record = decide(_sealed(demand=d, policy=_policy(permitted=False)))
        self.assertEqual(record.outcome, "REASONING_REJECTED")

    def test_structural_defect_beats_everything(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D1"] = "untried"
        d = _demand(underdetermined_claim=False)
        record = decide(_sealed(demand=d, ladder=_ladder(statuses), cap=None,
                                 policy=_policy(permitted=False)))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")


class StructuralDefectTests(unittest.TestCase):
    def test_missing_n1_claim_key(self):
        raw_demand = build_demand(
            "d.bad", "ro.cap.summarize", "C1", _SCOPE,
            underdetermined={}, generalization_required={"claim": True, "justification": "x"},
        )
        record = decide(_sealed(demand=raw_demand))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertTrue(any(d.startswith("n1_claim_missing:underdetermined")
                             for d in record.justification["defects"]))

    def test_missing_n1_justification(self):
        raw_demand = build_demand(
            "d.bad2", "ro.cap.summarize", "C1", _SCOPE,
            underdetermined={"claim": True, "justification": ""},
            generalization_required={"claim": True, "justification": "x"},
        )
        record = decide(_sealed(demand=raw_demand))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("n1_justification_missing:underdetermined", record.justification["defects"])

    def test_n1_claim_not_bool(self):
        raw_demand = build_demand(
            "d.bad3", "ro.cap.summarize", "C1", _SCOPE,
            underdetermined={"claim": "yes", "justification": "x"},
            generalization_required={"claim": True, "justification": "x"},
        )
        record = decide(_sealed(demand=raw_demand))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("n1_claim_not_bool:underdetermined", record.justification["defects"])

    def test_capability_id_mismatch(self):
        mismatched_cap = _capability(cap_id="ro.cap.other")
        record = decide(_sealed(cap=mismatched_cap))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("capability_id_mismatch", record.justification["defects"])

    def test_missing_ladder_rung_record(self):
        incomplete_ladder = _ladder()[:-1]  # drop D5
        record = decide(_sealed(ladder=incomplete_ladder))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertTrue(any(d.startswith("ladder_rungs_missing:")
                             for d in record.justification["defects"]))
        self.assertIn("D5", [d for d in record.justification["defects"]
                              if d.startswith("ladder_rungs_missing:")][0])

    def test_malformed_scope_missing_description(self):
        # build_demand itself refuses this at construction time (shape law) —
        # exercise the gate's OWN structural re-check via a hand-built
        # DemandArtifact bypassing the builder, per demand.py's documented
        # contract that the gate never trusts the builder path alone.
        from ro.demand import DemandArtifact
        bad = DemandArtifact(
            demand_id="d.bad4", required_capability_id="ro.cap.summarize", required_rung="C1",
            scope=MappingProxyType({"description": "", "granularity": "g", "narrowing": None}),
            underdetermined=MappingProxyType({"claim": True, "justification": "x"}),
            generalization_required=MappingProxyType({"claim": True, "justification": "x"}),
        )
        record = decide(_sealed(demand=bad))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("scope_incomplete", record.justification["defects"])

    def test_missing_rqm_hash(self):
        record = decide(_sealed(rqm=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("rqm_content_hash_missing", record.justification["defects"])

    def test_missing_workflow_unit_ref(self):
        record = decide(_sealed(wf=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("workflow_unit_ref_missing", record.justification["defects"])

    def test_bad_priors_version(self):
        record = decide(_sealed(priors_version=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("priors_version_missing_or_malformed", record.justification["defects"])

    def test_missing_policy(self):
        record = decide(_sealed(policy=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("policy_missing_or_malformed", record.justification["defects"])

    def test_missing_budget_flag(self):
        record = decide(_sealed(budget_available=None))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("budget_available_missing_or_malformed", record.justification["defects"])

    def test_narrowing_not_flagged_deterministic(self):
        from ro.demand import DemandArtifact
        bad = DemandArtifact(
            demand_id="d.bad5", required_capability_id="ro.cap.summarize", required_rung="C1",
            scope=MappingProxyType({"description": "d", "granularity": "g",
                                     "narrowing": MappingProxyType({"description": "sub"})}),
            underdetermined=MappingProxyType({"claim": True, "justification": "x"}),
            generalization_required=MappingProxyType({"claim": True, "justification": "x"}),
        )
        record = decide(_sealed(demand=bad))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("narrowing_not_flagged_deterministic", record.justification["defects"])

    def test_duplicate_ladder_rung(self):
        from ro.demand import LadderEvidence
        dup = _ladder()[:-1] + (
            LadderEvidence(rung="D4", status="exhausted", justification="x", outcome_record_ref=None),)
        record = decide(_sealed(ladder=dup))
        self.assertEqual(record.outcome, "INSUFFICIENT_INFORMATION")
        self.assertIn("ladder_rung_duplicate:D4", record.justification["defects"])


class GovernanceGroundTests(unittest.TestCase):
    def test_reasoning_not_permitted(self):
        record = decide(_sealed(policy=_policy(permitted=False)))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "reasoning_not_permitted")

    def test_category_not_permitted(self):
        record = decide(_sealed(policy=_policy(categories=("ANALYTIC",))))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "category_not_permitted")

    def test_rung_above_ceiling(self):
        d = _demand(required_rung="C4")
        record = decide(_sealed(demand=d, policy=_policy(rungs=("C0", "C1"))))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "rung_above_ceiling")

    def test_rung_at_ceiling_permitted(self):
        d = _demand(required_rung="C2")
        record = decide(_sealed(demand=d, policy=_policy(rungs=("C0", "C1", "C2"))))
        self.assertEqual(record.outcome, "REASONING_APPROVED")

    def test_budget_unavailable(self):
        record = decide(_sealed(budget_available=False))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "budget_unavailable")

    def test_capability_lifecycle_proposed(self):
        record = decide(_sealed(cap=_capability(lifecycle="proposed")))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "capability_lifecycle_ineligible")

    def test_capability_lifecycle_retired(self):
        record = decide(_sealed(cap=_capability(lifecycle="retired")))
        self.assertEqual(record.outcome, "GOVERNANCE_REFUSED")
        self.assertEqual(record.justification["ground"], "capability_lifecycle_ineligible")

    def test_capability_lifecycle_deprecated_permitted(self):
        record = decide(_sealed(cap=_capability(lifecycle="deprecated")))
        self.assertEqual(record.outcome, "REASONING_APPROVED")

    def test_governance_ground_ordering_permission_before_category(self):
        record = decide(_sealed(policy=_policy(permitted=False, categories=("ANALYTIC",))))
        self.assertEqual(record.justification["ground"], "reasoning_not_permitted")


class DeterminismReplayTests(unittest.TestCase):
    def test_identical_sealed_inputs_decided_twice_byte_identical(self):
        sealed = _sealed()
        r1 = decide(sealed)
        r2 = decide(sealed)
        self.assertEqual(content_hash(r1), content_hash(r2))
        self.assertEqual(canonical(r1), canonical(r2))

    def test_independently_rebuilt_equal_inputs_byte_identical(self):
        r1 = decide(_sealed())
        r2 = decide(_sealed())
        self.assertEqual(content_hash(r1), content_hash(r2))

    def test_determinism_holds_for_non_approval_outcomes(self):
        d = _demand(underdetermined_claim=False)
        r1 = decide(_sealed(demand=d))
        r2 = decide(_sealed(demand=d))
        self.assertEqual(content_hash(r1), content_hash(r2))


class DecidedFromCoordinatesTests(unittest.TestCase):
    def _assert_coordinates_present(self, record):
        keys = {
            "demand_content_hash", "rqm_content_hash", "ladder_evidence_hash",
            "workflow_unit_ref", "capability_content_hash", "priors_version",
            "policy_version", "budget_available",
        }
        self.assertEqual(set(record.decided_from), keys)

    def test_present_on_approved(self):
        self._assert_coordinates_present(decide(_sealed()))

    def test_present_on_rejected(self):
        d = _demand(underdetermined_claim=False)
        self._assert_coordinates_present(decide(_sealed(demand=d)))

    def test_present_on_continuation_required(self):
        statuses = {r: "exhausted" for r in RUNGS}
        statuses["D1"] = "untried"
        self._assert_coordinates_present(decide(_sealed(ladder=_ladder(statuses))))

    def test_present_on_insufficient_information(self):
        self._assert_coordinates_present(decide(_sealed(cap=None)))

    def test_present_on_governance_refused(self):
        self._assert_coordinates_present(decide(_sealed(policy=_policy(permitted=False))))

    def test_capability_hash_none_when_capability_missing(self):
        record = decide(_sealed(cap=None))
        self.assertIsNone(record.decided_from["capability_content_hash"])
        self.assertIsNotNone(record.decided_from["demand_content_hash"])


class PayloadShapeTests(unittest.TestCase):
    def test_non_approved_payload_fields_are_none(self):
        for record in (
            decide(_sealed(demand=_demand(underdetermined_claim=False))),
            decide(_sealed(cap=None)),
            decide(_sealed(policy=_policy(permitted=False))),
        ):
            self.assertIsNone(record.approved_capability_id)
            self.assertIsNone(record.approved_required_rung)
            self.assertIsNone(record.approved_scope)

    def test_decision_record_frozen(self):
        record = decide(_sealed())
        with self.assertRaises(Exception):
            record.outcome = "X"


class StaticInvariantTests(unittest.TestCase):
    """Mirrors prt/law_enforcer.py's AST-scan style for structural
    invariants no runtime unit test can catch (RO-D3, RO-D2/D6)."""

    def _module_path(self):
        return Path(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "src", "ro", "decision_gate.py"))

    def _names_referenced(self, tree):
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add((node.asname or node.name).split(".")[0])
        return names

    def test_no_descriptor_row_reference(self):
        tree = ast.parse(self._module_path().read_text(encoding="utf-8"))
        self.assertNotIn("DescriptorRow", self._names_referenced(tree))

    def test_no_time_or_random_import(self):
        tree = ast.parse(self._module_path().read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & {"time", "random", "datetime"})


if __name__ == "__main__":
    unittest.main()
