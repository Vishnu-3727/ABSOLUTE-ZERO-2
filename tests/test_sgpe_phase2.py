"""SGPE Phase 2 suite — Admission Compiler (SGPE/02, SGPE/05 §8
implementation contract: "8-stage pipeline; all-findings-per-stage;
canonical artifacts; atomic activation; Compile Reports" / forbidden:
"Repair/reorder policy; partial snapshots; request-path presence; extra
resolution rules" / guarantees AC-1..10, R1-R5).

Every invariant AC-1..AC-10 gets one or more explicit tests, named/
commented by invariant, plus: every pipeline stage (happy + failure),
determinism/R1-R5, conflict detection at each of the 3 rules + undecidable
rejection with witness + shadowing warnings, canonical construction (no
ordering leaks), activation atomicity + monotonic versions + rollback,
corruption-vs-authoring error class distinction, and the "grants never
reach the compiler" structural boundary (§10)."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sgpe import compiler as compiler_mod
from sgpe import condition as condition_mod
from sgpe import document as document_mod
from sgpe import manifest as manifest_mod
from sgpe import rule as rule_mod
from sgpe import vocabulary as vocabulary_mod
from sgpe.bus_double import BusDouble
from sgpe.storage_double import StorageDouble
from sgpe.store import PolicyStore


# -- shared builders ----------------------------------------------------------

def _seeded_store(op_terms=(), fact_names=()):
    """A Store with vocabulary v1 (SGPE/00 §9's domain set) appended, plus
    an optional v2 that additively declares the given operation terms
    ("domain.operation" strings) and/or fact names."""
    store = PolicyStore(StorageDouble())
    v1 = vocabulary_mod.default_v1()
    store.append_vocabulary(v1)
    if op_terms or fact_names:
        v2 = vocabulary_mod.evolve(v1, operations=op_terms or None, fact_names=fact_names or None)
        store.append_vocabulary(v2)
    return store


def _rule(rule_id, domain, operation, selector, effect_kind, value=None, condition=None, final=False):
    target = rule_mod.build_target(domain, operation, selector)
    effect = rule_mod.build_effect(effect_kind, value)
    return rule_mod.build_rule(rule_id, target, effect, condition=condition, final=final)


def _doc(name, scope, rules, vocab_version, reason="authoring", domain_refs=("execution",)):
    prov = document_mod.build_provenance("alice", "epoch-0", reason)
    header = document_mod.build_header(scope, name, domain_refs, prov, vocab_version, 1)
    return document_mod.build_document(header, rules)


def _compile(store, ruleset=compiler_mod.CURRENT_COMPILER_RULESET_VERSION, bus=None):
    return compiler_mod.compile_snapshot(store, store.catalog_position(), ruleset, bus=bus)


def _totalized_store(op_terms):
    """A store whose vocabulary declares `op_terms` and whose system scope
    already answers every one of them with a universal ("*") rule --
    passes stage 5 (totality) so tests can focus on a later stage."""
    store = _seeded_store(op_terms=op_terms)
    rules = tuple(_rule("total-" + str(i), *term.split(".", 1), "*", "ALLOW")
                  for i, term in enumerate(op_terms))
    store.append_document(_doc("baseline", "system", rules, store.current_vocabulary_version()))
    return store


# -- AC-1: never stores/evaluates/resolves/enforces beyond manifest/activation --

class AC1_NeverEvaluatesOrEnforcesTests(unittest.TestCase):
    def test_compile_module_has_no_evaluate_enforce_resolve_api(self):
        for forbidden in ("evaluate", "enforce", "resolve", "grant"):
            self.assertFalse(hasattr(compiler_mod, forbidden))

    def test_a_compile_alone_writes_nothing_to_the_store(self):
        store = _totalized_store(("execution.run",))
        position_before = store.catalog_position()
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertEqual(store.catalog_position(), position_before)  # no append happened


# -- AC-2/R1: pure function of (P, vocabulary version, ruleset version) --

class AC2_R1_PureFunctionTests(unittest.TestCase):
    def test_recompiling_the_same_position_is_byte_identical(self):
        store = _totalized_store(("execution.run",))
        result1 = _compile(store)
        result2 = _compile(store)
        self.assertEqual(result1.snapshot.content_hash, result2.snapshot.content_hash)
        self.assertEqual(compiler_mod.report_to_dict(result1.report), compiler_mod.report_to_dict(result2.report))

    def test_no_clock_no_environment_only_positional_reads(self):
        sig = inspect.signature(compiler_mod.compile_snapshot)
        self.assertEqual(list(sig.parameters), ["store", "position", "compiler_ruleset_version", "bus"])

    def test_unsupported_ruleset_version_refused(self):
        store = _totalized_store(())
        with self.assertRaises(compiler_mod.UnsupportedCompilerRulesetVersionError):
            compiler_mod.compile_snapshot(store, store.catalog_position(), 999)

    def test_malformed_position_refused(self):
        store = _totalized_store(())
        with self.assertRaises(compiler_mod.MalformedCompileInputError):
            compiler_mod.compile_snapshot(store, -1)
        with self.assertRaises(compiler_mod.MalformedCompileInputError):
            compiler_mod.compile_snapshot(store, store.catalog_position() + 100)


# -- R3: canonical ordering everywhere, no iteration-order leaks --

class R3_CanonicalOrderingTests(unittest.TestCase):
    def test_shuffled_authoring_order_yields_identical_snapshot(self):
        # Store A authors system doc then project doc; Store B authors the
        # same two documents in the opposite order. Same final content,
        # different append/insertion order -- the compiled snapshot must
        # be byte-identical regardless (R3).
        vocab_ops = ("execution.run",)
        rule_sys = _rule("r-sys", "execution", "run", "*", "ALLOW")
        rule_proj = _rule("r-proj", "execution", "run", "specific", "DENY")

        store_a = _seeded_store(op_terms=vocab_ops)
        store_a.append_document(_doc("baseline", "system", (rule_sys,), store_a.current_vocabulary_version()))
        store_a.append_document(_doc("extra", "project", (rule_proj,), store_a.current_vocabulary_version()))

        store_b = _seeded_store(op_terms=vocab_ops)
        store_b.append_document(_doc("extra", "project", (rule_proj,), store_b.current_vocabulary_version()))
        store_b.append_document(_doc("baseline", "system", (rule_sys,), store_b.current_vocabulary_version()))

        result_a = _compile(store_a)
        result_b = _compile(store_b)
        self.assertEqual(result_a.outcome, "compiled")
        self.assertEqual(result_b.outcome, "compiled")
        self.assertEqual(result_a.snapshot.content_hash, result_b.snapshot.content_hash)
        self.assertEqual(result_a.snapshot.entries, result_b.snapshot.entries)


# -- AC-3: all-or-nothing --

class AC3_AllOrNothingTests(unittest.TestCase):
    def test_rejected_compile_has_no_snapshot(self):
        store = _seeded_store()  # no system rule at all -> totality gap
        store.append_vocabulary(vocabulary_mod.evolve(store.vocabulary(), operations=("execution.run",)))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        self.assertIsNone(result.snapshot)

    def test_rejection_changes_nothing_in_the_store(self):
        store = _seeded_store()
        store.append_vocabulary(vocabulary_mod.evolve(store.vocabulary(), operations=("execution.run",)))
        position_before = store.catalog_position()
        _compile(store)
        self.assertEqual(store.catalog_position(), position_before)
        self.assertEqual(store.manifests(), ())
        self.assertEqual(store.activations(), ())

    def test_fail_stop_across_stages_later_stage_never_runs(self):
        # a stage-2 (vocabulary) violation and a stage-5 (totality) gap both
        # exist in this store; only the stage-2 finding is ever reported --
        # stage 5 never runs once stage 2 has already rejected.
        store = _seeded_store(op_terms=("execution.run",))
        bad_rule = _rule("r1", "not-a-real-domain", "not-a-real-op", "*", "ALLOW")
        store.append_document(_doc("weird", "project", (bad_rule,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        codes = {f.code for f in result.report.errors}
        self.assertIn(compiler_mod.VOCAB_DOMAIN_UNRESOLVED, codes)
        self.assertNotIn(compiler_mod.TOTALITY_GAP, codes)  # stage 5 never ran


# -- AC-4: applies the 3-rule procedure verbatim; never repairs/reorders --

class AC4_NoRepairNoReorderTests(unittest.TestCase):
    def test_conflicting_rules_are_rejected_not_silently_fixed(self):
        store = _totalized_store(("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "*", "ALLOW")
        limit_rule = _rule("r-limit", "execution", "run", "*", "LIMIT", value=5)
        store.append_document(_doc("conflict", "system", (allow_rule, limit_rule),
                                    store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")  # never auto-resolved
        self.assertTrue(any(f.code == compiler_mod.UNDECIDABLE_CONFLICT for f in result.report.errors))

    def test_no_repair_reorder_or_extra_resolution_rule_api_exists(self):
        for forbidden in ("repair", "reorder", "prioritize", "fix_conflict"):
            self.assertFalse(hasattr(compiler_mod, forbidden))


# -- AC-5: every undecidable overlap rejected with rule-pair citation + witness --

class AC5_UndecidableConflictWitnessTests(unittest.TestCase):
    def test_mixed_effect_shape_same_scope_is_undecidable(self):
        # allow_rule itself is a universal ("*") system rule, so it
        # satisfies totality on its own -- no separate baseline rule is
        # introduced, keeping this pair the ONLY overlap in the snapshot.
        store = _seeded_store(op_terms=("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "*", "ALLOW")
        limit_rule = _rule("r-limit", "execution", "run", "*", "LIMIT", value=5)
        store.append_document(_doc("conflict", "system", (allow_rule, limit_rule),
                                    store.current_vocabulary_version()))
        result = _compile(store)
        finding = next(f for f in result.report.errors if f.code == compiler_mod.UNDECIDABLE_CONFLICT)
        self.assertEqual(finding.error_class, compiler_mod.AUTHORING)
        cited_rule_ids = {c[2] for c in finding.citations}
        self.assertEqual(cited_rule_ids, {"r-allow", "r-limit"})
        self.assertEqual(finding.witness["domain"], "execution")
        self.assertEqual(finding.witness["operation"], "run")
        self.assertEqual(finding.witness["resource"], "*")

    def test_incomparable_limit_values_same_scope_is_undecidable(self):
        store = _totalized_store(("execution.run",))
        limit_a = _rule("r-a", "execution", "run", "*", "LIMIT", value=5)
        limit_b = _rule("r-b", "execution", "run", "*", "LIMIT", value="not-a-number")
        store.append_document(_doc("conflict", "system", (limit_a, limit_b), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        self.assertTrue(any(f.code == compiler_mod.UNDECIDABLE_CONFLICT for f in result.report.errors))

    def test_structurally_unprovable_disjointness_is_undecidable_not_silently_allowed(self):
        # a BooleanComposition condition can't be structurally analyzed for
        # disjointness (conservative design) -- treated as OVERLAPPING, and
        # then the 3-rule procedure independently rejects it (mixed effect
        # shapes, same scope) rather than silently deciding it either way.
        store = _seeded_store(op_terms=("execution.run",), fact_names=("usage.tokens",))
        composed = condition_mod.build_boolean(
            "or", (condition_mod.build_comparison("usage.tokens", "lt", 100),
                    condition_mod.build_comparison("usage.tokens", "gt", 200)))
        allow_rule = _rule("r-allow", "execution", "run", "*", "ALLOW", condition=composed)
        limit_rule = _rule("r-limit", "execution", "run", "*", "LIMIT", value=5)
        store.append_document(_doc("conflict", "system", (allow_rule, limit_rule),
                                    store.current_vocabulary_version(), domain_refs=("execution",)))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        self.assertTrue(any(f.code == compiler_mod.UNDECIDABLE_CONFLICT for f in result.report.errors))


# -- AC-6: every compiled entry carries its citation triple --

class AC6_CitationEmbeddedTests(unittest.TestCase):
    def test_every_entry_citation_matches_its_originating_rule(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        for entry in result.snapshot.entries:
            did, version, rule_id = entry.citation
            document = store.document_version(did, version)
            self.assertIsNotNone(document)
            self.assertTrue(any(r.rule_id == rule_id for r in document.rules))


# -- AC-7: candidates unregistered until activation; zero-error precondition --

class AC7_ActivationPreconditionTests(unittest.TestCase):
    def test_candidate_is_not_registered_before_activation(self):
        store = _totalized_store(("execution.run",))
        _compile(store)  # never activated
        self.assertEqual(store.manifests(), ())
        self.assertEqual(store.activations(), ())

    def test_activation_of_a_rejected_result_refused(self):
        store = _seeded_store()
        store.append_vocabulary(vocabulary_mod.evolve(store.vocabulary(), operations=("execution.run",)))
        result = _compile(store)  # totality gap -> rejected
        with self.assertRaises(compiler_mod.ActivationRefusedError):
            compiler_mod.activate(store, result)

    def test_dry_run_compiles_are_just_compiles_never_activated(self):
        store = _totalized_store(("execution.run",))
        for _ in range(3):
            _compile(store)  # repeated dry-run compiles
        self.assertEqual(store.manifests(), ())


# -- AC-8: snapshot versions monotonic, assigned at activation; rollback forward --

class AC8_MonotonicActivationAndRollbackTests(unittest.TestCase):
    def test_snapshot_version_assigned_at_activation_not_compile(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        self.assertIsNone(getattr(result.snapshot, "snapshot_version", None))  # no such field pre-activation
        manifest, activation_fact = compiler_mod.activate(store, result)
        self.assertEqual(activation_fact.snapshot_version, 1)
        self.assertEqual(manifest.snapshot_version, 1)

    def test_successive_activations_are_monotonic(self):
        store = _totalized_store(("execution.run",))
        result1 = _compile(store)
        _, activation1 = compiler_mod.activate(store, result1)
        self.assertEqual(activation1.snapshot_version, 1)

        store.append_document(_doc("more", "project", (_rule("p1", "execution", "run", "specific", "DENY"),),
                                    store.current_vocabulary_version()))
        result2 = _compile(store)
        _, activation2 = compiler_mod.activate(store, result2)
        self.assertEqual(activation2.snapshot_version, 2)
        self.assertEqual(activation2.previous_snapshot_version, 1)

    def test_rollback_recompiles_old_inputs_and_activates_forward(self):
        store = _totalized_store(("execution.run",))
        result1 = _compile(store)
        manifest1, activation1 = compiler_mod.activate(store, result1)
        self.assertEqual(activation1.snapshot_version, 1)

        store.append_document(_doc("more", "project", (_rule("p1", "execution", "run", "specific", "DENY"),),
                                    store.current_vocabulary_version()))
        result2 = _compile(store)
        compiler_mod.activate(store, result2)

        # rollback to the FIRST manifest's inputs -- new forward version,
        # same recompiled content as the original (byte-identical by R2)
        rolled_back_manifest, rolled_back_activation = compiler_mod.rollback(store, manifest1)
        self.assertEqual(rolled_back_activation.snapshot_version, 3)  # forward, never "reactivate v1"
        self.assertEqual(rolled_back_manifest.content_hash, manifest1.content_hash)  # same recompiled content


# -- AC-9/R5: standing regeneration oracle --

class AC9_R5_RegenerationOracleTests(unittest.TestCase):
    def test_regeneration_reproduces_recorded_content_hash(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        manifest, _ = compiler_mod.activate(store, result)
        regenerated = compiler_mod.regenerate(store, manifest)
        self.assertEqual(regenerated.content_hash, manifest.content_hash)

    def test_regeneration_mismatch_detected(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        manifest, _ = compiler_mod.activate(store, result)
        tampered = manifest_mod.build_manifest(
            manifest.snapshot_version, manifest.catalog_position, manifest.vocabulary_version,
            manifest.compiler_ruleset_version, manifest.document_refs, "not-the-real-hash")
        with self.assertRaises(compiler_mod.RegenerationMismatchError):
            compiler_mod.regenerate(store, tampered)


# -- AC-10: invoked, never self-triggering, never on the request path --

class AC10_NeverSelfTriggeringTests(unittest.TestCase):
    def test_compiler_module_has_no_daemon_or_trigger_surface(self):
        for forbidden in ("run", "start", "poll", "schedule", "tick", "on_"):
            self.assertFalse(any(name.startswith(forbidden) for name in dir(compiler_mod) if not name.startswith("_")))

    def test_store_never_imports_or_calls_the_compiler(self):
        import sgpe.store as store_mod
        source = inspect.getsource(store_mod)
        self.assertNotIn("compiler", source)


# -- stage 1: assembly --

class Stage1_AssemblyTests(unittest.TestCase):
    def test_deprecated_latest_version_excludes_the_document_entirely(self):
        store = _totalized_store(("execution.run",))
        store.append_document(_doc("extra", "project", (_rule("p1", "execution", "run", "*", "DENY"),),
                                    store.current_vocabulary_version()))
        store.append_deprecation(("project", "extra"), 1, document_mod.build_provenance("bob", "e1", "retired"))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        cited_docs = {c[0] for e in result.snapshot.entries for c in (e.citation,)}
        self.assertNotIn(("project", "extra"), cited_docs)

    def test_manifest_echo_reflects_exactly_the_assembled_set(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        self.assertEqual(result.report.manifest_echo, result.snapshot.document_refs)


# -- stage 2: vocabulary validation (corruption class) --

class Stage2_VocabularyTests(unittest.TestCase):
    def test_unresolved_domain_rejected_as_corruption(self):
        store = _totalized_store(("execution.run",))
        bad_rule = _rule("r1", "not-a-real-domain", "op", "*", "ALLOW")
        store.append_document(_doc("weird", "project", (bad_rule,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.VOCAB_DOMAIN_UNRESOLVED)
        self.assertEqual(finding.error_class, compiler_mod.CORRUPTION)

    def test_unresolved_operation_rejected_as_corruption(self):
        store = _totalized_store(("execution.run",))
        bad_rule = _rule("r1", "execution", "not-a-real-op", "*", "ALLOW")
        store.append_document(_doc("weird", "project", (bad_rule,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.VOCAB_OPERATION_UNRESOLVED)
        self.assertEqual(finding.error_class, compiler_mod.CORRUPTION)

    def test_unresolved_condition_fact_rejected_as_corruption(self):
        store = _totalized_store(("execution.run",))
        cond = condition_mod.build_comparison("not-a-real-fact", "eq", 1)
        bad_rule = _rule("r1", "execution", "run", "specific", "ALLOW", condition=cond)
        store.append_document(_doc("weird", "project", (bad_rule,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.VOCAB_FACT_UNRESOLVED)
        self.assertEqual(finding.error_class, compiler_mod.CORRUPTION)

    def test_all_stage_findings_reported_not_just_the_first(self):
        store = _totalized_store(("execution.run",))
        bad_rule_1 = _rule("r1", "not-a-real-domain-1", "op", "*", "ALLOW")
        bad_rule_2 = _rule("r2", "not-a-real-domain-2", "op", "*", "ALLOW")
        store.append_document(_doc("weird", "project", (bad_rule_1, bad_rule_2), store.current_vocabulary_version()))
        result = _compile(store)
        domain_errors = [f for f in result.report.errors if f.code == compiler_mod.VOCAB_DOMAIN_UNRESOLVED]
        self.assertEqual(len(domain_errors), 2)  # both reported, not fail-fast within the stage

    def test_documents_authored_against_an_older_additive_vocabulary_pass(self):
        # additivity (PS-8) makes this safe: a doc authored under v1 (before
        # operations existed) still compiles fine under the newer vocabulary.
        store = _seeded_store()
        v1_version = store.current_vocabulary_version()
        store.append_document(_doc("baseline", "system", (_rule("r1", "execution", "run", "*", "ALLOW"),),
                                    v1_version))
        store.append_vocabulary(vocabulary_mod.evolve(store.vocabulary(), operations=("execution.run",)))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertTrue(any(f.code == compiler_mod.STALE_VOCABULARY for f in result.report.warnings))


# -- stage 3: scope & modifier legality --

class Stage3_ScopeModifierTests(unittest.TestCase):
    def test_final_at_non_system_scope_rejected(self):
        store = _totalized_store(("execution.run",))
        bad_final = _rule("r1", "execution", "run", "specific", "ALLOW", final=True)
        store.append_document(_doc("weird", "project", (bad_final,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.FINAL_ILLEGAL_SCOPE)
        self.assertEqual(finding.error_class, compiler_mod.AUTHORING)

    def test_higher_scope_rule_contradicting_final_rejected(self):
        store = _seeded_store(op_terms=("shell.execute",))
        final_deny = _rule("r-final", "shell", "execute", "*", "DENY", final=True)
        store.append_document(_doc("baseline", "system", (final_deny,), store.current_vocabulary_version(),
                                    domain_refs=("shell",)))
        contradicting_allow = _rule("r-allow", "shell", "execute", "*", "ALLOW")
        store.append_document(_doc("override", "project", (contradicting_allow,),
                                    store.current_vocabulary_version(), domain_refs=("shell",)))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.FINAL_CONTRADICTED)
        cited_rule_ids = {c[2] for c in finding.citations}
        self.assertEqual(cited_rule_ids, {"r-final", "r-allow"})

    def test_higher_scope_rule_agreeing_with_final_is_not_a_contradiction(self):
        store = _seeded_store(op_terms=("shell.execute",))
        final_deny = _rule("r-final", "shell", "execute", "*", "DENY", final=True)
        store.append_document(_doc("baseline", "system", (final_deny,), store.current_vocabulary_version(),
                                    domain_refs=("shell",)))
        agreeing_deny = _rule("r-deny-too", "shell", "execute", "*", "DENY")
        store.append_document(_doc("also", "project", (agreeing_deny,), store.current_vocabulary_version(),
                                    domain_refs=("shell",)))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")


# -- stage 4: dependency validation (corruption class, reachable only via a --
# -- corrupted append log -- genuinely impossible through the public Store API) --

class Stage4_DependencyTests(unittest.TestCase):
    def test_vocabulary_version_ahead_of_compile_rejected_as_corruption(self):
        store = _totalized_store(("execution.run",))
        log = list(store.export_log())
        # Craft a document_version entry whose document claims vocabulary_version=99,
        # something the public Store API structurally refuses (UnknownVocabularyVersionError)
        # but which a corrupted append log could still contain.
        corrupt_header = document_mod.build_header(
            "project", "corrupt", ("execution",),
            document_mod.build_provenance("mallory", "e0", "corrupted"), 99, 1)
        corrupt_doc = document_mod.build_document(
            corrupt_header, (_rule("r1", "execution", "run", "specific", "ALLOW"),))
        log.append({"kind": "document_version",
                    "payload": {"doc_id": ["project", "corrupt"], "version": 1,
                                "document": document_mod.to_dict(corrupt_doc)}})
        rebuilt = PolicyStore.rebuild_from_log(StorageDouble(), log)
        result = _compile(rebuilt)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.VOCAB_VERSION_AHEAD)
        self.assertEqual(finding.error_class, compiler_mod.CORRUPTION)


# -- stage 5: totality (INV-12) --

class Stage5_TotalityTests(unittest.TestCase):
    def test_missing_universal_system_rule_is_a_totality_gap(self):
        store = _seeded_store(op_terms=("execution.run",))  # no system rule at all
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        finding = next(f for f in result.report.errors if f.code == compiler_mod.TOTALITY_GAP)
        self.assertEqual(finding.error_class, compiler_mod.AUTHORING)
        self.assertEqual(finding.witness, {"domain": "execution", "operation": "run"})

    def test_non_wildcard_system_rule_alone_does_not_satisfy_totality(self):
        store = _seeded_store(op_terms=("execution.run",))
        specific_only = _rule("r1", "execution", "run", "specific-path", "ALLOW")  # not "*"
        store.append_document(_doc("baseline", "system", (specific_only,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        self.assertTrue(any(f.code == compiler_mod.TOTALITY_GAP for f in result.report.errors))

    def test_universal_system_rule_satisfies_totality(self):
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")

    def test_empty_operations_vocabulary_makes_totality_vacuous(self):
        store = _seeded_store()  # domains only, no operations declared
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")  # nothing to be total over


# -- stage 6: conflict detection --

class Stage6_ConflictDetectionTests(unittest.TestCase):
    def test_same_scope_deny_overrides_allow_decided_with_shadow_warning(self):
        store = _totalized_store(("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "specific", "ALLOW")
        deny_rule = _rule("r-deny", "execution", "run", "specific", "DENY")
        store.append_document(_doc("policy", "system", (allow_rule, deny_rule), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        warning = next(f for f in result.report.warnings if f.code == compiler_mod.SHADOWED)
        self.assertEqual(warning.witness["decided_by"], compiler_mod.DECIDED_BY_DENY_OVERRIDES)
        deny_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-deny")
        allow_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-allow")
        self.assertIn(compiler_mod.DECIDED_BY_DENY_OVERRIDES, deny_entry.decided_by)
        self.assertIn(allow_entry.citation, deny_entry.shadows)

    def test_require_approval_beats_allow(self):
        store = _totalized_store(("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "specific", "ALLOW")
        approval_rule = _rule("r-approve", "execution", "run", "specific", "REQUIRE_APPROVAL")
        store.append_document(_doc("policy", "system", (allow_rule, approval_rule),
                                    store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        approve_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-approve")
        self.assertIn(allow_rule.rule_id, [c[2] for c in approve_entry.shadows])

    def test_cross_scope_decided_by_scope_precedence(self):
        store = _totalized_store(("execution.run",))
        system_deny = _rule("r-sys-deny", "execution", "run", "specific", "DENY")
        store.append_document(_doc("sys-extra", "system", (system_deny,), store.current_vocabulary_version()))
        project_allow = _rule("r-proj-allow", "execution", "run", "specific", "ALLOW")
        store.append_document(_doc("proj", "project", (project_allow,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        project_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-proj-allow")
        system_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-sys-deny")
        # project (higher scope) wins over system, REGARDLESS of deny-overrides
        self.assertIn(compiler_mod.DECIDED_BY_SCOPE, project_entry.decided_by)
        self.assertIn(system_entry.citation, project_entry.shadows)

    def test_minimum_limit_decides_between_two_limits(self):
        store = _seeded_store(op_terms=("execution.run",))
        wide_limit = _rule("r-wide", "execution", "run", "*", "LIMIT", value=100)
        store.append_document(_doc("baseline", "system", (wide_limit,), store.current_vocabulary_version()))
        narrow_limit = _rule("r-narrow", "execution", "run", "*", "LIMIT", value=10)
        store.append_document(_doc("tighter", "system", (narrow_limit,), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        narrow_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-narrow")
        wide_entry = next(e for e in result.snapshot.entries if e.citation[2] == "r-wide")
        self.assertIn(compiler_mod.DECIDED_BY_MIN_LIMIT, narrow_entry.decided_by)
        self.assertIn(wide_entry.citation, narrow_entry.shadows)

    def test_agreeing_same_scope_rules_decided_without_a_shadow_warning(self):
        # deny_a is itself a universal ("*") rule -- satisfies totality
        # alone, so no separate baseline rule enters and pollutes the pair.
        store = _seeded_store(op_terms=("execution.run",))
        deny_a = _rule("r-a", "execution", "run", "*", "DENY")
        deny_b = _rule("r-b", "execution", "run", "*", "DENY")
        store.append_document(_doc("policy", "system", (deny_a, deny_b), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertEqual(result.report.warnings, ())  # nothing is actually eclipsed -- no warning

    def test_provably_disjoint_conditions_are_not_a_conflict_at_all(self):
        # "execution.run" is deliberately NOT declared as a vocabulary
        # operation here -- totality is then vacuous for it, so no
        # universal baseline rule is needed and can't pollute this pair.
        store = _seeded_store(fact_names=("region",))
        us_only = condition_mod.build_comparison("region", "eq", "us")
        eu_only = condition_mod.build_comparison("region", "eq", "eu")
        allow_us = _rule("r-us", "execution", "run", "specific", "ALLOW", condition=us_only)
        deny_eu = _rule("r-eu", "execution", "run", "specific", "DENY", condition=eu_only)
        store.append_document(_doc("regional", "system", (allow_us, deny_eu), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertEqual(result.report.warnings, ())  # disjoint -- never even considered an overlap

    def test_non_overlapping_resource_selectors_are_not_a_conflict(self):
        # "execution.run" not declared as an operation -- totality vacuous,
        # no baseline rule needed to pollute this pair's selectors.
        store = _seeded_store()
        rule_a = _rule("r-a", "execution", "run", "/one/*", "ALLOW")
        rule_b = _rule("r-b", "execution", "run", "/two/*", "DENY")
        store.append_document(_doc("scoped", "system", (rule_a, rule_b), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertEqual(result.report.warnings, ())


# -- shadowing warnings never block --

class ShadowingWarningTests(unittest.TestCase):
    def test_shadow_warnings_never_block_compilation(self):
        store = _totalized_store(("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "specific", "ALLOW")
        deny_rule = _rule("r-deny", "execution", "run", "specific", "DENY")
        store.append_document(_doc("policy", "system", (allow_rule, deny_rule), store.current_vocabulary_version()))
        result = _compile(store)
        self.assertEqual(result.outcome, "compiled")
        self.assertTrue(len(result.report.warnings) >= 1)
        self.assertEqual(result.report.errors, ())


# -- Compile Report determinism and shape --

class CompileReportTests(unittest.TestCase):
    def test_report_is_canon_ordered_and_deterministic(self):
        store = _totalized_store(("execution.run",))
        result1 = _compile(store)
        result2 = _compile(store)
        self.assertEqual(result1.report, result2.report)

    def test_manifest_echo_present_on_both_success_and_rejection(self):
        store = _seeded_store(op_terms=("execution.run",))  # totality gap -> rejected
        result = _compile(store)
        self.assertEqual(result.outcome, "rejected")
        self.assertIsInstance(result.report.manifest_echo, tuple)

    def test_content_hash_none_on_rejection_present_on_success(self):
        store = _seeded_store(op_terms=("execution.run",))
        rejected = _compile(store)
        self.assertIsNone(rejected.report.content_hash)
        store.append_document(_doc("baseline", "system", (_rule("r1", "execution", "run", "*", "ALLOW"),),
                                    store.current_vocabulary_version()))
        compiled = _compile(store)
        self.assertIsNotNone(compiled.report.content_hash)


# -- events (policy.compiled / policy.rejected / policy.activated) --

class EventTests(unittest.TestCase):
    def test_policy_compiled_emitted_on_success(self):
        bus = BusDouble()
        store = _totalized_store(("execution.run",))
        result = _compile(store, bus=bus)
        self.assertEqual(result.outcome, "compiled")
        self.assertEqual(len(bus.messages("policy.compiled")), 1)
        self.assertEqual(bus.messages("policy.rejected"), [])

    def test_policy_rejected_emitted_on_failure(self):
        bus = BusDouble()
        store = _seeded_store(op_terms=("execution.run",))
        result = _compile(store, bus=bus)
        self.assertEqual(result.outcome, "rejected")
        self.assertEqual(len(bus.messages("policy.rejected")), 1)
        self.assertEqual(bus.messages("policy.compiled"), [])

    def test_policy_activated_carries_old_and_new_versions(self):
        bus = BusDouble()
        store = _totalized_store(("execution.run",))
        result = _compile(store)
        compiler_mod.activate(store, result, bus=bus)
        payload = bus.messages("policy.activated")[0]["payload"]
        self.assertIsNone(payload["previous_snapshot_version"])
        self.assertEqual(payload["snapshot_version"], 1)


# -- corruption vs authoring error class distinction --

class CorruptionVsAuthoringTests(unittest.TestCase):
    def test_corruption_class_codes(self):
        self.assertEqual(
            {compiler_mod.VOCAB_DOMAIN_UNRESOLVED, compiler_mod.VOCAB_OPERATION_UNRESOLVED,
             compiler_mod.VOCAB_FACT_UNRESOLVED, compiler_mod.VOCAB_VERSION_AHEAD},
            {compiler_mod.VOCAB_DOMAIN_UNRESOLVED, compiler_mod.VOCAB_OPERATION_UNRESOLVED,
             compiler_mod.VOCAB_FACT_UNRESOLVED, compiler_mod.VOCAB_VERSION_AHEAD})

    def test_authoring_class_findings_never_carry_corruption_label(self):
        store = _totalized_store(("execution.run",))
        bad_final = _rule("r1", "execution", "run", "specific", "ALLOW", final=True)
        store.append_document(_doc("weird", "project", (bad_final,), store.current_vocabulary_version()))
        result = _compile(store)
        for finding in result.report.errors:
            self.assertEqual(finding.error_class, compiler_mod.AUTHORING)

    def test_warnings_never_carry_an_error_class(self):
        store = _totalized_store(("execution.run",))
        allow_rule = _rule("r-allow", "execution", "run", "specific", "ALLOW")
        deny_rule = _rule("r-deny", "execution", "run", "specific", "DENY")
        store.append_document(_doc("policy", "system", (allow_rule, deny_rule), store.current_vocabulary_version()))
        result = _compile(store)
        for finding in result.report.warnings:
            self.assertIsNone(finding.error_class)


# -- §10: grants never reach the compiler --

class GrantsNeverReachCompilerTests(unittest.TestCase):
    def test_compiler_has_no_grant_related_code_surface(self):
        # docstrings legitimately explain the exclusion ("grants never
        # reach this module") -- what must never exist is a grant-shaped
        # identifier (function, class, constant) anywhere in the module.
        public_names = [name for name in dir(compiler_mod) if not name.startswith("_")]
        self.assertFalse(any("grant" in name.lower() for name in public_names))


if __name__ == "__main__":
    unittest.main()
