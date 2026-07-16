"""SGPE Policy Store — condition grammar (SGPE/01 §2). A rule's optional
`condition` is a declarative predicate over Question facts, drawn from a
closed, versioned grammar: comparisons, set membership, boolean
composition -- DATA structures, never executable code (no eval, no
Turing-completeness, no escape hatch to code). The Store stores and
structurally validates shape; what a condition MEANS at evaluation time is
the Evaluator's business (SGPE/00 §3.3), not this module's.

Three closed node kinds, nothing else:
- `Comparison` -- fact OP value, OP in COMPARISON_OPS
- `SetMembership` -- fact OP values, OP in SET_OPS
- `BooleanComposition` -- OP over nested condition nodes, OP in BOOL_OPS
  (`not` takes exactly one operand; `and`/`or` take two or more)"""
from dataclasses import dataclass

COMPARISON_OPS = ("eq", "ne", "lt", "lte", "gt", "gte")
SET_OPS = ("in", "not_in")
BOOL_OPS = ("and", "or", "not")

_SCALAR_TYPES = (str, int, float, type(None))  # bool checked separately (isinstance(True, int) is True)


class ConditionRefusal(Exception):
    """Base for condition.py refusals."""


class MalformedConditionError(ConditionRefusal):
    """A condition node failed structural validation against the closed
    grammar (unknown op, non-scalar value, empty/malformed operands)."""


def _validate_fact_name(fact):
    if not isinstance(fact, str) or not fact:
        raise MalformedConditionError("condition.bad_fact_name:" + repr(fact))


def _validate_scalar(value):
    if isinstance(value, bool):
        return
    if not isinstance(value, _SCALAR_TYPES):
        raise MalformedConditionError("condition.value_not_scalar:" + repr(value))


@dataclass(frozen=True)
class Comparison:
    fact: str
    op: str
    value: object


def build_comparison(fact, op, value):
    _validate_fact_name(fact)
    if op not in COMPARISON_OPS:
        raise MalformedConditionError("condition.unknown_comparison_op:" + repr(op))
    _validate_scalar(value)
    return Comparison(fact=fact, op=op, value=value)


@dataclass(frozen=True)
class SetMembership:
    fact: str
    op: str
    values: tuple


def build_set_membership(fact, op, values):
    _validate_fact_name(fact)
    if op not in SET_OPS:
        raise MalformedConditionError("condition.unknown_set_op:" + repr(op))
    if not isinstance(values, (tuple, list)) or not values:
        raise MalformedConditionError("condition.empty_or_bad_values:" + repr(values))
    value_tuple = tuple(values)
    for v in value_tuple:
        _validate_scalar(v)
    return SetMembership(fact=fact, op=op, values=value_tuple)


@dataclass(frozen=True)
class BooleanComposition:
    op: str
    operands: tuple


def build_boolean(op, operands):
    if op not in BOOL_OPS:
        raise MalformedConditionError("condition.unknown_bool_op:" + repr(op))
    if not isinstance(operands, (tuple, list)):
        raise MalformedConditionError("condition.bad_operands:" + repr(operands))
    operand_tuple = tuple(operands)
    for o in operand_tuple:
        if not isinstance(o, (Comparison, SetMembership, BooleanComposition)):
            raise MalformedConditionError("condition.operand_not_built:" + repr(o))
    if op == "not" and len(operand_tuple) != 1:
        raise MalformedConditionError(
            "condition.not_requires_exactly_one_operand:" + repr(len(operand_tuple)))
    if op in ("and", "or") and len(operand_tuple) < 2:
        raise MalformedConditionError(
            "condition.and_or_require_at_least_two_operands:" + repr(len(operand_tuple)))
    return BooleanComposition(op=op, operands=operand_tuple)


def to_dict(node):
    if isinstance(node, Comparison):
        return {"node": "comparison", "fact": node.fact, "op": node.op, "value": node.value}
    if isinstance(node, SetMembership):
        return {"node": "set_membership", "fact": node.fact, "op": node.op, "values": list(node.values)}
    if isinstance(node, BooleanComposition):
        return {"node": "boolean", "op": node.op, "operands": [to_dict(o) for o in node.operands]}
    raise MalformedConditionError("condition.unknown_node_type:" + repr(node))


def from_dict(data):
    kind = data.get("node")
    if kind == "comparison":
        return build_comparison(data["fact"], data["op"], data["value"])
    if kind == "set_membership":
        return build_set_membership(data["fact"], data["op"], tuple(data["values"]))
    if kind == "boolean":
        return build_boolean(data["op"], tuple(from_dict(o) for o in data["operands"]))
    raise MalformedConditionError("condition.unknown_node_type:" + repr(data))


if __name__ == "__main__":
    c1 = build_comparison("usage.tokens", "lt", 1000)
    c2 = build_set_membership("request.region", "in", ("us", "eu"))
    both = build_boolean("and", (c1, c2))
    neg = build_boolean("not", (c1,))

    assert both.operands == (c1, c2)
    assert neg.operands == (c1,)

    # round trip
    d = to_dict(both)
    restored = from_dict(d)
    assert restored == both

    # closed ops
    try:
        build_comparison("f", "matches", "x")
        raise SystemExit("invented comparison op accepted")
    except MalformedConditionError:
        pass
    try:
        build_set_membership("f", "subset_of", ("a",))
        raise SystemExit("invented set op accepted")
    except MalformedConditionError:
        pass
    try:
        build_boolean("xor", (c1, c2))
        raise SystemExit("invented boolean op accepted")
    except MalformedConditionError:
        pass

    # arity
    try:
        build_boolean("not", (c1, c2))
        raise SystemExit("not with two operands accepted")
    except MalformedConditionError:
        pass
    try:
        build_boolean("and", (c1,))
        raise SystemExit("and with one operand accepted")
    except MalformedConditionError:
        pass

    # not executable: only data types allowed as scalars -- no escape hatch to code
    try:
        build_comparison("f", "eq", lambda: 1)
        raise SystemExit("non-scalar (callable) value accepted")
    except MalformedConditionError:
        pass

    # nested composition round-trips
    nested = build_boolean("or", (build_boolean("not", (c1,)), c2))
    assert from_dict(to_dict(nested)) == nested

    print("condition selftest ok")
