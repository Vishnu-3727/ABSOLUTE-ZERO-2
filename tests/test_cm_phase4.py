"""CM Phase 4 suite — CM/00-implementation-blueprint.md Phase 4
(Budget, assembly, validation).

Covers: budget sweep never exceeds ceiling; overflow event fires with
correct payload iff material was degraded/dropped; priority-order
trimming (lowest priority degrades/drops first); end-to-end determinism
(gather -> resolve -> dedup -> prioritize -> assemble twice -> identical
canonical bytes + hash); each validator gate blocks its bad-artifact
class; assembler emits context.assembled with the correct payload; source
candidates unmutated after assembly; malformed inputs raise.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cm import budgeter as budgeter_mod
from cm import dedup as dedup_mod
from cm import prioritizer as prioritizer_mod
from cm import resolver as resolver_mod
from cm import sources, spec as spec_mod
from cm import validator as validator_mod
from cm.assembler import Assembler
from cm.config_view import ConfigView, DEFAULT
from cm.request_memory import SECTION_NAMES, canonical as rm_canonical, content_hash
from fixtures.cm_bundle import build_bundle


def _cand(id_, section="symbols", score=1.0, full_n=3, section_n=2, ref_n=1, stale=False):
    return {"id": id_, "section": section, "score": score, "stale": stale,
            "provenance": {"source": "test"},
            "content": {"full": "f " * full_n, "section": "s " * section_n,
                        "reference": "r " * ref_n}}


class BudgeterTests(unittest.TestCase):
    def setUp(self):
        self.config = ConfigView(DEFAULT)

    def test_ceiling_never_exceeded_across_budget_sweep(self):
        candidates = [_cand(str(i), score=float(-i), full_n=7, section_n=5, ref_n=2)
                      for i in range(10)]
        for budget in range(0, 300, 3):
            result = budgeter_mod.fit(candidates, budget, self.config)
            self.assertLessEqual(result["tokens_used"], budget)

    def test_section_envelopes_sum_to_budget(self):
        for budget in (0, 1, 17, 500, 8000):
            env = budgeter_mod.section_envelopes(self.config, budget)
            self.assertEqual(sum(env.values()), budget)

    def test_priority_order_trimming_lowest_priority_first(self):
        # two same-section candidates, priority order given highest-first;
        # the section envelope is consumed in that order, so "high" must
        # never fare worse than "low" -- it gets first claim on both the
        # section envelope and the global ceiling.
        candidates = [_cand("high", score=2.0, full_n=6, section_n=3, ref_n=1),
                      _cand("low", score=1.0, full_n=6, section_n=3, ref_n=1)]
        result = budgeter_mod.fit(candidates, 7, self.config)
        by_id = {item["id"]: item for item in result["items"]}
        if "high" in by_id and "low" in by_id:
            high_rank = budgeter_mod.TIERS.index(by_id["high"]["fidelity"])
            low_rank = budgeter_mod.TIERS.index(by_id["low"]["fidelity"])
            self.assertLessEqual(high_rank, low_rank)  # high is same-or-better fidelity
        elif "low" in by_id:
            self.fail("lower-priority item survived while higher-priority item was dropped")
        else:
            self.assertIn("high", by_id)

    def test_malformed_candidate_raises(self):
        with self.assertRaises(ValueError):
            budgeter_mod.fit([{"id": "x", "section": "symbols"}], 100, self.config)
        with self.assertRaises(ValueError):
            budgeter_mod.fit([_cand("x", section="not_a_section")], 100, self.config)

    def test_source_candidates_unmutated(self):
        original = _cand("a")
        snapshot = dict(original)
        budgeter_mod.fit([original], 100, self.config)
        self.assertEqual(original, snapshot)


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.config = ConfigView(DEFAULT)
        self.bus = None

    def _assemble(self, spec, candidates):
        from cm.bus_double import BusDouble
        bus = BusDouble()
        return Assembler().assemble(spec, candidates, self.config, bus), bus

    def test_blocks_ceiling_breach(self):
        from cm.request_memory import build as build_rm
        rm = build_rm("r1", "h1", "obj",
                      sections={"symbols": ({"id": "s1", "section": "symbols", "score": 1.0,
                                             "stale": False, "provenance": {"source": "x"},
                                             "content": "x"},)},
                      budget_meta={"budget_tokens": 1, "tokens_used": 5})
        ok, reason = validator_mod.validate(rm)
        self.assertFalse(ok)
        self.assertEqual(reason, "validator.ceiling_exceeded")

    def test_blocks_duplicate_ids(self):
        from cm.request_memory import build as build_rm
        item = lambda: {"id": "dup", "section": "symbols", "score": 1.0, "stale": False,
                        "provenance": {"source": "x"}, "content": "x"}
        rm = build_rm("r1", "h1", "obj", sections={"symbols": (item(), item())},
                     budget_meta={"budget_tokens": 100, "tokens_used": 2})
        ok, reason = validator_mod.validate(rm)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("validator.duplicate_id"))

    def test_blocks_missing_provenance(self):
        from cm.request_memory import build as build_rm
        rm = build_rm("r1", "h1", "obj",
                      sections={"symbols": ({"id": "s1", "section": "symbols", "score": 1.0,
                                             "stale": False, "provenance": {}, "content": "x"},)},
                      budget_meta={"budget_tokens": 100, "tokens_used": 1})
        ok, reason = validator_mod.validate(rm)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("validator.missing_provenance"))

    def test_blocks_missing_section(self):
        import dataclasses
        from types import MappingProxyType
        from cm.request_memory import build as build_rm
        rm = build_rm("r1", "h1", "obj", budget_meta={"budget_tokens": 10, "tokens_used": 0})
        truncated = dataclasses.replace(rm, sections=MappingProxyType(
            {k: v for k, v in rm.sections.items() if k != "files"}))
        ok, reason = validator_mod.validate(truncated)
        self.assertFalse(ok)
        self.assertEqual(reason, "validator.missing_section")

    def test_assembler_raises_on_underlying_validation_failure(self):
        # a spec whose objective/constraints are fine but candidates carry
        # duplicate ids after budgeting -> assembler must raise loud, never
        # silently repair.
        spec = spec_mod.build("r1", "obj", 100)
        dup_candidates = [_cand("same", section="symbols"), _cand("same", section="symbols")]
        with self.assertRaises(ValueError):
            self._assemble(spec, dup_candidates)


class AssemblerTests(unittest.TestCase):
    def setUp(self):
        self.config = ConfigView(DEFAULT)

    def test_emits_context_assembled_with_correct_payload(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "do the thing", 100)
        candidates = [_cand("s1", section="symbols", score=2.0),
                      _cand("f1", section="files", score=1.0)]
        bus = BusDouble()
        rm = Assembler().assemble(spec, candidates, self.config, bus)
        messages = bus.messages("context.assembled")
        self.assertEqual(len(messages), 1)
        payload = messages[0]["payload"]
        self.assertEqual(payload["request_id"], "r1")
        self.assertEqual(payload["memory_id"], rm.memory_id)
        self.assertEqual(payload["hash"], content_hash(rm))
        self.assertEqual(payload["tokens_used"], rm.budget_meta["tokens_used"])
        self.assertEqual(set(payload), {"request_id", "memory_id", "hash", "tokens_used", "coverage"})

    def test_no_overflow_event_when_everything_fits(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "obj", 1000)
        candidates = [_cand("s1"), _cand("f1", section="files")]
        bus = BusDouble()
        Assembler().assemble(spec, candidates, self.config, bus)
        self.assertEqual(bus.messages("context.overflow"), [])

    def test_overflow_event_fires_when_material_exceeds_budget(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "obj", 2)  # tiny -> forces drop/degrade
        candidates = [_cand(str(i), score=float(-i), full_n=6, section_n=4, ref_n=2)
                      for i in range(5)]
        bus = BusDouble()
        rm = Assembler().assemble(spec, candidates, self.config, bus)
        self.assertTrue(rm.budget_meta["truncated"])
        overflow_msgs = bus.messages("context.overflow")
        self.assertEqual(len(overflow_msgs), 1)
        payload = overflow_msgs[0]["payload"]
        self.assertEqual(payload["budget_tokens"], 2)
        self.assertEqual(payload["tokens_used"], rm.budget_meta["tokens_used"])

    def test_source_candidates_unmutated_after_assembly(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "obj", 50)
        candidates = [_cand("s1"), _cand("f1", section="files")]
        snapshot = [dict(c) for c in candidates]
        Assembler().assemble(spec, candidates, self.config, BusDouble())
        self.assertEqual(candidates, snapshot)

    def test_malformed_candidates_raise(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "obj", 50)
        with self.assertRaises(ValueError):
            Assembler().assemble(spec, "not-a-list", self.config, BusDouble())

    def test_log_before_publish(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build("r1", "obj", 50)
        candidates = [_cand("s1")]
        bus = BusDouble()
        asm = Assembler()
        rm = asm.assemble(spec, candidates, self.config, bus)
        self.assertEqual(len(asm.log), 1)
        self.assertEqual(asm.log[0]["memory_id"], rm.memory_id)
        self.assertEqual(asm.log[0]["hash"], content_hash(rm))


class EndToEndDeterminismTests(unittest.TestCase):
    """gather -> resolve -> dedup -> prioritize -> assemble, twice, must
    yield byte-identical Request Memory (Law 6 / CM-I2)."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()
        cls.config = ConfigView(DEFAULT)

    def _run(self):
        from cm.bus_double import BusDouble
        spec = spec_mod.build(request_id="r1", objective="add", budget_tokens=200,
                               references=["knowledge:k1"])
        candidates, _ = sources.gather(spec, self.bundle, "r1")
        edges = [{"src": c["id"], "dst": c["id"] + ":dep"} for c in candidates
                  if c["provenance"]["source"] == "ums"]
        expanded, _trace = resolver_mod.expand(candidates, edges, self.config.resolver_depth_cap)
        deduped = dedup_mod.dedup(expanded)
        prioritized = prioritizer_mod.prioritize(deduped, self.config)
        bus = BusDouble()
        rm = Assembler().assemble(spec, prioritized, self.config, bus)
        return rm, bus

    def test_full_pipeline_replay_is_byte_identical(self):
        rm1, bus1 = self._run()
        rm2, bus2 = self._run()
        self.assertEqual(rm_canonical(rm1), rm_canonical(rm2))
        self.assertEqual(content_hash(rm1), content_hash(rm2))
        self.assertEqual(rm1.memory_id, rm2.memory_id)
        self.assertEqual(bus1.messages("context.assembled")[0]["payload"],
                         bus2.messages("context.assembled")[0]["payload"])

    def test_all_required_sections_present(self):
        rm, _bus = self._run()
        self.assertEqual(set(rm.sections), set(SECTION_NAMES))


if __name__ == "__main__":
    unittest.main()
