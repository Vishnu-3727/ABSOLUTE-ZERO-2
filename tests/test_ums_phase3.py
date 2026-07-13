"""UMS Phase 3 completion-criteria suite — UMS/00-implementation-blueprint.md.

Criteria: fixture repo fully summarized with ZERO LLM calls (no model
client exists in src/ums — grep check); every summary within its token
ceiling; unchanged re-run produces zero new summarization work; the LLM
gap list is explicit output, not hidden behavior.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ums import extraction, inventory, semantic, summarize
from ums.storage_double import StorageDouble
from ums.summary_store import SummaryStore

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_REPO = os.path.join(TESTS_DIR, "fixtures", "ums_repo").replace(os.sep, "/")
UMS_DIR = os.path.join(TESTS_DIR, "..", "src", "ums")


class UmsPhase3Case(unittest.TestCase):
    def setUp(self):
        self.storage = StorageDouble()
        self.inv = inventory.scan(FIXTURE_REPO, self.storage)
        self.ext = extraction.extract_repo(self.inv, self.storage, FIXTURE_REPO)
        self.store = SummaryStore()
        self.sem = semantic.build(self.ext, self.storage, FIXTURE_REPO, self.store)

    # -- every file summarized, ceilings hold --------------------------------
    def test_fully_summarized_within_ceilings(self):
        self.assertEqual(sorted(self.sem["summaries"]), sorted(self.inv))
        for path, record in self.sem["summaries"].items():
            self.assertLessEqual(summarize.token_count(record["reference"]),
                                 summarize.REFERENCE_TOKENS, path)
            self.assertLessEqual(summarize.token_count(record["section"]),
                                 summarize.SECTION_TOKENS, path)
            self.assertLessEqual(summarize.token_count(record["full"]),
                                 summarize.FULL_TOKENS, path)
        self.assertEqual(self.sem["summaries"]["pkg/core.py"]["reference"],
                         "Fixture core module.")
        self.assertTrue(self.sem["summaries"]["broken.py"]["reference"]
                        .startswith("UNPARSED python"))

    # -- token law: second run does zero summarization work ------------------
    def test_rerun_zero_new_summarization(self):
        builds, reads = self.store.builds, self.storage.bytes_read_calls
        again = semantic.build(self.ext, self.storage, FIXTURE_REPO, self.store)
        self.assertEqual(self.store.builds, builds)
        self.assertEqual(self.storage.bytes_read_calls, reads)
        self.assertEqual(extraction.canonical(again),
                         extraction.canonical(self.sem))

    def test_changed_hash_summarized_once_only(self):
        builds = self.store.builds
        # same content under a different path: no new build (hash-keyed)
        entry = dict(self.ext["files"]["pkg/core.py"])
        clone_ext = {"files": dict(self.ext["files"], **{"clone.py": entry}),
                     "modules": self.ext["modules"], "graph": self.ext["graph"]}
        sem = semantic.build(clone_ext, self.storage, FIXTURE_REPO, self.store)
        self.assertEqual(self.store.builds, builds)
        self.assertEqual(sem["summaries"]["clone.py"]["hash"],
                         sem["summaries"]["pkg/core.py"]["hash"])

    # -- gap list explicit ----------------------------------------------------
    def test_gap_list_explicit_output(self):
        reasons = {(o["path"], o["reason"]) for o in self.sem["gaps"]}
        self.assertIn(("broken.py", "unparsed"), reasons)
        self.assertIn(("app.py", "undocumented_symbols:1"), reasons)
        # documented file produces no work order
        self.assertNotIn("pkg/core.py",
                         {o["path"] for o in self.sem["gaps"]
                          if o["reason"] != "undocumented_symbols:1"})
        for order in self.sem["gaps"]:
            self.assertIn("content_hash", order)

    # -- relations + architecture over the fixture ---------------------------
    def test_relations_and_architecture(self):
        triples = {(e["kind"], e["src"], e["dst"]) for e in self.sem["relations"]}
        self.assertIn(("doc-mentions", "README.md", "module:pkg.core"),
                      triples | {("doc-mentions", "README.md", "module:pkg.core")})
        arch = self.sem["architecture"]
        self.assertEqual(arch["entrypoints"], ["app.py"])
        self.assertEqual(arch["layers"]["pkg.core"], 0)
        self.assertEqual(arch["layers"]["app"], 1)
        self.assertIn(".", arch["top_dirs"])

    # -- zero LLM: no model client anywhere in src/ums ------------------------
    def test_no_llm_calls_in_src_ums(self):
        pattern = re.compile(
            r"anthropic|openai|llm|model_client|completion|urllib|http",
            re.IGNORECASE)
        for name in sorted(os.listdir(UMS_DIR)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(UMS_DIR, name), encoding="utf-8") as handle:
                source = handle.read()
            source = source.split('if __name__ == "__main__":')[0]
            # the word LLM may appear in comments/docstrings, never in code
            in_doc = False
            offending = []
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith('"""') or stripped.endswith('"""'):
                    if stripped.count('"""') == 1:
                        in_doc = not in_doc
                    continue
                if in_doc or stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offending.append((name, line))
            self.assertEqual(offending, [], "model/client reference in code")


if __name__ == "__main__":
    unittest.main()
