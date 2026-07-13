"""RSM Milestone 5 suite — RSM/05-implementation-spec.md M5 (final
milestone).

Covers: coalesced `state.updated` (Lifecycle-block changes immediate, one
per change; Work/Context/Budget-block changes coalesce to at most one
emission per request per configured coalescing interval); the end-to-end
acceptance demo — driving the full ARCHITECTURE.md request-lifecycle event
sequence (admission -> plan -> steps -> verify -> commit -> completed)
through `bus_double`, asserting the final record, the final journal, and a
full journal replay are all byte-identical (RSM-I12); recovery's
reads-closed-until-done gate; and the structural checks RSM/05 §4/§5 call
for (sole-mutator discipline RSM-I2, no-control-on-telemetry RSM-I15,
stdlib-only, exclusion-table grep RSM-I13) — the last milestone is where the
16/16 invariant table (RSM/05 §4) and the §5 validation checklist both close
out.
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rsm.store import Store
from rsm.journal import Journal
from rsm.ingest import Ingest, make_event, APPLIED, DROPPED
from rsm.bus_double import BusDouble
from rsm.config_view import RsmConfigView
from rsm.telemetry import Telemetry, evict_and_notify
from rsm import persistence, recovery, transitions
from ums.storage_double import StorageDouble

SRC_RSM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "rsm")


class FakeClock:
    """Injectable zero-arg time source (no sleep, no wall-clock reads) —
    same shape every earlier phase's tests use."""

    def __init__(self, start=0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# ---------------------------------------------------------------------------
# Coalescing behavior
# ---------------------------------------------------------------------------
class CoalescingTests(unittest.TestCase):
    """RSM/03 §8, RSM/05 M5: Lifecycle-block changes emit immediately, one
    per change, no batching; Work/Context/Budget-block changes coalesce to
    at most one emission per request per configured interval."""

    def _telemetry(self, coalescing_interval=5):
        bus = BusDouble()
        cfg = RsmConfigView(retention_window=100, checkpoint_n=10,
                             coalescing_interval=coalescing_interval)
        clock = FakeClock(0)
        return Telemetry(bus, cfg, clock), bus, clock

    def test_lifecycle_changes_never_coalesce(self):
        tel, bus, clock = self._telemetry()
        for i in range(4):  # rapid-fire, clock never advances
            emitted = tel.state_updated("r1", "request.completed", immediate=True)
            self.assertTrue(emitted)
        self.assertEqual(tel.counters["state_updated"], 4)
        self.assertEqual(len(bus.pending("state.updated")), 4)
        self.assertEqual(tel.counters["coalescing_backlog"], 0)

    def test_work_context_budget_changes_coalesce_to_one_per_interval(self):
        tel, bus, clock = self._telemetry(coalescing_interval=5)
        self.assertTrue(tel.state_updated("r2", "task.scheduled", immediate=False))
        clock.advance(1)
        self.assertFalse(tel.state_updated("r2", "cost.recorded", immediate=False))
        clock.advance(1)
        self.assertFalse(tel.state_updated("r2", "cost.recorded", immediate=False))
        clock.advance(1)
        self.assertFalse(tel.state_updated("r2", "context.assembled", immediate=False))
        # only the first change emitted; three suppressed and counted
        self.assertEqual(tel.counters["state_updated"], 1)
        self.assertEqual(tel.counters["coalescing_backlog"], 3)
        self.assertEqual(len(bus.pending("state.updated")), 1)

        # interval elapses: the next change emits again
        clock.advance(5)
        self.assertTrue(tel.state_updated("r2", "cost.recorded", immediate=False))
        self.assertEqual(tel.counters["state_updated"], 2)

    def test_coalescing_is_per_request_not_global(self):
        tel, bus, clock = self._telemetry(coalescing_interval=5)
        self.assertTrue(tel.state_updated("r1", "task.scheduled", immediate=False))
        # a different request's first change also emits immediately —
        # coalescing tracks each request_id's own last-emit time
        self.assertTrue(tel.state_updated("r2", "task.scheduled", immediate=False))
        self.assertEqual(tel.counters["state_updated"], 2)
        self.assertEqual(tel.counters["coalescing_backlog"], 0)

    def test_eviction_never_coalesces(self):
        tel, bus, clock = self._telemetry(coalescing_interval=1000)
        tel.state_evicted("r1")
        tel.state_evicted("r1")  # a second eviction (different id in practice, but
        self.assertEqual(tel.counters["state_evicted"], 2)  # never gated by the interval

    def test_zero_coalescing_interval_emits_every_change(self):
        tel, bus, clock = self._telemetry(coalescing_interval=0)
        for _ in range(3):
            self.assertTrue(tel.state_updated("r1", "cost.recorded", immediate=False))
        self.assertEqual(tel.counters["coalescing_backlog"], 0)


# ---------------------------------------------------------------------------
# Ingest -> telemetry wiring (RSM-I14: every applied event is observable)
# ---------------------------------------------------------------------------
class IngestTelemetryWiringTests(unittest.TestCase):
    def test_birth_and_terminal_are_immediate_others_coalesce(self):
        bus = BusDouble()
        cfg = RsmConfigView(retention_window=100, checkpoint_n=10, coalescing_interval=1000)
        clock = FakeClock(0)
        tel = Telemetry(bus, cfg, clock)
        store, journal = Store(), Journal()
        ing = Ingest(store, journal, telemetry=tel)

        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ing.process(make_event("e1", "task.scheduled", "r1", 1,
                                {"task_id": "t1", "budget_granted": 10}))
        ing.process(make_event("e2", "task.started", "r1", 1, {"task_id": "t1"}))
        ing.process(make_event("e3", "request.completed", "r1", 1, {}))

        # birth + terminal both emitted (immediate); the two contributing
        # family changes in between were coalesced (interval never elapses)
        self.assertEqual(tel.counters["state_updated"], 2)
        self.assertEqual(tel.counters["coalescing_backlog"], 2)
        # but the record and journal reflect every applied event regardless
        # (RSM-I15: telemetry suppression never touches the write path)
        self.assertEqual(len(journal.entries("r1")), 4)
        self.assertEqual(store.get("r1").work["tasks"]["t1"]["state"], "started")

    def test_fault_always_emits(self):
        bus = BusDouble()
        cfg = RsmConfigView(retention_window=100, checkpoint_n=10, coalescing_interval=1000)
        clock = FakeClock(0)
        tel = Telemetry(bus, cfg, clock)
        store, journal = Store(), Journal()
        ing = Ingest(store, journal, telemetry=tel)

        ing.process(make_event("e0", "task.started", "ghost", 1, {"task_id": "t1"}))
        self.assertEqual(tel.counters["fault_recorded"], 1)
        self.assertEqual(len(bus.pending("fault.recorded")), 1)

    def test_telemetry_optional_no_telemetry_still_works(self):
        # M1-M4 call sites: Ingest(store, journal), no telemetry — must be
        # unaffected by M5's wiring.
        store, journal = Store(), Journal()
        ing = Ingest(store, journal)
        result = ing.process(make_event("e0", "request.received", "r1", 1,
                                         {"declared_type": "a", "origin": "fe"}))
        self.assertEqual(result, APPLIED)


# ---------------------------------------------------------------------------
# End-to-end acceptance demo (RSM/05 M5, the closest thing RSM has to one)
# ---------------------------------------------------------------------------
class EndToEndLifecycleTests(unittest.TestCase):
    """Drives the full ARCHITECTURE.md request-lifecycle sequence
    (admission -> plan -> steps -> verify -> commit -> completed,
    ARCHITECTURE.md request-lifecycle sequence diagram) through
    `bus_double`, asserting the final record, the final journal, and a full
    journal replay are all identical (RSM-I12)."""

    def _script(self, request_id):
        return [
            # admission
            ("request.received", make_event("e0", "request.received", request_id, 1,
                                              {"declared_type": "type.alpha", "origin": "frontend"})),
            # plan
            ("classify.completed", make_event("e1", "classify.completed", request_id, 1,
                                               {"classification_ref": "cls-1"})),
            ("plan.created", make_event("e2", "plan.created", request_id, 1,
                                         {"plan_id": "p1", "revision": 0})),
            ("plan.validated", make_event("e3", "plan.validated", request_id, 1,
                                           {"verdict_ref": "v-plan-1"})),
            # steps (context assembly, schedule, start, execute)
            ("context.assembled", make_event("e4", "context.assembled", request_id, 1,
                                              {"step": "s1", "context_package_id": "ctx-1"})),
            ("task.scheduled", make_event("e5", "task.scheduled", request_id, 1,
                                           {"task_id": "t1", "budget_granted": 10})),
            ("task.started", make_event("e6", "task.started", request_id, 1, {"task_id": "t1"})),
            ("exec.started", make_event("e7", "exec.started", request_id, 1,
                                         {"exec_id": "x1", "task_id": "t1"})),
            ("exec.completed", make_event("e8", "exec.completed", request_id, 1,
                                           {"exec_id": "x1", "outcome_ref": "out-1"})),
            # verify
            ("verify.requested", make_event("e9", "verify.requested", request_id, 1,
                                             {"gate": "g1"})),
            ("verify.passed", make_event("e10", "verify.passed", request_id, 1,
                                          {"gate": "g1", "verdict_ref": "v-gate-1"})),
            # commit
            ("storage.committed", make_event("e11", "storage.committed", request_id, 1,
                                              {"commit_ref": "commit-1"})),
            ("task.completed", make_event("e12", "task.completed", request_id, 1,
                                           {"task_id": "t1"})),
            # completed
            ("request.completed", make_event("e13", "request.completed", request_id, 1, {})),
        ]

    def test_full_lifecycle_record_journal_and_replay_are_identical(self):
        request_id = "r-e2e"
        script = self._script(request_id)
        events_by_id = {family_event[1]["event_id"]: family_event[1] for family_event in script}

        storage = StorageDouble()
        store, journal = Store(), Journal()
        bus = BusDouble()
        cfg = RsmConfigView(retention_window=1000, checkpoint_n=100, coalescing_interval=1000)
        clock = FakeClock(0)
        tel = Telemetry(bus, cfg, clock)
        ing = Ingest(store, journal, telemetry=tel)

        for topic, event in script:
            bus.publish(topic, event)
        for topic, event in script:
            outcome = bus.deliver_one(ing, topic)
            self.assertEqual(outcome, APPLIED, msg="family=%s" % topic)

        self.assertEqual(store.state_of(request_id), transitions.TERMINAL)
        live_record = store.get(request_id)
        live_journal = journal.entries(request_id)
        self.assertEqual(len(live_journal), len(script))

        # sanity: every block actually got populated by the drive
        self.assertEqual(live_record.identity["declared_type"], "type.alpha")
        self.assertEqual(live_record.plan["status"], "validated")
        self.assertEqual(live_record.work["tasks"]["t1"]["state"], "completed")
        self.assertEqual(live_record.context, {"s1": "ctx-1"})
        self.assertEqual(live_record.verification["g1"]["state"], "passed")
        self.assertEqual(live_record.budget, {"granted": 10})
        self.assertEqual(live_record.work["commit_ref"], "commit-1")
        self.assertEqual(live_record.lifecycle, {"state": "completed"})
        self.assertEqual(live_record.failure, ())

        # telemetry emitted immediately for birth+terminal, coalesced others
        self.assertEqual(tel.counters["state_updated"], 2)
        self.assertGreater(tel.counters["coalescing_backlog"], 0)

        # persist, then verify a full journal replay is byte-identical to
        # both the live record and the persisted terminal snapshot (RSM-I12)
        persistence.persist_terminal(storage, journal, store, request_id, clock)
        terminal_snapshot = persistence.read_terminal_snapshot(storage, request_id)
        self.assertTrue(recovery.verify_byte_identical(terminal_snapshot, live_record))

        replay_store, replayed_journal, replayed_record = recovery.replay_from_journal_index(
            storage, request_id, events_by_id)
        self.assertTrue(recovery.verify_byte_identical(replayed_record, live_record))
        self.assertEqual(replayed_journal.entries(request_id), live_journal)

        # run the replay a second time from the same journal — RSM/05 §5
        # item 3's "replay determinism demo": zero diff between two replays
        _, _, replayed_record_again = recovery.replay_from_journal_index(
            storage, request_id, events_by_id)
        self.assertEqual(replayed_record_again, replayed_record)

    def test_recovery_gate_refuses_reads_until_opened(self):
        gate = recovery.RecoveryGate()
        with self.assertRaises(recovery.RecoveringError):
            gate.guard()
        gate.open()
        gate.guard()  # no longer raises


# ---------------------------------------------------------------------------
# Eviction telemetry wiring
# ---------------------------------------------------------------------------
class EvictionTelemetryTests(unittest.TestCase):
    def test_eviction_emits_state_evicted_exactly_once(self):
        storage = StorageDouble()
        store, journal = Store(), Journal()
        bus = BusDouble()
        cfg = RsmConfigView(retention_window=10, checkpoint_n=100, coalescing_interval=1)
        clock = FakeClock(0)
        tel = Telemetry(bus, cfg, clock)
        ing = Ingest(store, journal, telemetry=tel)

        ing.process(make_event("e0", "request.received", "r1", 1,
                                {"declared_type": "a", "origin": "fe"}))
        ing.process(make_event("e1", "request.completed", "r1", 1, {}))
        persistence.persist_terminal(storage, journal, store, "r1", clock)

        clock.advance(9)
        self.assertFalse(evict_and_notify(store, tel, "r1", clock, retention_window=10))
        self.assertEqual(tel.counters["state_evicted"], 0)

        clock.advance(1)
        self.assertTrue(evict_and_notify(store, tel, "r1", clock, retention_window=10))
        self.assertEqual(tel.counters["state_evicted"], 1)
        self.assertEqual(store.state_of("r1"), transitions.EVICTED)


# ---------------------------------------------------------------------------
# Structural tests (RSM/05 §4 "Structural test", §5 validation checklist)
# ---------------------------------------------------------------------------
def _rsm_source_files():
    return sorted(
        f for f in os.listdir(SRC_RSM)
        if f.endswith(".py") and not f.startswith("__")
    )


def _read(name):
    with open(os.path.join(SRC_RSM, name), "r", encoding="utf-8") as fh:
        return fh.read()


class StructuralTests(unittest.TestCase):
    """Source-scan tests, kernel IT-7 precedent (RSM/05 §4). RSM-I2's sole-
    mutator discipline is checked at the granularity the spec names: (a)
    only `ingest.py` calls into `reducers` (constructs/dispatches a
    reducer); (b) no module outside `store.py` writes to `store`'s private
    maps directly — every other module goes through `store`'s own public
    methods (`create`/`apply`/`apply_terminal`/`mark_persisted`/
    `mark_evicted`/`evict_gate`/`seed`), never `self._active[...]` etc.
    directly. RSM-I15 is checked the same way: no module outside
    `telemetry.py`/`ingest.py` (the emit call site) even references the
    `state.updated`/`state.evicted` topic strings, so nothing could gate a
    decision on them."""

    def test_only_ingest_calls_into_reducers(self):
        offenders = []
        for name in _rsm_source_files():
            if name in ("ingest.py", "reducers.py", "recovery.py"):
                # ingest: the sole caller. reducers.py: defines itself.
                # recovery.py: constructs its own Ingest and calls .process
                # (never reducers.REGISTRY/birth_reducer directly) — allowed
                # by inspection below, not by blanket exclusion.
                continue
            text = _read(name)
            if "reducers." in text or "birth_reducer(" in text:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_recovery_never_calls_reducers_directly(self):
        text = _read("recovery.py")
        self.assertNotIn("reducers.", text)
        self.assertNotIn("birth_reducer(", text)

    def test_no_module_writes_store_private_maps_directly(self):
        forbidden = ("._active[", "._retained[", "._state[", "._persisted_at[",
                     "._evicted_ids")
        offenders = []
        for name in _rsm_source_files():
            if name == "store.py":
                continue
            text = _read(name)
            if any(marker in text for marker in forbidden):
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_state_updated_and_evicted_topics_only_referenced_by_telemetry_and_ingest(self):
        allowed = {"telemetry.py", "ingest.py"}
        offenders = []
        for name in _rsm_source_files():
            if name in allowed:
                continue
            text = _read(name)
            if '"state.updated"' in text or "'state.updated'" in text \
                    or '"state.evicted"' in text or "'state.evicted'" in text:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_no_module_reads_state_topics_from_a_bus_to_gate_a_decision(self):
        # RSM-I15 structural extension: nothing in src/rsm/ ever calls
        # bus.pending/deliver* against the state.updated/state.evicted
        # topics — telemetry only ever publishes to them, never consumes.
        for name in _rsm_source_files():
            if name in ("__init__.py",):
                continue
            text = _read(name)
            for marker in ('pending("state.updated")', "pending('state.updated')",
                            'pending("state.evicted")', "pending('state.evicted')"):
                self.assertNotIn(marker, text, msg=name)

    def test_stdlib_only_module_level_imports(self):
        """Acceptance criterion (f): no third-party import anywhere in
        src/rsm/. Module-level imports (outside each file's own
        `if __name__ == "__main__":` selftest guard, which legitimately
        imports the ums/kernel *doubles* for self-test convenience, same
        precedent as persistence.py's existing selftest) must be either a
        relative (intra-package) import or a stdlib module."""
        stdlib_ok = {"dataclasses", "collections", "json", "typing", "itertools"}
        for name in _rsm_source_files():
            path = os.path.join(SRC_RSM, name)
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=name)
            for node in tree.body:
                if _is_main_guard(node):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Import):
                        for alias in sub.names:
                            top = alias.name.split(".")[0]
                            self.assertIn(top, stdlib_ok,
                                          msg="%s imports non-stdlib %r at module level"
                                          % (name, alias.name))
                    elif isinstance(sub, ast.ImportFrom):
                        if sub.level == 0:  # absolute import
                            top = (sub.module or "").split(".")[0]
                            self.assertIn(top, stdlib_ok,
                                          msg="%s imports non-stdlib %r at module level"
                                          % (name, sub.module))

    def test_exclusion_table_grep_no_forbidden_domain_logic(self):
        """RSM/05 §5 item 1: RSM must contain zero planning, scheduling,
        verification-decision, prompt-construction, retrieval, or learning
        logic (RSM/01-problem-definition.md §5 exclusion table, RSM-I13).
        A curated forbidden-keyword scan — not exhaustive, but a real,
        checkable build-time audit demo per the spec's own description
        ("not a unit test, a build-time check")."""
        forbidden_substrings = (
            "def retrieve(", "def choose_action(", "def generate_prompt(",
            "prompt_template", "import openai", "embedding_model",
            "vector_store", "def schedule_next(", "def call_llm(",
        )
        for name in _rsm_source_files():
            text = _read(name)
            for marker in forbidden_substrings:
                self.assertNotIn(marker, text, msg="%s contains forbidden marker %r" %
                                  (name, marker))


def _is_main_guard(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


if __name__ == "__main__":
    unittest.main()
