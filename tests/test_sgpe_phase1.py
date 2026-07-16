"""SGPE Phase 1 suite — Policy Store (SGPE/01, SGPE/05 §8 implementation
contract: "Append/version/catalog documents; structural gate; position-
stamped reads; manifests + activation facts" / forbidden: "Any semantic
judgment; edit/delete; self-initiated behavior" / guarantees PS-1..10).

Every invariant PS-1..PS-10 (SGPE/01 §12) gets one or more explicit tests,
named/commented by invariant, plus: determinism of position-stamped reads,
append-only enforcement, monotonicity, content-hash stability, additive
vocabulary enforcement, structural-rejection cases (SGPE/01 §7's table),
the semantic-checks-absent boundary proof, replay, and failure paths."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sgpe import condition as condition_mod
from sgpe import document as document_mod
from sgpe import events
from sgpe import manifest as manifest_mod
from sgpe import rule as rule_mod
from sgpe import vocabulary as vocabulary_mod
from sgpe.bus_double import BusDouble
from sgpe.catalog import Catalog, CatalogAppendRejectedError, UnknownEntryKindError
from sgpe.storage_double import StorageDouble
from sgpe.store import (
    IdentityCollisionError,
    MalformedAppendError,
    NonMonotonicVersionError,
    PolicyStore,
    UnknownDocumentVersionError,
    UnknownVocabularyVersionError,
    VocabularyNotAdditiveError as StoreVocabularyNotAdditiveError,
)


# -- shared builders ---------------------------------------------------------

def _provenance(reason="authoring"):
    return document_mod.build_provenance("alice", "epoch-0", reason)


def _target(domain="execution", operation="run", resource="*"):
    return rule_mod.build_target(domain, operation, resource)


def _rule(rule_id="r1", effect="DENY", value=None, condition=None, final=False, **target_kwargs):
    return rule_mod.build_rule(rule_id, _target(**target_kwargs), rule_mod.build_effect(effect, value),
                                condition=condition, final=final)


def _header(name, scope="system", vocabulary_version=1, domain_refs=("execution",), reason="authoring"):
    return document_mod.build_header(scope, name, domain_refs, _provenance(reason), vocabulary_version, 1)


def _document(name, scope="system", rules=None, vocabulary_version=1, domain_refs=("execution",),
              reason="authoring"):
    rules = rules if rules is not None else (_rule(),)
    return document_mod.build_document(_header(name, scope, vocabulary_version, domain_refs, reason), rules)


def _store(bus=None):
    store = PolicyStore(StorageDouble(), bus=bus)
    store.append_vocabulary(vocabulary_mod.default_v1())
    return store


# -- PS-1: the Store stores/catalogs/returns; never evaluates/compiles/resolves/enforces/caches --

class PS1_NoEvaluationSurfaceTests(unittest.TestCase):
    def test_store_has_no_evaluation_compile_resolve_enforce_cache_api(self):
        store = _store()
        for forbidden in ("evaluate", "decide", "compile", "resolve", "enforce", "cache", "activate"):
            self.assertFalse(hasattr(store, forbidden), "PolicyStore must not expose " + forbidden)

    def test_store_answers_only_catalog_and_document_reads(self):
        store = _store()
        store.append_document(_document("baseline"))
        # the only two kinds of request SGPE/01 §1 names: give me these
        # document versions, and what exists as of position P.
        self.assertIsNotNone(store.document_version(("system", "baseline"), 1))
        self.assertEqual(store.documents_as_of(store.catalog_position()), ((("system", "baseline"), 1),))


# -- PS-2: document versions immutable once written; deletion does not exist --

class PS2_ImmutabilityTests(unittest.TestCase):
    def test_no_edit_delete_update_api_on_store(self):
        store = _store()
        for forbidden in ("edit_document", "delete_document", "update_document", "remove_document"):
            self.assertFalse(hasattr(store, forbidden))

    def test_no_edit_delete_update_api_on_catalog(self):
        cat = Catalog(StorageDouble())
        for forbidden in ("update", "delete", "edit", "remove"):
            self.assertFalse(hasattr(cat, forbidden))

    def test_returned_document_content_is_frozen(self):
        store = _store()
        store.append_document(_document("baseline"))
        doc = store.document_version(("system", "baseline"), 1)
        with self.assertRaises(AttributeError):
            doc.header = None

    def test_content_provenance_and_metadata_all_immutable_by_construction(self):
        # frozen dataclasses everywhere -- no field reassignment escape hatch
        header = _header("baseline")
        with self.assertRaises(AttributeError):
            header.name = "renamed"
        with self.assertRaises(AttributeError):
            header.provenance = None


# -- PS-3: versions monotonic per doc id; ids never reused or renamed --

class PS3_MonotonicVersioningTests(unittest.TestCase):
    def test_versions_assigned_monotonically_by_the_store(self):
        store = _store()
        e1 = store.append_document(_document("baseline", reason="v1"))
        e2 = store.append_document(_document("baseline", reason="v2"))
        self.assertEqual(e1.payload["version"], 1)
        self.assertEqual(e2.payload["version"], 2)
        self.assertEqual(store.latest_version(("system", "baseline")), 2)

    def test_public_append_path_can_never_go_non_monotonic(self):
        # the public API always assigns current+1 -- no parameter exists to
        # request an out-of-order version through append_document at all.
        import inspect
        sig = inspect.signature(PolicyStore.append_document)
        self.assertNotIn("version", sig.parameters)

    def test_replay_rejects_non_monotonic_version(self):
        store = _store()
        store.append_document(_document("baseline"))
        log = list(store.export_log())
        # corrupt: duplicate the document_version entry's payload version (skip to 3, no 2)
        corrupt_entry = dict(log[-1])
        corrupt_entry["payload"] = dict(corrupt_entry["payload"])
        corrupt_entry["payload"]["version"] = 3
        log.append(corrupt_entry)
        with self.assertRaises(NonMonotonicVersionError):
            PolicyStore.rebuild_from_log(StorageDouble(), log)

    def test_replay_rejects_duplicate_version(self):
        store = _store()
        store.append_document(_document("baseline"))
        log = list(store.export_log())
        log.append(dict(log[-1]))  # re-append version 1 verbatim -- duplicate
        with self.assertRaises(NonMonotonicVersionError):
            PolicyStore.rebuild_from_log(StorageDouble(), log)

    def test_identity_never_reused_ids_never_renamed_in_place(self):
        # a "rename" is a new document id plus deprecation of the old one --
        # there is no rename operation on the Store at all.
        store = _store()
        self.assertFalse(hasattr(store, "rename_document"))


# -- PS-4: every stored artifact addressable forever; archival is placement only --

class PS4_AddressabilityTests(unittest.TestCase):
    def test_old_versions_remain_addressable_after_superseding(self):
        store = _store()
        store.append_document(_document("baseline", reason="v1"))
        store.append_document(_document("baseline", reason="v2"))
        v1 = store.document_version(("system", "baseline"), 1)
        v2 = store.document_version(("system", "baseline"), 2)
        self.assertIsNotNone(v1)
        self.assertIsNotNone(v2)
        self.assertNotEqual(v1.header.provenance.reason, v2.header.provenance.reason)

    def test_deprecated_version_remains_addressable(self):
        store = _store()
        store.append_document(_document("baseline"))
        store.append_deprecation(("system", "baseline"), 1, _provenance("stale"))
        self.assertTrue(store.is_deprecated(("system", "baseline"), 1))
        self.assertIsNotNone(store.document_version(("system", "baseline"), 1))  # never removed

    def test_no_archival_call_alters_addressability(self):
        # archival is a placement hint only (SGPE/01 §4) -- Phase 1 stores
        # nothing that could implement "cold storage," so there must be no
        # API that removes or hides a version at all.
        store = _store()
        for forbidden in ("archive", "purge", "gc", "compact"):
            self.assertFalse(hasattr(store, forbidden))


# -- PS-5: catalog append-only, monotonic position; state = pure function of log --

class PS5_ReplayTests(unittest.TestCase):
    def test_catalog_position_monotonic_across_all_append_kinds(self):
        store = _store()  # vocabulary append = position 1
        store.append_document(_document("baseline"))                      # position 2
        store.append_deprecation(("system", "baseline"), 1, _provenance())  # position 3
        manifest = manifest_mod.build_manifest(1, store.catalog_position(), 1, 1,
                                                ((("system", "baseline"), 1),), "h")
        store.append_manifest(manifest)                                   # position 4
        store.append_activation(manifest_mod.build_activation(None, 1))   # position 5
        self.assertEqual(store.catalog_position(), 5)

    def test_replay_rebuilds_identical_observable_state(self):
        store = _store()
        store.append_document(_document("baseline", reason="v1"))
        store.append_document(_document("baseline", reason="v2"))
        store.append_deprecation(("system", "baseline"), 1, _provenance("stale"))
        manifest = manifest_mod.build_manifest(1, store.catalog_position(), 1, 1,
                                                ((("system", "baseline"), 2),), "h")
        store.append_manifest(manifest)
        store.append_activation(manifest_mod.build_activation(None, 1))

        rebuilt = PolicyStore.rebuild_from_log(StorageDouble(), store.export_log())

        self.assertEqual(rebuilt.catalog_position(), store.catalog_position())
        self.assertEqual(rebuilt.latest_version(("system", "baseline")),
                          store.latest_version(("system", "baseline")))
        self.assertEqual(rebuilt.is_deprecated(("system", "baseline"), 1),
                          store.is_deprecated(("system", "baseline"), 1))
        self.assertEqual(rebuilt.documents_as_of(rebuilt.catalog_position()),
                          store.documents_as_of(store.catalog_position()))
        self.assertEqual(rebuilt.manifests(), store.manifests())
        self.assertEqual(rebuilt.activations(), store.activations())
        self.assertEqual(rebuilt.current_vocabulary_version(), store.current_vocabulary_version())

    def test_replay_of_corrupted_manifest_reference_refused(self):
        store = _store()
        store.append_document(_document("baseline"))
        log = list(store.export_log())
        corrupt = {"kind": "manifest", "payload": manifest_mod.manifest_to_dict(
            manifest_mod.build_manifest(1, 2, 1, 1, ((("system", "nonexistent"), 1),), "h"))}
        log.append(corrupt)
        with self.assertRaises(UnknownDocumentVersionError):
            PolicyStore.rebuild_from_log(StorageDouble(), log)

    def test_no_update_delete_edit_api_on_catalog_or_store(self):
        store = _store()
        for forbidden in ("update", "delete", "edit", "remove"):
            self.assertFalse(hasattr(store, forbidden))


# -- PS-6: structure only; no semantic judgment anywhere in the Store --

class PS6_SemanticBoundaryTests(unittest.TestCase):
    def test_unknown_vocabulary_terms_are_accepted_not_rejected(self):
        store = _store()
        weird_rule = _rule(domain="not-a-real-domain", operation="not-a-real-op")
        doc = _document("weird", scope="project", rules=(weird_rule,))
        entry = store.append_document(doc)  # must NOT raise -- term-checking is the Compiler's job
        self.assertEqual(entry.payload["version"], 1)

    def test_conflicting_rules_within_a_document_are_accepted(self):
        # two rules targeting the identical (domain, operation, resource)
        # with contradictory effects -- conflict detection is the Compiler's
        # job (SGPE/00 §6), never the Store's.
        store = _store()
        allow_rule = _rule(rule_id="r-allow", effect="ALLOW")
        deny_rule = _rule(rule_id="r-deny", effect="DENY")
        doc = _document("conflicting", scope="project", rules=(allow_rule, deny_rule))
        entry = store.append_document(doc)
        self.assertEqual(len(entry.payload["document"].rules), 2)

    def test_final_on_a_non_system_scope_rule_is_accepted(self):
        # `final` is legal at system scope only per SGPE/00 §6 -- but that
        # legality is the Compiler's semantic check; the Store only records
        # the flag structurally (SGPE/01 §2).
        store = _store()
        final_rule = _rule(rule_id="r1", effect="ALLOW", final=True)
        doc = _document("proj-final", scope="project", rules=(final_rule,))
        entry = store.append_document(doc)
        self.assertTrue(entry.payload["document"].rules[0].final)

    def test_deprecation_honoring_is_not_the_stores_decision(self):
        # the Store records the marker; it never filters compiles or acts on it.
        store = _store()
        store.append_document(_document("baseline"))
        store.append_deprecation(("system", "baseline"), 1, _provenance("stale"))
        # still fully readable and still usable in a manifest -- the Store
        # does not refuse to reference a deprecated version.
        manifest = manifest_mod.build_manifest(1, store.catalog_position(), 1, 1,
                                                ((("system", "baseline"), 1),), "h")
        store.append_manifest(manifest)  # must not raise


# -- PS-7: no clock, no triggers, no self-initiated behavior --

class PS7_NoClockNoTriggerTests(unittest.TestCase):
    def test_store_has_no_clock_reading_or_background_behavior(self):
        store = _store()
        for forbidden in ("tick", "run", "start", "poll", "schedule", "now"):
            self.assertFalse(hasattr(store, forbidden))

    def test_timestamps_are_opaque_caller_supplied_never_generated(self):
        # authoring_timestamp is whatever the caller passes -- the Store
        # never reads a system clock to produce or validate it.
        prov = document_mod.build_provenance("alice", "any-caller-supplied-token", "reason")
        self.assertEqual(prov.authoring_timestamp, "any-caller-supplied-token")
        prov2 = document_mod.build_provenance("alice", 12345, "reason")  # even an int is accepted verbatim
        self.assertEqual(prov2.authoring_timestamp, 12345)

    def test_every_transition_requires_an_explicit_external_call(self):
        # nothing happens on construction beyond object creation -- no
        # background thread, no scheduled callback.
        store = PolicyStore(StorageDouble())
        self.assertEqual(store.catalog_position(), 0)

    def test_store_consumes_no_events(self):
        for name in events.PUBLISHED:
            with self.assertRaises(events.UnknownEventError):
                events.check_consumed(name)
        self.assertEqual(events.CONSUMED, ())


# -- PS-8: vocabulary and schema evolve additively only --

class PS8_AdditiveEvolutionTests(unittest.TestCase):
    def test_vocabulary_evolve_is_additive_only(self):
        v1 = vocabulary_mod.default_v1()
        v2 = vocabulary_mod.evolve(v1, operations=("read", "write"))
        self.assertTrue(v2.operations.issuperset(v1.operations))
        with self.assertRaises(vocabulary_mod.VocabularyNotAdditiveError):
            vocabulary_mod.evolve(v2, operations=("read",))  # dropped "write"

    def test_store_enforces_additivity_structurally_defense_in_depth(self):
        # even a hand-built (non-evolved) Vocabulary object that skips
        # dropping/renaming detection in vocabulary.py is still caught by
        # the Store's own re-check on append.
        store = _store()
        current = store.vocabulary()
        bad_next = vocabulary_mod.Vocabulary(version=2, domains=frozenset({"execution"}),  # dropped most domains
                                              operations=current.operations, fact_names=current.fact_names)
        with self.assertRaises(StoreVocabularyNotAdditiveError):
            store.append_vocabulary(bad_next)

    def test_vocabulary_version_must_advance_by_exactly_one(self):
        store = _store()
        skip_version = vocabulary_mod.Vocabulary(
            version=3, domains=store.vocabulary().domains | frozenset({"new-domain"}),
            operations=store.vocabulary().operations, fact_names=store.vocabulary().fact_names)
        with self.assertRaises(NonMonotonicVersionError):
            store.append_vocabulary(skip_version)

    def test_old_documents_remain_valid_under_their_recorded_schema_version(self):
        # SUPPORTED_SCHEMA_VERSIONS grows additively; a document authored
        # under an old (still-supported) version is never re-validated
        # against a newer one.
        doc = _document("baseline")
        self.assertEqual(doc.header.schema_version, 1)
        self.assertIn(doc.header.schema_version, document_mod.SUPPORTED_SCHEMA_VERSIONS)


# -- PS-9: position-stamped reads deterministic, byte-for-byte --

class PS9_DeterministicReadsTests(unittest.TestCase):
    def test_identical_query_and_position_returns_identical_result(self):
        store = _store()
        store.append_document(_document("baseline"))
        p = store.catalog_position()
        r1 = store.documents_as_of(p, scope="system")
        r2 = store.documents_as_of(p, scope="system")
        self.assertEqual(r1, r2)

    def test_appends_after_position_p_do_not_change_the_read_at_p(self):
        store = _store()
        store.append_document(_document("baseline"))
        p = store.catalog_position()
        before = store.documents_as_of(p)
        store.append_document(_document("second", scope="project"))
        after = store.documents_as_of(p)  # same position P, queried again
        self.assertEqual(before, after)

    def test_byte_identical_across_two_independently_built_stores(self):
        # same append sequence -> same query at the same position -> same
        # bytes, independent of which Store instance produced them.
        log = None
        for _ in range(2):
            store = _store()
            store.append_document(_document("baseline"))
            snapshot = store.documents_as_of(store.catalog_position())
            if log is None:
                log = snapshot
            else:
                self.assertEqual(log, snapshot)

    def test_vocabulary_as_of_is_also_position_stamped(self):
        store = _store()
        p1 = store.catalog_position()
        store.append_vocabulary(vocabulary_mod.evolve(store.vocabulary(), operations=("read",)))
        self.assertEqual(store.vocabulary_as_of(p1).version, 1)
        self.assertEqual(store.vocabulary_as_of(store.catalog_position()).version, 2)


# -- PS-10: compiled artifacts never system-of-record; only documents/markers/manifests/facts --

class PS10_NoCompiledArtifactsTests(unittest.TestCase):
    def test_store_has_no_snapshot_or_index_storage_api(self):
        store = _store()
        for forbidden in ("store_snapshot", "store_index", "save_compiled", "snapshot"):
            self.assertFalse(hasattr(store, forbidden))

    def test_manifest_only_references_document_versions_not_compiled_content(self):
        store = _store()
        store.append_document(_document("baseline"))
        manifest = manifest_mod.build_manifest(1, store.catalog_position(), 1, 1,
                                                ((("system", "baseline"), 1),), "h")
        store.append_manifest(manifest)
        # the manifest is (snapshot version, catalog position, doc refs) --
        # a list of ids and versions, nothing decision-shaped.
        self.assertEqual(manifest.document_refs, ((("system", "baseline"), 1),))


# -- Structural rejection cases: SGPE/01 §7's left column, one per row --

class StructuralRejectionTests(unittest.TestCase):
    def test_unparseable_schema_invalid_document_refused_at_construction(self):
        with self.assertRaises(document_mod.MalformedHeaderError):
            document_mod.build_header("system", "", ("execution",), _provenance(), 1, 1)  # empty name

    def test_duplicate_rule_ids_within_a_document_refused(self):
        r1 = _rule(rule_id="dup", effect="ALLOW")
        r2 = _rule(rule_id="dup", effect="DENY")
        with self.assertRaises(document_mod.DuplicateRuleIdError):
            document_mod.build_document(_header("baseline"), (r1, r2))

    def test_non_monotonic_or_duplicate_version_append_refused(self):
        store = _store()
        store.append_document(_document("baseline"))
        log = list(store.export_log())
        log.append(dict(log[-1]))  # duplicate version 1
        with self.assertRaises(NonMonotonicVersionError):
            PolicyStore.rebuild_from_log(StorageDouble(), log)

    def test_identity_collision_existing_id_different_document_refused(self):
        store = _store()
        store.append_document(_document("baseline", reason="original"))
        with self.assertRaises(IdentityCollisionError):
            store.append_document(_document("baseline", reason="imposter"), expect_new=True)

    def test_unknown_schema_version_refused(self):
        with self.assertRaises(document_mod.MalformedHeaderError):
            document_mod.build_header("system", "baseline", ("execution",), _provenance(), 1, 999)

    def test_reference_to_nonexistent_vocabulary_version_refused(self):
        store = _store()
        with self.assertRaises(UnknownVocabularyVersionError):
            store.append_document(_document("baseline", vocabulary_version=999))


# -- append-only enforcement (mutation attempts fail loudly) --

class AppendOnlyEnforcementTests(unittest.TestCase):
    def test_catalog_storage_rejection_never_gets_a_position(self):
        storage = StorageDouble()
        storage.script_reject("sgpe/catalog/1")
        store = PolicyStore(storage)
        with self.assertRaises(CatalogAppendRejectedError):
            store.append_vocabulary(vocabulary_mod.default_v1())
        self.assertEqual(store.catalog_position(), 0)

    def test_no_mutating_methods_anywhere_on_the_public_surface(self):
        store = _store()
        forbidden_substrings = ("edit", "delete", "update", "remove", "mutate", "overwrite")
        public_methods = [name for name in dir(store) if not name.startswith("_")]
        for name in public_methods:
            for bad in forbidden_substrings:
                self.assertNotIn(bad, name, "found a mutating-shaped method: " + name)


# -- content-hash stability + rollback --

class ContentHashTests(unittest.TestCase):
    def test_identical_document_content_hashes_identically(self):
        doc_a = _document("baseline", reason="same-content")
        doc_b = _document("baseline", reason="same-content")
        self.assertEqual(document_mod.content_hash(doc_a), document_mod.content_hash(doc_b))

    def test_different_content_hashes_differently(self):
        doc_a = _document("baseline", reason="v1")
        doc_b = _document("baseline", reason="v2")
        self.assertNotEqual(document_mod.content_hash(doc_a), document_mod.content_hash(doc_b))

    def test_rollback_reissues_identical_content_at_a_new_version_same_hash(self):
        # SGPE/01 §3: "two identical contents at different versions are legal"
        store = _store()
        original = _document("baseline", reason="v1")
        store.append_document(original)
        store.append_document(_document("baseline", reason="v2"))
        rollback = _document("baseline", reason="v1")  # identical content to version 1
        store.append_document(rollback)  # version 3, same content as version 1
        h1 = store.content_hash(("system", "baseline"), 1)
        h3 = store.content_hash(("system", "baseline"), 3)
        self.assertEqual(h1, h3)
        self.assertEqual(store.latest_version(("system", "baseline")), 3)


# -- events --

class EventTests(unittest.TestCase):
    def test_authoring_emits_policy_authored(self):
        bus = BusDouble()
        store = PolicyStore(StorageDouble(), bus=bus)
        store.append_vocabulary(vocabulary_mod.default_v1())
        store.append_document(_document("baseline"))
        msgs = bus.messages("policy.authored")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["payload"]["version"], 1)

    def test_deprecation_emits_policy_deprecated(self):
        bus = BusDouble()
        store = PolicyStore(StorageDouble(), bus=bus)
        store.append_vocabulary(vocabulary_mod.default_v1())
        store.append_document(_document("baseline"))
        store.append_deprecation(("system", "baseline"), 1, _provenance("stale"))
        msgs = bus.messages("policy.deprecated")
        self.assertEqual(len(msgs), 1)

    def test_policy_activated_is_never_emitted_by_the_store(self):
        bus = BusDouble()
        store = PolicyStore(StorageDouble(), bus=bus)
        store.append_vocabulary(vocabulary_mod.default_v1())
        store.append_document(_document("baseline"))
        manifest = manifest_mod.build_manifest(1, store.catalog_position(), 1, 1,
                                                ((("system", "baseline"), 1),), "h")
        store.append_manifest(manifest)
        store.append_activation(manifest_mod.build_activation(None, 1))
        self.assertEqual(bus.messages("policy.activated"), [])  # Compiler's event, not the Store's

    def test_invented_event_name_refused(self):
        with self.assertRaises(events.UnknownEventError):
            events.emit(BusDouble(), "policy.made_up", "e1", "s", {})


# -- condition grammar: closed, non-executable --

class ConditionGrammarTests(unittest.TestCase):
    def test_closed_comparison_ops(self):
        with self.assertRaises(condition_mod.MalformedConditionError):
            condition_mod.build_comparison("f", "regex_match", "x")

    def test_boolean_composition_arity_enforced(self):
        c = condition_mod.build_comparison("f", "eq", 1)
        with self.assertRaises(condition_mod.MalformedConditionError):
            condition_mod.build_boolean("not", (c, c))

    def test_condition_is_data_not_code(self):
        with self.assertRaises(condition_mod.MalformedConditionError):
            condition_mod.build_comparison("f", "eq", object())

    def test_condition_attaches_to_a_rule_and_round_trips(self):
        cond = condition_mod.build_set_membership("region", "in", ("us", "eu"))
        r = _rule(rule_id="r-cond", effect="LIMIT", value=100, condition=cond)
        restored = rule_mod.from_dict(rule_mod.to_dict(r))
        self.assertEqual(restored.condition, cond)


# -- rule / effect alphabet --

class EffectAlphabetTests(unittest.TestCase):
    def test_closed_effect_kinds(self):
        self.assertEqual(rule_mod.EFFECT_KINDS, ("ALLOW", "DENY", "REQUIRE_APPROVAL", "LIMIT"))

    def test_limit_requires_a_value_others_must_not_carry_one(self):
        with self.assertRaises(rule_mod.MalformedEffectError):
            rule_mod.build_effect("LIMIT")
        with self.assertRaises(rule_mod.MalformedEffectError):
            rule_mod.build_effect("DENY", 5)


# -- document/header/target/effect serialization round-trips --

class SerializationRoundTripTests(unittest.TestCase):
    def test_document_round_trip_deterministic(self):
        doc = _document("baseline")
        d1 = document_mod.to_dict(doc)
        d2 = document_mod.to_dict(doc)
        self.assertEqual(d1, d2)
        restored = document_mod.from_dict(d1)
        self.assertEqual(restored, doc)
        self.assertEqual(document_mod.canonical(doc), document_mod.canonical(restored))

    def test_manifest_and_activation_round_trip(self):
        m = manifest_mod.build_manifest(1, 3, 1, 1, ((("system", "baseline"), 1),), "h")
        self.assertEqual(manifest_mod.manifest_from_dict(manifest_mod.manifest_to_dict(m)), m)
        a = manifest_mod.build_activation(1, 2)
        self.assertEqual(manifest_mod.activation_from_dict(manifest_mod.activation_to_dict(a)), a)

    def test_vocabulary_round_trip(self):
        v = vocabulary_mod.default_v1()
        self.assertEqual(vocabulary_mod.from_dict(vocabulary_mod.to_dict(v)), v)

    def test_dicts_are_json_serializable_plain_data(self):
        import json
        doc = _document("baseline")
        json.dumps(document_mod.to_dict(doc))  # must not raise


# -- BusDouble / StorageDouble sanity (own copies, phase-1 doubles) --

class DoubleTests(unittest.TestCase):
    def test_bus_double_per_topic_fifo(self):
        bus = BusDouble()
        bus.publish("policy.authored", {"n": 1})
        bus.publish("policy.authored", {"n": 2})
        self.assertEqual(bus.messages("policy.authored"), [{"n": 1}, {"n": 2}])

    def test_storage_double_scripted_rejection_is_an_outcome(self):
        store = StorageDouble()
        store.script_reject("k")
        self.assertEqual(store.write("k", b"v"), "rejected")
        self.assertFalse(store.exists("k"))


if __name__ == "__main__":
    unittest.main()
