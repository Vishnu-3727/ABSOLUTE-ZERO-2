"""PRT Phase 3 suite — PRT/03-binding-load-policy.md (PRT-B1..B12).

Covers: determinism (PRT-B1/B2) including dict-insertion-order independence
(PRT-B3); no forbidden inputs; empty-eligible-set and unknown-capability
loud failures with every per-candidate reason recorded (PRT-B4/B5);
contract immutability + coordinates (PRT-B6); load transitions minting no
registry version (PRT-B8) and consulting the legality callable on every
transition, refusal leaving state/events untouched (PRT-B9); availability
as a pure eligibility predicate, every rung reachable (PRT-B11); explain()
replaying a decision from the artifact alone (PRT-B12); the three-way
tie-break order; snapshot/registry both left untouched by resolve(); replay
against a historical at_version snapshot after later registry mutations;
plugin.loaded/unloaded emitted with canon names only.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from prt import events
from prt.availability import rung_for
from prt.binding import BindingContract, BindingFailure, explain, resolve
from prt.bus_double import BusDouble
from prt.config_view import ConfigView
from prt.health_view import HealthSnapshot
from prt.load_policy import (
    AllowAllLegality, LoadPolicyView, LoadStateTracker, prerequisites_bound,
)
from prt.records import build_binding, build_capability, build_provider, build_relationship
from prt.registry import Registry


def _registry_with_three_providers(cap_id="cap.p3.x"):
    """One active capability, three active providers all bound to it —
    the standard fixture the tie-break/eligibility tests arrange around."""
    reg = Registry()
    cap = build_capability(cap_id, "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": cap})
    for pid in ("prov.p3.a", "prov.p3.b", "prov.p3.c"):
        reg.apply({"kind": "add_provider", "record": build_provider(pid, "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": pid, "to_state": "active"})
        reg.apply({"kind": "add_binding", "record": build_binding(cap_id, pid)})
    return reg


def _all_available_snapshot(reliabilities):
    return HealthSnapshot({
        pid: {"availability": "available", "reliability": rel}
        for pid, rel in reliabilities.items()
    })


class DeterminismCase(unittest.TestCase):
    """PRT-B1/B2: identical (capability id, registry version, health
    snapshot, policy) -> identical contract, including contract id, every
    time -- no exception."""

    def test_b1_b2_repeat_resolution_identical_including_contract_id(self):
        reg = _registry_with_three_providers()
        snap = _all_available_snapshot({"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))

        c1 = resolve(reg, "cap.p3.x", snap, policy)
        c2 = resolve(reg, "cap.p3.x", snap, policy)
        self.assertIsInstance(c1, BindingContract)
        self.assertEqual(c1, c2)
        self.assertEqual(c1.contract_id, c2.contract_id)

        # a fresh, independently-built but equal registry yields the same contract
        reg_b = _registry_with_three_providers()
        c3 = resolve(reg_b, "cap.p3.x", snap, LoadPolicyView(reg_b, ConfigView({"version": 1})))
        self.assertEqual(c1.contract_id, c3.contract_id)
        self.assertEqual(c1.provider_id, c3.provider_id)

    def test_b3_dict_insertion_order_never_influences_choice(self):
        reg = _registry_with_three_providers()
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        data_a = {"prov.p3.a": {"availability": "available", "reliability": 0.5},
                  "prov.p3.b": {"availability": "available", "reliability": 0.9},
                  "prov.p3.c": {"availability": "available", "reliability": 0.1}}
        data_b = {"prov.p3.c": {"availability": "available", "reliability": 0.1},
                  "prov.p3.a": {"availability": "available", "reliability": 0.5},
                  "prov.p3.b": {"availability": "available", "reliability": 0.9}}
        snap_a = HealthSnapshot(data_a)
        snap_b = HealthSnapshot(data_b)
        self.assertEqual(snap_a.content_hash, snap_b.content_hash)

        c_a = resolve(reg, "cap.p3.x", snap_a, policy)
        c_b = resolve(reg, "cap.p3.x", snap_b, policy)
        self.assertEqual(c_a.provider_id, c_b.provider_id)
        self.assertEqual(c_a.contract_id, c_b.contract_id)


class TieBreakCase(unittest.TestCase):
    """Fixed total order: declared preference > reliability (descending) >
    stable provider id (ascending) -- PRT/00 §4, three providers arranged to
    prove each level in turn."""

    def test_tie_break_levels(self):
        reg = _registry_with_three_providers()

        # level 3 only: no preference, tied reliability -> lowest id wins
        tied_snap = _all_available_snapshot(
            {"prov.p3.a": 0.5, "prov.p3.b": 0.5, "prov.p3.c": 0.5})
        policy_no_pref = LoadPolicyView(reg, ConfigView({"version": 1}))
        c = resolve(reg, "cap.p3.x", tied_snap, policy_no_pref)
        self.assertEqual(c.provider_id, "prov.p3.a")

        # level 2: no preference, distinct reliability -> highest reliability wins
        distinct_snap = _all_available_snapshot(
            {"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        c2 = resolve(reg, "cap.p3.x", distinct_snap, policy_no_pref)
        self.assertEqual(c2.provider_id, "prov.p3.b")

        # level 1: declared preference beats a higher-reliability non-preferred candidate
        policy_pref = LoadPolicyView(reg, ConfigView({"version": 1}),
                                     preferences={"cap.p3.x": ("prov.p3.c",)})
        c3 = resolve(reg, "cap.p3.x", distinct_snap, policy_pref)
        self.assertEqual(c3.provider_id, "prov.p3.c")


class FailureCase(unittest.TestCase):
    """PRT-B4/B5: empty eligible set and unknown capability id are loud,
    ordinary BindingFailure results -- never exceptions, never a widened
    search, never cross-capability substitution."""

    def test_b5_unknown_capability_id_loud_failure(self):
        reg = _registry_with_three_providers()
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        snap = HealthSnapshot({})
        failure = resolve(reg, "cap.totally.unknown", snap, policy)
        self.assertIsInstance(failure, BindingFailure)
        self.assertTrue(failure.unknown_capability)
        self.assertEqual(failure.reasons, ())

    def test_b4_b5_empty_eligible_set_records_every_reason_no_fallback(self):
        reg = _registry_with_three_providers()
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        empty_snap = HealthSnapshot({})  # no health data -> all stay LOADABLE
        failure = resolve(reg, "cap.p3.x", empty_snap, policy)
        self.assertIsInstance(failure, BindingFailure)
        self.assertFalse(failure.unknown_capability)
        reasons = dict(failure.reasons)
        self.assertEqual(set(reasons), {"prov.p3.a", "prov.p3.b", "prov.p3.c"})
        for reason in reasons.values():
            self.assertTrue(reason.startswith("ineligible:"))
        # never substitutes across capability ids -- resolve() has no
        # alternative-capability parameter or fallback path at all
        import inspect
        self.assertNotIn("fallback", inspect.signature(resolve).parameters)


class ContractImmutabilityCase(unittest.TestCase):
    """PRT-B6: the Binding Contract is immutable once issued and carries the
    exact registry version + health-state coordinates it was resolved
    under."""

    def test_b6_contract_immutable_and_carries_coordinates(self):
        reg = _registry_with_three_providers()
        snap = _all_available_snapshot({"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        contract = resolve(reg, "cap.p3.x", snap, policy)

        self.assertEqual(contract.registry_version, reg.current_version)
        self.assertEqual(contract.health_snapshot_hash, snap.content_hash)

        with self.assertRaises(Exception):
            contract.provider_id = "prov.p3.a"
        with self.assertRaises(TypeError):
            contract.constraints["x"] = 1
        with self.assertRaises(TypeError):
            contract.load_policy["x"] = 1


class SnapshotAndRegistryUntouchedCase(unittest.TestCase):
    """Binding never mutates the registry (reads only) and never modifies
    the health snapshot it consumed -- hash unchanged after resolve()."""

    def test_registry_and_snapshot_untouched_by_resolve(self):
        reg = _registry_with_three_providers()
        version_before = reg.current_version
        snap = _all_available_snapshot({"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        hash_before = snap.content_hash
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))

        resolve(reg, "cap.p3.x", snap, policy)

        self.assertEqual(reg.current_version, version_before)
        self.assertEqual(snap.content_hash, hash_before)
        # content-level check too, not just the version counter
        self.assertEqual(len(reg.bindings_for("cap.p3.x")), 3)


class ReplayCase(unittest.TestCase):
    """PRT-B12 + replay: resolving against an at_version(n) snapshot after
    later registry mutations reproduces the exact same contract the
    original resolution produced."""

    def test_replay_against_at_version_after_later_mutations(self):
        reg = _registry_with_three_providers()
        snap = _all_available_snapshot({"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        original = resolve(reg, "cap.p3.x", snap, policy)
        version_at_original = reg.current_version

        # registry mutates further after the original binding
        reg.apply({"kind": "add_provider", "record": build_provider("prov.p3.d", "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.p3.d", "to_state": "active"})
        reg.apply({"kind": "add_binding", "record": build_binding("cap.p3.x", "prov.p3.d")})
        self.assertGreater(reg.current_version, version_at_original)

        historical = reg.at_version(version_at_original)
        replay_policy = LoadPolicyView(historical, ConfigView({"version": 1}),
                                       preferences=dict(policy._preferences))
        replayed = resolve(historical, "cap.p3.x", snap, replay_policy)

        self.assertEqual(replayed.contract_id, original.contract_id)
        self.assertEqual(explain(replayed), explain(original))

    def test_b12_explain_reproduces_decision_from_artifact_alone(self):
        reg = _registry_with_three_providers()
        snap = _all_available_snapshot({"prov.p3.a": 0.5, "prov.p3.b": 0.9, "prov.p3.c": 0.1})
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        contract = resolve(reg, "cap.p3.x", snap, policy)
        explanation = explain(contract)
        self.assertEqual(explanation["provider_id"], contract.provider_id)
        self.assertEqual(explanation["registry_version"], contract.registry_version)
        self.assertEqual(explanation["health_snapshot_hash"], contract.health_snapshot_hash)
        self.assertEqual(explanation["contract_id"], contract.contract_id)

        empty_snap = HealthSnapshot({})
        failure = resolve(reg, "cap.p3.x", empty_snap, policy)
        fail_explanation = explain(failure)
        self.assertEqual(fail_explanation["outcome"], "failed")
        self.assertEqual(set(fail_explanation["reasons"]),
                         {"prov.p3.a", "prov.p3.b", "prov.p3.c"})


class AvailabilityLadderCase(unittest.TestCase):
    """PRT-B11: availability is an eligibility predicate only (no scoring);
    every rung reachable via a deterministic combination of inputs."""

    def test_every_rung_reachable(self):
        reg = _registry_with_three_providers()
        pid = "prov.p3.a"

        class _Policy:
            def __init__(self, permits=True, barred=False, load_state="NOT_LOADED"):
                self._permits, self._barred, self._load_state = permits, barred, load_state

            def is_admin_barred(self, provider_id):
                return self._barred

            def permits(self, provider_id):
                return self._permits

            def load_state(self, provider_id):
                return self._load_state

        no_health = HealthSnapshot({})
        available_health = HealthSnapshot({pid: {"availability": "available", "reliability": 0.5}})
        quarantined_health = HealthSnapshot(
            {pid: {"availability": "quarantined", "reliability": 0.5}})

        self.assertEqual(rung_for(reg, "prov.missing.entirely", _Policy(), no_health), "RETIRED")
        self.assertEqual(rung_for(reg, pid, _Policy(permits=False), no_health), "REGISTERED")
        self.assertEqual(rung_for(reg, pid, _Policy(), no_health), "LOADABLE")
        self.assertEqual(rung_for(reg, pid, _Policy(barred=True), no_health), "UNAVAILABLE")
        self.assertEqual(rung_for(reg, pid, _Policy(), quarantined_health), "UNAVAILABLE")
        self.assertEqual(rung_for(reg, pid, _Policy(), available_health), "AVAILABLE")
        self.assertEqual(
            rung_for(reg, pid, _Policy(load_state="LOADED"), available_health), "OPERATIONAL")

    def test_availability_never_scores_only_filters(self):
        # rung_for's return is always one of the six named rungs -- never a
        # number, never something a caller could rank two AVAILABLE
        # providers by (PRT-B11).
        import prt.availability as availability_mod
        reg = _registry_with_three_providers()
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        snap = _all_available_snapshot({"prov.p3.a": 0.9, "prov.p3.b": 0.1, "prov.p3.c": 0.5})
        rungs = {pid: rung_for(reg, pid, policy, snap)
                for pid in ("prov.p3.a", "prov.p3.b", "prov.p3.c")}
        self.assertEqual(set(rungs.values()), {"AVAILABLE"})  # identical rung despite differing reliability
        for rung in rungs.values():
            self.assertIn(rung, availability_mod.RUNGS)


class LoadLifecycleCase(unittest.TestCase):
    """PRT-B8: load transitions mint no registry version. PRT-B9: the
    legality callable is consulted on every transition; a refusal leaves
    state and events untouched. Canon event names only."""

    def test_b8_transitions_mint_no_registry_version(self):
        reg = _registry_with_three_providers()
        version_before = reg.current_version
        legality = AllowAllLegality()
        tracker = LoadStateTracker(legality, bus=BusDouble())

        tracker.request_transition("prov.p3.a", "LOADING")
        tracker.request_transition("prov.p3.a", "PREPARED")
        tracker.request_transition("prov.p3.a", "LOADED")
        tracker.request_transition("prov.p3.a", "RELEASED")

        self.assertEqual(reg.current_version, version_before)  # registry untouched throughout

    def test_b9_legality_consulted_every_transition_refusal_is_a_no_op(self):
        legality = AllowAllLegality()
        bus = BusDouble()
        tracker = LoadStateTracker(legality, bus=bus)

        tracker.request_transition("prov.x", "LOADING")
        tracker.request_transition("prov.x", "PREPARED")
        self.assertEqual(len(legality.calls), 2)
        self.assertEqual(legality.calls[0], ("prov.x", "NOT_LOADED", "LOADING"))
        self.assertEqual(legality.calls[1], ("prov.x", "LOADING", "PREPARED"))

        def _refuse(pid, from_state, to_state):
            return False

        refusing_tracker = LoadStateTracker(_refuse, bus=bus)
        state_before = refusing_tracker.state("prov.y")
        events_before = len(bus.messages("plugin.loaded")) + len(bus.messages("plugin.unloaded"))
        ok = refusing_tracker.request_transition("prov.y", "LOADING")
        self.assertFalse(ok)
        self.assertEqual(refusing_tracker.state("prov.y"), state_before)  # unchanged
        events_after = len(bus.messages("plugin.loaded")) + len(bus.messages("plugin.unloaded"))
        self.assertEqual(events_before, events_after)  # no event either

    def test_events_canon_names_only(self):
        legality = AllowAllLegality()
        bus = BusDouble()
        tracker = LoadStateTracker(legality, bus=bus)
        tracker.request_transition("prov.z", "LOADING")
        tracker.request_transition("prov.z", "PREPARED")
        tracker.request_transition("prov.z", "LOADED")
        self.assertEqual(len(bus.messages("plugin.loaded")), 1)
        tracker.request_transition("prov.z", "RELEASED")
        self.assertEqual(len(bus.messages("plugin.unloaded")), 1)
        # only canon names ever land on the bus (events.py's closed PUBLISHED set)
        for name in ("plugin.loaded", "plugin.unloaded"):
            self.assertIn(name, events.PUBLISHED)
        self.assertEqual(bus.messages("plugin.disabled"), [])


class PrerequisitesCheckCase(unittest.TestCase):
    def test_prerequisites_bound_check_not_acquisition(self):
        reg = Registry()
        cap_a = build_capability("cap.pq.a", "d", "nlp", lifecycle="active",
                                 verification_expectations=("x",))
        cap_b = build_capability("cap.pq.b", "d", "nlp", lifecycle="active",
                                 verification_expectations=("x",))
        reg.apply({"kind": "add_capability", "record": cap_a})
        reg.apply({"kind": "add_capability", "record": cap_b})
        reg.apply({"kind": "add_relationship", "record": build_relationship(
            "dependency", "cap.pq.a", "cap.pq.b")})
        policy = LoadPolicyView(reg, ConfigView({"version": 1}))
        empty_snap = HealthSnapshot({})

        def resolve_fn(cid):
            return resolve(reg, cid, empty_snap, policy)

        ok, unmet = prerequisites_bound(reg, "cap.pq.a", resolve_fn)
        self.assertFalse(ok)
        self.assertEqual(unmet, ("cap.pq.b",))

        # bind a provider to the prerequisite -> now satisfied
        reg.apply({"kind": "add_provider", "record": build_provider("prov.pq.b", "1.0")})
        reg.apply({"kind": "lifecycle_transition", "entity": "provider",
                  "id": "prov.pq.b", "to_state": "active"})
        reg.apply({"kind": "add_binding", "record": build_binding("cap.pq.b", "prov.pq.b")})
        snap_ok = HealthSnapshot({"prov.pq.b": {"availability": "available", "reliability": 0.5}})

        def resolve_fn2(cid):
            return resolve(reg, cid, snap_ok, policy)

        ok2, unmet2 = prerequisites_bound(reg, "cap.pq.a", resolve_fn2)
        self.assertTrue(ok2)
        self.assertEqual(unmet2, ())


if __name__ == "__main__":
    unittest.main()
