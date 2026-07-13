"""CM Phase 1 suite — CM/00-implementation-blueprint.md Phase 1 (Foundation
& artifact).

Covers: artifact immutability (mutation attempt raises); byte-identical
serialization replay (build twice from same inputs -> identical bytes +
hash); spec-hash determinism (input order / dict order must not change
hash); event-name closure (invented event name raises); metadata
correctness.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from cm import request_memory
from cm import spec as spec_mod
from cm import events
from cm.bus_double import BusDouble
from cm.config_view import ConfigView, DEFAULT as DEFAULT_CONFIG


def _sample_rm(**overrides):
    kwargs = dict(
        request_id="r1",
        spec_hash="spec-hash-1",
        objective="fix the bug",
        constraints={"max_files": 5},
        sections={"symbols": ({"id": "s1"},), "files": ({"id": "f1", "path": "a.py"},)},
        assembly_meta={"assembled_at": 0},
        validation_meta={"ok": True},
        budget_meta={"budget_tokens": 100, "tokens_used": 10},
    )
    kwargs.update(overrides)
    return request_memory.build(**kwargs)


class RequestMemoryImmutabilityTests(unittest.TestCase):
    def test_field_reassignment_raises(self):
        rm = _sample_rm()
        with self.assertRaises(AttributeError):
            rm.objective = "different"

    def test_constraints_mutation_raises(self):
        rm = _sample_rm()
        with self.assertRaises(TypeError):
            rm.constraints["max_files"] = 999

    def test_sections_mutation_raises(self):
        rm = _sample_rm()
        with self.assertRaises(TypeError):
            rm.sections["symbols"] = ()

    def test_meta_blocks_mutation_raises(self):
        rm = _sample_rm()
        with self.assertRaises(TypeError):
            rm.assembly_meta["assembled_at"] = 1
        with self.assertRaises(TypeError):
            rm.validation_meta["ok"] = False
        with self.assertRaises(TypeError):
            rm.budget_meta["tokens_used"] = 999

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            request_memory.build("r1", "h", "x", sections={"bogus": ()})

    def test_closed_section_tuple_always_present(self):
        rm = request_memory.build("r1", "h", "x")
        self.assertEqual(set(rm.sections), set(request_memory.SECTION_NAMES))
        for name in request_memory.SECTION_NAMES:
            self.assertEqual(rm.sections[name], ())


class RequestMemorySerializationReplayTests(unittest.TestCase):
    def test_byte_identical_replay(self):
        rm1 = _sample_rm()
        rm2 = _sample_rm()
        self.assertEqual(request_memory.canonical(rm1), request_memory.canonical(rm2))
        self.assertEqual(request_memory.content_hash(rm1), request_memory.content_hash(rm2))
        self.assertEqual(rm1.memory_id, rm2.memory_id)

    def test_different_spec_hash_changes_content_hash(self):
        rm1 = _sample_rm()
        rm2 = _sample_rm(spec_hash="spec-hash-2")
        self.assertNotEqual(request_memory.content_hash(rm1), request_memory.content_hash(rm2))
        self.assertNotEqual(rm1.memory_id, rm2.memory_id)

    def test_canonical_is_deterministic_bytes(self):
        rm = _sample_rm()
        self.assertIsInstance(request_memory.canonical(rm), bytes)
        self.assertEqual(request_memory.canonical(rm), request_memory.canonical(rm))


class RequestMemoryMetadataTests(unittest.TestCase):
    def test_metadata_blocks_round_trip(self):
        rm = _sample_rm()
        d = request_memory.to_dict(rm)
        self.assertEqual(d["assembly_meta"], {"assembled_at": 0})
        self.assertEqual(d["validation_meta"], {"ok": True})
        self.assertEqual(d["budget_meta"], {"budget_tokens": 100, "tokens_used": 10})
        self.assertEqual(d["sections"]["symbols"], [{"id": "s1"}])

    def test_request_id_and_objective_preserved(self):
        rm = _sample_rm()
        self.assertEqual(rm.request_id, "r1")
        self.assertEqual(rm.objective, "fix the bug")


class SpecHashDeterminismTests(unittest.TestCase):
    def test_capability_and_reference_order_does_not_change_hash(self):
        s1 = spec_mod.build("r1", "fix bug", 500, capabilities=["read", "write"],
                             constraints={"lang": "py"}, references=["b.md", "a.md"])
        s2 = spec_mod.build("r1", "fix bug", 500, capabilities=["write", "read"],
                             constraints={"lang": "py"}, references=["a.md", "b.md"])
        self.assertEqual(s1, s2)
        self.assertEqual(spec_mod.spec_hash(s1), spec_mod.spec_hash(s2))

    def test_constraints_dict_order_does_not_change_hash(self):
        s1 = spec_mod.build("r1", "x", 10, constraints={"a": 1, "b": 2})
        s2 = spec_mod.build("r1", "x", 10, constraints={"b": 2, "a": 1})
        self.assertEqual(spec_mod.spec_hash(s1), spec_mod.spec_hash(s2))

    def test_duplicate_capabilities_and_references_deduped(self):
        s = spec_mod.build("r1", "x", 10, capabilities=["read", "read"],
                            references=["a.md", "a.md"])
        self.assertEqual(s["capabilities"], ["read"])
        self.assertEqual(s["references"], ["a.md"])

    def test_different_budget_changes_hash(self):
        s1 = spec_mod.build("r1", "x", 10)
        s2 = spec_mod.build("r1", "x", 11)
        self.assertNotEqual(spec_mod.spec_hash(s1), spec_mod.spec_hash(s2))

    def test_bad_request_id_rejected(self):
        for bad in ("", None, 5):
            with self.assertRaises(ValueError):
                spec_mod.build(bad, "x", 10)

    def test_bad_budget_tokens_rejected(self):
        for bad in (-1, "10", True):
            with self.assertRaises(ValueError):
                spec_mod.build("r1", "x", bad)


class EventClosureTests(unittest.TestCase):
    def test_closed_events_publish(self):
        bus = BusDouble()
        events.emit(bus, "context.assembled", "r1",
                    {"request_id": "r1", "memory_id": "m1", "hash": "abc",
                     "tokens_used": 10, "coverage": 1.0})
        events.emit(bus, "context.overflow", "r1", {"dropped": 2})
        events.emit(bus, "context.invalidated", "r1")
        self.assertEqual(bus.messages("context.assembled")[0]["payload"]["memory_id"], "m1")
        self.assertEqual(bus.messages("context.invalidated")[0]["payload"], {})

    def test_invented_event_name_raises_and_nothing_leaks(self):
        bus = BusDouble()
        with self.assertRaises(ValueError):
            events.emit(bus, "context.rebuilt", "r1")
        self.assertEqual(bus.messages("context.rebuilt"), [])

    def test_event_names_closed_set(self):
        self.assertEqual(set(events.EVENT_NAMES),
                          {"context.assembled", "context.overflow", "context.invalidated"})


class ConfigViewTests(unittest.TestCase):
    def test_default_config_valid(self):
        view = ConfigView(DEFAULT_CONFIG)
        self.assertEqual(view.version, 1)
        self.assertGreater(view.default_budget_tokens, 0)

    def test_section_weights_restricted_to_closed_sections(self):
        bad = dict(DEFAULT_CONFIG, section_weights={"not_a_section": 1})
        with self.assertRaises(ValueError):
            ConfigView(bad)

    def test_read_only(self):
        view = ConfigView(DEFAULT_CONFIG)
        with self.assertRaises(AttributeError):
            view.version = 99


if __name__ == "__main__":
    unittest.main()
