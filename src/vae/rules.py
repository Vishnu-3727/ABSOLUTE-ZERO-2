"""VAE rules-as-data (VAE/06 Phase 1, VAE/04 §7.1 rules binding, VAE-S5-style
monotonic-version pattern mirroring `ro/priors.py`). A `RulesVersion` is an
immutable snapshot: artifact type -> required check set, verification depth,
per-check deadline. Rules are never inferred or defaulted — they are data
VAE consumes, never invents (VAE-I1's perimeter held at the config surface).

`RulesStore` is the strictly-monotonic ingest ledger (mirrors
`ro/priors.py`'s `PriorsStore`): a version once ingested is readable forever
by `lookup(artifact_type, version)`; a stale-or-duplicate version is refused
loud, never silently ignored or overwritten. Lookup of an absent
(artifact_type, version) pair is a loud `UnknownVersionError` /
`UnknownArtifactTypeError` — there is no default rule set to fall back to,
by design (VAE/06 Phase 1 completion criteria)."""
from dataclasses import dataclass
from types import MappingProxyType


class RulesRefusal(Exception):
    """Base for every rules.py refusal."""


class MalformedRulesError(RulesRefusal):
    """A rules payload failed structural validation."""


class StaleOrDuplicateVersionError(RulesRefusal):
    """Rules versions are strictly monotonic; a version <= the current one
    is refused loud, never silently accepted or overwritten."""


class UnknownVersionError(RulesRefusal):
    """lookup() asked for a rules version never ingested. Never a default."""


class UnknownArtifactTypeError(RulesRefusal):
    """lookup() asked for an artifact type absent from the named version.
    Never a default rule set."""


def _validate_checks(required_checks):
    if not isinstance(required_checks, (tuple, list)) or not required_checks:
        raise MalformedRulesError("rules.empty_or_bad_required_checks:" + repr(required_checks))
    checks = tuple(required_checks)
    for c in checks:
        if not isinstance(c, str) or not c:
            raise MalformedRulesError("rules.bad_check_name:" + repr(c))
    if len(set(checks)) != len(checks):
        raise MalformedRulesError("rules.duplicate_check_name:" + repr(checks))
    return checks


def _validate_deadlines(deadlines, checks):
    if not isinstance(deadlines, dict) and not isinstance(deadlines, MappingProxyType):
        raise MalformedRulesError("rules.bad_deadlines:" + repr(deadlines))
    if set(deadlines.keys()) != set(checks):
        raise MalformedRulesError(
            "rules.deadlines_must_cover_exactly_required_checks:" +
            repr(sorted(deadlines.keys())) + "!=" + repr(sorted(checks)))
    for check, deadline in deadlines.items():
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or deadline <= 0:
            raise MalformedRulesError("rules.bad_deadline:" + str(check) + ":" + repr(deadline))
    return MappingProxyType(dict(deadlines))


@dataclass(frozen=True)
class ArtifactRules:
    required_checks: tuple
    depth: str
    deadlines: MappingProxyType  # check name -> per-check deadline (VAE/04 §7.1)


def build_artifact_rules(required_checks, depth, deadlines):
    checks = _validate_checks(required_checks)
    if not isinstance(depth, str) or not depth:
        raise MalformedRulesError("rules.bad_depth:" + repr(depth))
    frozen_deadlines = _validate_deadlines(deadlines, checks)
    return ArtifactRules(required_checks=checks, depth=depth, deadlines=frozen_deadlines)


@dataclass(frozen=True)
class RulesVersion:
    version: int
    artifact_rules: MappingProxyType  # artifact_type -> ArtifactRules


def build_rules_version(version, artifact_rules):
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MalformedRulesError("rules.bad_version:" + repr(version))
    if (not isinstance(artifact_rules, dict) and not isinstance(artifact_rules, MappingProxyType)) \
            or not artifact_rules:
        raise MalformedRulesError("rules.empty_or_bad_artifact_rules:" + repr(artifact_rules))
    frozen = {}
    for artifact_type, spec in dict(artifact_rules).items():
        if not isinstance(artifact_type, str) or not artifact_type:
            raise MalformedRulesError("rules.bad_artifact_type:" + repr(artifact_type))
        if isinstance(spec, ArtifactRules):
            frozen[artifact_type] = spec
        elif isinstance(spec, dict):
            frozen[artifact_type] = build_artifact_rules(
                spec.get("required_checks"), spec.get("depth"), spec.get("deadlines"))
        else:
            raise MalformedRulesError("rules.bad_artifact_rules_spec:" + repr(spec))
    return RulesVersion(version=version, artifact_rules=MappingProxyType(frozen))


class RulesStore:
    """Append-only, strictly-monotonic ingest ledger for `RulesVersion`
    snapshots (mirrors `ro/priors.py`'s `PriorsStore` pattern, VAE-S5)."""

    def __init__(self):
        self._history = {}  # version -> RulesVersion
        self._current_version = 0

    def ingest(self, version, artifact_rules):
        rv = build_rules_version(version, artifact_rules)
        if rv.version <= self._current_version:
            raise StaleOrDuplicateVersionError(
                "rules.stale_or_duplicate_version:got=" + str(rv.version) +
                ":current=" + str(self._current_version))
        self._history[rv.version] = rv
        self._current_version = rv.version
        return rv

    def lookup(self, artifact_type, version):
        """(artifact_type, version) -> ArtifactRules. Absent version or
        absent artifact type within a known version both refuse loud —
        never a default rule set (VAE/06 Phase 1 completion criteria)."""
        if version not in self._history:
            raise UnknownVersionError("rules.unknown_version:" + str(version))
        rv = self._history[version]
        if artifact_type not in rv.artifact_rules:
            raise UnknownArtifactTypeError(
                "rules.unknown_artifact_type:" + str(artifact_type) + ":version=" + str(version))
        return rv.artifact_rules[artifact_type]

    def current_version(self):
        return self._current_version if self._current_version else None


if __name__ == "__main__":
    store = RulesStore()
    assert store.current_version() is None

    v1 = store.ingest(1, {
        "plugin_output": {
            "required_checks": ("structural", "semantic"),
            "depth": "standard",
            "deadlines": {"structural": 5, "semantic": 10},
        },
    })
    assert v1.version == 1
    assert store.current_version() == 1

    looked_up = store.lookup("plugin_output", 1)
    assert looked_up.required_checks == ("structural", "semantic")
    assert looked_up.deadlines["semantic"] == 10

    # stale/duplicate version refused loud
    try:
        store.ingest(1, {"plugin_output": {
            "required_checks": ("structural",), "depth": "standard",
            "deadlines": {"structural": 5}}})
        raise SystemExit("duplicate version accepted")
    except StaleOrDuplicateVersionError:
        pass

    # monotonic: version 2 accepted, version 1 still readable (pinning)
    store.ingest(2, {"plugin_output": {
        "required_checks": ("structural",), "depth": "minimal",
        "deadlines": {"structural": 3}}})
    assert store.lookup("plugin_output", 1).depth == "standard"
    assert store.lookup("plugin_output", 2).depth == "minimal"

    # absent version / absent artifact type -> loud refusal, never a default
    try:
        store.lookup("plugin_output", 99)
        raise SystemExit("unknown version accepted")
    except UnknownVersionError:
        pass
    try:
        store.lookup("plan", 1)
        raise SystemExit("unknown artifact type accepted")
    except UnknownArtifactTypeError:
        pass

    # malformed rules refused loud
    for bad_checks in ((), "not-a-tuple", ("dup", "dup")):
        try:
            build_artifact_rules(bad_checks, "standard", {})
            raise SystemExit("malformed required_checks accepted: " + repr(bad_checks))
        except MalformedRulesError:
            pass
    try:
        build_artifact_rules(("structural",), "standard", {"other": 1})
        raise SystemExit("deadlines not covering required_checks accepted")
    except MalformedRulesError:
        pass
    try:
        build_artifact_rules(("structural",), "standard", {"structural": -1})
        raise SystemExit("non-positive deadline accepted")
    except MalformedRulesError:
        pass
    try:
        build_rules_version(0, {"plugin_output": {
            "required_checks": ("structural",), "depth": "standard",
            "deadlines": {"structural": 1}}})
        raise SystemExit("non-positive version accepted")
    except MalformedRulesError:
        pass

    print("rules selftest ok")
