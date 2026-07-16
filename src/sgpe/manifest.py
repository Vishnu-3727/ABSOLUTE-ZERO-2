"""SGPE Policy Store — snapshot manifests and activation facts (SGPE/01
§9). Both are DATA ABOUT a compile/activation, appended to the Store as
externally caused facts (the Compiler performs the compile/activation
act; the Store only records it, PS-1/PS-7). The compiled decision index
itself is never stored here (PS-10) -- only the manifest naming which
document versions it was built from, at which catalog position."""
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
    document_refs: tuple           # tuple of ((scope, name), version) pairs


def build_manifest(snapshot_version, catalog_position, document_refs):
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        raise MalformedManifestError("manifest.bad_snapshot_version:" + repr(snapshot_version))
    if not isinstance(catalog_position, int) or isinstance(catalog_position, bool) or catalog_position < 0:
        raise MalformedManifestError("manifest.bad_catalog_position:" + repr(catalog_position))
    if not isinstance(document_refs, (tuple, list)):
        raise MalformedManifestError("manifest.bad_document_refs:" + repr(document_refs))
    ref_tuple = tuple(document_refs)
    for ref in ref_tuple:
        if (not isinstance(ref, tuple) or len(ref) != 2 or not isinstance(ref[0], tuple)
                or len(ref[0]) != 2 or not isinstance(ref[1], int) or isinstance(ref[1], bool)):
            raise MalformedManifestError("manifest.bad_document_ref:" + repr(ref))
    return SnapshotManifest(snapshot_version=snapshot_version, catalog_position=catalog_position,
                             document_refs=ref_tuple)


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
            "document_refs": [[list(did), version] for did, version in m.document_refs]}


def manifest_from_dict(data):
    refs = tuple((tuple(did), version) for did, version in data["document_refs"])
    return build_manifest(data["snapshot_version"], data["catalog_position"], refs)


def activation_to_dict(a):
    return {"previous_snapshot_version": a.previous_snapshot_version, "snapshot_version": a.snapshot_version}


def activation_from_dict(data):
    return build_activation(data["previous_snapshot_version"], data["snapshot_version"])


if __name__ == "__main__":
    m = build_manifest(1, 3, ((("system", "baseline"), 1),))
    restored = manifest_from_dict(manifest_to_dict(m))
    assert restored == m

    a = build_activation(None, 1)
    a2 = build_activation(1, 2)
    assert activation_from_dict(activation_to_dict(a2)) == a2

    try:
        build_manifest(0, 3, ())
        raise SystemExit("non-positive snapshot version accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, -1, ())
        raise SystemExit("negative catalog position accepted")
    except MalformedManifestError:
        pass
    try:
        build_manifest(1, 3, (("bad", "ref"),))
        raise SystemExit("malformed document ref accepted")
    except MalformedManifestError:
        pass
    try:
        build_activation(None, 0)
        raise SystemExit("non-positive activation snapshot version accepted")
    except MalformedActivationFactError:
        pass

    print("manifest selftest ok")
