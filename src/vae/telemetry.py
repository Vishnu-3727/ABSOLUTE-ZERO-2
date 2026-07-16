"""VAE Phase 5 -- Telemetry (VAE/06 Phase 5, VAE/04 §8, VAE-O8, VAE-I12).

VAE/04 §8 fixes *what families of signals exist*, not their expression in
Observability's schema ("no metric definitions or math appear here" --
mirrors `ro/metrics.py`'s "zero computation" discipline, applied here to
zero NEW computation: every emit_* function below only reshapes facts
Phases 1-4 already computed -- evidence items, a derivation account, a
delegation/static-check transition -- into a reference-shaped payload for
an injected sink. Nothing here derives a verdict, a confidence dimension,
or an assurance level a second time; Phase 3's `derivation.derive()` stays
the sole authority for all of that (VAE-A1).

The six signal families, VAE/04 §8's table, closed here exactly as
`events.py` closes VAE's own publish/consume sets -- SIGNAL_FAMILIES is
this module's own closed five-plus-one, structurally enforced by `_emit`
the same way `events.build_envelope` refuses an invented event name:

- `judgment_outcome` -- every verdict (artifact, rules version, verdict,
  failure cause, assurance level) -- feeds calibration.
- `check_activity` -- every delegation/static-check transition (dispatched,
  resulted, expired, static_run) with its result category -- feeds
  historical verification effectiveness.
- `coverage_readout` -- per judgment, the derivation account's own coverage
  dimension (level/established/total) -- feeds evidence coverage honesty.
- `agreement_record` -- per (level, rule) claim with two or more
  independent/corroborating/conflicting items, whether the sources agreed
  or conflicted -- feeds the independence-agreement concern (VAE-M4:
  substrate preserved, never collapsed to a single number here).
- `derivation_consistency` -- the record's own content hash alongside its
  derived verdict/assurance level -- feeds cross-execution consistency
  (VAE-I6 demonstrated, not asserted: an external comparer, or Phase 5's
  own `runtime.replay`, ties two of these together to prove it).
- `latency_demand` -- judgment/delegation durations and queue depth, ALL
  caller-supplied numbers (this module reads no clock, VAE-I6; a caller
  that has an injected `now` source computes durations itself and hands
  them in already-subtracted).

`emit_*` functions are pure except for the one side effect of calling
`sink.record(family, payload)` -- no branch here reads back what it just
recorded, and no telemetry emission is ever conditional on system load
(VAE-O8: "emitted unconditionally... no sampling"). `TelemetrySinkDouble`
is VAE's own in-memory stand-in for Observability's real sink (the same
zero-seam-over-DRY doubles discipline `bus_double.py`/`storage_double.py`
already state)."""

SIGNAL_FAMILIES = (
    "judgment_outcome", "check_activity", "coverage_readout",
    "agreement_record", "derivation_consistency", "latency_demand",
)

CHECK_PHASES = ("dispatched", "resulted", "expired", "static_run")


class TelemetryRefusal(Exception):
    """Base for telemetry.py refusals."""


class UnknownSignalFamilyError(TelemetryRefusal):
    """A signal family outside VAE/04 §8's closed six."""


class UnknownCheckPhaseError(TelemetryRefusal):
    """emit_check_activity() given a phase outside the closed four."""


def _emit(sink, family, payload):
    if family not in SIGNAL_FAMILIES:
        raise UnknownSignalFamilyError("telemetry.unknown_signal_family:" + str(family))
    sink.record(family, dict(payload))


def emit_judgment_outcome(sink, artifact_ref, rules_version, verdict, failure_cause, assurance_level):
    """One per terminal verdict (VAE/04 §8 row 1)."""
    _emit(sink, "judgment_outcome", {
        "artifact_id": artifact_ref, "rules_version": rules_version,
        "verdict": verdict, "failure_cause": failure_cause, "assurance_level": assurance_level,
    })


def emit_check_activity(sink, artifact_ref, check, phase, result_category=None):
    """One per delegation/static-check transition (VAE/04 §8 row 2).
    `phase` is one of CHECK_PHASES; `result_category` is the recorded
    outcome string when the transition settled one (omitted for
    "dispatched", which has no outcome yet)."""
    if phase not in CHECK_PHASES:
        raise UnknownCheckPhaseError("telemetry.unknown_check_phase:" + str(phase))
    payload = {"artifact_id": artifact_ref, "check": check, "phase": phase}
    if result_category is not None:
        payload["result_category"] = result_category
    _emit(sink, "check_activity", payload)


def emit_coverage_readout(sink, artifact_ref, coverage):
    """One per judgment, from the derivation account's own `coverage`
    mapping (VAE/04 §8 row 3) -- never recomputed here."""
    _emit(sink, "coverage_readout", {
        "artifact_id": artifact_ref, "level": coverage["level"],
        "established": coverage["established"], "total": coverage["total"],
    })


def _group_claims(items):
    """(level, rule) -> items, in append order -- reshaping only, for the
    agreement-record signal; never recomputes confidence or verdict math
    (that stays derivation.py's exclusive job, VAE-A1)."""
    claims = {}
    order = []
    for item in items:
        key = (item.level, item.rule)
        if key not in claims:
            claims[key] = []
            order.append(key)
        claims[key].append(item)
    return order, claims


def emit_agreement_records(sink, artifact_ref, items):
    """One per (level, rule) claim that has at least two independent/
    corroborating/conflicting items to compare (VAE/04 §8 row 4) -- a
    single-source or all-missing claim has nothing to agree or conflict
    about yet, so it emits nothing here (Phase 3's uncertainty/coverage
    signals already cover that case). `sources` is sorted for determinism
    (VAE-I6: no dict/set-iteration-order leakage into an emitted payload)."""
    order, claims = _group_claims(items)
    for level, rule in order:
        entries = claims[(level, rule)]
        conflicting = [it for it in entries if it.contribution_kind == "conflicting"]
        substantive = [it for it in entries if it.contribution_kind in ("independent", "corroborating")]
        if not conflicting and len(substantive) < 2:
            continue
        if conflicting:
            agreement = "conflicted"
        elif len({it.result for it in substantive}) <= 1:
            agreement = "agreed"
        else:
            agreement = "disagreed"
        sources = tuple(sorted(it.source for it in entries if it.source))
        _emit(sink, "agreement_record", {
            "artifact_id": artifact_ref, "level": level, "rule": rule,
            "sources": sources, "agreement": agreement,
        })


def emit_derivation_consistency(sink, artifact_ref, rules_version, record_content_hash, account):
    """One per judgment: the record's own content hash alongside its
    derived verdict/assurance level (VAE/04 §8 row 5) -- the reference
    pair an external comparer (or `runtime.replay`) ties together to
    demonstrate re-derivation consistency, never asserted here."""
    _emit(sink, "derivation_consistency", {
        "artifact_id": artifact_ref, "rules_version": rules_version,
        "record_content_hash": record_content_hash,
        "verdict": account["verdict"], "assurance_level": account["assurance_level"],
    })


def emit_latency_demand(sink, artifact_ref, judgment_duration=None,
                         delegation_durations=None, queue_depth=None):
    """Judgment/delegation durations and queue depth (VAE/04 §8 row 6) --
    every number is caller-supplied; this module never reads a clock
    (VAE-I6). All three fields are optional so a caller with only some of
    them (e.g. queue depth alone, at intake time) still emits a valid
    signal rather than inventing zeros for what it does not know."""
    payload = {"artifact_id": artifact_ref}
    if judgment_duration is not None:
        payload["judgment_duration"] = judgment_duration
    if delegation_durations is not None:
        payload["delegation_durations"] = dict(sorted(delegation_durations.items()))
    if queue_depth is not None:
        payload["queue_depth"] = queue_depth
    _emit(sink, "latency_demand", payload)


class TelemetrySinkDouble:
    """VAE's own in-memory stand-in for Observability's real telemetry
    sink -- records everything, in arrival order, per family."""

    def __init__(self):
        self._records = []

    def record(self, family, payload):
        self._records.append({"family": family, "payload": dict(payload)})

    def all(self):
        return list(self._records)

    def by_family(self, family):
        return [r["payload"] for r in self._records if r["family"] == family]


if __name__ == "__main__":
    from . import derivation
    from . import evidence

    sink = TelemetrySinkDouble()

    # -- judgment_outcome ----------------------------------------------------
    emit_judgment_outcome(sink, "artifact:a1", 1, "passed", None, "Verified — High Assurance")
    assert sink.by_family("judgment_outcome")[-1]["verdict"] == "passed"

    # -- check_activity: closed phase set, unknown phase refused loud -------
    emit_check_activity(sink, "artifact:a1", "structural", "dispatched")
    emit_check_activity(sink, "artifact:a1", "structural", "resulted", result_category="success")
    activity = sink.by_family("check_activity")
    assert activity[0]["phase"] == "dispatched" and "result_category" not in activity[0]
    assert activity[1]["result_category"] == "success"
    try:
        emit_check_activity(sink, "artifact:a1", "structural", "teleported")
        raise SystemExit("unknown check phase accepted")
    except UnknownCheckPhaseError:
        pass

    # -- coverage_readout -----------------------------------------------------
    emit_coverage_readout(sink, "artifact:a1", {"level": "strong", "established": 3, "total": 3})
    assert sink.by_family("coverage_readout")[-1]["level"] == "strong"

    # -- agreement_record: corroborated, conflicted, and skipped-single -----
    def item(rule, source, result, kind, level="structural"):
        return evidence.build_evidence_item(rule, "artifact:a1", source, result, kind, level)

    corroborated_items = [item("r1", "s1", "pass", "independent"),
                            item("r1", "s2", "pass", "corroborating")]
    emit_agreement_records(sink, "artifact:a1", corroborated_items)
    agreement = sink.by_family("agreement_record")
    assert agreement[-1]["agreement"] == "agreed"
    assert agreement[-1]["sources"] == ("s1", "s2")  # sorted, deterministic

    conflicted_items = [item("r2", "s1", "pass", "independent"),
                         item("r2", "s2", "fail", "conflicting")]
    emit_agreement_records(sink, "artifact:a1", conflicted_items)
    assert sink.by_family("agreement_record")[-1]["agreement"] == "conflicted"

    disagreed_items = [item("r3", "s1", "pass", "independent"),
                        item("r3", "s2", "fail", "corroborating")]
    emit_agreement_records(sink, "artifact:a1", disagreed_items)
    assert sink.by_family("agreement_record")[-1]["agreement"] == "disagreed"

    single_item = [item("r4", "s1", "pass", "independent")]
    before = len(sink.by_family("agreement_record"))
    emit_agreement_records(sink, "artifact:a1", single_item)
    assert len(sink.by_family("agreement_record")) == before  # nothing to agree/conflict about

    # -- derivation_consistency ------------------------------------------------
    policy = derivation.build_derivation_policy(1, coverage_moderate_min_fraction=0.5,
                                                 coverage_strong_min_fraction=0.9)
    record = evidence.build_evidence_record("artifact:a1", 1)
    record = evidence.append_item(record, item("r1", "s1", "pass", "independent"))
    account = derivation.derive(record, policy)
    record_hash = evidence.content_hash(evidence.with_derivation_account(record, account))
    emit_derivation_consistency(sink, "artifact:a1", 1, record_hash, account)
    consistency = sink.by_family("derivation_consistency")[-1]
    assert consistency["record_content_hash"] == record_hash
    assert consistency["verdict"] == account["verdict"]

    # -- latency_demand: caller-supplied numbers only, no clock read ---------
    emit_latency_demand(sink, "artifact:a1", judgment_duration=42,
                         delegation_durations={"semantic": 5, "structural": 10}, queue_depth=3)
    latency = sink.by_family("latency_demand")[-1]
    assert latency["judgment_duration"] == 42 and latency["queue_depth"] == 3
    assert list(latency["delegation_durations"].items()) == [("semantic", 5), ("structural", 10)]

    emit_latency_demand(sink, "artifact:a2", queue_depth=1)  # partial fields are fine
    partial = sink.by_family("latency_demand")[-1]
    assert "judgment_duration" not in partial and "delegation_durations" not in partial

    # -- unconditional, unsampled: every call above actually recorded --------
    assert len(sink.all()) == (1 + 2 + 1 + 3 + 1 + 2)  # single-claim case emits nothing

    # -- unknown signal family refused loud (closed six, VAE-O8) -------------
    try:
        _emit(sink, "made_up_family", {})
        raise SystemExit("unknown signal family accepted")
    except UnknownSignalFamilyError:
        pass

    print("telemetry selftest ok")
