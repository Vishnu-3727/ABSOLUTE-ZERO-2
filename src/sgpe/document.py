"""SGPE Policy Store — the Policy Document model (SGPE/01 §2-3). A
document is a Header (identity, scope, provenance, vocabulary/schema
versions) plus an ordered list of Rules. Structural gate only (PS-6): this
module validates SHAPE (duplicate rule ids, unknown schema version,
required fields present) -- never MEANING (vocabulary terms, rule
conflicts, `final` scope-legality; those are the Admission Compiler's,
Phase 2)."""
from dataclasses import dataclass
import hashlib
import json

from . import rule as rule_mod
from .rule import Rule

SCOPES = ("system", "project", "user")  # request-grant lives in the Grant Ledger, not the Store (SGPE/01 §5)

# Additive, versioned document schema (SGPE/01 §7). Old documents remain
# valid under their recorded schema version forever -- history is never
# re-validated when this set grows.
SUPPORTED_SCHEMA_VERSIONS = (1,)


class DocumentRefusal(Exception):
    """Base for document.py refusals."""


class MalformedProvenanceError(DocumentRefusal):
    """Provenance missing a required field."""


class MalformedHeaderError(DocumentRefusal):
    """A header field failed structural validation, including an unknown
    schema version or scope (SGPE/01 §7's structural-rejection rows)."""


class DuplicateRuleIdError(DocumentRefusal):
    """Two rules in the same document share a rule_id -- PS-6/§7's
    structural rejection, decidable without knowing what any rule means."""


class MalformedDocumentError(DocumentRefusal):
    """A document failed structural validation (bad header, bad rules)."""


@dataclass(frozen=True)
class Provenance:
    author_principal: str
    authoring_timestamp: object  # opaque, caller-supplied; never clock-read here
    reason: str


def build_provenance(author_principal, authoring_timestamp, reason):
    if not isinstance(author_principal, str) or not author_principal:
        raise MalformedProvenanceError("document.bad_author_principal:" + repr(author_principal))
    if authoring_timestamp is None:
        raise MalformedProvenanceError("document.missing_authoring_timestamp")
    if not isinstance(reason, str) or not reason:
        raise MalformedProvenanceError("document.bad_reason:" + repr(reason))
    return Provenance(author_principal=author_principal, authoring_timestamp=authoring_timestamp, reason=reason)


@dataclass(frozen=True)
class Header:
    scope: str
    name: str
    domain_refs: tuple
    provenance: Provenance
    vocabulary_version: int
    schema_version: int


def build_header(scope, name, domain_refs, provenance, vocabulary_version, schema_version):
    if scope not in SCOPES:
        raise MalformedHeaderError("document.unknown_scope:" + repr(scope))
    if not isinstance(name, str) or not name:
        raise MalformedHeaderError("document.bad_name:" + repr(name))
    if not isinstance(domain_refs, (tuple, list)):
        raise MalformedHeaderError("document.bad_domain_refs:" + repr(domain_refs))
    domain_tuple = tuple(domain_refs)
    for d in domain_tuple:
        if not isinstance(d, str) or not d:
            raise MalformedHeaderError("document.bad_domain_ref:" + repr(d))
    if not isinstance(provenance, Provenance):
        raise MalformedHeaderError("document.provenance_not_built:" + repr(provenance))
    if not isinstance(vocabulary_version, int) or isinstance(vocabulary_version, bool) or vocabulary_version < 1:
        raise MalformedHeaderError("document.bad_vocabulary_version:" + repr(vocabulary_version))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise MalformedHeaderError("document.unknown_schema_version:" + repr(schema_version))
    return Header(scope=scope, name=name, domain_refs=domain_tuple, provenance=provenance,
                  vocabulary_version=vocabulary_version, schema_version=schema_version)


@dataclass(frozen=True)
class PolicyDocument:
    header: Header
    rules: tuple  # tuple of Rule, ordered (SGPE/01 §2: "an ordered list")


def build_document(header, rules):
    if not isinstance(header, Header):
        raise MalformedDocumentError("document.header_not_built:" + repr(header))
    if not isinstance(rules, (tuple, list)):
        raise MalformedDocumentError("document.bad_rules:" + repr(rules))
    rule_tuple = tuple(rules)
    seen_ids = set()
    for r in rule_tuple:
        if not isinstance(r, Rule):
            raise MalformedDocumentError("document.rule_not_built:" + repr(r))
        if r.rule_id in seen_ids:
            raise DuplicateRuleIdError("document.duplicate_rule_id:" + r.rule_id)
        seen_ids.add(r.rule_id)
    return PolicyDocument(header=header, rules=rule_tuple)


def doc_id(document):
    """The stable (scope, name) identity (SGPE/01 §3) -- never reused,
    never renamed (a rename is a new document plus deprecation of the
    old)."""
    return (document.header.scope, document.header.name)


# -- serialization (deterministic, human-readable) -------------------------

def provenance_to_dict(p):
    return {"author_principal": p.author_principal, "authoring_timestamp": p.authoring_timestamp,
            "reason": p.reason}


def provenance_from_dict(data):
    return build_provenance(data["author_principal"], data["authoring_timestamp"], data["reason"])


def _header_to_dict(h):
    return {
        "scope": h.scope, "name": h.name, "domain_refs": list(h.domain_refs),
        "provenance": provenance_to_dict(h.provenance),
        "vocabulary_version": h.vocabulary_version, "schema_version": h.schema_version,
    }


def _header_from_dict(data):
    return build_header(data["scope"], data["name"], tuple(data["domain_refs"]),
                         provenance_from_dict(data["provenance"]), data["vocabulary_version"],
                         data["schema_version"])


def to_dict(document):
    return {
        "header": _header_to_dict(document.header),
        "rules": [rule_mod.to_dict(r) for r in document.rules],
    }


def from_dict(data):
    header = _header_from_dict(data["header"])
    rules = tuple(rule_mod.from_dict(r) for r in data["rules"])
    return build_document(header, rules)


def canonical(document):
    """Canonical serialized bytes -- the content-hash anchor (SGPE/01 §3)."""
    return json.dumps(to_dict(document), sort_keys=True, separators=(",", ":")).encode()


def content_hash(document):
    """SHA-256 of the canonical serialization -- integrity check and
    replay anchor (SGPE/01 §3). Two identical contents at different
    versions legally hash identically (rollback re-issues old content as a
    new version)."""
    return hashlib.sha256(canonical(document)).hexdigest()


if __name__ == "__main__":
    prov = build_provenance("alice", "epoch-0", "initial authoring")
    header = build_header("system", "baseline", ("execution",), prov, 1, 1)
    target = rule_mod.build_target("execution", "run", "*")
    r1 = rule_mod.build_rule("r1", target, rule_mod.build_effect("DENY"))
    doc = build_document(header, (r1,))

    assert doc_id(doc) == ("system", "baseline")
    restored = from_dict(to_dict(doc))
    assert restored == doc
    assert content_hash(doc) == content_hash(restored)

    # duplicate rule ids refused
    try:
        build_document(header, (r1, r1))
        raise SystemExit("duplicate rule id accepted")
    except DuplicateRuleIdError:
        pass

    # unknown schema version refused
    try:
        build_header("system", "baseline", ("execution",), prov, 1, 99)
        raise SystemExit("unknown schema version accepted")
    except MalformedHeaderError:
        pass

    # unknown scope refused (request-grant lives in the Grant Ledger, not the Store)
    try:
        build_header("request-grant", "baseline", ("execution",), prov, 1, 1)
        raise SystemExit("request-grant scope accepted by the Store's header")
    except MalformedHeaderError:
        pass

    # final is recorded structurally regardless of scope legality (PS-6:
    # the Store never judges `final`'s scope-appropriateness -- Compiler's job)
    project_header = build_header("project", "p1", ("execution",), prov, 1, 1)
    final_rule = rule_mod.build_rule("r2", target, rule_mod.build_effect("ALLOW"), final=True)
    project_doc = build_document(project_header, (final_rule,))
    assert project_doc.rules[0].final is True  # accepted, not rejected -- structural boundary proof

    # rollback: identical content at a different version legally hashes the same
    header_v2 = build_header("system", "baseline", ("execution",), prov, 1, 1)
    doc_v2 = build_document(header_v2, (r1,))
    assert content_hash(doc) == content_hash(doc_v2)

    print("document selftest ok")
