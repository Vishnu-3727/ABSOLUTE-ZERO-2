"""PRT Phase 4 suite — PRT/04-health-reliability.md (PRT-H1..H12).

Covers: journal append-only with no mutation surface, corrections as new
entries (PRT-H6); evidence determinism (same entries -> same fold -> same
snapshot hash); replay (fold-from-scratch == incrementally maintained
state, PRT-H1); graduated degradation (1 failure -> DEGRADED, threshold
failures -> quarantine REQUEST -> QUARANTINED); guaranteed recovery path
(favorable evidence -> RECOVERING -> RECOVERED -> HEALTHY, PRT-H5); admin
override both directions explicit (force_quarantine/force_release) +
disable/enable UNAVAILABLE bar; legality refusal -> no transition, no
event (PRT-H11); health never mints a registry version (PRT-H2); snapshot
immutability + Phase 3 integration (produced snapshot feeds binding.resolve,
quarantined provider filtered at eligibility, a historical BindingContract
stays unchanged after later health changes, PRT-H8); plugin.health.changed
emitted on transitions only, canon name; reliability.updated consumption
via the bridge changes reliability in the next snapshot but availability
only per state rules (PRT/04 §5); priors_version recorded (PRT-H1 input
class).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from prt import events
from prt.binding import BindingContract, BindingFailure, resolve
from prt.bus_double import BusDouble
from prt.config_view import ConfigView
from prt.evidence import EvidenceJournal
from prt.health import DEFAULT_THRESHOLDS, HealthManager, fold_provider
from prt.load_policy import LoadPolicyView
from prt.reliability_bridge import consume_reliability_update, drain_reliability_updates
from prt.records import build_binding, build_capability, build_provider
from prt.registry import Registry


def _reg_with_provider(pid="prov.p4.a", cap_id="cap.p4.x"):
    reg = Registry()
    cap = build_capability(cap_id, "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": cap})
    reg.apply({"kind": "add_provider", "record": build_provider(pid, "1.0")})
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": pid, "to_state": "active"})
    reg.apply({"kind": "add_binding", "record": build_binding(cap_id, pid)})
    return reg


class JournalAppendOnlyTests(unittest.TestCase):
    def test_no_mutation_surface(self):
        j = EvidenceJournal()
        j.append_live("p", "exec.failed")
        entries = j.entries()
        entries[0]["kind"] = "tampered"
        self.assertEqual(j.entries()[0]["kind"], "exec.failed")

    def test_correction_is_new_entry_never_edit(self):
        j = EvidenceJournal()
        j.append_admin("p", "disable", actor="op", reason="r1")
        j.append_admin("p", "enable", actor="op", reason="r2 (correction)")
        self.assertEqual(len(j), 2)
        self.assertEqual(j.entries()[0]["kind"], "disable")
        self.assertEqual(j.entries()[1]["kind"], "enable")

    def test_closed_input_classes_only(self):
        j = EvidenceJournal()
        with self.assertRaises(ValueError):
            j.append_live("p", "process.failed")  # dead vocabulary, D2
        with self.assertRaises(ValueError):
            j.append_live("p", "not.an.event")
        with self.assertRaises(ValueError):
            j.append_admin("p", "bogus", actor="op", reason="r")
        with self.assertRaises(ValueError):
            j.append_admin("p", "disable", actor="", reason="")  # never silent, §7


class EvidenceDeterminismTests(unittest.TestCase):
    def test_same_entries_same_fold_same_snapshot_hash(self):
        j1, j2 = EvidenceJournal(), EvidenceJournal()
        for j in (j1, j2):
            j.append_live("p", "exec.failed")
            j.append_live("p", "exec.completed")
            j.append_priors("p", 0.77, priors_version=2)
        m1, m2 = HealthManager(j1), HealthManager(j2)
        self.assertEqual(m1.state("p"), m2.state("p"))
        snap1, snap2 = m1.snapshot(["p"]), m2.snapshot(["p"])
        self.assertEqual(snap1.content_hash, snap2.content_hash)

    def test_order_variation_allowed_to_differ(self):
        # same entries, different order across two providers -> not required
        # to match; only IDENTICAL order guarantees an identical result.
        j = EvidenceJournal()
        j.append_live("p", "exec.failed")
        j.append_live("p", "exec.completed")
        state_a = fold_provider(j.entries_for("p"))["state"]

        j2 = EvidenceJournal()
        j2.append_live("p", "exec.completed")
        j2.append_live("p", "exec.failed")
        state_b = fold_provider(j2.entries_for("p"))["state"]
        # different order legitimately gives a different state here
        # (failed-then-completed clears to HEALTHY; completed-then-failed
        # degrades) -- demonstrating order is a real input, not incidental.
        self.assertNotEqual(state_a, state_b)


class ReplayTests(unittest.TestCase):
    def test_fold_from_scratch_equals_incremental(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        for kind in ("exec.failed", "exec.failed", "exec.timeout", "exec.completed",
                    "exec.completed", "exec.completed"):
            mgr.record_outcome("p", kind)
        incremental_state = mgr.state("p")
        incremental_reliability = mgr.reliability("p")

        scratch = fold_provider(j.entries_for("p"))
        self.assertEqual(incremental_state, scratch["state"])
        self.assertEqual(incremental_reliability, scratch["reliability"])

        snap_incremental = mgr.snapshot(["p"])
        # a second manager over the same journal, queried only once (no
        # incremental history) must fold to the identical snapshot hash.
        mgr_fresh = HealthManager(EvidenceJournal())
        for e in j.entries_for("p"):
            if e["type"] == "live":
                mgr_fresh.record_outcome("p", e["kind"], e["detail"])
        self.assertEqual(mgr_fresh.snapshot(["p"]).content_hash,
                        snap_incremental.content_hash)


class GraduatedDegradationTests(unittest.TestCase):
    def test_one_failure_degrades(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        mgr.record_outcome("p", "exec.failed")
        self.assertEqual(mgr.state("p"), "DEGRADED")

    def test_threshold_failures_quarantine(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        for _ in range(DEFAULT_THRESHOLDS["failures_to_quarantine"]):
            mgr.record_outcome("p", "exec.failed")
        self.assertEqual(mgr.state("p"), "QUARANTINED")


class RecoveryPathTests(unittest.TestCase):
    def test_guaranteed_recovery_no_permanent_blacklist(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        for _ in range(DEFAULT_THRESHOLDS["failures_to_quarantine"]):
            mgr.record_outcome("p", "exec.failed")
        self.assertEqual(mgr.state("p"), "QUARANTINED")

        mgr.record_outcome("p", "exec.completed")
        self.assertEqual(mgr.state("p"), "RECOVERING")
        for _ in range(DEFAULT_THRESHOLDS["successes_to_recover"] - 1):
            mgr.record_outcome("p", "exec.completed")
        self.assertEqual(mgr.state("p"), "RECOVERED")
        mgr.record_outcome("p", "exec.completed")
        self.assertEqual(mgr.state("p"), "HEALTHY")


class AdminOverrideTests(unittest.TestCase):
    def test_force_quarantine_from_healthy(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        self.assertEqual(mgr.state("p"), "HEALTHY")
        mgr.force_quarantine("p", actor="op.1", reason="incident")
        self.assertEqual(mgr.state("p"), "QUARANTINED")

    def test_force_release_from_quarantined(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        mgr.force_quarantine("p", actor="op.1", reason="incident")
        mgr.force_release("p", actor="op.1", reason="resolved")
        self.assertEqual(mgr.state("p"), "HEALTHY")

    def test_disable_enable_unavailable_bar(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        mgr.disable("p", actor="op.1", reason="maintenance")
        self.assertEqual(mgr.state("p"), "UNAVAILABLE")
        # bar is independent of quarantine underneath
        mgr.force_quarantine("p", actor="op.1", reason="also on fire")
        self.assertEqual(mgr.state("p"), "UNAVAILABLE")
        mgr.enable("p", actor="op.1", reason="maintenance done")
        self.assertEqual(mgr.state("p"), "QUARANTINED")  # bar lifted, underlying state shows


class LegalityRefusalTests(unittest.TestCase):
    def test_refused_legality_no_transition_no_event(self):
        def _refuse(pid, frm, to):
            return False
        j = EvidenceJournal()
        bus = BusDouble()
        mgr = HealthManager(j, legality=_refuse, bus=bus)
        mgr.record_outcome("p", "exec.failed")
        self.assertEqual(mgr.state("p"), "HEALTHY")
        self.assertEqual(bus.messages("plugin.health.changed"), [])


class NoRegistryVersionMintTests(unittest.TestCase):
    def test_full_health_life_never_mints_registry_version(self):
        reg = _reg_with_provider()
        before = reg.current_version
        j = EvidenceJournal()
        mgr = HealthManager(j)
        for _ in range(DEFAULT_THRESHOLDS["failures_to_quarantine"]):
            mgr.record_outcome("prov.p4.a", "exec.failed")
        mgr.force_release("prov.p4.a", actor="op", reason="ok")
        mgr.disable("prov.p4.a", actor="op", reason="x")
        mgr.enable("prov.p4.a", actor="op", reason="y")
        self.assertEqual(reg.current_version, before)


class SnapshotAndBindingIntegrationTests(unittest.TestCase):
    def test_snapshot_immutable_and_feeds_binding_resolve(self):
        reg = _reg_with_provider()
        j = EvidenceJournal()
        mgr = HealthManager(j)
        snap = mgr.snapshot(["prov.p4.a"])
        with self.assertRaises(AttributeError):
            snap.content_hash = "x"

        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        contract = resolve(reg, "cap.p4.x", snap, policy)
        self.assertIsInstance(contract, BindingContract)
        self.assertEqual(contract.provider_id, "prov.p4.a")

    def test_quarantined_provider_filtered_at_eligibility(self):
        reg = _reg_with_provider()
        j = EvidenceJournal()
        mgr = HealthManager(j)
        mgr.force_quarantine("prov.p4.a", actor="op", reason="bad")
        snap = mgr.snapshot(["prov.p4.a"])
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        result = resolve(reg, "cap.p4.x", snap, policy)
        self.assertIsInstance(result, BindingFailure)
        self.assertIn("prov.p4.a", dict(result.reasons))

    def test_historical_contract_unchanged_after_later_health_change(self):
        reg = _reg_with_provider()
        j = EvidenceJournal()
        mgr = HealthManager(j)
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))

        snap_early = mgr.snapshot(["prov.p4.a"])
        contract_early = resolve(reg, "cap.p4.x", snap_early, policy)
        self.assertIsInstance(contract_early, BindingContract)
        frozen_hash = contract_early.health_snapshot_hash

        # health degrades to quarantine well after the contract was minted
        for _ in range(DEFAULT_THRESHOLDS["failures_to_quarantine"]):
            mgr.record_outcome("prov.p4.a", "exec.failed")
        self.assertEqual(mgr.state("prov.p4.a"), "QUARANTINED")

        # the earlier contract's frozen coordinate never changes (PRT-H8)
        self.assertEqual(contract_early.health_snapshot_hash, frozen_hash)
        self.assertEqual(contract_early.provider_id, "prov.p4.a")


class HealthChangedEventTests(unittest.TestCase):
    def test_emitted_on_transition_only_canon_name(self):
        j = EvidenceJournal()
        bus = BusDouble()
        mgr = HealthManager(j, bus=bus)
        mgr.record_outcome("p", "exec.failed")  # HEALTHY -> DEGRADED
        mgr.record_outcome("p", "exec.completed")  # DEGRADED -> HEALTHY
        changed = bus.messages("plugin.health.changed")
        self.assertEqual(len(changed), 2)
        self.assertEqual(changed[0]["event_name"], "plugin.health.changed")
        self.assertEqual(changed[0]["payload"], {"provider_id": "p", "from": "HEALTHY", "to": "DEGRADED"})
        self.assertEqual(changed[1]["payload"], {"provider_id": "p", "from": "DEGRADED", "to": "HEALTHY"})

    def test_no_event_on_no_change(self):
        j = EvidenceJournal()
        bus = BusDouble()
        mgr = HealthManager(j, bus=bus)
        mgr.record_outcome("p", "exec.completed")  # HEALTHY -> HEALTHY: no-op
        self.assertEqual(bus.messages("plugin.health.changed"), [])


class ReliabilityBridgeTests(unittest.TestCase):
    def test_reliability_updated_changes_reliability_not_availability(self):
        j = EvidenceJournal()
        mgr = HealthManager(j)
        snap_before = mgr.snapshot(["p"])
        self.assertEqual(snap_before.get("p")["reliability"], 0.5)
        self.assertEqual(snap_before.get("p")["availability"], "available")

        bus = BusDouble()
        bus.publish("reliability.updated", {
            "event_name": "reliability.updated", "subject_id": "p",
            "payload": {"provider_id": "p", "prior": 0.92, "priors_version": 7}})
        drain_reliability_updates(bus, j)

        snap_after = mgr.snapshot(["p"])
        self.assertEqual(snap_after.get("p")["reliability"], 0.92)
        # health/reliability separation (§5): availability moves only per
        # state rules, unaffected by a reliability-only update
        self.assertEqual(snap_after.get("p")["availability"], "available")

    def test_priors_version_recorded(self):
        j = EvidenceJournal()
        consume_reliability_update(j, {
            "event_name": "reliability.updated",
            "payload": {"provider_id": "p", "prior": 0.6, "priors_version": 3}})
        entry = j.entries_for("p")[0]
        self.assertEqual(entry["type"], "priors")
        self.assertEqual(entry["priors_version"], 3)

    def test_dead_event_name_refused(self):
        j = EvidenceJournal()
        with self.assertRaises(ValueError):
            consume_reliability_update(j, {
                "event_name": "process.failed", "payload": {}})


if __name__ == "__main__":
    unittest.main()
