"""VAE Phase 3 suite — VAE/06-implementation-blueprint.md Phase 3
(derivation: verdict, confidence, uncertainty, assurance). Covers:
determinism (identical body -> byte-identical account, item order does not
change the outcome); VAE/02 §5's five contribution-kind effects; all five
VAE/02 §7 assurance levels reachable; all five VAE/01 §11 / VAE-K8 failure
causes reachable and correctly classified; uncertainty explicit and
separate from confidence (VAE-A3); traceability of every derived value to
real evidence items (VAE-A10); derivation-account immutability and
re-derivation matching the stored account (VAE-A1); Phase 1+2 integration
(judgment.close() output feeding derive() directly)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from vae import evidence
from vae import derivation as derivation_mod
from vae import judgment as judgment_mod
from vae.execution_double import ExecutionDouble
from vae.static_checks import StaticCheckRegistry


POLICY = derivation_mod.build_derivation_policy(
    1, coverage_moderate_min_fraction=0.5, coverage_strong_min_fraction=0.9)


def _record(items):
    r = evidence.build_evidence_record("artifact:a1", 1)
    for it in items:
        r = evidence.append_item(r, it)
    return r


def _item(rule, source, result, kind, level="structural"):
    return evidence.build_evidence_item(rule, "artifact:a1", source, result, kind, level)


# -- determinism ----------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_identical_body_byte_identical_account(self):
        body = _record([_item("r1", "s1", "pass", "independent"),
                         _item("r2", "s2", "pass", "independent", level="semantic")])
        self.assertEqual(derivation_mod.derive(body, POLICY), derivation_mod.derive(body, POLICY))

    def test_item_order_does_not_change_verdict_or_confidence_levels(self):
        a = _item("r1", "s1", "pass", "independent")
        b = _item("r2", "s2", "pass", "independent", level="semantic")
        acc_ab = derivation_mod.derive(_record([a, b]), POLICY)
        acc_ba = derivation_mod.derive(_record([b, a]), POLICY)
        self.assertEqual(acc_ab["verdict"], acc_ba["verdict"])
        for dim in derivation_mod.DIMENSIONS:
            self.assertEqual(acc_ab["confidence"][dim]["level"], acc_ba["confidence"][dim]["level"])
        self.assertEqual(acc_ab["coverage"]["level"], acc_ba["coverage"]["level"])

    def test_different_rules_versions_are_independent(self):
        r1 = evidence.build_evidence_record("artifact:a1", 1)
        r2 = evidence.build_evidence_record("artifact:a1", 2)
        acc1 = derivation_mod.derive(r1, POLICY)
        acc2 = derivation_mod.derive(r2, POLICY)
        self.assertEqual(acc1["rules_version"], 1)
        self.assertEqual(acc2["rules_version"], 2)


# -- contribution-kind effects (VAE/02 §5) ---------------------------------

class ContributionKindEffectsTests(unittest.TestCase):
    def test_single_independent_is_weak(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "pass", "independent")]), POLICY)
        self.assertEqual(acc["confidence"]["structural"]["level"], "weak")

    def test_corroborating_strengthens_beyond_single(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "pass", "corroborating"),
        ]), POLICY)
        self.assertEqual(acc["confidence"]["structural"]["level"], "strong")

    def test_conflicting_reduces_below_either_item_alone(self):
        conflicted = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "fail", "conflicting"),
        ]), POLICY)
        single = derivation_mod.derive(_record([_item("r1", "s1", "pass", "independent")]), POLICY)
        self.assertEqual(conflicted["confidence"]["structural"]["level"], "conflicted")
        self.assertLess(
            derivation_mod.CONFIDENCE_LEVELS.index(conflicted["confidence"]["structural"]["level"]),
            derivation_mod.CONFIDENCE_LEVELS.index(single["confidence"]["structural"]["level"]))

    def test_redundant_adds_nothing(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s1", "pass", "redundant"),
        ]), POLICY)
        self.assertEqual(acc["confidence"]["structural"]["level"], "weak")  # same as single

    def test_missing_caps_coverage_not_confidence(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "pass", "corroborating"),
            _item("r2", None, "not_run", "missing", level="semantic"),
        ]), POLICY)
        self.assertEqual(acc["confidence"]["structural"]["level"], "strong")
        self.assertEqual(acc["coverage"]["established"], 1)
        self.assertEqual(acc["coverage"]["total"], 2)
        # a rules-identified absence still degrades the verdict to a definite fail
        self.assertEqual(acc["verdict"], derivation_mod.VERDICT_FAILED)
        self.assertEqual(acc["failure_cause"], derivation_mod.EVIDENCE_INSUFFICIENCY)


# -- all five assurance levels ---------------------------------------------

class AssuranceLevelTests(unittest.TestCase):
    def test_verified_high(self):
        items = []
        for i, level in enumerate(("structural", "execution", "semantic", "system")):
            items.append(_item("r" + str(i), "s" + str(i) + "a", "pass", "independent", level=level))
            items.append(_item("r" + str(i), "s" + str(i) + "b", "pass", "corroborating", level=level))
        acc = derivation_mod.derive(_record(items), POLICY)
        self.assertEqual(acc["assurance_level"], derivation_mod.VERIFIED_HIGH)

    def test_verified_moderate_on_mixed_dimension_strength(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "pass", "corroborating"),
            _item("r2", "s3", "pass", "independent", level="execution"),
        ]), POLICY)
        self.assertEqual(acc["assurance_level"], derivation_mod.VERIFIED_MODERATE)

    def test_verified_low_on_minimal_evidence(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "pass", "independent")]), POLICY)
        self.assertEqual(acc["assurance_level"], derivation_mod.VERIFIED_LOW)

    def test_verification_failed_on_any_fail_verdict(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "fail", "independent")]), POLICY)
        self.assertEqual(acc["assurance_level"], derivation_mod.VERIFICATION_FAILED)

    def test_unverified_is_the_named_pre_verdict_level_not_a_derive_output(self):
        self.assertEqual(derivation_mod.UNVERIFIED, "Unverified")
        self.assertIn(derivation_mod.UNVERIFIED, derivation_mod.ASSURANCE_LEVELS)

    def test_assurance_levels_closed_five_exact_names(self):
        self.assertEqual(set(derivation_mod.ASSURANCE_LEVELS), {
            "Verified — High Assurance", "Verified — Moderate Assurance",
            "Verified — Low Assurance", "Unverified", "Verification Failed",
        })


# -- all five failure causes -------------------------------------------------

class FailureCauseTests(unittest.TestCase):
    def test_evidence_insufficiency_on_empty_body(self):
        acc = derivation_mod.derive(evidence.build_evidence_record("artifact:a1", 1), POLICY)
        self.assertEqual(acc["verdict"], derivation_mod.VERDICT_FAILED)
        self.assertEqual(acc["failure_cause"], derivation_mod.EVIDENCE_INSUFFICIENCY)

    def test_evidence_insufficiency_on_identified_absence(self):
        acc = derivation_mod.derive(_record([_item("r1", None, "not_run", "missing")]), POLICY)
        self.assertEqual(acc["failure_cause"], derivation_mod.EVIDENCE_INSUFFICIENCY)

    def test_execution_failure(self):
        acc = derivation_mod.derive(
            _record([_item("r1", "s1", "execution_failure", "independent")]), POLICY)
        self.assertEqual(acc["failure_cause"], derivation_mod.EXECUTION_FAILURE)

    def test_execution_failure_from_closed_execution_double_outcomes(self):
        for outcome in ("failure", "timeout", "crash"):
            acc = derivation_mod.derive(_record([_item("r1", "s1", outcome, "independent")]), POLICY)
            self.assertEqual(acc["failure_cause"], derivation_mod.EXECUTION_FAILURE)

    def test_verification_failure(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "fail", "independent")]), POLICY)
        self.assertEqual(acc["failure_cause"], derivation_mod.VERIFICATION_FAILURE)

    def test_inconclusive_verification(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "ambiguous", "independent")]), POLICY)
        self.assertEqual(acc["failure_cause"], derivation_mod.INCONCLUSIVE_VERIFICATION)

    def test_contradictory_evidence(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "fail", "conflicting"),
        ]), POLICY)
        self.assertEqual(acc["failure_cause"], derivation_mod.CONTRADICTORY_EVIDENCE)

    def test_failure_causes_closed_five_exact_names(self):
        self.assertEqual(set(derivation_mod.FAILURE_CAUSES), {
            "execution_failure", "verification_failure", "evidence_insufficiency",
            "inconclusive_verification", "contradictory_evidence",
        })

    def test_pass_verdict_has_no_failure_cause(self):
        acc = derivation_mod.derive(_record([_item("r1", "s1", "pass", "independent")]), POLICY)
        self.assertEqual(acc["verdict"], derivation_mod.VERDICT_PASSED)
        self.assertIsNone(acc["failure_cause"])


# -- uncertainty explicit and separate from confidence (VAE-A3) -----------

class UncertaintyTests(unittest.TestCase):
    def test_uncertainty_present_for_missing_claims_only(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r2", None, "not_run", "missing", level="semantic"),
        ]), POLICY)
        self.assertEqual(len(acc["uncertainty"]), 1)
        self.assertEqual(acc["uncertainty"][0]["reason"], "missing_evidence")
        self.assertEqual(acc["uncertainty"][0]["rule"], "r2")

    def test_high_confidence_can_coexist_with_uncertainty(self):
        acc = derivation_mod.derive(_record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "pass", "corroborating"),
            _item("r2", None, "not_run", "missing", level="semantic"),
        ]), POLICY)
        self.assertEqual(acc["confidence"]["structural"]["level"], "strong")
        self.assertEqual(len(acc["uncertainty"]), 1)

    def test_uncertainty_is_a_distinct_field_from_confidence(self):
        acc = derivation_mod.derive(_record([_item("r1", None, "not_run", "missing")]), POLICY)
        self.assertNotEqual(acc["uncertainty"], acc["confidence"])
        self.assertIn("uncertainty", acc)
        self.assertIn("confidence", acc)


# -- traceability (VAE-A10) -------------------------------------------------

class TraceabilityTests(unittest.TestCase):
    def test_every_confidence_ref_resolves_to_a_real_item(self):
        body = _record([
            _item("r1", "s1", "pass", "independent"),
            _item("r1", "s2", "pass", "corroborating"),
            _item("r2", None, "not_run", "missing", level="semantic"),
        ])
        acc = derivation_mod.derive(body, POLICY)
        for dim in derivation_mod.DIMENSIONS:
            for idx in acc["confidence"][dim]["refs"]:
                self.assertTrue(0 <= idx < len(body.items))

    def test_every_uncertainty_ref_resolves_to_a_real_item(self):
        body = _record([_item("r1", None, "not_run", "missing")])
        acc = derivation_mod.derive(body, POLICY)
        for stmt in acc["uncertainty"]:
            for idx in stmt["refs"]:
                self.assertTrue(0 <= idx < len(body.items))

    def test_coverage_refs_cover_the_whole_body(self):
        body = _record([_item("r1", "s1", "pass", "independent"),
                         _item("r2", None, "not_run", "missing", level="semantic")])
        acc = derivation_mod.derive(body, POLICY)
        self.assertEqual(set(acc["coverage"]["refs"]), set(range(len(body.items))))


# -- account immutability and re-derivation (VAE-A1, VAE-A6) --------------

class AccountImmutabilityTests(unittest.TestCase):
    def test_attach_derivation_fills_the_phase1_slot_without_mutating_original(self):
        body = _record([_item("r1", "s1", "pass", "independent")])
        attached = derivation_mod.attach_derivation(body, POLICY)
        self.assertIsNone(body.derivation_account)
        self.assertEqual(attached.derivation_account, derivation_mod.derive(body, POLICY))
        self.assertEqual(attached.items, body.items)

    def test_slot_already_filled_is_refused_not_overwritten(self):
        body = _record([_item("r1", "s1", "pass", "independent")])
        attached = derivation_mod.attach_derivation(body, POLICY)
        with self.assertRaises(evidence.DerivationAccountRefusedError):
            derivation_mod.attach_derivation(attached, POLICY)

    def test_rederivation_from_account_bearing_record_matches_stored_account(self):
        body = _record([_item("r1", "s1", "pass", "independent"),
                         _item("r1", "s2", "pass", "corroborating")])
        attached = derivation_mod.attach_derivation(body, POLICY)
        self.assertEqual(derivation_mod.derive(attached, POLICY), attached.derivation_account)

    def test_with_derivation_account_refuses_non_mapping(self):
        body = _record([])
        with self.assertRaises(evidence.DerivationAccountMalformedError):
            evidence.with_derivation_account(body, ["not", "a", "mapping"])

    def test_build_evidence_record_still_refuses_non_none_account_after_phase3(self):
        with self.assertRaises(evidence.DerivationAccountRefusedError):
            evidence.build_evidence_record("artifact:a1", 1, derivation_account={"verdict": "x"})


# -- validation / refusals ---------------------------------------------------

class ValidationTests(unittest.TestCase):
    def test_unknown_verification_level_refused_loud(self):
        bad = evidence.build_evidence_item("r1", "artifact:a1", "s1", "pass",
                                            "independent", "not_a_real_level")
        with self.assertRaises(derivation_mod.UnknownVerificationLevelError):
            derivation_mod.derive(_record([bad]), POLICY)

    def test_malformed_policy_refused_loud(self):
        with self.assertRaises(derivation_mod.MalformedDerivationPolicyError):
            derivation_mod.build_derivation_policy(1, coverage_moderate_min_fraction=0,
                                                    coverage_strong_min_fraction=0.9)
        with self.assertRaises(derivation_mod.MalformedDerivationPolicyError):
            derivation_mod.build_derivation_policy(1, coverage_moderate_min_fraction=0.9,
                                                    coverage_strong_min_fraction=0.5)
        with self.assertRaises(derivation_mod.MalformedDerivationPolicyError):
            derivation_mod.build_derivation_policy(0, coverage_moderate_min_fraction=0.5,
                                                    coverage_strong_min_fraction=0.9)

    def test_derive_refuses_non_record_and_non_policy(self):
        with self.assertRaises(derivation_mod.DerivationRefusal):
            derivation_mod.derive("not-a-record", POLICY)
        body = evidence.build_evidence_record("artifact:a1", 1)
        with self.assertRaises(derivation_mod.DerivationRefusal):
            derivation_mod.derive(body, "not-a-policy")


# -- Phase 1 + 2 integration -------------------------------------------------

class Phase1And2IntegrationTests(unittest.TestCase):
    def test_judgment_closure_output_feeds_derivation_directly(self):
        exe = ExecutionDouble()
        registry = StaticCheckRegistry()
        j = judgment_mod.open_judgment(
            "judgment:p3a", "artifact:p3a", rules_version=1,
            delegated_checks={"structural": {"deadline": 10, "level": "structural"}},
            static_checks_spec={"reference_wellformed": {"level": "semantic"}})
        j = judgment_mod.run_static_check(j, "reference_wellformed", registry, {})
        j = judgment_mod.dispatch_delegation(j, "structural", exe, {"check": "structural"})
        exe.script_result("judgment:p3a:structural", arrival_time=1, outcome="success")
        j = judgment_mod.resolve_delegation(j, "structural", exe, now=1)
        self.assertTrue(judgment_mod.is_closed(j))
        j = judgment_mod.close(j)

        acc = derivation_mod.derive(j.record, POLICY)
        self.assertEqual(acc["verdict"], derivation_mod.VERDICT_PASSED)
        self.assertEqual(acc["rules_version"], 1)

        attached = derivation_mod.attach_derivation(j.record, POLICY)
        self.assertEqual(attached.derivation_account["verdict"], derivation_mod.VERDICT_PASSED)

    def test_expired_delegation_feeds_execution_failure_cause(self):
        exe = ExecutionDouble()
        j = judgment_mod.open_judgment(
            "judgment:p3b", "artifact:p3b", rules_version=1,
            delegated_checks={"semantic": {"deadline": 5, "level": "semantic"}},
            static_checks_spec={})
        j = judgment_mod.dispatch_delegation(j, "semantic", exe, {"check": "semantic"})
        j = judgment_mod.resolve_delegation(j, "semantic", exe, now=5)
        j = judgment_mod.close(j)

        acc = derivation_mod.derive(j.record, POLICY)
        self.assertEqual(acc["verdict"], derivation_mod.VERDICT_FAILED)
        self.assertEqual(acc["failure_cause"], derivation_mod.EXECUTION_FAILURE)


if __name__ == "__main__":
    unittest.main()
