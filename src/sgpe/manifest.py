"""SGPE Policy Store — snapshot manifests and activation facts (SGPE/01
§9, extended by SGPE/02 §7). Both are DATA ABOUT a compile/activation,
appended to the Store as externally caused facts (the Compiler performs
the compile/activation act; the Store only records it, PS-1/PS-7). The
compiled decision index itself is never stored here (PS-10) -- only the
manifest naming which document versions it was built from, at which
catalog position, under which vocabulary and compiler-ruleset versions,
plus the content hash that anchors the (regenerable) compiled index's
integrity (AC-9/R5).

Phase 2 note (additive extension, not a Phase 1 redesign): SGPE/01 §9
described the manifest as `(snapshot version, catalog position, list of
(document id, version))`. SGPE/02 §7 names three more fields the manifest
must carry once a Compiler exists to produce them: vocabulary version,
compiler ruleset version, and the compiled index's content hash. Adding
fields to a data shape that had no consumer needing them yet is additive,
matching every other "extend, never replace" precedent in this canon
(vocabulary/schema evolution, SGPE/01 §7-8) -- it is not a change to
Phase 1's semantics, invariants, or existing behavior."""
from dataclasses import dataclass


class ManifestRefusal(Exception):
    """Base for manifest.py refusals."""


class MalformedManifestError(ManifestRefusal):
    """A manifest failed structural validation."""


class MalformedActivationFactError(ManifestRefusal):
    """An activation fact failed structural validation."""


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_version: int
    catalog_position: int          # the catalog position the compile read as-of
    vocabulary_version: int        # the compile vocabulary version (newest as of catalog_position)
    compiler_ruleset_version: int  # the compilation semantics version that produced this manifest
    document_refs: tuple           # tuple of ((scope, name), version) pairs
    content_hash: str              # hash of the canonical compiled index (AC-9/R5 integrity anchor)


def build_manifest(snapshot_version, catalog_position, vocabulary_version, compiler_ruleset_version,
                    document_refs, content_hash):
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise MalformedManifestError("manifest.bad_snapshot_version:" + repr(snapshot_version))
    if not isinstance(catalog_position, int) or isinstance(catalog_position, bool) or catalog_position < 0:
        raise MalformedManifestError("manifest.bad_catalog_position:" + repr(catalog_position))
    if not isinstance(vocabulary_version, int) or isinstance(vocabulary_version, bool) or vocabulary_version < 1:
        raise MalformedManifestError("manifest.bad_vocabulary_version:" + repr(vocabulary_version))
    if (not isinstance(compiler_ruleset_version, int) or isinstance(compiler_ruleset_version, bool)
            or compiler_ruleset_version < 1):
        raise MalformedManifestError("manifest.bad_compiler_ruleset_version:" + repr(compiler_ruleset_version))
    if not isinstance(document_refs, (tuple, list)):
        raise MalformedManifestError("manifest.bad_document_refs:" + repr(document_refs))
    ref_tuple = tuple(document_refs)
    for ref in ref_tuple:
        if (not isinstance(ref, tuple) or len(ref) != 2 or not isinstance(ref[0], tuple)
                or len(ref[0]) != 2 or not isinstance(ref[1], int) or isinstance(ref[1], bool)):
            raise MalformedManifestError("manifest.bad_document_ref:" + repr(ref))
    if not isinstance(content_hash, str) or not content_hash:
        raise MalformedManifestError("manifest.bad_content_hash:" + repr(content_hash))
    return SnapshotManifest(snapshot_version=snapshot_version, catalog_position=catalog_position,
                             vocabulary_version=vocabulary_version,
                             compiler_ruleset_version=compiler_ruleset_version,
                             document_refs=ref_tuple, content_hash=content_hash)


@dataclass(frozen=True)
class ActivationFact:
    previous_snapshot_version: object  # None on first activation, else int
    snapshot_version: int


def build_activation(previous_snapshot_version, snapshot_version):
    if previous_snapshot_version is not None and (
            not isinstance(previous_snapshot_version, int) or isinstance(previous_snapshot_version, bool)):
        raise MalformedActivationFactError(
            "activation.bad_previous_snapshot_version:" + repr(previous_snapshot_version))
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise MalformedActivationFactError("activation.bad_snapshot_version:" + repr(snapshot_version))
    return ActivationFact(previous_snapshot_version=previous_snapshot_version, snapshot_version=snapshot_version)


def manifest_to_dict(m):
    return {"snapshot_version": m.snapshot_version, "catalog_position": m.catalog_position,
            "vocabulary_version": m.vocabulary_version,
            "compiler_ruleset_version": m.compiler_ruleset_version,
            "document_refs": [[list(did), version] for did, version in m.document_refs],
            "content_hash": m.content_hash}


def manifest_from_dict(data):
    refs = tuple((tuple(did), version) for did, version in data["document_refs"])
    return build_manifest(data["snapshot_version"], data["catalog_position"], data["vocabulary_version"],
                           data["compiler_ruleset_version"], refs, data["content_hash"])


def activation_to_dict(a):
    return {"previous_snapshot_version": a.previous_snapshot_version, "snapshot_version": a.snapshot_version}


def activation_from_dict(data):
    return build_activation(data["previous_snapshot_version"], data["snapshot_version"])


if __name__ == "__main__":
    m = build_manifest(1, 3, 1, 1, ((("system", "baseline"), 1),), "deadbeef")
    restored = manifest_from_dict(manifest_to_dict(m))
    assert restored == m

    a = build_activation(None, 1)
    a2 = build_activation(1, 2)
    assert activation_from_dict(activation_to_dict(a2)) == a2

    try:
        build_manifest(0, 3, 1, 1, (), "h")
        raise SystemExit("non-positive snapshot version accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, -1, 1, 1, (), "h")
        raise SystemExit("negative catalog position accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, 3, 1, 1, (("bad", "ref"),), "h")
        raise SystemExit("malformed document ref accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, 3, 0, 1, (), "h")
        raise SystemExit("non-positive vocabulary version accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, 3, 1, 0, (), "h")
        raise SystemExit("non-positive compiler ruleset version accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, 3, 1, 1, (), "")
        raise SystemExit("empty content hash accepted")
    except MalformedManifestError:
        pass
    try:
        build_activation(None, 0)
        raise SystemExit("non-positive activation snapshot version accepted")
    except MalformedActivationFactError:
        pass

    print("manifest selftest ok")
