"""SGPE Policy Store (SGPE/01 -- all sections; SGPE/05 §8 implementation
contract). The passive, deterministic repository of authored governance
data: documents, vocabulary, manifests, activation facts, deprecation
markers, and the catalog that indexes them. Structural gate only (PS-6) --
this module is the sharp boundary named in SGPE/01 §7: it rejects
unparseable/malformed data and identity/version corruption structurally,
but it NEVER judges vocabulary terms, rule conflicts, `final` legality, or
scope-appropriateness (Admission Compiler, Phase 2).

Every state transition is an externally caused append (PS-7): there is no
clock, no trigger, no self-initiated behavior anywhere in this class --
its entire observable state is a pure function of the ordered sequence of
append_* calls (PS-5), which is also what makes `rebuild_from_log`
(replay) exact and byte-identical."""
from dataclasses import dataclass

from . import document as document_mod
from . import events as events_mod
from . import manifest as manifest_mod
from . import vocabulary as vocabulary_mod
from .catalog import Catalog
from .document import PolicyDocument
from .document import doc_id as document_doc_id
from .manifest import ActivationFact, SnapshotManifest
from .vocabulary import Vocabulary


class StoreRefusal(Exception):
    """Base for store.py refusals."""


class MalformedAppendError(StoreRefusal):
    """append_* was handed something other than the typed, already-built
    record it requires."""


class IdentityCollisionError(StoreRefusal):
    """append_document(..., expect_new=True) was asked to author a
    document id that already has recorded history -- ids are never reused
    (PS-3); the caller believed this was a brand-new document lineage and
    it is not (SGPE/01 §7's "identity collision" structural rejection)."""


class NonMonotonicVersionError(StoreRefusal):
    """An explicit version (only reachable via `rebuild_from_log`/replay)
    was not exactly current+1 for its document or vocabulary id --
    non-monotonic or duplicate version append, refused loud (PS-3,
    SGPE/01 §7)."""


class UnknownVocabularyVersionError(StoreRefusal):
    """A document cites a vocabulary version the Store has never recorded
    -- SGPE/01 §7's "reference to a nonexistent vocabulary version"."""


class VocabularyNotAdditiveError(StoreRefusal):
    """append_vocabulary was handed a Vocabulary that drops/redefines an
    existing term relative to the current one on any axis -- defense in
    depth on top of vocabulary.py's own evolve() check (PS-8)."""


class UnknownDocumentVersionError(StoreRefusal):
    """A deprecation marker or manifest cites a (doc id, version) the
    Store has never recorded."""


@dataclass(frozen=True)
class DeprecationMarker:
    target_doc_id: tuple    # (scope, name)
    target_version: int
    provenance: object      # document.Provenance -- explicit authored marker, carries its own reason


def _deprecation_to_dict(marker):
    return {
        "target_doc_id": list(marker.target_doc_id), "target_version": marker.target_version,
        "provenance": document_mod.provenance_to_dict(marker.provenance),
    }


def _deprecation_from_dict(data):
    return DeprecationMarker(
        target_doc_id=tuple(data["target_doc_id"]), target_version=data["target_version"],
        provenance=document_mod.provenance_from_dict(data["provenance"]))


def _document_version_payload_to_dict(payload):
    return {"doc_id": list(payload["doc_id"]), "version": payload["version"],
            "document": document_mod.to_dict(payload["document"])}


class PolicyStore:
    def __init__(self, storage, bus=None):
        self._catalog = Catalog(storage)
        self._bus = bus
        self._doc_versions = {}          # doc_id -> latest recorded version (int)
        self._doc_content = {}           # (doc_id, version) -> PolicyDocument
        self._doc_hash = {}              # (doc_id, version) -> content hash
        self._deprecated = set()         # {(doc_id, version)} explicitly deprecated
        self._vocabulary_versions = {}   # version -> Vocabulary
        self._current_vocabulary_version = 0
        self._manifests = []
        self._activations = []

    # -- documents (SGPE/01 §2-4) --------------------------------------------

    def append_document(self, document, expect_new=False):
        """Append a new version of `document`. Version is always assigned
        by the Store as current+1 (PS-3) -- the public path can never
        produce a non-monotonic or duplicate version. `expect_new=True`
        asks the Store to refuse loud if this document id already has
        recorded history (SGPE/01 §7's identity-collision row) -- the
        caller believed this was a brand-new document lineage."""
        if not isinstance(document, PolicyDocument):
            raise MalformedAppendError("store.document_not_built:" + repr(document))
        did = document_doc_id(document)
        if document.header.vocabulary_version not in self._vocabulary_versions:
            raise UnknownVocabularyVersionError(
                "store.unknown_vocabulary_version:" + repr(document.header.vocabulary_version))
        current = self._doc_versions.get(did, 0)
        if expect_new and current != 0:
            raise IdentityCollisionError("store.identity_collision:" + repr(did))
        version = current + 1
        return self._apply_document_version(did, version, document)

    def _apply_document_version(self, did, version, document):
        current = self._doc_versions.get(did, 0)
        if version != current + 1:
            raise NonMonotonicVersionError(
                "store.non_monotonic_version:" + repr(did) + ":expected=" + str(current + 1) +
                ":got=" + str(version))
        entry = self._catalog.append(
            "document_version", {"doc_id": did, "version": version, "document": document},
            _document_version_payload_to_dict)
        self._doc_versions[did] = version
        self._doc_content[(did, version)] = document
        self._doc_hash[(did, version)] = document_mod.content_hash(document)
        if self._bus is not None:
            events_mod.emit(
                self._bus, "policy.authored", "authored:" + did[0] + ":" + did[1] + ":" + str(version),
                did[0] + "/" + did[1],
                {"doc_id": list(did), "version": version, "catalog_position": entry.position})
        return entry

    def document_version(self, did, version):
        return self._doc_content.get((did, version))

    def latest_version(self, did):
        return self._doc_versions.get(did)

    def content_hash(self, did, version):
        return self._doc_hash.get((did, version))

    def is_deprecated(self, did, version):
        return (did, version) in self._deprecated

    # -- vocabulary (SGPE/00 §9, SGPE/01 §6) ---------------------------------

    def append_vocabulary(self, vocabulary):
        if not isinstance(vocabulary, Vocabulary):
            raise MalformedAppendError("store.vocabulary_not_built:" + repr(vocabulary))
        return self._apply_vocabulary_version(vocabulary)

    def _apply_vocabulary_version(self, vocabulary):
        if self._current_vocabulary_version == 0:
            if vocabulary.version != 1:
                raise NonMonotonicVersionError(
                    "store.vocabulary_must_start_at_1:got=" + str(vocabulary.version))
        else:
            current = self._vocabulary_versions[self._current_vocabulary_version]
            if vocabulary.version != current.version + 1:
                raise NonMonotonicVersionError(
                    "store.non_monotonic_vocabulary_version:expected=" + str(current.version + 1) +
                    ":got=" + str(vocabulary.version))
            # PS-8, defense in depth: the Store re-checks additivity itself
            # rather than trusting that the caller went through evolve().
            if not (vocabulary.domains.issuperset(current.domains)
                    and vocabulary.operations.issuperset(current.operations)
                    and vocabulary.fact_names.issuperset(current.fact_names)):
                raise VocabularyNotAdditiveError("store.vocabulary_not_additive:" + repr(vocabulary))
        entry = self._catalog.append("vocabulary_version", vocabulary, vocabulary_mod.to_dict)
        self._vocabulary_versions[vocabulary.version] = vocabulary
        self._current_vocabulary_version = vocabulary.version
        return entry

    def vocabulary(self, version=None):
        if version is None:
            version = self._current_vocabulary_version
        return self._vocabulary_versions.get(version)

    def current_vocabulary_version(self):
        return self._current_vocabulary_version

    # -- deprecation (SGPE/01 §4) --------------------------------------------

    def append_deprecation(self, did, version, provenance):
        if (did, version) not in self._doc_content:
            raise UnknownDocumentVersionError("store.unknown_document_version:" + repr((did, version)))
        marker = DeprecationMarker(target_doc_id=did, target_version=version, provenance=provenance)
        return self._apply_deprecation(marker)

    def _apply_deprecation(self, marker):
        entry = self._catalog.append("deprecation", marker, _deprecation_to_dict)
        self._deprecated.add((marker.target_doc_id, marker.target_version))
        if self._bus is not None:
            did = marker.target_doc_id
            events_mod.emit(
                self._bus, "policy.deprecated",
                "deprecated:" + did[0] + ":" + did[1] + ":" + str(marker.target_version),
                did[0] + "/" + did[1],
                {"doc_id": list(did), "version": marker.target_version, "catalog_position": entry.position})
        return entry

    # -- manifests + activation facts (SGPE/01 §9) ---------------------------

    def append_manifest(self, manifest):
        if not isinstance(manifest, SnapshotManifest):
            raise MalformedAppendError("store.manifest_not_built:" + repr(manifest))
        return self._apply_manifest(manifest)

    def _apply_manifest(self, manifest):
        for did, version in manifest.document_refs:
            if (did, version) not in self._doc_content:
                raise UnknownDocumentVersionError(
                    "store.manifest_cites_unknown_document_version:" + repr((did, version)))
        entry = self._catalog.append("manifest", manifest, manifest_mod.manifest_to_dict)
        self._manifests.append(manifest)
        return entry

    def append_activation(self, activation_fact):
        if not isinstance(activation_fact, ActivationFact):
            raise MalformedAppendError("store.activation_not_built:" + repr(activation_fact))
        return self._apply_activation(activation_fact)

    def _apply_activation(self, activation_fact):
        entry = self._catalog.append("activation", activation_fact, manifest_mod.activation_to_dict)
        self._activations.append(activation_fact)
        return entry

    def manifests(self):
        return tuple(self._manifests)

    def activations(self):
        return tuple(self._activations)

    # -- position-stamped catalog reads (SGPE/01 §5, PS-9) -------------------

    def catalog_position(self):
        return self._catalog.current_position()

    def documents_as_of(self, position, scope=None, domain=None):
        """All document versions applicable to scope S / domain D, as of
        catalog position P -- deterministic enumeration (SGPE/01 §5): the
        SAME (query, position) always returns the SAME result, because it
        is computed purely from the catalog prefix up to `position` and
        nothing that happens after `position` can affect it."""
        latest = {}
        for entry in self._catalog.as_of(position, kind="document_version"):
            did = entry.payload["doc_id"]
            version = entry.payload["version"]
            document = entry.payload["document"]
            latest[did] = (version, document)
        results = []
        for did, (version, document) in latest.items():
            if scope is not None and did[0] != scope:
                continue
            if domain is not None and domain not in document.header.domain_refs:
                continue
            results.append((did, version))
        return tuple(sorted(results))

    def vocabulary_as_of(self, position):
        entries = self._catalog.as_of(position, kind="vocabulary_version")
        if not entries:
            return None
        return entries[-1].payload

    # -- replay (PS-5: entire state is a pure function of the append log) ---

    def export_log(self):
        """The ordered, canonical-dict form of every catalog append --
        sufficient (with a fresh Storage double) to rebuild an identical
        Store via `rebuild_from_log`."""
        return tuple(e.canonical_dict for e in self._catalog.all())

    @classmethod
    def rebuild_from_log(cls, storage, log, bus=None):
        """Reconstruct a Store by re-applying a recorded append sequence
        in order, through the SAME structural checks `append_*` uses
        (explicit versions this time, since the log already fixes them) --
        PS-5's "entire state is a pure function of the append sequence,"
        made literal and testable. A corrupted log (skipped/duplicated
        version, unknown-referencing manifest, ...) is refused loud, the
        same way live appends are."""
        store = cls(storage, bus=bus)
        for record in log:
            kind = record["kind"]
            payload = record["payload"]
            if kind == "document_version":
                did = tuple(payload["doc_id"])
                document = document_mod.from_dict(payload["document"])
                store._apply_document_version(did, payload["version"], document)
            elif kind == "vocabulary_version":
                store._apply_vocabulary_version(vocabulary_mod.from_dict(payload))
            elif kind == "deprecation":
                store._apply_deprecation(_deprecation_from_dict(payload))
            elif kind == "manifest":
                store._apply_manifest(manifest_mod.manifest_from_dict(payload))
            elif kind == "activation":
                store._apply_activation(manifest_mod.activation_from_dict(payload))
            else:
                raise MalformedAppendError("store.replay_unknown_kind:" + repr(kind))
        return store


if __name__ == "__main__":
    from . import document as doc_mod
    from . import rule as rule_mod
    from .bus_double import BusDouble
    from .storage_double import StorageDouble

    def _doc(name, scope="system", version_reason="v1"):
        prov = doc_mod.build_provenance("alice", "epoch-0", version_reason)
        header = doc_mod.build_header(scope, name, ("execution",), prov, 1, 1)
        target = rule_mod.build_target("execution", "run", "*")
        r = rule_mod.build_rule("r1", target, rule_mod.build_effect("DENY"))
        return doc_mod.build_document(header, (r,))

    bus = BusDouble()
    store = PolicyStore(StorageDouble(), bus=bus)
    store.append_vocabulary(vocabulary_mod.default_v1())

    entry = store.append_document(_doc("baseline"))
    assert entry.position == 2  # vocabulary append took position 1
    assert store.latest_version(("system", "baseline")) == 1
    assert bus.messages("policy.authored")[-1]["payload"]["version"] == 1

    # monotonic versioning: a second append of the same doc id is version 2
    entry2 = store.append_document(_doc("baseline", version_reason="v2"))
    assert entry2.position == 3
    assert store.latest_version(("system", "baseline")) == 2

    # identity collision: expect_new=True on an existing lineage is refused
    try:
        store.append_document(_doc("baseline", version_reason="v3"), expect_new=True)
        raise SystemExit("identity collision accepted")
    except IdentityCollisionError:
        pass

    # unknown vocabulary version reference refused
    bad_prov = doc_mod.build_provenance("alice", "epoch-1", "bad vocab ref")
    bad_header = doc_mod.build_header("system", "other", ("execution",), bad_prov, 99, 1)
    bad_doc = doc_mod.build_document(bad_header, (rule_mod.build_rule(
        "r1", rule_mod.build_target("execution", "run", "*"), rule_mod.build_effect("DENY")),))
    try:
        store.append_document(bad_doc)
        raise SystemExit("reference to nonexistent vocabulary version accepted")
    except UnknownVocabularyVersionError:
        pass

    # deprecation
    dep_prov = doc_mod.build_provenance("alice", "epoch-2", "superseded by v2")
    store.append_deprecation(("system", "baseline"), 1, dep_prov)
    assert store.is_deprecated(("system", "baseline"), 1)
    assert not store.is_deprecated(("system", "baseline"), 2)

    # manifest + activation
    manifest = manifest_mod.build_manifest(1, store.catalog_position(), ((("system", "baseline"), 2),))
    store.append_manifest(manifest)
    store.append_activation(manifest_mod.build_activation(None, 1))
    assert store.manifests() == (manifest,)

    # position-stamped, deterministic reads (PS-9)
    p_before = 3  # right after the second document version, before deprecation/manifest/activation
    docs_at_p = store.documents_as_of(p_before, scope="system")
    assert docs_at_p == store.documents_as_of(p_before, scope="system")  # repeat -> identical
    assert docs_at_p == ((("system", "baseline"), 2),)

    # replay: rebuild from the exported log is byte-identical in observable state
    log = store.export_log()
    rebuilt = PolicyStore.rebuild_from_log(StorageDouble(), log)
    assert rebuilt.latest_version(("system", "baseline")) == 2
    assert rebuilt.documents_as_of(p_before, scope="system") == docs_at_p
    assert rebuilt.catalog_position() == store.catalog_position()

    # semantic checks are absent: an unknown-vocabulary-TERM rule and a
    # conflicting-effect rule set are both ACCEPTED (Compiler's job, not
    # the Store's -- PS-6's sharp boundary, proven structurally here)
    weird_target = rule_mod.build_target("not-a-real-domain", "not-a-real-op", "*")
    weird_rule = rule_mod.build_rule("r1", weird_target, rule_mod.build_effect("ALLOW"))
    weird_prov = doc_mod.build_provenance("alice", "epoch-3", "nonsense terms, still structurally valid")
    weird_header = doc_mod.build_header("project", "weird", (), weird_prov, 1, 1)
    weird_doc = doc_mod.build_document(weird_header, (weird_rule,))
    store.append_document(weird_doc)  # does not raise -- vocabulary TERMS are never checked here

    print("store selftest ok")
