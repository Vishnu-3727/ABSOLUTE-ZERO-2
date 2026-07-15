"""VAE Phase 4 -- Pending-judgment projection (VAE/06 Phase 4, VAE/04 §4,
§6, VAE-O1, VAE-O10).

VAE/04 §6.1 classifies VAE's pending state exactly as RSM/02 ADR-RSM-2
classifies the Kernel Ledger: "a deterministic, discardable,
rebuildable-from-the-bus projection kept purely for a subsystem's own fast
decisions" -- never a second authority. The authoritative records are
elsewhere (already-persisted evidence/verdicts via Storage, the demand
events that opened each judgment, the rules versions, VAE/04 §6.1's table).

This module holds exactly that projection -- open `judgment.py` aggregates,
keyed by artifact reference, plus the `Intake` that already tracks which
artifacts are open vs. terminal (intake.py's own job, reused rather than
duplicated) -- and one function, `rebuild`, that reconstructs it from
durable sources alone:

- **demand events** (replayed/redelivered, at-least-once) -- each names the
  artifact, the judgment id it would open, the rules version pinned at
  demand time, and which required checks are delegated vs. static, with
  their verification levels (VAE/01 §5) -- see interpretation call 1.
- **persisted records** -- artifact_ref -> already-persisted, account-
  bearing `EvidenceRecord` for every artifact whose verdict was already
  durably written and published; these are recognized terminal and never
  reopened (VAE-O10), via `Intake.mark_terminal` -- the same seam
  emission.py's choreography uses.
- **the rules store** -- the AUTHORITATIVE source of each required check's
  deadline (`ArtifactRules.deadlines`), fetched fresh at rebuild time
  rather than trusted from whatever a demand event happened to carry, so a
  rebuilt judgment's in-flight delegations always carry their original
  rules-assigned deadlines (§6.2), never a stale or drifted copy.

Rebuild never resurrects delegation STATE (VAE-O1: pending state itself is
not durable) -- every rebuilt judgment's delegations start at `Required`,
exactly as `judgment.open_judgment` always starts them; a delegation that
was in flight at crash time is simply re-dispatched (the permitted
no-outcome-yet re-issue, VAE-O3) and, if its rules-assigned deadline has
since passed, resolves straight to Expired through `delegation.py`'s
existing machinery -- no special crash-recovery expiry path exists, per
VAE/04 §6.2's "no special crash-recovery verdict semantics."

**Interpretation calls flagged, most conservative reading taken:**

1. `rules.py`'s `ArtifactRules` fixes `required_checks`/`depth`/`deadlines`
   only -- it has no field classifying a required check as delegated vs.
   static, nor a per-check verification level (VAE/01 §5); that
   classification is not modeled anywhere in Phases 1-3 (the existing
   Phase 2/3 tests supply `delegated_checks`/`static_checks_spec` dicts
   directly to `open_judgment`, never derived from `rules.py`). Rebuild
   therefore takes that classification from each demand event (as
   `delegated_check_levels`/`static_check_levels` mappings) and takes ONLY
   the deadline from the rules store -- the one part of "rules-assigned"
   that IS modeled and durable. Building the delegated/static split from
   rules-as-data is a composition-root concern for a later phase, not
   something this module invents.
2. A demand event whose `judgment_id`/`event_id` has already been applied
   (via `Intake`'s own dedup) is a no-op during rebuild, identically to
   ordinary live intake -- rebuild is "replay the same demand events
   through the same intake discipline," not a bespoke recovery algorithm."""
from dataclasses import dataclass

from . import evidence as evidence_mod
from . import intake as intake_mod
from . import judgment as judgment_mod


class PendingRefusal(Exception):
    """Base for pending.py refusals."""


@dataclass(frozen=True)
class PendingEntry:
    """A read-only, reference-shaped snapshot of one open judgment for
    external inspection (VAE/04 §4: "pending holds references, not
    bodies") -- built on demand from a live `Judgment`, never itself a
    second copy of authority."""
    judgment_id: str
    artifact_ref: str
    rules_version: int
    delegation_states: tuple  # ((check, state, deadline), ...) sorted by check
    static_pending: frozenset
    evidence_item_count: int


def snapshot(judgment):
    states = tuple(sorted(
        (check, d.state, d.deadline) for check, d in judgment.delegations.items()))
    return PendingEntry(
        judgment_id=judgment.judgment_id, artifact_ref=judgment.artifact_ref,
        rules_version=judgment.rules_version, delegation_states=states,
        static_pending=judgment.static_pending, evidence_item_count=len(judgment.record.items))


class PendingProjection:
    """The non-authoritative projection itself: artifact_ref -> open
    `Judgment`, plus the `Intake` recognizing terminal artifacts. Cheap to
    discard and rebuild (VAE-O1) -- there is deliberately no persistence
    method on this class."""

    def __init__(self, intake, judgments):
        self.intake = intake
        self.judgments = dict(judgments)

    def get(self, artifact_ref):
        return self.judgments.get(artifact_ref)

    def update(self, judgment):
        """Record a judgment's advanced state (e.g. after
        dispatch/resolve). A judgment that has been closed and emitted is
        removed by `close_terminal`, not left open here."""
        self.judgments[judgment.artifact_ref] = judgment

    def close_terminal(self, artifact_ref, evidence_record_ref):
        """Retire an artifact from the open projection once its verdict is
        durably persisted and published -- mirrors `intake.mark_terminal`,
        called alongside it (emission.py calls `intake.mark_terminal`
        directly; this is the pending-side half of the same event)."""
        self.intake.mark_terminal(artifact_ref, evidence_record_ref)
        self.judgments.pop(artifact_ref, None)

    def snapshot_all(self):
        return {ref: snapshot(j) for ref, j in self.judgments.items()}


def rebuild(demand_events, persisted_records, rules_store):
    """`(demand events, {artifact_ref: persisted EvidenceRecord}, RulesStore)
    -> PendingProjection`, reconstructed from durable sources only
    (VAE-O10). Persisted-record artifacts are marked terminal before any
    demand event is replayed, so a terminal artifact's demand events are
    answered by the existing verdict and never reopen a judgment
    (VAE/04 §2.2, VAE-O10). Deterministic: identical inputs always produce
    an identical set of open judgments, regardless of process history."""
    intake = intake_mod.Intake()
    for artifact_ref, record in persisted_records.items():
        verdict_ref = "storage:vae/ev/" + evidence_mod.content_hash(record)
        intake.mark_terminal(artifact_ref, verdict_ref)

    judgments = {}
    for demand in demand_events:
        result = intake.receive(demand["event_name"], demand["event_id"],
                                 demand["artifact_ref"], demand["judgment_id"])
        if result.action != intake_mod.OPENED:
            continue

        artifact_rules = rules_store.lookup(demand["artifact_type"], demand["rules_version"])
        delegated_checks = {}
        for check, level in demand.get("delegated_check_levels", {}).items():
            delegated_checks[check] = {"deadline": artifact_rules.deadlines[check], "level": level}
        static_checks_spec = {check: {"level": level}
                               for check, level in demand.get("static_check_levels", {}).items()}

        judgments[demand["artifact_ref"]] = judgment_mod.open_judgment(
            demand["judgment_id"], demand["artifact_ref"], demand["rules_version"],
            delegated_checks, static_checks_spec)

    return PendingProjection(intake, judgments)


if __name__ == "__main__":
    from . import derivation
    from . import evidence
    from .execution_double import ExecutionDouble
    from .rules import RulesStore

    rules_store = RulesStore()
    rules_store.ingest(1, {
        "plugin_output": {
            "required_checks": ("structural", "reference_wellformed"),
            "depth": "standard",
            "deadlines": {"structural": 10, "reference_wellformed": 5},
        },
    })

    demand_a1 = {
        "event_name": "verify.requested", "event_id": "e1",
        "artifact_ref": "artifact:a1", "judgment_id": "judgment:a1",
        "artifact_type": "plugin_output", "rules_version": 1,
        "delegated_check_levels": {"structural": "structural"},
        "static_check_levels": {"reference_wellformed": "system"},
    }
    demand_a2 = {
        "event_name": "verify.requested", "event_id": "e2",
        "artifact_ref": "artifact:a2", "judgment_id": "judgment:a2",
        "artifact_type": "plugin_output", "rules_version": 1,
        "delegated_check_levels": {"structural": "structural"},
        "static_check_levels": {"reference_wellformed": "system"},
    }

    # -- basic rebuild: two open judgments, references only ------------------
    proj = rebuild([demand_a1, demand_a2], {}, rules_store)
    assert set(proj.judgments) == {"artifact:a1", "artifact:a2"}
    j1 = proj.get("artifact:a1")
    assert not j1.closed
    assert j1.delegations["structural"].deadline == 10  # rules-assigned, from the store
    entry = snapshot(j1)
    assert entry.artifact_ref == "artifact:a1" and entry.evidence_item_count == 0

    # -- determinism: rebuild again from the SAME durable inputs -> identical --
    proj_again = rebuild([demand_a1, demand_a2], {}, rules_store)
    assert proj_again.judgments == proj.judgments

    # -- redelivered demand event (at-least-once) is a no-op, not a second open --
    proj_dup = rebuild([demand_a1, demand_a1, demand_a2], {}, rules_store)
    assert proj_dup.judgments == proj.judgments

    # -- terminal-not-reopened: a persisted record for a1 means rebuild never
    # opens a judgment for it again, even though its demand event replays ----
    def rec(artifact_ref, items):
        r = evidence.build_evidence_record(artifact_ref, 1)
        for it in items:
            r = evidence.append_item(r, it)
        return r

    policy = derivation.build_derivation_policy(1, coverage_moderate_min_fraction=0.5,
                                                 coverage_strong_min_fraction=0.9)
    passed_body = rec("artifact:a1", [
        evidence.build_evidence_item("rule.structural", "artifact:a1", "check.structural",
                                      "pass", "independent", "structural")])
    persisted_a1 = derivation.attach_derivation(passed_body, policy)

    proj_terminal = rebuild([demand_a1, demand_a2], {"artifact:a1": persisted_a1}, rules_store)
    assert "artifact:a1" not in proj_terminal.judgments  # recognized terminal, never reopened
    assert "artifact:a2" in proj_terminal.judgments
    assert proj_terminal.intake.terminal_verdict("artifact:a1") is not None

    # -- crash with an in-flight delegation: expires post-rebuild through the
    # SAME existing machinery (delegation.py's own resolve()), no bespoke path --
    exe = ExecutionDouble()
    j2 = proj.get("artifact:a2")
    j2 = judgment_mod.dispatch_delegation(j2, "structural", exe, {"check": "structural"})
    proj.update(j2)
    # simulate crash: build a brand-new projection from the same durable inputs,
    # with nothing carried over from the in-memory dispatch above
    proj_recovered = rebuild([demand_a1, demand_a2], {}, rules_store)
    recovered_j2 = proj_recovered.get("artifact:a2")
    assert recovered_j2.delegations["structural"].state == "required"  # dispatch state not resurrected

    from .static_checks import StaticCheckRegistry
    registry = StaticCheckRegistry()
    recovered_j2 = judgment_mod.run_static_check(recovered_j2, "reference_wellformed", registry, {})
    recovered_j2 = judgment_mod.dispatch_delegation(recovered_j2, "structural", exe, {"check": "structural"})
    # no result ever scripted for this key -> deadline (10, rules-assigned) passes -> Expired
    recovered_j2 = judgment_mod.resolve_delegation(recovered_j2, "structural", exe, now=10)
    assert judgment_mod.is_closed(recovered_j2)
    assert recovered_j2.delegations["structural"].state == "expired"
    closed_j2 = judgment_mod.close(recovered_j2)
    account = derivation.attach_derivation(closed_j2.record, policy)
    assert account.derivation_account["failure_cause"] == derivation.EXECUTION_FAILURE

    print("pending selftest ok")
