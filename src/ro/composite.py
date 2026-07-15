"""RO/04 §8 — Multi-Provider Coordination (RO/05 §10 blueprint group G5).

Composite reasoning is governed COMPOSITION of individually-sealed single
invocations (RO-E11) — there is no special multi-provider invocation
primitive. `run_composite` never touches an engine boundary itself: it
drives an injected `constituent_runner(request, resolution, budget_envelope)
-> tuple of SealedOutcomeRecord`, already bound (by whoever built it) to
its own boundary double and execution policy — composite.py is pure
sequencing + aggregation + budget threading over already-sealed artifacts.

Sequential/specialist/review patterns pass PRIOR SEALED FINAL RECORDS
(never a live engine handle, never another provider's channel) into the
next constituent's `prepare` callable — the only integration point,
mirroring RO/03's own preparation machinery (RO-E11 isolation). Parallel/
ensemble/debate patterns run in the plan's stable declared order with no
data flowing between constituents (concurrency is derived, never required
— RO/04 §8).

Aggregation (ensemble/debate) is a pure function over CONFORMING (RETURNED)
constituent finals only, never anything with its own reasoning judgment
(RO/00 §6 territory) — the RO/02-gated aggregation variant is explicitly
out of scope here (RO/04 §8 "unless that aggregation is itself a governed
approved demand through the full RO/02 gate").
"""
from dataclasses import dataclass
import hashlib
import json

from . import outcome as _outcome
from . import budget as _budget

PATTERNS = ("sequential", "parallel", "ensemble", "specialist_pipeline",
            "review_chain", "debate")
AGGREGATION_RULES = ("majority_of_conforming", "first_conforming_by_stable_order")
FAILURE_SEMANTICS = ("all_required", "any_sufficient", "quorum")

# Patterns whose constituents feed on PRIOR sealed finals (RO/04 §8 table);
# the rest run independently in declared order.
_SEQUENTIAL_PATTERNS = ("sequential", "specialist_pipeline", "review_chain")
_ENSEMBLE_PATTERNS = ("ensemble", "debate")


class CompositeRefusal(Exception):
    """Base for composite-plan/composition-time refusals."""


class UnknownPatternError(CompositeRefusal):
    pass


class MissingAggregationRuleError(CompositeRefusal):
    """RO/04 §8: ensemble/debate must declare an aggregation rule at
    composition time — never improvised at run time."""


class UnknownFailureSemanticsError(CompositeRefusal):
    pass


class EmptyConstituentsError(CompositeRefusal):
    pass


@dataclass(frozen=True)
class ConstituentSpec:
    constituent_id: str
    prepare: object       # callable(prior_sealed_finals: tuple) -> (request, resolution)
    budget_ceiling: int


@dataclass(frozen=True)
class CompositePlan:
    pattern: str
    constituents: tuple            # tuple of ConstituentSpec, stable declared order
    aggregation_rule: object       # str | None — required for ensemble/debate
    failure_semantics: str
    quorum_k: object               # int | None — required for "quorum"


def build_composite_plan(pattern, constituents, failure_semantics, *,
                          aggregation_rule=None, quorum_k=None):
    """RO/04 §8: refuses loud on any missing declared-data element — a
    composite with undeclared failure semantics or aggregation never
    starts (mirrors RO/03 §9 constraint-completeness discipline)."""
    if pattern not in PATTERNS:
        raise UnknownPatternError("composite.unknown_pattern:" + str(pattern))
    constituents = tuple(constituents)
    if not constituents:
        raise EmptyConstituentsError("composite.empty_constituents")
    if failure_semantics not in FAILURE_SEMANTICS:
        raise UnknownFailureSemanticsError("composite.unknown_failure_semantics:" + str(failure_semantics))
    if pattern in _ENSEMBLE_PATTERNS and aggregation_rule not in AGGREGATION_RULES:
        raise MissingAggregationRuleError("composite.missing_aggregation_rule:" + str(aggregation_rule))
    if failure_semantics == "quorum":
        if not isinstance(quorum_k, int) or isinstance(quorum_k, bool) \
                or not (1 <= quorum_k <= len(constituents)):
            raise CompositeRefusal("composite.bad_quorum_k:" + repr(quorum_k))
    return CompositePlan(pattern=pattern, constituents=constituents,
                          aggregation_rule=aggregation_rule,
                          failure_semantics=failure_semantics, quorum_k=quorum_k)


@dataclass(frozen=True)
class CompositeOutcome:
    composite_id: str
    pattern: str
    constituent_final_refs: tuple      # tuple of sealed-final content hashes, declared order
    aggregation_result_ref: object     # str (a constituent final's content hash) | None
    failure_semantics_verdict: str     # "satisfied" | "failed"


def _aggregate(rule, finals):
    """Pure function over CONFORMING (RETURNED) finals only. Returns the
    winning SealedOutcomeRecord, or None if nothing conformed."""
    conforming = [(i, f) for i, f in enumerate(finals) if f.recovery_kind == "RETURNED"]
    if not conforming:
        return None
    if rule == "first_conforming_by_stable_order":
        return conforming[0][1]
    if rule == "majority_of_conforming":
        groups = {}
        for i, f in conforming:
            key = json.dumps(_outcome._unfreeze(f.output), sort_keys=True, separators=(",", ":"))
            groups.setdefault(key, []).append((i, f))
        best_key, best_group = None, None
        for key, group in groups.items():
            group.sort(key=lambda t: t[0])
            if best_group is None or len(group) > len(best_group) \
                    or (len(group) == len(best_group) and group[0][0] < best_group[0][0]):
                best_key, best_group = key, group
        return best_group[0][1]
    raise CompositeRefusal("composite.unknown_aggregation_rule:" + str(rule))


def _verdict(semantics, quorum_k, finals):
    returned_count = sum(1 for f in finals if f.recovery_kind == "RETURNED")
    if semantics == "all_required":
        ok = returned_count == len(finals)
    elif semantics == "any_sufficient":
        ok = returned_count >= 1
    else:  # "quorum"
        ok = returned_count >= quorum_k
    return "satisfied" if ok else "failed"


def _composite_id(plan, finals):
    payload = plan.pattern + ":" + ",".join(_outcome.content_hash(f) for f in finals)
    return hashlib.sha256(payload.encode()).hexdigest()


def run_composite(plan, parent_envelope, constituent_runner):
    """RO/04 §8: one parent envelope (RO-P7 threading — every child envelope
    is allocated FROM the parent, sibling accounting via
    `already_allocated_from_parent`); every constituent sealed individually
    via the injected `constituent_runner`; composite outcome sealed like
    everything else."""
    already_allocated = 0
    finals = []
    prior_finals = ()

    for spec in plan.constituents:
        child_envelope = _budget.allocate_budget(
            spec.budget_ceiling, parent_envelope.source_policy_version,
            parent=parent_envelope, already_allocated_from_parent=already_allocated)
        already_allocated += spec.budget_ceiling

        inputs = prior_finals if plan.pattern in _SEQUENTIAL_PATTERNS else ()
        request, resolution = spec.prepare(inputs)
        sealed = constituent_runner(request, resolution, child_envelope)
        final = sealed[-1]
        finals.append(final)
        if plan.pattern in _SEQUENTIAL_PATTERNS:
            prior_finals = prior_finals + (final,)

    aggregation_result = None
    if plan.pattern in _ENSEMBLE_PATTERNS:
        aggregation_result = _aggregate(plan.aggregation_rule, finals)

    verdict = _verdict(plan.failure_semantics, plan.quorum_k, finals)

    return CompositeOutcome(
        composite_id=_composite_id(plan, finals),
        pattern=plan.pattern,
        constituent_final_refs=tuple(_outcome.content_hash(f) for f in finals),
        aggregation_result_ref=(_outcome.content_hash(aggregation_result)
                                 if aggregation_result is not None else None),
        failure_semantics_verdict=verdict,
    )


def to_dict(composite_outcome):
    return {
        "composite_id": composite_outcome.composite_id, "pattern": composite_outcome.pattern,
        "constituent_final_refs": list(composite_outcome.constituent_final_refs),
        "aggregation_result_ref": composite_outcome.aggregation_result_ref,
        "failure_semantics_verdict": composite_outcome.failure_semantics_verdict,
    }


def canonical(composite_outcome):
    return json.dumps(to_dict(composite_outcome), sort_keys=True, separators=(",", ":")).encode()


def content_hash(composite_outcome):
    return hashlib.sha256(canonical(composite_outcome)).hexdigest()


if __name__ == "__main__":
    from .budget import allocate_budget

    def _final(kind, idx, output=None, failure_class=None):
        return _outcome.build_sealed_outcome(
            request_content_hash="r" + str(idx), resolution_content_hash="s" + str(idx),
            preparation_coordinates={}, attempt_index=1, attempt_history_refs=(),
            recovery_kind=kind, provider_id="p" + str(idx), budget_consumed=1, budget_remaining=9,
            failure_class=failure_class, output=output,
        )

    parent = allocate_budget(1000, source_policy_version=1)

    # sequential: prior sealed output feeds next prepare()
    seen = []

    def _seq_runner(request, resolution, envelope):
        seen.append((request, envelope.ceiling))
        idx = len(seen)
        return (_final("RETURNED", idx, output={"n": idx}),)

    specs = tuple(
        ConstituentSpec(constituent_id="c" + str(i),
                         prepare=(lambda prior, i=i: (("req", tuple(f.output["n"] for f in prior) if prior else ()), "res")),
                         budget_ceiling=100)
        for i in range(3)
    )
    seq_plan = build_composite_plan("sequential", specs, "all_required")
    seq_out = run_composite(seq_plan, parent, _seq_runner)
    assert seq_out.pattern == "sequential"
    assert seen[1][0] == ("req", (1,))   # constituent 2 saw constituent 1's sealed output
    assert seen[2][0] == ("req", (1, 2))
    assert seq_out.failure_semantics_verdict == "satisfied"

    # parallel independence: prepare() always receives an empty prior tuple
    par_calls = []

    def _par_runner(request, resolution, envelope):
        idx = len(par_calls) + 1
        par_calls.append(request)
        return (_final("RETURNED", idx, output={"n": idx}),)

    par_specs = tuple(
        ConstituentSpec("p" + str(i), prepare=lambda prior: (("independent", prior), "res"), budget_ceiling=50)
        for i in range(3)
    )
    par_plan = build_composite_plan("parallel", par_specs, "any_sufficient")
    par_out = run_composite(par_plan, parent, _par_runner)
    assert all(req == ("independent", ()) for req in par_calls)
    assert par_out.failure_semantics_verdict == "satisfied"

    # ensemble: majority_of_conforming with stable tie-break
    def _ens_runner_factory(outputs):
        calls = []

        def _runner(request, resolution, envelope):
            idx = len(calls)
            calls.append(idx)
            kind, out = outputs[idx]
            return (_final(kind, idx, output=out, failure_class=("F1" if kind == "FAILED" else None)),)
        return _runner

    ens_specs = tuple(
        ConstituentSpec("e" + str(i), prepare=lambda prior: (("x",), "res"), budget_ceiling=10)
        for i in range(4)
    )
    ens_plan = build_composite_plan("ensemble", ens_specs, "any_sufficient",
                                     aggregation_rule="majority_of_conforming")
    outputs = [("RETURNED", {"a": 1}), ("RETURNED", {"a": 2}), ("RETURNED", {"a": 1}), ("FAILED", None)]
    ens_out = run_composite(ens_plan, parent, _ens_runner_factory(outputs))
    # {"a": 1} appears twice (indices 0, 2) vs {"a": 2} once -> majority wins, first of the group (index 0)
    winner_hash = _outcome.content_hash(_final("RETURNED", 0, output={"a": 1}))
    assert ens_out.aggregation_result_ref == winner_hash

    # first_conforming_by_stable_order
    fc_plan = build_composite_plan("ensemble", ens_specs, "any_sufficient",
                                    aggregation_rule="first_conforming_by_stable_order")
    outputs2 = [("FAILED", None), ("RETURNED", {"a": 9}), ("RETURNED", {"a": 8}), ("FAILED", None)]
    fc_out = run_composite(fc_plan, parent, _ens_runner_factory(outputs2))
    assert fc_out.aggregation_result_ref == _outcome.content_hash(_final("RETURNED", 1, output={"a": 9}))

    # failure semantics: all_required fails if any constituent isn't RETURNED
    mixed_outputs = [("RETURNED", {"a": 1}), ("FAILED", None), ("RETURNED", {"a": 1}), ("RETURNED", {"a": 1})]
    all_req_plan = build_composite_plan("parallel", ens_specs, "all_required")
    all_req_out = run_composite(all_req_plan, parent, _ens_runner_factory(mixed_outputs))
    assert all_req_out.failure_semantics_verdict == "failed"

    # quorum: mixed_outputs has 3 RETURNED of 4 constituents
    quorum_met_plan = build_composite_plan("parallel", ens_specs, "quorum", quorum_k=3)
    quorum_met_out = run_composite(quorum_met_plan, parent, _ens_runner_factory(mixed_outputs))
    assert quorum_met_out.failure_semantics_verdict == "satisfied"
    quorum_unmet_plan = build_composite_plan("parallel", ens_specs, "quorum", quorum_k=4)
    quorum_unmet_out = run_composite(quorum_unmet_plan, parent, _ens_runner_factory(mixed_outputs))
    assert quorum_unmet_out.failure_semantics_verdict == "failed"

    # missing aggregation rule refused
    try:
        build_composite_plan("ensemble", ens_specs, "any_sufficient")
        raise SystemExit("missing aggregation rule accepted")
    except MissingAggregationRuleError:
        pass

    # bad quorum_k refused
    try:
        build_composite_plan("parallel", ens_specs, "quorum", quorum_k=0)
        raise SystemExit("bad quorum_k accepted")
    except CompositeRefusal:
        pass

    # empty constituents refused
    try:
        build_composite_plan("parallel", (), "any_sufficient")
        raise SystemExit("empty constituents accepted")
    except EmptyConstituentsError:
        pass

    print("composite selftest ok")
