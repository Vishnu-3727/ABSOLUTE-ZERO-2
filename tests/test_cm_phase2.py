"""CM Phase 2 suite — CM/00-implementation-blueprint.md Phase 2 (Sources).

Covers: zero duplicated retrieval (UMS query call-count assertion);
provenance completeness; RSM read-only (store never mutated); absent
request handled loud-but-graceful; deterministic candidate order; input
normalization via spec.py; invalid runtime input fails loud.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cm import sources, spec as spec_mod
from fixtures.cm_bundle import build_bundle
from rsm import query as rsm_query
from rsm.ingest import Ingest, make_event, APPLIED
from rsm.journal import Journal
from rsm.store import Store


def _sample_spec(**overrides):
    kwargs = dict(request_id="r1", objective="add", budget_tokens=200,
                  capabilities=["read"], constraints={},
                  references=["knowledge:k1", "experience:e1"])
    kwargs.update(overrides)
    return spec_mod.build(**kwargs)


def _counting_query_fn():
    calls = []

    def fn(bundle, text, budget_tokens, query_class=None):
        calls.append((text, budget_tokens, query_class))
        return sources.ums_query.query(bundle, text, budget_tokens, query_class)

    return fn, calls


class UmsAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()

    def test_zero_duplicated_retrieval_one_call_per_assembly(self):
        fn, calls = _counting_query_fn()
        spec = _sample_spec()
        candidates, call_count = sources.gather(spec, self.bundle, "r1", query_fn=fn)
        self.assertEqual(call_count, 1)
        self.assertEqual(len(calls), 1)  # one query() call covers every planned store

    def test_symbol_and_file_hits_land_in_correct_sections(self):
        spec = _sample_spec(objective="add")
        candidates, _ = sources.gather(spec, self.bundle, "r1")
        sections = {c["section"] for c in candidates if c["provenance"]["source"] == "ums"}
        self.assertTrue(sections <= {"symbols", "files"})
        self.assertIn("symbols", sections)

    def test_stale_passed_through_never_rederived(self):
        self.bundle["freshness"].mark_stale(["pkg/core.py"])
        try:
            spec = _sample_spec(objective="add")
            candidates, _ = sources.gather(spec, self.bundle, "r1")
            core_hits = [c for c in candidates
                        if c["provenance"].get("store") == "symbol"
                        and c["id"] == "sym:pkg/core.py:add"]
            self.assertTrue(core_hits)
            self.assertTrue(core_hits[0]["stale"])
        finally:
            self.bundle["freshness"].track_fresh(["pkg/core.py"])

    def test_unknown_store_kind_has_no_section_mapping_gap(self):
        # every UMS store kind currently defined maps to a real CM section
        self.assertEqual(set(sources._SECTION_BY_KIND.values()) - {"symbols", "files"}, set())


class ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()

    def test_every_candidate_carries_complete_provenance(self):
        spec = _sample_spec()
        candidates, _ = sources.gather(spec, self.bundle, "r1")
        self.assertTrue(candidates)
        for c in candidates:
            self.assertEqual(set(c), {"id", "section", "content", "score", "stale", "provenance"})
            self.assertIn("source", c["provenance"])
            self.assertIn(c["provenance"]["source"], {"ums", "rsm", "reference"})


class RsmAdapterTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.journal = Journal()
        self.ing = Ingest(self.store, self.journal)

    def test_absent_request_handled_loud_but_graceful(self):
        candidates = sources.gather_rsm(self.store, "ghost")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["provenance"]["status"], rsm_query.ABSENT)
        self.assertIsNone(candidates[0]["stale"])

    def test_evicted_request_handled_loud_but_graceful(self):
        self.assertEqual(self.ing.process(make_event(
            "e0", "request.received", "r1", 1, {"declared_type": "a", "origin": "fe"})), APPLIED)
        self.store.mark_evicted("r1")
        candidates = sources.gather_rsm(self.store, "r1")
        self.assertEqual(candidates[0]["provenance"]["status"], rsm_query.EVICTED)

    def test_read_only_store_never_mutated(self):
        self.assertEqual(self.ing.process(make_event(
            "e0", "request.received", "r1", 1, {"declared_type": "a", "origin": "fe"})), APPLIED)
        before = rsm_query.snapshot(self.store, "r1")
        sources.gather_rsm(self.store, "r1")
        after = rsm_query.snapshot(self.store, "r1")
        self.assertEqual(before, after)
        self.assertIs(before, after)  # no evolve() ever called -> same object

    def test_blocks_read_are_identity_plan_budget(self):
        self.assertEqual(self.ing.process(make_event(
            "e0", "request.received", "r1", 1, {"declared_type": "a", "origin": "fe"})), APPLIED)
        candidates = sources.gather_rsm(self.store, "r1")
        self.assertEqual({c["provenance"]["block"] for c in candidates}, set(sources.RSM_BLOCKS))

    def test_store_none_skips_rsm_entirely(self):
        bundle = build_bundle()
        spec = _sample_spec()
        candidates, _ = sources.gather(spec, bundle, "r1", store=None)
        self.assertFalse(any(c["provenance"]["source"] == "rsm" for c in candidates))


class ReferenceResolverTests(unittest.TestCase):
    def test_knowledge_and_experience_resolved(self):
        candidates = sources.resolve_references(["knowledge:k1", "experience:e1"])
        self.assertEqual([c["section"] for c in candidates], ["knowledge", "experience"])
        for c in candidates:
            self.assertEqual(c["provenance"]["source"], "reference")

    def test_malformed_reference_fails_loud(self):
        with self.assertRaises(ValueError):
            sources.resolve_references(["no_colon_here"])

    def test_unknown_section_reference_fails_loud(self):
        with self.assertRaises(ValueError):
            sources.resolve_references(["files:f1"])  # files is not a reference-target section

    def test_empty_reference_id_fails_loud(self):
        with self.assertRaises(ValueError):
            sources.resolve_references(["knowledge:"])


class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle()

    def test_identical_spec_and_state_yields_identical_candidates(self):
        spec = _sample_spec()
        c1, n1 = sources.gather(spec, self.bundle, "r1")
        c2, n2 = sources.gather(spec, self.bundle, "r1")
        self.assertEqual(c1, c2)
        self.assertEqual(n1, n2)

    def test_reference_order_follows_spec_normalization(self):
        # spec.build sorts references regardless of call-site order
        spec_a = _sample_spec(references=["experience:e1", "knowledge:k1"])
        spec_b = _sample_spec(references=["knowledge:k1", "experience:e1"])
        self.assertEqual(spec_a["references"], spec_b["references"])
        ca, _ = sources.gather(spec_a, self.bundle, "r1")
        cb, _ = sources.gather(spec_b, self.bundle, "r1")
        ref_ids_a = [c["id"] for c in ca if c["provenance"]["source"] == "reference"]
        ref_ids_b = [c["id"] for c in cb if c["provenance"]["source"] == "reference"]
        self.assertEqual(ref_ids_a, ref_ids_b)


class InputNormalizationTests(unittest.TestCase):
    def test_gather_uses_normalized_spec_fields(self):
        bundle = build_bundle()
        spec = _sample_spec(references=["experience:e1", "knowledge:k1"])
        self.assertEqual(spec["references"], ["experience:e1", "knowledge:k1"])
        candidates, _ = sources.gather(spec, bundle, "r1")
        self.assertTrue(candidates)


if __name__ == "__main__":
    unittest.main()
