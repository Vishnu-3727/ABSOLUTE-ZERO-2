"""RO/05 §7 — Architectural Metrics: RO owns the DEFINITIONS, never the
computation (RO-S7, mirrors CP/04 "benchmarks != architecture"). The ten
rows below are §7's table verbatim, as frozen data. No function in this
module accepts a record or event — that structural absence is what makes
RO-S7 scannable (law_enforcer.py checks it: no callable here has a
parameter shaped like a record/event input, `get_definition` excepted,
which takes only a `metric_id` string)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    name: str
    definition_text: str
    derived_from: tuple  # record/event field names this metric reads, downstream (Observability)


METRIC_DEFINITIONS = (
    MetricDefinition(
        "reasoning_approval_rate", "Reasoning approval rate",
        "Governance permissiveness in practice: REASONING_APPROVED decisions "
        "over all decided outcomes.",
        ("reasoning.decided.payload.outcome",),
    ),
    MetricDefinition(
        "deterministic_avoidance_rate", "Deterministic avoidance rate",
        "Demands resolved below rung R (the headline metric, RO/00 §11.1) — "
        "must trend up.",
        ("reasoning.decided.payload.outcome",),
    ),
    MetricDefinition(
        "provider_utilization", "Provider utilization",
        "Attempt/invocation volume per descriptor row (provider_id).",
        ("reasoning.completed.payload.provider_id", "reasoning.failed.payload.provider_id"),
    ),
    MetricDefinition(
        "budget_utilization", "Budget utilization",
        "Allocated vs. consumed, per sealed outcome record.",
        ("outcome.budget_consumed", "outcome.budget_remaining"),
    ),
    MetricDefinition(
        "retry_frequency", "Retry frequency",
        "Attempts per envelope, attributed per failure class (F1-F8).",
        ("outcome.attempt_index", "outcome.failure_class"),
    ),
    MetricDefinition(
        "context_reduction_ratio", "Context reduction ratio",
        "RQM offered vs. sent — request.context_audit's inclusion/reduction sizes.",
        ("reasoning_request.context_audit",),
    ),
    MetricDefinition(
        "first_pass_success", "First-pass success",
        "Returned + verification-accepted on attempt 1.",
        ("outcome.attempt_index", "outcome.recovery_kind"),
    ),
    MetricDefinition(
        "verification_acceptance_rate", "Verification acceptance rate",
        "Consumed from Verification's own events (RO/05 §5), attributed per "
        "capability/provider.",
        ("verification.accepted",),
    ),
    MetricDefinition(
        "reasoning_latency_class_distribution", "Reasoning latency class distribution",
        "Cost-shape visibility over the descriptor row's declared latency class.",
        ("descriptor_row.latency_class",),
    ),
    MetricDefinition(
        "cost_class_distribution", "Cost class distribution",
        "Spend-shape visibility over the descriptor row's declared cost class.",
        ("descriptor_row.cost_class",),
    ),
)

_BY_ID = {m.metric_id: m for m in METRIC_DEFINITIONS}


def get_definition(metric_id):
    return _BY_ID.get(metric_id)


if __name__ == "__main__":
    assert len(METRIC_DEFINITIONS) == 10
    ids = [m.metric_id for m in METRIC_DEFINITIONS]
    assert len(ids) == len(set(ids))  # stable, unique ids
    assert get_definition("budget_utilization").name == "Budget utilization"
    assert get_definition("nonexistent") is None

    # RO/00 §11.1's headline metric is present
    assert "deterministic_avoidance_rate" in ids

    print("metrics selftest ok")
