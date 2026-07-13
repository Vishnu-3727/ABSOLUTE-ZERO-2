"""UMS Phase 2 completion-criteria suite — UMS/00-implementation-blueprint.md.

Criteria: fixture repo -> asserted (golden) symbol table + edge list,
reproducible run-to-run; extraction consumes only Phase-1 inventory
(never re-walks disk — grep-level check); unparseable file recorded as
unparsed, loud, never silently skipped; unchanged content never re-read.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ums import extraction, inventory
from ums.storage_double import StorageDouble

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_REPO = os.path.join(TESTS_DIR, "fixtures", "ums_repo").replace(os.sep, "/")
UMS_DIR = os.path.join(TESTS_DIR, "..", "src", "ums")
PHASE2_MODULES = ("classify.py", "symbols.py", "deps.py", "conventions.py",
                  "module_model.py", "extraction.py")


class UmsPhase2Case(unittest.TestCase):
    def setUp(self):
        self.store = StorageDouble()
        self.inv = inventory.scan(FIXTURE_REPO, self.store)
        self.out = extraction.extract_repo(self.inv, self.store, FIXTURE_REPO)

    # -- golden symbol table ----------------------------------------------
    def test_golden_symbol_table(self):
        core = self.out["files"]["pkg/core.py"]
        self.assertEqual(core["symbols"], [
            {"name": "add", "qualname": "add", "kind": "function", "line": 4,
             "signature": "(a: int, b: int) -> int", "doc": "Add two numbers."},
            {"name": "Calc", "qualname": "Calc", "kind": "class", "line": 9,
             "signature": "", "doc": "Tiny calculator."},
            {"name": "mul", "qualname": "Calc.mul", "kind": "method",
             "line": 12, "signature": "(self, a, b)", "doc": None},
        ])
        self.assertEqual(
            [s["qualname"] for s in self.out["files"]["app.py"]["symbols"]],
            ["main"])
        # non-Python = file-level record, no symbol table
        self.assertIsNone(self.out["files"]["README.md"]["symbols"])
        self.assertEqual(self.out["files"]["README.md"]["classification"],
                         {"language": "markdown", "role": "doc"})
        self.assertEqual(self.out["files"]["settings.toml"]["classification"],
                         {"language": "toml", "role": "config"})

    # -- golden edge list ---------------------------------------------------
    def test_golden_edge_list(self):
        imports = [e for e in self.out["graph"]["edges"]
                   if e["kind"] == "imports"]
        self.assertEqual(imports, [
            {"kind": "imports", "src": "file:app.py", "dst": "module:os",
             "dep": "stdlib"},
            {"kind": "imports", "src": "file:app.py", "dst": "module:pkg.core",
             "dep": "internal"},
            {"kind": "imports", "src": "file:app.py", "dst": "module:requests",
             "dep": "third_party"},
            {"kind": "imports", "src": "file:pkg/__init__.py",
             "dst": "module:pkg.core", "dep": "internal"},
        ])
        contains = {(e["src"], e["dst"]) for e in self.out["graph"]["edges"]
                    if e["kind"] == "contains"}
        self.assertIn(("module:pkg.core", "file:pkg/core.py"), contains)
        self.assertIn(("file:pkg/core.py", "sym:pkg/core.py:Calc.mul"), contains)
        self.assertEqual(self.out["modules"]["packages"], ["pkg"])
        self.assertEqual(self.out["modules"]["top_level"],
                         ["app", "broken", "pkg", "util"])

    # -- unparsed accounting: loud, never skipped ---------------------------
    def test_unparsed_recorded_loud(self):
        self.assertEqual(self.out["unparsed"], ["broken.py"])
        entry = self.out["files"]["broken.py"]
        self.assertTrue(entry["unparsed"].startswith("SyntaxError"))
        self.assertIsNone(entry["symbols"])
        self.assertIn("broken.py", self.out["files"])  # present, not skipped
        # unparsed file still classified and inventoried
        self.assertEqual(entry["classification"]["language"], "python")

    # -- determinism ---------------------------------------------------------
    def test_run_to_run_determinism(self):
        again = extraction.extract_repo(self.inv, self.store, FIXTURE_REPO)
        self.assertEqual(extraction.canonical(again),
                         extraction.canonical(self.out))

    # -- token law: unchanged content never re-read --------------------------
    def test_unchanged_hash_reuses_records_zero_reads(self):
        reads = self.store.bytes_read_calls
        again = extraction.extract_repo(self.inv, self.store, FIXTURE_REPO,
                                        previous=self.out)
        self.assertEqual(self.store.bytes_read_calls, reads)  # zero new reads
        self.assertEqual(extraction.canonical(again),
                         extraction.canonical(self.out))
        for path in self.inv:
            self.assertIs(again["files"][path], self.out["files"][path])

    # -- law check: extraction never walks disk ------------------------------
    def test_no_disk_walk_in_phase2_modules(self):
        pattern = re.compile(
            r"os\.walk|os\.listdir|os\.scandir|\bglob\b|os\.stat|\bopen\(")
        for name in PHASE2_MODULES:
            with open(os.path.join(UMS_DIR, name), encoding="utf-8") as handle:
                source = handle.read()
            source = source.split('if __name__ == "__main__":')[0]
            self.assertIsNone(pattern.search(source),
                              "disk access in src/ums/" + name)

    # -- convention profile: measured numbers ---------------------------------
    def test_convention_profile_measured(self):
        prof = self.out["conventions"]
        # parsed python files: app.py, util.py, pkg/core.py, pkg/__init__.py
        self.assertEqual(prof["files_measured"], 4)
        self.assertEqual(prof["indent_common_width"], 4)
        self.assertEqual(prof["counts"]["indent_tab_lines"], 0)
        # defs: main, shout, add, Calc.mul -> docs on shout? no: add only
        self.assertEqual(prof["counts"]["defs"], 4)
        self.assertEqual(prof["docstring_coverage"], round(1 / 4, 4))
        self.assertEqual(prof["hint_coverage"], round(1 / 4, 4))
        self.assertEqual(prof["snake_case_def_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
