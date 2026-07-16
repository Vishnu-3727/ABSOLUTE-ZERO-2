"""SGPE Policy Store — rule shape (SGPE/01 §2). A Rule is a data record,
never procedural logic: `rule_id` (unique within its document -- checked
by document.py, not here, since uniqueness is a document-level property),
`target` (domain + operation + resource selector, in vocabulary terms --
terms are Compiler-checked, not the Store's job), `effect` (one of the
SGPE/00 §3.3 decision alphabet: ALLOW / DENY / REQUIRE_APPROVAL /
LIMIT(value)), optional `condition` (condition.py's closed grammar), and
optional `final` (SGPE/00 §6's only modifier -- legal at system scope
only, but THAT legality check is the Compiler's; this module records
`final` as a structural bool field, nothing more, per PS-6)."""
from dataclasses import dataclass

from .condition import BooleanComposition, Comparison, SetMembership

EFFECT_KINDS = ("ALLOW", "DENY", "REQUIRE_APPROVAL", "LIMIT")

_CONDITION_TYPES = (Comparison, SetMembership, BooleanComposition)


class RuleRefusal(Exception):
    """Base for rule.py refusals."""


class MalformedEffectError(RuleRefusal):
    """An effect kind outside the closed decision alphabet, or a LIMIT
    effect missing/carrying a spurious value."""


class MalformedTargetError(RuleRefusal):
    """A target (domain/operation/resource selector) failed structural
    validation."""


class MalformedRuleError(RuleRefusal):
    """A rule failed structural validation (bad rule_id, unbuilt target,
    unbuilt effect, unbuilt condition, non-bool final)."""


@dataclass(frozen=True)
class Effect:
    kind: str
    value: object  # None except LIMIT


def build_effect(kind, value=None):
    if kind not in EFFECT_KINDS:
        raise MalformedEffectError("rule.unknown_effect_kind:" + repr(kind))
    if kind == "LIMIT":
        if value is None:
            raise MalformedEffectError("rule.limit_requires_a_value")
    elif value is not None:
        raise MalformedEffectError("rule.non_limit_effect_carries_a_value:" + repr(kind) + ":" + repr(value))
    return Effect(kind=kind, value=value)


@dataclass(frozen=True)
class Target:
    domain: str
    operation: str
    resource_selector: str


def build_target(domain, operation, resource_selector):
    for label, value in (("domain", domain), ("operation", operation),
                          ("resource_selector", resource_selector)):
        if not isinstance(value, str) or not value:
            raise MalformedTargetError("rule.bad_" + label + ":" + repr(value))
    return Target(domain=domain, operation=operation, resource_selector=resource_selector)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    target: Target
    effect: Effect
    condition: object  # None, or one of condition.py's built node types
    final: bool


def build_rule(rule_id, target, effect, condition=None, final=False):
    if not isinstance(rule_id, str) or not rule_id:
        raise MalformedRuleError("rule.bad_rule_id:" + repr(rule_id))
    if not isinstance(target, Target):
        raise MalformedRuleError("rule.target_not_built:" + repr(target))
    if not isinstance(effect, Effect):
        raise MalformedRuleError("rule.effect_not_built:" + repr(effect))
    if condition is not None and not isinstance(condition, _CONDITION_TYPES):
        raise MalformedRuleError("rule.condition_not_built:" + repr(condition))
    if not isinstance(final, bool):
        raise MalformedRuleError("rule.final_not_bool:" + repr(final))
    return Rule(rule_id=rule_id, target=target, effect=effect, condition=condition, final=final)


# -- serialization --------------------------------------------------------

def _effect_to_dict(effect):
    return {"kind": effect.kind, "value": effect.value}


def _effect_from_dict(data):
    return build_effect(data["kind"], data.get("value"))


def _target_to_dict(target):
    return {"domain": target.domain, "operation": target.operation,
            "resource_selector": target.resource_selector}


def _target_from_dict(data):
    return build_target(data["domain"], data["operation"], data["resource_selector"])


def to_dict(rule):
    from . import condition as condition_mod
    return {
        "rule_id": rule.rule_id,
        "target": _target_to_dict(rule.target),
        "effect": _effect_to_dict(rule.effect),
        "condition": condition_mod.to_dict(rule.condition) if rule.condition is not None else None,
        "final": rule.final,
    }


def from_dict(data):
    from . import condition as condition_mod
    condition = condition_mod.from_dict(data["condition"]) if data.get("condition") is not None else None
    return build_rule(data["rule_id"], _target_from_dict(data["target"]), _effect_from_dict(data["effect"]),
                       condition=condition, final=data.get("final", False))


if __name__ == "__main__":
    from . import condition as condition_mod

    target = build_target("filesystem", "write", "/tmp/*")
    effect = build_effect("DENY")
    limit_effect = build_effect("LIMIT", 1000)
    cond = condition_mod.build_comparison("usage.tokens", "lt", 1000)

    r1 = build_rule("r1", target, effect)
    r2 = build_rule("r2", target, limit_effect, condition=cond, final=True)
    assert r1.final is False
    assert r2.final is True

    # round trip
    restored = from_dict(to_dict(r2))
    assert restored == r2
    restored_no_condition = from_dict(to_dict(r1))
    assert restored_no_condition == r1

    # closed effect alphabet
    try:
        build_effect("MAYBE")
        raise SystemExit("invented effect kind accepted")
    except MalformedEffectError:
        pass
    try:
        build_effect("LIMIT")
        raise SystemExit("LIMIT effect without a value accepted")
    except MalformedEffectError:
        pass
    try:
        build_effect("ALLOW", 5)
        raise SystemExit("non-LIMIT effect carrying a value accepted")
    except MalformedEffectError:
        pass

    # target completeness
    try:
        build_target("", "write", "/tmp/*")
        raise SystemExit("empty domain accepted")
    except MalformedTargetError:
        pass

    # rule completeness
    try:
        build_rule("", target, effect)
        raise SystemExit("empty rule_id accepted")
    except MalformedRuleError:
        pass
    try:
        build_rule("r3", {"not": "a target"}, effect)
        raise SystemExit("unbuilt target accepted")
    except MalformedRuleError:
        pass
    try:
        build_rule("r4", target, effect, final="yes")
        raise SystemExit("non-bool final accepted")
    except MalformedRuleError:
        pass

    print("rule selftest ok")
