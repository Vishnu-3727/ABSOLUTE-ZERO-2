"""VAE Phase 1 suite — VAE/06-implementation-blueprint.md Phase 1
(foundation: rules-as-data, evidence model, event canon, doubles). Covers:
rules ingest/refusal/monotonic-version/pinning; append-only evidence
enforcement (no edit/remove API exists); closed-set refusals (event names,
contribution kinds); derivation-account slot refusal; evidence
content-hash stability and order-sensitivity; bus/storage double script
behavior."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from vae import rules
from vae import evidence
from vae import events
from vae.bus_double import BusDouble
from vae.storage_double import StorageDouble


def _artifact_rules_spec(checks=("structural", "semantic"), depth="standard", deadlines=None):
    if deadlines is None:
        deadlines = {c: 5 for c in checks}
    return {"required_checks": checks, "depth": depth, "deadlines": deadlines}


class RulesIngestTests(unittest.TestCase):
    def test_ingest_and_lookup(self):
        store = rules.RulesStore()
        store.ingest(1, {"plugin_output": _artifact_rules_spec()})
        got = store.lookup("plugin_output", 1)
        self.assertEqual(got.required_checks, ("structural", "semantic"))
        self.assertEqual(got.depth, "standard")
        self.assertEqual(got.deadlines["structural"], 5)

    def test_monotonic_version_stale_and_duplicate_refused(self):
        store = rules.RulesStore()
        store.ingest(1, {"plugin_output": _artifact_rules_spec()})
        with self.assertRaises(rules.StaleOrDuplicateVersionError):
            store.ingest(1, {"plugin_output": _artifact_rules_spec(depth="minimal")})
        store.ingest(2, {"plugin_output": _artifact_rules_spec(depth="deep")})
        with self.assertRaises(rules.StaleOrDuplicateVersionError):
            store.ingest(2, {"plugin_output": _artifact_rules_spec()})

    def test_pinning_old_version_still_readable(self):
        store = rules.RulesStore()
        store.ingest(1, {"plugin_output": _artifact_rules_spec(depth="standard")})
        store.ingest(2, {"plugin_output": _artifact_rules_spec(depth="deep")})
        self.assertEqual(store.lookup("plugin_output", 1).depth, "standard")
        self.assertEqual(store.lookup("plugin_output", 2).depth, "deep")
        self.assertEqual(store.current_version(), 2)

    def test_absent_version_refused_never_a_default(self):
        store = rules.RulesStore()
        store.ingest(1, {"plugin_output": _artifact_rules_spec()})
        with self.assertRaises(rules.UnknownVersionError):
            store.lookup("plugin_output", 99)

    def test_absent_artifact_type_refused_never_a_default(self):
        store = rules.RulesStore()
        store.ingest(1, {"plugin_output": _artifact_rules_spec()})
        with self.assertRaises(rules.UnknownArtifactTypeError):
            store.lookup("plan", 1)

    def test_malformed_rules_refused_loud(self):
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_artifact_rules((), "standard", {})
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_artifact_rules(("a", "a"), "standard", {"a": 1})
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_artifact_rules(("a",), "standard", {"a": -1})
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_artifact_rules(("a",), "standard", {"other": 1})
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_rules_version(0, {"plugin_output": _artifact_rules_spec()})
        with self.assertRaises(rules.MalformedRulesError):
            rules.build_rules_version(1, {})

    def test_current_version_none_before_any_ingest(self):
        store = rules.RulesStore()
        self.assertIsNone(store.current_version())


class EvidenceAppendOnlyTests(unittest.TestCase):
    def test_append_grows_record_without_mutating_original(self):
        rec = evidence.build_evidence_record("artifact:a1", 1)
        item = evidence.build_evidence_item(
            "rule.structural", "artifact:a1", "check.structural", "pass", "independent", "structural")
        rec2 = evidence.append_item(rec, item)
        self.assertEqual(rec.items, ())
        self.assertEqual(rec2.items, (item,))

    def test_no_edit_or_remove_api_exists(self):
        rec = evidence.build_evidence_record("artifact:a1", 1)
        self.assertFalse(hasattr(rec, "edit_item"))
        self.assertFalse(hasattr(rec, "remove_item"))
        self.assertFalse(hasattr(rec, "set_item"))
        self.assertFalse(hasattr(evidence, "edit_item"))
        self.assertFalse(hasattr(evidence, "remove_item"))

    def test_record_and_item_fields_frozen(self):
        rec = evidence.build_evidence_record("artifact:a1", 1)
        item = evidence.build_evidence_item(
            "rule.structural", "artifact:a1", "check.structural", "pass", "independent", "structural")
        with self.assertRaises(AttributeError):
            rec.items = ()
        with self.assertRaises(AttributeError):
            item.result = "fail"

    def test_identified_absence_is_first_class_item(self):
        rec = evidence.build_evidence_record("artifact:a1", 1)
        absence = evidence.build_evidence_item(
            "rule.system", "artifact:a1", None, "not_run", "missing", "system")
        rec2 = evidence.append_item(rec, absence)
        self.assertEqual(len(rec2.items), 1)
        self.assertEqual(rec2.items[0].contribution_kind, "missing")


class ClosedSetRefusalTests(unittest.TestCase):
    def test_contribution_kind_outside_closed_five_refused(self):
        self.assertEqual(
            evidence.CONTRIBUTION_KINDS,
            ("independent", "corroborating", "redundant", "conflicting", "missing"))
        with self.assertRaises(evidence.UnknownContributionKindError):
            evidence.build_evidence_item("r", "a", "s", "res", "speculative", "structural")

    def test_missing_item_must_carry_no_source(self):
        with self.assertRaises(evidence.MalformedEvidenceItemError):
            evidence.build_evidence_item("r", "a", "some.source", "not_run", "missing", "system")

    def test_non_missing_item_must_carry_a_source(self):
        with self.assertRaises(evidence.MalformedEvidenceItemError):
            evidence.build_evidence_item("r", "a", None, "pass", "independent", "structural")

    def test_event_closed_sets_match_spec(self):
        self.assertEqual(events.PUBLISHED, (
            "verify.passed", "verify.failed", "plan.validated", "plan.rejected",
            "fault.recorded"))
        self.assertEqual(events.CONSUMED, (
            "verify.requested", "plan.created", "exec.completed", "reasoning.completed"))

    def test_invented_publish_name_refused(self):
        bus = BusDouble()
        with self.assertRaises(events.UnknownEventError):
            events.emit(bus, "verify.maybe", "e1", "artifact:a1", {})
        self.assertEqual(bus.messages("verify.maybe"), [])

    def test_invented_consume_name_refused(self):
        with self.assertRaises(events.UnknownEventError):
            events.check_consumed("verify.maybe")

    def test_published_name_not_a_consumed_name(self):
        with self.assertRaises(events.UnknownEventError):
            events.check_consumed("verify.passed")

    def test_consumed_name_not_a_published_name(self):
        with self.assertRaises(events.UnknownEventError):
            events.emit(BusDouble(), "verify.requested", "e1", "s", {})


class DerivationAccountRefusalTests(unittest.TestCase):
    def test_setting_derivation_account_in_phase_1_is_refused(self):
        with self.assertRaises(evidence.DerivationAccountRefusedError):
            evidence.build_evidence_record(
                "artifact:a1", 1, derivation_account={"verdict": "verify.passed"})

    def test_default_derivation_account_is_none(self):
        rec = evidence.build_evidence_record("artifact:a1", 1)
        self.assertIsNone(rec.derivation_account)
        item = evidence.build_evidence_item(
            "rule.structural", "artifact:a1", "check.structural", "pass", "independent", "structural")
        rec2 = evidence.append_item(rec, item)
        self.assertIsNone(rec2.derivation_account)


class ContentHashTests(unittest.TestCase):
    def _two_items(self):
        item_a = evidence.build_evidence_item(
            "rule.structural", "artifact:a1", "check.structural", "pass", "independent", "structural")
        item_b = evidence.build_evidence_item(
            "rule.semantic", "artifact:a1", "check.semantic", "pass", "corroborating", "semantic")
        return item_a, item_b

    def test_same_items_same_order_same_hash(self):
        item_a, item_b = self._two_items()
        rec1 = evidence.append_item(
            evidence.append_item(evidence.build_evidence_record("artifact:a1", 1), item_a), item_b)
        rec2 = evidence.append_item(
            evidence.append_item(evidence.build_evidence_record("artifact:a1", 1), item_a), item_b)
        self.assertEqual(evidence.content_hash(rec1), evidence.content_hash(rec2))

    def test_different_order_different_hash(self):
        item_a, item_b = self._two_items()
        forward = evidence.append_item(
            evidence.append_item(evidence.build_evidence_record("artifact:a1", 1), item_a), item_b)
        backward = evidence.append_item(
            evidence.append_item(evidence.build_evidence_record("artifact:a1", 1), item_b), item_a)
        self.assertNotEqual(evidence.content_hash(forward), evidence.content_hash(backward))


class BusDoubleTests(unittest.TestCase):
    def test_per_topic_fifo(self):
        bus = BusDouble()
        bus.publish("verify.passed", {"n": 1})
        bus.publish("verify.passed", {"n": 2})
        bus.publish("fault.recorded", {"n": 99})
        self.assertEqual(bus.messages("verify.passed"), [{"n": 1}, {"n": 2}])
        self.assertEqual(bus.messages("fault.recorded"), [{"n": 99}])

    def test_inject_duplicate_scripts_at_least_once_redelivery(self):
        bus = BusDouble()
        bus.publish("verify.passed", {"event_id": "e1"})
        bus.inject_duplicate("verify.passed")
        self.assertEqual(bus.messages("verify.passed"),
                          [{"event_id": "e1"}, {"event_id": "e1"}])

    def test_fail_publishes_scripting(self):
        bus = BusDouble()
        bus.fail_publishes = True
        with self.assertRaises(ConnectionError):
            bus.publish("verify.passed", {})

    def test_drain_empties_topic(self):
        bus = BusDouble()
        bus.publish("verify.passed", {"n": 1})
        self.assertEqual(bus.drain("verify.passed"), [{"n": 1}])
        self.assertEqual(bus.messages("verify.passed"), [])


class StorageDoubleTests(unittest.TestCase):
    def test_write_commits_by_default(self):
        store = StorageDouble()
        self.assertEqual(store.write("vae/ev/a1", b"v1"), "committed")
        self.assertEqual(store.read("vae/ev/a1"), b"v1")

    def test_scripted_rejection_outcome_not_an_exception(self):
        store = StorageDouble()
        store.script_reject("vae/ev/a2")
        self.assertEqual(store.write("vae/ev/a2", b"v2"), "rejected")
        self.assertFalse(store.exists("vae/ev/a2"))

    def test_rejection_is_one_shot(self):
        store = StorageDouble()
        store.script_reject("vae/ev/a2")
        store.write("vae/ev/a2", b"v2")
        self.assertEqual(store.write("vae/ev/a2", b"v2b"), "committed")
        self.assertEqual(store.read("vae/ev/a2"), b"v2b")

    def test_read_of_missing_key_raises(self):
        store = StorageDouble()
        with self.assertRaises(KeyError):
            store.read("missing")

    def test_write_requires_bytes(self):
        store = StorageDouble()
        with self.assertRaises(TypeError):
            store.write("k", "not bytes")


if __name__ == "__main__":
    unittest.main()
