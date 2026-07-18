"""C3 System Integration, phase 1: the OS composition root exists in src
and runs the wired pipeline end to end over the REAL substrate.

Charter guards, not behavior duplicates: the pipeline's own laws are
tested where they live (kernel, ws, execution, communication suites).
This file asserts the WHOLE: one System object, one submit(), a completed
request whose evidence sits in the kernel ledger, the bus replay log, and
Storage on disk.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from system import System  # noqa: E402


class SystemPhase1(unittest.TestCase):
    def test_full_pipeline_over_real_substrate(self):
        with tempfile.TemporaryDirectory() as td:
            system = System(td)
            try:
                system.subscribe_observer("probe")
                record = system.submit("build",
                                       ["analyze the repo", "report"])
                rid = record["request_id"]

                # kernel ledger: request completed through real gates
                entry = system.kernel.ledger.get(rid)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.lifecycle_state, "completed")

                # workflow ran every unit to a verified terminal state
                run = record["run"]
                self.assertEqual(run.status, "completed")
                self.assertTrue(all(state == "succeeded"
                                    for state in run.unit_state.values()),
                                run.unit_state)

                # the stand-in seams are labeled, never silent
                self.assertIn("VAE", record["provenance"]["verification"])
                self.assertIn("PRT", record["provenance"]["binding"])

                # governance really consulted: EP bound at admission, the
                # ALLOW decision stamped and replayable
                gov = record["governance"]
                self.assertEqual(gov["admission"]["effect"], "ALLOW")
                self.assertTrue(gov["ep_stamp"])
                self.assertTrue(gov["admission"]["question_hash"])

                # a denied operation refuses BEFORE the kernel sees it:
                # the constitution's final DENY on approval.waive
                from sgpe.evaluator import build_question
                view = system.governance.view_for(gov["ep_stamp"])
                denied = view.consult(build_question(
                    "kernel", rid, "workbench", "approval", "waive",
                    "workflow", {}))
                self.assertEqual(denied.effect_kind, "DENY")

                # bus: events landed on the replay log (durable, sequenced)
                self.assertTrue(system.bus.replay("request.completed"))

                # storage: journals really on disk under owner namespaces
                self.assertTrue(system.store.keys("communication"))
                self.assertTrue(system.store.keys("execution"))
                self.assertTrue(system.store.keys("ws"))
            finally:
                system.close()

    def test_gateway_session_is_composition_free(self):
        """The gateway must consume src/system.py, not re-assemble the OS.
        Guard: session.py imports System and constructs no component
        directly (the UI adapter stays an adapter)."""
        here = os.path.dirname(os.path.abspath(__file__))
        session_path = os.path.join(here, "..", "workbench", "gateway",
                                    "session.py")
        source = open(session_path, encoding="utf-8").read()
        self.assertIn("from system import System", source)
        for forbidden in ("Coordinator(", "Engine(", "Bus(",
                          "compile_workflow(", "build_artifact("):
            self.assertNotIn(forbidden, source,
                             "gateway composes %s itself" % forbidden)


if __name__ == "__main__":
    unittest.main()
