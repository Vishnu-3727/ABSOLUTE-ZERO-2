"""SGPE Phase 4 suite — Grant Ledger + Effective Policy Resolver (SGPE/04,
ERRATA C3, SGPE/05 §8 implementation contract: "append-only Ledger, two
record kinds, deterministic slices; stateless Resolver, two atomic
admission reads, immutable EP binding, closed §2.3 growth rule,
fail-closed admission" / forbidden: "grant evaluation; signature parsing;
compiled-policy reads; expiry/compaction; Resolver state; mid-request
external grants" / guarantees GL-1..GL-7, EPR-1..EPR-7).

Every invariant GL-1..GL-7 and EPR-1..EPR-7 gets one or more explicit
tests, named by invariant, plus: record construction/validation,
revocation inheritance, storage-rejection behavior, replay corruption
refusal, the ERRATA C3 growth rule at each boundary (≤P₀, external after
P₀, request-scoped after P₀, revocations through the same door), and an
end-to-end approval-loop regression through the real Phase 3 Evaluator."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sgpe import compiler as compiler_mod
from sgpe import condition as condition_mod
from sgpe import document as document_mod
from sgpe import events as events_mod
from sgpe import ledger as ledger_mod
from sgpe import resolver as resolver_mod
from sgpe import rule as rule_mod
from sgpe import vocabulary as vocabulary_mod
from sgpe.bus_double import BusDouble
from sgpe.evaluator import (
    GRANT,
    REVOCATION,
    GrantRecord,
    ask_signature,
    build_question,
    decision_bytes,
    evaluate,
)
from sgpe.ledger import (
    GrantLedger,
    GrantProvenance,
    LedgerAppendRejectedError,
    MalformedGrantAppendError,
    ScopeBinding,
    UnknownGrantIdError,
    build_grant_provenance,
    build_scope_binding,
    record_from_dict,
    record_to_dict,
)
from sgpe.resolver import (
    REFUSED_LEDGER_UNREACHABLE,
    REFUSED_NO_ACTIVE_SNAPSHOT,
    REFUSED_SNAPSHOT_FACT_UNREADABLE,
    AdmissionRefusedError,
    EffectivePolicy,
    MalformedAdmissionInputError,
    admit,
    consultation_slice,
    effective_policy_from_dict,
    effective_policy_to_dict,
)
from sgpe.storage_double import StorageDouble
from sgpe.store import PolicyStore


# -- shared builders ----------------------------------------------------------

def _prov(grantor="approver", reason="approved"):
    return build_grant_provenance(grantor, 1, 0, 1, "a" * 16, reason)


def _ledger(bus=None):
    return GrantLedger(StorageDouble(), bus=bus)


def _scope(kind="request", subject="req-1"):
    return build_scope_binding(kind, subject)


def _admit(ledger, snapshot_version=1, request_id="req-1", principal="alice", project="proj-x"):
    return admit(lambda: snapshot_version, ledger, request_id, principal, project)


class _UnreachableLedger(GrantLedger):
    """A Ledger whose position read fails — the one I/O-dependent read in
    SGPE's runtime path, scripted to be unreachable (EPR-5)."""

    def position(self):
        raise ConnectionError("ledger storage unreachable")


# -- GL-1: append-only, monotonic, immutable ------------------------------------

class GL1AppendOnly(unittest.TestCase):
    def test_positions_are_monotonic_and_ids_never_reused(self):
        ledger = _ledger()
        g1 = ledger.append_grant("sig-a", _scope(), _prov())
        g2 = ledger.append_grant("sig-a", _scope(), _prov())
        rv = ledger.append_revocation(g1.record_id, _prov())
        self.assertEqual([r.position for r in (g1, g2, rv)], [1, 2, 3])
        self.assertEqual([r.record_id for r in (g1, g2, rv)], ["grant-1", "grant-2", "revocation-3"])
        self.assertEqual(ledger.position(), 3)

    def test_records_are_frozen(self):
        ledger = _ledger()
        record = ledger.append_grant("sig-a", _scope(), _prov())
        with self.assertRaises(Exception):
            record.ask_signature = "tampered"
        with self.assertRaises(Exception):
            record.scope.subject = "someone-else"

    def test_no_delete_edit_or_expiry_api_exists(self):
        ledger = _ledger()
        for name in ("update", "delete", "remove", "edit", "expire", "compact", "supersede"):
            self.assertFalse(hasattr(ledger, name), name)

    def test_storage_rejection_gains_no_position(self):
        storage = StorageDouble()
        storage.script_reject("sgpe/ledger/1")
        ledger = GrantLedger(storage)
        with self.assertRaises(LedgerAppendRejectedError):
            ledger.append_grant("sig-a", _scope(), _prov())
        self.assertEqual(ledger.position(), 0)
        retried = ledger.append_grant("sig-a", _scope(), _prov())
        self.assertEqual(retried.position, 1)


# -- GL-2 / GL-5: stores and returns, never judges --------------------------------

class GL2GL5StoresNeverJudges(unittest.TestCase):
    def test_module_never_touches_compiled_policy_or_evaluation(self):
        source = inspect.getsource(ledger_mod).split('if __name__ == "__main__":')[0]
        for token in ("CompiledSnapshot", "compile_snapshot", "evaluate(", "PolicyStore",
                       "import time", "import datetime"):
            self.assertNotIn(token, source)

    def test_signature_stored_opaquely_and_exactly(self):
        # not a hash this Ledger computed — an arbitrary opaque string,
        # stored byte-exactly, never parsed (GL-4 kin)
        ledger = _ledger()
        weird = "sig with spaces / slashes / ünïcode / {json?}"
        record = ledger.append_grant(weird, _scope(), _prov())
        self.assertEqual(record.ask_signature, weird)

    def test_lapsed_bound_grants_are_still_stored_and_returned(self):
        # bounds are declared condition DATA; the Ledger returns the
        # record regardless — lapse is the Evaluator's call (GL-5)
        bound = condition_mod.build_comparison("request.phase", "eq", "active")
        ledger = _ledger()
        record = ledger.append_grant("sig-a", _scope(), _prov(), bound=bound)
        self.assertEqual(record.bound, bound)
        self.assertEqual(ledger.slice("req-1", "u", "j", 1), (record,))

    def test_duplicate_grants_coexist_without_supersession(self):
        ledger = _ledger()
        g1 = ledger.append_grant("sig-a", _scope(), _prov())
        g2 = ledger.append_grant("sig-a", _scope(), _prov())
        self.assertEqual(ledger.slice("req-1", "u", "j", 2), (g1, g2))


# -- GL-3: two record kinds, revocation semantics ----------------------------------

class GL3RecordKinds(unittest.TestCase):
    def test_revocation_names_grant_and_inherits_signature_and_scope(self):
        ledger = _ledger()
        grant = ledger.append_grant("sig-a", _scope("principal", "alice"), _prov())
        rv = ledger.append_revocation(grant.record_id, _prov(reason="emergency revoke"))
        self.assertEqual(rv.kind, REVOCATION)
        self.assertEqual(rv.revoked_grant_id, grant.record_id)
        self.assertEqual(rv.ask_signature, grant.ask_signature)
        self.assertEqual(rv.scope, grant.scope)
        self.assertIsNone(rv.bound)

    def test_revocation_of_unknown_or_non_grant_target_refused(self):
        ledger = _ledger()
        grant = ledger.append_grant("sig-a", _scope(), _prov())
        rv = ledger.append_revocation(grant.record_id, _prov())
        with self.assertRaises(UnknownGrantIdError):
            ledger.append_revocation("grant-99", _prov())
        with self.assertRaises(UnknownGrantIdError):
            ledger.append_revocation(rv.record_id, _prov())  # revoking a revocation

    def test_double_revocation_is_a_harmless_additional_fact(self):
        ledger = _ledger()
        grant = ledger.append_grant("sig-a", _scope(), _prov())
        rv1 = ledger.append_revocation(grant.record_id, _prov())
        rv2 = ledger.append_revocation(grant.record_id, _prov())
        self.assertNotEqual(rv1.record_id, rv2.record_id)
        self.assertEqual(ledger.position(), 3)

    def test_structural_validation_of_appends(self):
        ledger = _ledger()
        with self.assertRaises(MalformedGrantAppendError):
            ledger.append_grant("", _scope(), _prov())
        with self.assertRaises(MalformedGrantAppendError):
            ledger.append_grant("sig-a", ("request", "req-1"), _prov())
        with self.assertRaises(MalformedGrantAppendError):
            ledger.append_grant("sig-a", _scope(), {"grantor": "x"})
        with self.assertRaises(MalformedGrantAppendError):
            ledger.append_grant("sig-a", _scope(), _prov(), bound="until friday")
        with self.assertRaises(MalformedGrantAppendError):
            build_scope_binding("team", "core")  # three widths are canon
        with self.assertRaises(MalformedGrantAppendError):
            build_grant_provenance("", 1, 0, 1, "h", "r")


# -- GL-4: matching surface = signature + scope binding only ------------------------

class GL4MatchingSurface(unittest.TestCase):
    def test_grant_record_carries_no_selectors_patterns_or_own_conditions(self):
        field_names = set(ledger_mod.LedgerRecord.__dataclass_fields__)
        self.assertEqual(field_names, {"record_id", "kind", "ask_signature", "revoked_grant_id",
                                        "scope", "bound", "provenance", "position"})

    def test_scope_binding_is_one_subject_at_one_width(self):
        for kind in ledger_mod.SCOPE_KINDS:
            binding = build_scope_binding(kind, "subject-1")
            self.assertEqual((binding.kind, binding.subject), (kind, "subject-1"))


# -- GL-6: deterministic position-stamped slices --------------------------------------

class GL6Slices(unittest.TestCase):
    def setUp(self):
        self.ledger = _ledger()
        self.g_req = self.ledger.append_grant("s1", _scope("request", "req-1"), _prov())
        self.g_pri = self.ledger.append_grant("s2", _scope("principal", "alice"), _prov())
        self.g_prj = self.ledger.append_grant("s3", _scope("project", "proj-x"), _prov())
        self.g_other = self.ledger.append_grant("s4", _scope("principal", "bob"), _prov())

    def test_slice_selects_by_all_three_scope_subjects(self):
        s = self.ledger.slice("req-1", "alice", "proj-x", 4)
        self.assertEqual(s, (self.g_req, self.g_pri, self.g_prj))

    def test_slice_is_position_prefix_stamped(self):
        self.assertEqual(self.ledger.slice("req-1", "alice", "proj-x", 1), (self.g_req,))
        self.assertEqual(self.ledger.slice("req-1", "alice", "proj-x", 0), ())

    def test_same_arguments_same_slice_byte_for_byte(self):
        a = self.ledger.slice("req-1", "alice", "proj-x", 4)
        b = self.ledger.slice("req-1", "alice", "proj-x", 4)
        self.assertEqual([record_to_dict(r) for r in a], [record_to_dict(r) for r in b])

    def test_later_appends_never_change_an_earlier_stamped_read(self):
        before = self.ledger.slice("req-1", "alice", "proj-x", 4)
        self.ledger.append_grant("s5", _scope("principal", "alice"), _prov())
        self.assertEqual(self.ledger.slice("req-1", "alice", "proj-x", 4), before)


# -- GL-7: every append is a bus event -------------------------------------------------

class GL7Events(unittest.TestCase):
    def test_grant_and_revocation_appends_emit_canonical_events(self):
        bus = BusDouble()
        ledger = _ledger(bus=bus)
        grant = ledger.append_grant("sig-a", _scope(), _prov())
        ledger.append_revocation(grant.record_id, _prov())
        (recorded,) = bus.messages("grant.recorded")
        (revoked,) = bus.messages("grant.revoked")
        self.assertEqual(recorded["payload"], record_to_dict(ledger.record("grant-1")))
        self.assertEqual(revoked["payload"]["revoked_grant_id"], "grant-1")
        for name in ("grant.recorded", "grant.revoked"):
            self.assertIn(name, events_mod.PUBLISHED)


# -- Ledger replay (GL-1/GL-6) ------------------------------------------------------------

class LedgerReplay(unittest.TestCase):
    def test_rebuild_from_log_is_byte_identical(self):
        ledger = _ledger()
        bound = condition_mod.build_set_membership("request.region", "in", ("us", "eu"))
        g = ledger.append_grant("sig-a", _scope("principal", "alice"), _prov(), bound=bound)
        ledger.append_revocation(g.record_id, _prov(reason="changed mind"))
        rebuilt = GrantLedger.rebuild_from_log(StorageDouble(), ledger.export_log())
        self.assertEqual(rebuilt.export_log(), ledger.export_log())
        self.assertEqual(rebuilt.position(), ledger.position())
        self.assertEqual([record_to_dict(r) for r in rebuilt.slice("r", "alice", "j", 2)],
                          [record_to_dict(r) for r in ledger.slice("r", "alice", "j", 2)])

    def test_record_round_trip(self):
        ledger = _ledger()
        record = ledger.append_grant("sig-a", _scope(), _prov(),
                                       bound=condition_mod.build_comparison("t", "lt", 5))
        self.assertEqual(record_from_dict(record_to_dict(record)), record)

    def test_corrupted_log_refused_loud(self):
        ledger = _ledger()
        g = ledger.append_grant("sig-a", _scope(), _prov())
        ledger.append_grant("sig-b", _scope(), _prov())
        log = [dict(e) for e in ledger.export_log()]
        with self.assertRaises(MalformedGrantAppendError):
            GrantLedger.rebuild_from_log(StorageDouble(), (log[1],))  # gap: starts at position 2
        reordered = (log[1], log[0])
        with self.assertRaises(MalformedGrantAppendError):
            GrantLedger.rebuild_from_log(StorageDouble(), reordered)
        edited = dict(log[0])
        edited["record_id"] = "grant-7"
        with self.assertRaises(MalformedGrantAppendError):
            GrantLedger.rebuild_from_log(StorageDouble(), (edited,))
        _ = g


# -- EPR-1: one snapshot version + one baseline, atomically ------------------------------

class EPR1Admission(unittest.TestCase):
    def test_admission_binds_active_snapshot_and_current_position(self):
        ledger = _ledger()
        ledger.append_grant("sig-a", _scope("principal", "alice"), _prov())
        ep = _admit(ledger, snapshot_version=3)
        self.assertEqual(ep, EffectivePolicy(3, 1, "req-1", "alice", "proj-x"))

    def test_admission_writes_nothing(self):
        ledger = _ledger()
        log_before = ledger.export_log()
        _admit(ledger)
        self.assertEqual(ledger.export_log(), log_before)

    def test_admission_input_validation(self):
        ledger = _ledger()
        with self.assertRaises(MalformedAdmissionInputError):
            admit(lambda: 1, ledger, "", "alice", "proj-x")
        with self.assertRaises(MalformedAdmissionInputError):
            admit(1, ledger, "req-1", "alice", "proj-x")  # not a reader
        with self.assertRaises(MalformedAdmissionInputError):
            admit(lambda: 1, "not a ledger", "req-1", "alice", "proj-x")


# -- EPR-2: immutable binding, external world frozen at (S, P0) ----------------------------

class EPR2Immutability(unittest.TestCase):
    def test_binding_is_frozen(self):
        ep = _admit(_ledger())
        with self.assertRaises(Exception):
            ep.snapshot_version = 2

    def test_activation_after_admission_never_enters(self):
        # the active-version fact moving after admission changes nothing:
        # the binding holds the version read at admission, by value
        versions = [1]
        ledger = _ledger()
        ep = admit(lambda: versions[-1], ledger, "req-1", "alice", "proj-x")
        versions.append(2)  # a later activation
        self.assertEqual(ep.snapshot_version, 1)
        ep_later = admit(lambda: versions[-1], ledger, "req-2", "alice", "proj-x")
        self.assertEqual(ep_later.snapshot_version, 2)  # binds only requests admitted after it

    def test_external_grants_after_p0_never_enter(self):
        ledger = _ledger()
        ep = _admit(ledger)
        ledger.append_grant("sig-x", _scope("principal", "alice"), _prov())
        ledger.append_grant("sig-y", _scope("project", "proj-x"), _prov())
        self.assertEqual(consultation_slice(ledger, ep, ledger.position()), ())

    def test_standing_grants_at_p0_are_in_from_the_start(self):
        ledger = _ledger()
        standing_pri = ledger.append_grant("sig-a", _scope("principal", "alice"), _prov())
        standing_prj = ledger.append_grant("sig-b", _scope("project", "proj-x"), _prov())
        ledger.append_grant("sig-c", _scope("principal", "bob"), _prov())  # someone else's
        ep = _admit(ledger)
        s = consultation_slice(ledger, ep, ledger.position())
        self.assertEqual([g.grant_id for g in s], [standing_pri.record_id, standing_prj.record_id])


# -- EPR-3: reads two facts, emits one value ------------------------------------------------

class EPR3NoSideEffects(unittest.TestCase):
    def test_module_never_evaluates_compiles_or_touches_the_store(self):
        source = inspect.getsource(resolver_mod).split('if __name__ == "__main__":')[0]
        for token in ("PolicyStore", "compile_snapshot", "CompiledSnapshot",
                       "import evaluate", "events_mod", "emit("):
            self.assertNotIn(token, source)

    def test_resolver_is_functions_only_no_class_no_registry(self):
        classes = [name for name, value in vars(resolver_mod).items()
                   if isinstance(value, type) and value.__module__ == resolver_mod.__name__
                   and not issubclass(value, Exception)]
        self.assertEqual(classes, ["EffectivePolicy"])  # one value type, zero stateful machinery


# -- EPR-4: the closed growth rule (ERRATA C3) ------------------------------------------------

class EPR4ClosedGrowthRule(unittest.TestCase):
    def setUp(self):
        self.ledger = _ledger()
        self.standing = self.ledger.append_grant("sig-a", _scope("principal", "alice"), _prov())
        self.ep = _admit(self.ledger)  # P0 = 1

    def test_request_scoped_appends_after_p0_enter_as_they_land(self):
        own = self.ledger.append_grant("sig-b", _scope("request", "req-1"), _prov())
        s = consultation_slice(self.ledger, self.ep, self.ledger.position())
        self.assertEqual([g.grant_id for g in s], [self.standing.record_id, own.record_id])

    def test_other_requests_grants_never_enter(self):
        self.ledger.append_grant("sig-b", _scope("request", "req-2"), _prov())
        s = consultation_slice(self.ledger, self.ep, self.ledger.position())
        self.assertEqual([g.grant_id for g in s], [self.standing.record_id])

    def test_mid_request_revocation_of_mid_request_grant_is_visible_immediately(self):
        own = self.ledger.append_grant("sig-b", _scope("request", "req-1"), _prov())
        self.ledger.append_revocation(own.record_id, _prov(reason="emergency"))
        s = consultation_slice(self.ledger, self.ep, self.ledger.position())
        self.assertEqual([(g.kind, g.grant_id) for g in s],
                          [(GRANT, self.standing.record_id), (GRANT, own.record_id),
                           (REVOCATION, own.record_id)])

    def test_slice_grows_only_forward_per_consultation_stamp(self):
        own = self.ledger.append_grant("sig-b", _scope("request", "req-1"), _prov())
        at_p0 = consultation_slice(self.ledger, self.ep, 1)
        at_p2 = consultation_slice(self.ledger, self.ep, 2)
        self.assertEqual([g.grant_id for g in at_p0], [self.standing.record_id])
        self.assertEqual([g.grant_id for g in at_p2], [self.standing.record_id, own.record_id])

    def test_consultation_before_admission_position_is_a_caller_bug(self):
        with self.assertRaises(MalformedAdmissionInputError):
            consultation_slice(self.ledger, self.ep, 0)

    def test_projection_shape_is_the_evaluators_own(self):
        own = self.ledger.append_grant("sig-b", _scope("request", "req-1"), _prov())
        self.ledger.append_revocation(own.record_id, _prov())
        for projected in consultation_slice(self.ledger, self.ep, self.ledger.position()):
            self.assertIsInstance(projected, GrantRecord)


# -- EPR-5: fail-closed admission ---------------------------------------------------------------

class EPR5FailClosed(unittest.TestCase):
    def test_no_active_snapshot_refuses_admission(self):
        with self.assertRaises(AdmissionRefusedError) as ctx:
            admit(lambda: None, _ledger(), "req-1", "alice", "proj-x")
        self.assertEqual(ctx.exception.code, REFUSED_NO_ACTIVE_SNAPSHOT)

    def test_unreadable_snapshot_fact_refuses_admission(self):
        def broken_reader():
            raise IOError("activation record unreadable")
        with self.assertRaises(AdmissionRefusedError) as ctx:
            admit(broken_reader, _ledger(), "req-1", "alice", "proj-x")
        self.assertEqual(ctx.exception.code, REFUSED_SNAPSHOT_FACT_UNREADABLE)

    def test_garbage_snapshot_fact_refuses_admission(self):
        for garbage in (0, -1, "v1", True):
            with self.assertRaises(AdmissionRefusedError) as ctx:
                admit(lambda g=garbage: g, _ledger(), "req-1", "alice", "proj-x")
            self.assertEqual(ctx.exception.code, REFUSED_SNAPSHOT_FACT_UNREADABLE)

    def test_unreachable_ledger_refuses_admission(self):
        with self.assertRaises(AdmissionRefusedError) as ctx:
            admit(lambda: 1, _UnreachableLedger(StorageDouble()), "req-1", "alice", "proj-x")
        self.assertEqual(ctx.exception.code, REFUSED_LEDGER_UNREACHABLE)

    def test_no_fail_open_path_exists(self):
        source = inspect.getsource(resolver_mod)
        self.assertNotIn("allow_all", source)
        self.assertNotIn("default_allow", source)


# -- EPR-6: stateless between invocations, isolation ----------------------------------------------

class EPR6Isolation(unittest.TestCase):
    def test_concurrent_requests_hold_independent_bindings(self):
        ledger = _ledger()
        ep_a = _admit(ledger, snapshot_version=1, request_id="req-a")
        ledger.append_grant("sig-x", _scope("request", "req-a"), _prov())
        ep_b = _admit(ledger, snapshot_version=2, request_id="req-b", principal="bob")
        self.assertEqual((ep_a.snapshot_version, ep_a.admission_ledger_position), (1, 0))
        self.assertEqual((ep_b.snapshot_version, ep_b.admission_ledger_position), (2, 1))
        # req-a's own grant never leaks into req-b's slice
        self.assertEqual(consultation_slice(ledger, ep_b, ledger.position()), ())

    def test_no_module_level_mutable_state(self):
        for name, value in vars(resolver_mod).items():
            if name.startswith("_") or callable(value) or isinstance(value, type):
                continue
            self.assertNotIsInstance(value, (dict, list, set),
                                      "module-level mutable state: " + name)


# -- EPR-7: replay reconstructs every historical consultation -------------------------------------

class EPR7Replay(unittest.TestCase):
    def test_effective_policy_round_trips_through_rsm_shaped_dict(self):
        ep = _admit(_ledger(), snapshot_version=4)
        self.assertEqual(effective_policy_from_dict(effective_policy_to_dict(ep)), ep)

    def test_rebuilt_ledger_plus_recorded_stamps_reproduce_slices(self):
        ledger = _ledger()
        ledger.append_grant("sig-a", _scope("principal", "alice"), _prov())
        ep = _admit(ledger)
        own = ledger.append_grant("sig-b", _scope("request", "req-1"), _prov())
        ledger.append_revocation(own.record_id, _prov())
        recorded_positions = (1, 2, 3)
        original = [consultation_slice(ledger, ep, p) for p in recorded_positions]

        rebuilt_ledger = GrantLedger.rebuild_from_log(StorageDouble(), ledger.export_log())
        rebuilt_ep = effective_policy_from_dict(effective_policy_to_dict(ep))
        replayed = [consultation_slice(rebuilt_ledger, rebuilt_ep, p) for p in recorded_positions]
        self.assertEqual(replayed, original)


# -- end-to-end regression: approval loop through the real Evaluator -------------------------------

class ApprovalLoopEndToEnd(unittest.TestCase):
    """The full Phase 1-4 chain: authored policy -> compiled snapshot ->
    admission -> REQUIRE_APPROVAL -> Kernel-routed grant append ->
    re-ask under the SAME frozen EP -> ALLOW; then emergency revocation
    -> REQUIRE_APPROVAL again; then byte-exact replay of every
    consultation from stamps alone."""

    def setUp(self):
        store = PolicyStore(StorageDouble())
        v1 = vocabulary_mod.default_v1()
        store.append_vocabulary(v1)
        store.append_vocabulary(vocabulary_mod.evolve(v1, operations=("execution.run",)))
        prov = document_mod.build_provenance("alice", "epoch-0", "authoring")
        header = document_mod.build_header("system", "baseline", ("execution",), prov, 2, 1)
        r = rule_mod.build_rule("r1", rule_mod.build_target("execution", "run", "*"),
                                 rule_mod.build_effect("REQUIRE_APPROVAL"))
        store.append_document(document_mod.build_document(header, (r,)))
        result = compiler_mod.compile_snapshot(store, store.catalog_position())
        _, activation = compiler_mod.activate(store, result)
        self.snapshot = result.snapshot
        self.active_version = activation.snapshot_version
        self.ledger = _ledger()
        self.question = build_question("kernel", "req-1", "alice", "execution", "run", "repo-x", {})

    def _consult(self, ep, position):
        return evaluate(ep.snapshot_version, self.snapshot, position,
                         consultation_slice(self.ledger, ep, position), self.question)

    def test_approval_loop_and_replay(self):
        ep = admit(lambda: self.active_version, self.ledger, "req-1", "alice", "proj-x")

        d1 = self._consult(ep, self.ledger.position())
        self.assertEqual(d1.effect_kind, "REQUIRE_APPROVAL")

        # Kernel routes the approval into a request-scoped Ledger append
        grant = self.ledger.append_grant(
            d1.ask_signature, build_scope_binding("request", "req-1"),
            build_grant_provenance("approver", d1.snapshot_version, d1.grant_slice_position,
                                     d1.evaluation_ruleset_version, d1.question_hash, "approved"))

        d2 = self._consult(ep, self.ledger.position())
        self.assertEqual(d2.effect_kind, "ALLOW")

        # emergency revocation through the same request-scoped door
        self.ledger.append_revocation(grant.record_id, _prov(reason="emergency"))
        d3 = self._consult(ep, self.ledger.position())
        self.assertEqual(d3.effect_kind, "REQUIRE_APPROVAL")

        # replay every consultation from stamps alone, byte-compare
        rebuilt_ledger = GrantLedger.rebuild_from_log(StorageDouble(), self.ledger.export_log())
        rebuilt_ep = effective_policy_from_dict(effective_policy_to_dict(ep))
        for original in (d1, d2, d3):
            replayed = evaluate(
                rebuilt_ep.snapshot_version, self.snapshot, original.grant_slice_position,
                consultation_slice(rebuilt_ledger, rebuilt_ep, original.grant_slice_position),
                self.question, evaluation_ruleset_version=original.evaluation_ruleset_version)
            self.assertEqual(decision_bytes(replayed), decision_bytes(original))

    def test_external_grant_cannot_unlock_a_running_request(self):
        ep = admit(lambda: self.active_version, self.ledger, "req-1", "alice", "proj-x")
        d1 = self._consult(ep, self.ledger.position())
        # a well-meaning admin grants at principal width AFTER admission
        self.ledger.append_grant(d1.ask_signature, build_scope_binding("principal", "alice"), _prov())
        d2 = self._consult(ep, self.ledger.position())
        self.assertEqual(d2.effect_kind, "REQUIRE_APPROVAL")  # still: external never enters
        # a fresh request admitted after it sees the standing grant
        ep_new = admit(lambda: self.active_version, self.ledger, "req-2", "alice", "proj-x")
        question_new = build_question("kernel", "req-2", "alice", "execution", "run", "repo-x", {})
        d3 = evaluate(ep_new.snapshot_version, self.snapshot, self.ledger.position(),
                       consultation_slice(self.ledger, ep_new, self.ledger.position()), question_new)
        self.assertEqual(d3.effect_kind, "ALLOW")


if __name__ == "__main__":
    unittest.main()
