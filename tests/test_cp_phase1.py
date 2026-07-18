"""CP Phase 1 — Foundation & vocabulary door (CP/05 blueprint, ERRATA C16).

Artifact immutability + hash determinism + lineage; spec-hash
order-independence; event closure (stale `classify.completed` refused);
registry view alias/lifecycle/version semantics; **scheduler
compatibility**: the artifact's sealed-graph projection compiles through
the real WS compiler unchanged; C16 vocabulary guard on the real bus.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from cp import (ArtifactRefusal, EVENT_NAMES, RegistryView,  # noqa: E402
                RegistryViewRefusal, SpecRefusal, build_artifact, build_spec,
                emit)
from cp.bus_double import BusDouble  # noqa: E402
from cp.registry_double import RegistryDouble  # noqa: E402

DET = {"request_id": "r1", "registry_version": 3, "priors_version": 1,
       "request_memory_hash": "rmh", "config_version": 1}
NODES = {"read": {"capability_id": "cap.read", "origin": "explicit",
                  "priority_band": "CRITICAL", "confidence": 0.9},
         "build": {"capability_id": "cap.build", "origin": "derived",
                   "priority_band": "REQUIRED", "confidence": 0.8},
         "alt-a": {"capability_id": "cap.a", "origin": "derived",
                   "priority_band": "OPTIONAL", "confidence": 0.7,
                   "group_id": "g", "rank": 2},
         "alt-b": {"capability_id": "cap.b", "origin": "derived",
                   "priority_band": "OPTIONAL", "confidence": 0.7,
                   "group_id": "g", "rank": 1}}
EDGES = [("requires", "read", "build"), ("requires", "read", "alt-a"),
         ("requires", "read", "alt-b"), ("alternative-of", "alt-a", "alt-b")]


def artifact(**overrides):
    kwargs = dict(determinism=DET, nodes=NODES, edges=EDGES,
                  groups={"g": ["alt-a", "alt-b"]}, confidence=0.82)
    kwargs.update(overrides)
    return build_artifact(**kwargs)


class TestArtifact(unittest.TestCase):
    def test_deterministic_hash_and_replay(self):
        a, b = artifact(), artifact(nodes=json.loads(json.dumps(NODES)))
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.plan_id, b.plan_id)

    def test_immutable(self):
        a = artifact()
        with self.assertRaises(TypeError):
            a.nodes["read"]["priority_band"] = "DEFERRED"
        with self.assertRaises(TypeError):
            a.determinism["registry_version"] = 99

    def test_lineage(self):
        a = artifact()
        revised = artifact(confidence=0.9,
                           predecessor=(a.plan_id, a.plan_version))
        self.assertEqual(revised.plan_version, 2)
        self.assertEqual(revised.predecessor, (a.plan_id, 1))
        self.assertNotEqual(revised.plan_id, a.plan_id)  # new artifact, never edit

    def test_fail_closed(self):
        for bad in (dict(determinism={"request_id": "r"}),
                    dict(nodes={}),
                    dict(edges=[("requires", "read", "ghost")]),
                    dict(edges=[("orders-before", "read", "build")]),
                    dict(confidence=1.5)):
            with self.assertRaises(ArtifactRefusal):
                artifact(**bad)

    def test_no_provider_awareness(self):
        bad_nodes = json.loads(json.dumps(NODES))
        bad_nodes["read"]["provider_id"] = "plugin.x"
        with self.assertRaises(ArtifactRefusal):
            artifact(nodes=bad_nodes)

    def test_scheduler_compatibility_ws_compiles_unchanged(self):
        from ws import compile_workflow

        sealed = artifact().to_sealed_graph()
        wf = compile_workflow(sealed, ws_config_version=1)
        self.assertEqual(len(wf.units), 4)           # WS-W2: 1:1
        self.assertEqual(len(wf.edges), 3)           # requires-edges only
        self.assertEqual(len(wf.groups["g"]), 2)     # alternatives intact
        # determinism carries through both artifacts
        wf2 = compile_workflow(artifact().to_sealed_graph(), 1)
        self.assertEqual(wf.content_hash, wf2.content_hash)


class TestSpec(unittest.TestCase):
    def test_hash_order_independent_content_by_hash(self):
        a = build_spec("r1", "do it", ["g2", "g1"], ["c2", "c1"], "rmh",
                       {"content": 1}, {"s": 1}, 3, 1, 1)
        b = build_spec("r1", "do it", ["g1", "g2"], ["c1", "c2"], "rmh",
                       {"content": "different"}, {"s": 2}, 3, 1, 1)
        self.assertEqual(a.spec_hash, b.spec_hash)
        self.assertNotEqual(
            a.spec_hash,
            build_spec("r1", "do it", ["g1"], [], "rmh", {}, {}, 4, 1, 1).spec_hash)

    def test_intake_fail_closed(self):
        with self.assertRaises(SpecRefusal):
            build_spec("", "x", [], [], "h", {}, {}, 1, 1, 1)
        with self.assertRaises(SpecRefusal):
            build_spec("r", "   ", [], [], "h", {}, {}, 1, 1, 1)


class TestEvents(unittest.TestCase):
    def test_closed_set(self):
        self.assertEqual(len(EVENT_NAMES), 4)
        bus = BusDouble()
        emit(bus, "intent.classified", "e1",
             {"request_id": "r1", "label": "repair", "confidence": 0.7,
              "alternatives": ["refactor"]})
        self.assertEqual(bus.messages("intent.classified")[0]["payload"]["label"],
                         "repair")
        with self.assertRaises(ValueError):  # C16: stale name refused
            emit(bus, "classify.completed", "e2", {"request_id": "r1"})

    def test_canonical_name_on_real_bus(self):
        from communication import Bus, SchemaViolation

        bus = Bus()
        bus.subscribe("intent.classified", "probe")
        emit(bus, "intent.classified", "e1",
             {"request_id": "r1", "label": "repair", "confidence": 0.7,
              "alternatives": []})
        self.assertEqual(len(bus.drain("intent.classified", "probe")), 1)
        with self.assertRaises(SchemaViolation):  # stale name gone from vocabulary
            bus.publish("classify.completed",
                        {"event_id": "e", "event_name": "classify.completed",
                         "request_id": None, "timestamp": 0, "payload": {}})


class TestRegistryView(unittest.TestCase):
    def setUp(self):
        self.view = RegistryView(
            RegistryDouble(version=7)
            .add("cap.read", relations=(("requires", "cap.fs"),))
            .add("cap.fs")
            .add("cap.old", lifecycle="deprecated", replacement="cap.read")
            .add("cap.gone", lifecycle="retired")
            .alias("read-files", "cap.read").alias("rf", "read-files")
            .alias("loop-a", "loop-b").alias("loop-b", "loop-a"))

    def test_alias_chain_and_version_stamp(self):
        hit = self.view.resolve("rf")
        self.assertEqual(hit["capability_id"], "cap.read")
        self.assertTrue(hit["matchable"])
        self.assertEqual(hit["registry_version"], 7)

    def test_lifecycle_semantics(self):
        dep = self.view.resolve("cap.old")
        self.assertTrue(dep["matchable"])
        self.assertEqual(dep["replacement"], "cap.read")  # recorded, not swapped
        self.assertFalse(self.view.resolve("cap.gone")["matchable"])  # tombstone
        self.assertIsNone(self.view.resolve("cap.never"))  # unknown -> caller gaps

    def test_alias_cycle_fails_loud(self):
        with self.assertRaises(RegistryViewRefusal):
            self.view.resolve("loop-a")

    def test_no_mutation_surface(self):
        for name in dir(self.view):
            self.assertFalse(name.startswith(("add", "set", "write", "delete")),
                             "registry view must expose no mutation: " + name)


if __name__ == "__main__":
    unittest.main()
