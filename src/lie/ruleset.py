"""LIE Derivation Ruleset (LIE/02 §1) -- the complete, versioned,
declarative statement of how intelligence follows from experience:
"rules are explicit criteria over facets, relations, verdicts, and
counts -- data, not code behavior" (same rules-as-data spirit as
`vae/rules.py`). The Distillery (distillery.py) is the executor of a
ruleset; ALL threshold values live here as validated data, none are baked
into the compiler.

Ruleset content this phase carries (the minimal set that exercises every
LIE/02 §3 derivation shape):

- `pattern_min_episodes` -- how many episodes sharing a signature AND an
  approach make recurrence (draws the Lesson/Pattern line, LIE/01 §5.2).
- `recipe_min_episodes` -- how many step-agreeing episodes make a Recipe.
- `corroborated_min_episodes` / `established_min_projects` -- the Maturity
  Grade rungs (LIE/02 §4; the grade NAMES are canon, these numbers are
  ruleset policy).
- `pack_scopes` -- the declared facet scope per Domain Knowledge Pack
  (LIE/01 §5.6: "a pack is defined by its facet scope"); pack membership
  then follows deterministically from the layer.

The version is part of every derived output's provenance (it is the
`ruleset_version` leg of the Derivation State triple). Old versions are
never deleted -- but version *storage/governance* is Curator material
(LIE/03 §6); this phase needs only the immutable value object."""
from dataclasses import dataclass
from types import MappingProxyType


class RulesetRefusal(Exception):
    """Base for ruleset.py refusals."""


class MalformedRulesetError(RulesetRefusal):
    """A ruleset field failed structural validation."""


def _positive_int(label, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MalformedRulesetError("ruleset.bad_" + label + ":" + repr(value))
    return value


@dataclass(frozen=True)
class DerivationRuleset:
    version: int
    pattern_min_episodes: int
    recipe_min_episodes: int
    corroborated_min_episodes: int
    established_min_projects: int
    pack_scopes: MappingProxyType  # pack name -> tuple of facet terms (declared scope)


def build_ruleset(version, *, pattern_min_episodes, recipe_min_episodes,
                   corroborated_min_episodes, established_min_projects, pack_scopes=None):
    _positive_int("version", version)
    _positive_int("pattern_min_episodes", pattern_min_episodes)
    _positive_int("recipe_min_episodes", recipe_min_episodes)
    _positive_int("corroborated_min_episodes", corroborated_min_episodes)
    _positive_int("established_min_projects", established_min_projects)
    scopes = {}
    for name, facets in dict(pack_scopes or {}).items():
        if not isinstance(name, str) or not name:
            raise MalformedRulesetError("ruleset.bad_pack_name:" + repr(name))
        if not isinstance(facets, (tuple, list)) or not facets:
            raise MalformedRulesetError("ruleset.empty_or_bad_pack_scope:" + repr(facets))
        facet_tuple = tuple(facets)
        for f in facet_tuple:
            if not isinstance(f, str) or not f:
                raise MalformedRulesetError("ruleset.bad_pack_scope_facet:" + repr(f))
        scopes[name] = facet_tuple
    return DerivationRuleset(
        version=version, pattern_min_episodes=pattern_min_episodes,
        recipe_min_episodes=recipe_min_episodes,
        corroborated_min_episodes=corroborated_min_episodes,
        established_min_projects=established_min_projects,
        pack_scopes=MappingProxyType(scopes))


def default_ruleset(version=1, pack_scopes=None):
    """The minimal default: recurrence at 2, corroboration at 2,
    establishment at 2 projects. Values are DATA -- tests and later
    governance override them freely; nothing in the compiler assumes
    them."""
    return build_ruleset(version, pattern_min_episodes=2, recipe_min_episodes=2,
                          corroborated_min_episodes=2, established_min_projects=2,
                          pack_scopes=pack_scopes)


def to_dict(ruleset):
    return {
        "version": ruleset.version,
        "pattern_min_episodes": ruleset.pattern_min_episodes,
        "recipe_min_episodes": ruleset.recipe_min_episodes,
        "corroborated_min_episodes": ruleset.corroborated_min_episodes,
        "established_min_projects": ruleset.established_min_projects,
        "pack_scopes": {name: list(facets) for name, facets in sorted(ruleset.pack_scopes.items())},
    }


def from_dict(data):
    return build_ruleset(
        data["version"], pattern_min_episodes=data["pattern_min_episodes"],
        recipe_min_episodes=data["recipe_min_episodes"],
        corroborated_min_episodes=data["corroborated_min_episodes"],
        established_min_projects=data["established_min_projects"],
        pack_scopes={name: tuple(facets) for name, facets in data["pack_scopes"].items()})


if __name__ == "__main__":
    rs = default_ruleset()
    assert rs.version == 1
    assert rs.pattern_min_episodes == 2
    assert rs.pack_scopes == {}

    rs2 = build_ruleset(2, pattern_min_episodes=3, recipe_min_episodes=2,
                         corroborated_min_episodes=4, established_min_projects=2,
                         pack_scopes={"ros2": ("ros2", "jetson")})
    assert rs2.pack_scopes["ros2"] == ("ros2", "jetson")

    # frozen: no in-place field reassignment; scopes mapping frozen too
    try:
        rs2.version = 3
        raise SystemExit("ruleset field reassignment allowed")
    except AttributeError:
        pass
    try:
        rs2.pack_scopes["cuda"] = ("cuda",)
        raise SystemExit("pack_scopes mutation allowed")
    except TypeError:
        pass

    # thresholds are validated data
    for bad in (0, -1, True, "2", 1.5):
        try:
            build_ruleset(1, pattern_min_episodes=bad, recipe_min_episodes=2,
                           corroborated_min_episodes=2, established_min_projects=2)
            raise SystemExit("bad threshold accepted: " + repr(bad))
        except MalformedRulesetError:
            pass
    try:
        build_ruleset(1, pattern_min_episodes=2, recipe_min_episodes=2,
                       corroborated_min_episodes=2, established_min_projects=2,
                       pack_scopes={"ros2": ()})
        raise SystemExit("empty pack scope accepted")
    except MalformedRulesetError:
        pass

    # round-trip, deterministic (INV-7: the ruleset is readable data)
    assert from_dict(to_dict(rs2)) == rs2
    assert to_dict(from_dict(to_dict(rs2))) == to_dict(rs2)

    print("ruleset selftest ok")
