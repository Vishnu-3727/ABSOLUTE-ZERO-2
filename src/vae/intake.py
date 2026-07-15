"""VAE demand intake (VAE/06 Phase 2, VAE/04 §2). Turns an incoming demand
event into exactly one of four intake outcomes, never a fifth:

- **opened** — a new judgment starts for this artifact occurrence.
- **already_open** — this artifact already has an open (non-terminal)
  judgment; the demand does not open a second one (VAE/04 §2.2 "one
  judgment per gated occurrence").
- **answered_by_existing_verdict** — this artifact already holds a
  terminal verdict; the demand is answered by the existing record
  reference, never a re-judgment (VAE/03 §4.1, VAE/04 §2.2).
- **deduped** — this exact event id was already applied once; the bus is
  at-least-once (ARCHITECTURE.md), so a redelivery is a no-op (VAE/04 §2.2
  "dedup by event id", mirroring KERNEL/INVARIANTS.md #8 and RSM-I4).

Only events.CONSUMED rows obligate VAE to act (VAE/04 §2.1); this module
reuses `events.check_consumed` rather than re-deriving the closed set, so
an invented event name is refused the same way events.py already refuses
one (VAE-O2).

`Intake` holds only references (artifact refs, judgment ids, verdict refs)
— never artifact content — matching VAE/04 §4's "pending holds references,
not bodies." It knows nothing about *why* an artifact became terminal;
`mark_terminal` is the seam a later phase's verdict-emission choreography
calls once a verdict is durably persisted and published (VAE-O5) — Phase 2
itself never derives a verdict, it only remembers that one exists once
told."""
from dataclasses import dataclass

from . import events

OPENED = "opened"
ALREADY_OPEN = "already_open"
ANSWERED_BY_EXISTING_VERDICT = "answered_by_existing_verdict"
DEDUPED = "deduped"

ACTIONS = (OPENED, ALREADY_OPEN, ANSWERED_BY_EXISTING_VERDICT, DEDUPED)


class IntakeRefusal(Exception):
    """Base for intake.py refusals."""


class DemandAlreadyTerminalConflictError(IntakeRefusal):
    """mark_terminal() called for an artifact that already has a different
    recorded verdict reference — verdicts are immutable (VAE/03 §4.1); this
    would mean two verdicts for one gated occurrence."""


@dataclass(frozen=True)
class IntakeResult:
    action: str                 # one of ACTIONS
    artifact_ref: str
    judgment_id: object          # str when action is opened/already_open, else None
    verdict_ref: object          # str when action is answered_by_existing_verdict, else None


class Intake:
    def __init__(self):
        self._seen_event_ids = set()
        self._open_judgments = {}     # artifact_ref -> judgment_id
        self._terminal_verdicts = {}  # artifact_ref -> verdict_ref

    def receive(self, event_name, event_id, artifact_ref, judgment_id):
        """Apply one demand event. `judgment_id` is the id the caller would
        use if this call turns out to open a new judgment — supplied by
        the caller (e.g. judgment.py's id-building convention) rather than
        invented here, keeping this module's only responsibility the four
        intake outcomes, not identifier minting.

        Every event_name accepted must be one VAE actually consumes
        (events.CONSUMED); an invented name raises events.UnknownEventError
        exactly as events.check_consumed already does — this module adds
        no second closed-set check to keep in sync with events.py's."""
        events.check_consumed(event_name)

        if event_id in self._seen_event_ids:
            return IntakeResult(DEDUPED, artifact_ref, None, None)
        self._seen_event_ids.add(event_id)

        if artifact_ref in self._terminal_verdicts:
            return IntakeResult(ANSWERED_BY_EXISTING_VERDICT, artifact_ref, None,
                                 self._terminal_verdicts[artifact_ref])

        if artifact_ref in self._open_judgments:
            return IntakeResult(ALREADY_OPEN, artifact_ref,
                                 self._open_judgments[artifact_ref], None)

        self._open_judgments[artifact_ref] = judgment_id
        return IntakeResult(OPENED, artifact_ref, judgment_id, None)

    def mark_terminal(self, artifact_ref, verdict_ref):
        """Record that `artifact_ref` now holds a terminal verdict,
        answerable without re-judgment (VAE/04 §2.2). Idempotent for the
        same verdict_ref (a redelivered verdict-emission notice is not an
        error); a DIFFERENT verdict_ref for an already-terminal artifact is
        refused loud — verdicts are immutable."""
        existing = self._terminal_verdicts.get(artifact_ref)
        if existing is not None and existing != verdict_ref:
            raise DemandAlreadyTerminalConflictError(
                "intake.terminal_verdict_conflict:artifact_ref=" + artifact_ref +
                ":existing=" + existing + ":new=" + str(verdict_ref))
        self._terminal_verdicts[artifact_ref] = verdict_ref
        self._open_judgments.pop(artifact_ref, None)

    def is_open(self, artifact_ref):
        return artifact_ref in self._open_judgments

    def terminal_verdict(self, artifact_ref):
        return self._terminal_verdicts.get(artifact_ref)


if __name__ == "__main__":
    intake = Intake()

    # first demand opens a judgment
    r1 = intake.receive("verify.requested", "e1", "artifact:a1", "judgment:a1")
    assert r1.action == OPENED and r1.judgment_id == "judgment:a1"
    assert intake.is_open("artifact:a1")

    # redelivered event id (same e1) is deduped, not re-opened
    r2 = intake.receive("verify.requested", "e1", "artifact:a1", "judgment:a1-again")
    assert r2.action == DEDUPED

    # a DIFFERENT demand event for the same artifact, still open -> already_open,
    # not a second judgment (one judgment per gated occurrence)
    r3 = intake.receive("exec.completed", "e2", "artifact:a1", "judgment:a1-second")
    assert r3.action == ALREADY_OPEN and r3.judgment_id == "judgment:a1"

    # a different artifact opens its own judgment independently
    r4 = intake.receive("plan.created", "e3", "artifact:a2", "judgment:a2")
    assert r4.action == OPENED

    # once terminal, further demand for that artifact is answered by the
    # existing verdict, never re-judged
    intake.mark_terminal("artifact:a1", "storage:vae/ev/a1")
    assert not intake.is_open("artifact:a1")
    r5 = intake.receive("reasoning.completed", "e4", "artifact:a1", "judgment:a1-third")
    assert r5.action == ANSWERED_BY_EXISTING_VERDICT
    assert r5.verdict_ref == "storage:vae/ev/a1"

    # idempotent re-mark with the same verdict is fine
    intake.mark_terminal("artifact:a1", "storage:vae/ev/a1")

    # a conflicting re-mark (a second, different verdict) is refused loud
    try:
        intake.mark_terminal("artifact:a1", "storage:vae/ev/a1-different")
        raise SystemExit("conflicting terminal verdict accepted")
    except DemandAlreadyTerminalConflictError:
        pass

    # invented event name refused via events.py's own closed-set check
    try:
        intake.receive("verify.maybe", "e5", "artifact:a3", "judgment:a3")
        raise SystemExit("invented demand event name accepted")
    except events.UnknownEventError:
        pass

    # a PUBLISHED-only name is not demand either
    try:
        intake.receive("verify.passed", "e6", "artifact:a3", "judgment:a3")
        raise SystemExit("published-only event name accepted as demand")
    except events.UnknownEventError:
        pass

    print("intake selftest ok")
