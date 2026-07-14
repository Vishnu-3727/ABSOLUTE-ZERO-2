"""PRT Phase 5 suite — PRT/05-system-integration.md (PRT-S1..S9).
Integration only: discovery -> admission -> binding -> load -> evidence ->
health -> rebind, on one PluginRuntime; reliability/health separation;
lifecycle retirement; full replay from artifacts alone (zero live-world
reads); event-stream determinism; persistence round trip; lifecycle
legality refusal; BindingFailure surfacing; law_enforcer green.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from prt import law_enforcer, persistence
from prt.binding import BindingContract, BindingFailure
from prt.declarations import build_declaration
from prt.discovery import FixtureSource
from prt.load_policy import LoadStateTracker
from prt.records import build_binding, build_capability, build_provider
from prt.runtime import PluginRuntime


def _two_provider_setup(rt, cap_id="cap.p5.x", pid_a="prov.p5.a", pid_b="prov.p5.b"):
    cap = build_capability(cap_id, "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    prov_a = build_provider(pid_a, "1.0")
    prov_b = build_provider(pid_b, "1.0")
    decl_a = build_declaration(prov_a, capabilities=(cap,),
                              bindings=(build_binding(cap_id, pid_a),))
    decl_b = build_declaration(prov_b, bindings=(build_binding(cap_id, pid_b),))
    candidacies = rt.discover_and_admit([FixtureSource([decl_a, decl_b])])
    assert all(c.state == "ADMITTED" for c in candidacies), candidacies
    return cap_id, pid_a, pid_b


def _fail(rt, provider_id, n):
    for _ in range(n):
        rt.bus.publish("exec.failed", {"event_name": "exec.failed",
                                       "subject_id": provider_id, "payload": {}})
    return rt.drain_and_handle()


class FullLoopTests(unittest.TestCase):
    """discovery -> admission -> binding -> load -> evidence -> health ->
    rebind, one degrading provider, next bind picks the healthy one."""

    def test_multi_provider_degrade_and_rebind(self):
        rt = PluginRuntime()
        cap_id, pid_a, pid_b = _two_provider_setup(rt)

        first = rt.bind(cap_id)
        self.assertIsInstance(first, BindingContract)
        self.assertEqual(first.provider_id, pid_a)  # stable-id tie-break, no evidence yet

        # load prov.a through its lifecycle
        self.assertTrue(rt.load_tracker.request_transition(pid_a, "LOADING"))
        self.assertTrue(rt.load_tracker.request_transition(pid_a, "PREPARED"))
        self.assertTrue(rt.load_tracker.request_transition(pid_a, "LOADED"))
        self.assertEqual(len(rt.bus.messages("plugin.loaded")), 1)

        # degrade prov.a to quarantine via exec.failed events (refusal reasons
        # recorded along the way, availability barred once quarantined)
        handled = _fail(rt, pid_a, 3)
        self.assertEqual(handled.count("exec.failed"), 3)
        self.assertEqual(rt.health.state(pid_a), "QUARANTINED")

        second = rt.bind(cap_id)
        self.assertIsInstance(second, BindingContract)
        self.assertEqual(second.provider_id, pid_b)  # the healthy one, picked instead

        # refusal reasons for the barred provider are visible via explain()
        # on the FAILURE path when NO provider is eligible (both barred)
        _fail(rt, pid_b, 3)
        failure = rt.bind(cap_id)
        self.assertIsInstance(failure, BindingFailure)
        self.assertIn(pid_a, dict(failure.reasons))
        self.assertIn(pid_b, dict(failure.reasons))


class HealthReliabilitySeparationTests(unittest.TestCase):
    """reliability.updated arrives mid-stream: next snapshot reflects the
    updated prior, availability unchanged (health/reliability separation,
    PRT/04 §5)."""

    def test_reliability_update_changes_reliability_not_availability(self):
        rt = PluginRuntime()
        cap_id, pid_a, _ = _two_provider_setup(rt)
        before = rt.health.snapshot([pid_a]).get(pid_a)
        self.assertEqual(before["availability"], "available")

        rt.bus.publish("reliability.updated", {
            "event_name": "reliability.updated", "subject_id": pid_a,
            "payload": {"provider_id": pid_a, "prior": 0.99, "priors_version": 1}})
        handled = rt.drain_and_handle()
        self.assertIn("reliability.updated", handled)

        after = rt.health.snapshot([pid_a]).get(pid_a)
        self.assertEqual(after["availability"], "available")  # unchanged
        self.assertEqual(after["reliability"], 0.99)           # updated
        self.assertNotEqual(before["reliability"], after["reliability"])


class RetirementTests(unittest.TestCase):
    """plugin.lifecycle.changed retirement: registry version mint +
    bindings removed + historic contracts/at_version intact."""

    def test_retirement_mints_version_removes_bindings_history_intact(self):
        rt = PluginRuntime()
        cap_id, pid_a, pid_b = _two_provider_setup(rt)

        contract = rt.bind(cap_id)
        version_at_bind = contract.registry_version
        self.assertTrue(rt.registry.bindings_for(cap_id))

        rt.bus.publish("plugin.lifecycle.changed", {
            "event_name": "plugin.lifecycle.changed", "subject_id": pid_a,
            "payload": {"entity": "provider", "id": pid_a, "to_state": "deprecated"}})
        rt.drain_and_handle()
        rt.bus.publish("plugin.lifecycle.changed", {
            "event_name": "plugin.lifecycle.changed", "subject_id": pid_a,
            "payload": {"entity": "provider", "id": pid_a, "to_state": "retired"}})
        rt.drain_and_handle()

        self.assertGreater(rt.registry.current_version, version_at_bind)
        remaining = [b.provider_id for b in rt.registry.bindings_for(cap_id)]
        self.assertNotIn(pid_a, remaining)
        self.assertIn(pid_b, remaining)

        # historic contract/at_version snapshot from before retirement is
        # untouched (PRT-S7): prov.a's binding still resolves at that version
        historic = rt.registry.at_version(version_at_bind)
        self.assertIn(pid_a, [b.provider_id for b in historic.bindings_for(cap_id)])


class FullReplayTests(unittest.TestCase):
    """After the whole scenario, reconstruct from artifacts ALONE: persisted
    registry snapshot -> load_into_new_registry; journal folds; original
    contract's coordinates -> resolve against at_version + rebuilt snapshot
    == original contract, byte-identical, zero live-world reads."""

    def test_full_replay_from_artifacts_alone(self):
        rt = PluginRuntime()
        cap_id, pid_a, pid_b = _two_provider_setup(rt)
        contract = rt.bind(cap_id)
        rt.persist()

        # replay_bind: reconstructs at_version + persisted snapshot artifact,
        # never touches rt.registry's LIVE state or rt.health's live view
        replayed = rt.replay_bind(contract)
        self.assertIsInstance(replayed, BindingContract)
        self.assertEqual(replayed.contract_id, contract.contract_id)
        self.assertEqual(replayed.content_hash(), contract.content_hash())

        # registry persistence: reconstruct a WHOLE new registry from the
        # persisted snapshot alone (content-equal, version carried alongside)
        restored, persisted_version = persistence.load_registry(rt.storage)
        self.assertEqual(persisted_version, rt.registry.current_version)
        self.assertEqual(restored.get_capability(cap_id).id, cap_id)
        self.assertEqual(
            sorted(b.provider_id for b in restored.bindings_for(cap_id)),
            sorted(b.provider_id for b in rt.registry.bindings_for(cap_id)))

        # even after further LIVE health changes, the original contract's
        # frozen coordinates still replay to the identical contract (PRT-H8)
        _fail(rt, pid_a, 5)
        self.assertNotEqual(rt.health.state(pid_a), "HEALTHY")
        replayed_again = rt.replay_bind(contract)
        self.assertEqual(replayed_again.contract_id, contract.contract_id)


class EventStreamDeterminismTests(unittest.TestCase):
    """Event stream on the bus is canon names only, deterministic order
    across two identical runs."""

    def _run(self):
        rt = PluginRuntime()
        cap_id, pid_a, pid_b = _two_provider_setup(rt)
        rt.bind(cap_id)
        _fail(rt, pid_a, 3)
        rt.bind(cap_id)
        published = []
        for topic in ("plugin.discovered", "plugin.registered", "plugin.loaded",
                     "plugin.unloaded", "plugin.health.changed"):
            for msg in rt.bus.messages(topic):
                published.append((msg["event_name"], msg["subject_id"]))
        return published

    def test_canon_names_only_and_deterministic_across_runs(self):
        from prt import events
        run1, run2 = self._run(), self._run()
        self.assertEqual(run1, run2)
        for event_name, _ in run1:
            self.assertIn(event_name, events.PUBLISHED)


class PersistenceRoundTripTests(unittest.TestCase):
    def test_content_hash_equality_round_trip(self):
        rt = PluginRuntime()
        _two_provider_setup(rt)
        data = rt.persist()
        restored, _ = persistence.load_registry(rt.storage)
        # re-persisting the restored registry (fresh Storage) yields the
        # same content (version-independent comparison, module ponytail note)
        from prt.storage_double import StorageDouble
        store2 = StorageDouble()
        persistence.persist_registry(restored, store2)
        import json
        original_no_version = {k: v for k, v in json.loads(data).items() if k != "version"}
        restored_no_version = {k: v for k, v in
                               json.loads(store2.read(persistence.SNAPSHOT_KEY)).items()
                               if k != "version"}
        self.assertEqual(original_no_version, restored_no_version)


class LifecycleLegalityRefusalTests(unittest.TestCase):
    """Illegal health/load transition refused end to end: no state change,
    no event."""

    def test_illegal_health_transition_refused(self):
        rt = PluginRuntime()
        cap_id, pid_a, _ = _two_provider_setup(rt)
        self.assertEqual(rt.health.state(pid_a), "HEALTHY")
        # HEALTHY -> RECOVERING is not in HEALTH_TRANSITIONS, and no code
        # path in health.py's _step ever proposes it -- verify the table
        # itself refuses it directly (defense in depth over the callable
        # health.py actually injects).
        self.assertFalse(rt.health_legality(pid_a, "HEALTHY", "RECOVERING"))

    def test_illegal_load_transition_refused_no_state_change_no_event(self):
        rt = PluginRuntime()
        cap_id, pid_a, _ = _two_provider_setup(rt)
        self.assertTrue(rt.load_tracker.request_transition(pid_a, "LOADING"))
        before_events = len(rt.bus.messages("plugin.loaded"))
        # LOADING -> LOADED is shape-illegal (must pass through PREPARED)
        result = rt.load_tracker.request_transition(pid_a, "LOADED")
        self.assertFalse(result)
        self.assertEqual(rt.load_tracker.state(pid_a), "LOADING")  # unchanged
        self.assertEqual(len(rt.bus.messages("plugin.loaded")), before_events)  # no event


class BindingFailureSurfacesTests(unittest.TestCase):
    def test_binding_failure_is_an_ordinary_ok_result(self):
        rt = PluginRuntime()
        result = rt.bind("cap.does.not.exist")
        self.assertIsInstance(result, BindingFailure)
        self.assertTrue(result.unknown_capability)


class LawEnforcerTests(unittest.TestCase):
    def test_law_enforcer_green(self):
        self.assertTrue(law_enforcer.run())


if __name__ == "__main__":
    unittest.main()
