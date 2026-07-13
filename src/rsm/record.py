"""Request State record — the nine blocks (RSM/02-architectural-blueprint.md
§1: Identity, Lifecycle, Plan, Work, Context, Verification, Budget, Failure,
Journal-metadata). Records are immutable versioned snapshots — a mutation
never edits in place, it produces a new version via evolve(), so a reader
holding an old reference never observes a torn record (RSM-I9).
"""
from dataclasses import dataclass, field, replace

BLOCK_NAMES = ("identity", "lifecycle", "plan", "work", "context",
               "verification", "budget", "failure", "journal_meta")


@dataclass(frozen=True)
class RequestRecord:
    """One immutable snapshot of a request's materialized state.

    `failure` is append-only (RSM/03 §6: a fixed tuple, "append" means
    evolve(failure=old_failure + (entry,))). `journal_meta` is the one block
    RSM authors itself (RSM/02 §4 ownership matrix, RSM-I6): applied-event
    seq, last applied event id, reducer_version.
    """
    request_id: str
    version: int = 0
    identity: dict = field(default_factory=dict)
    lifecycle: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    work: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    budget: dict = field(default_factory=dict)
    failure: tuple = field(default_factory=tuple)
    journal_meta: dict = field(default_factory=dict)

    def evolve(self, **block_updates):
        """Return a new, version+1 snapshot with the named blocks replaced.

        Never mutates self (RSM-I9) — dataclasses.replace() always builds a
        new instance. Blocks not named in block_updates carry over
        unchanged. `request_id` and `version` are not settable here:
        identity is fixed at birth, version is evolve()'s own bookkeeping.
        """
        bad = set(block_updates) - set(BLOCK_NAMES)
        if bad:
            raise ValueError("record.unknown_block:" + ",".join(sorted(bad)))
        return replace(self, version=self.version + 1, **block_updates)


def birth(request_id, identity_fields):
    """Create the version-0 snapshot at request.received — the sole
    creation trigger (RSM-I10)."""
    return RequestRecord(
        request_id=request_id,
        version=0,
        identity=dict(identity_fields),
        journal_meta={"seq": 0, "last_event_id": None, "reducer_version": 1},
    )


if __name__ == "__main__":
    r = birth("r1", {"declared_type": "type.alpha", "origin": "frontend"})
    assert r.version == 0 and r.identity["declared_type"] == "type.alpha"

    r2 = r.evolve(lifecycle={"state": "executing"})
    assert r2.version == 1 and r2.lifecycle["state"] == "executing"
    assert r.version == 0 and r.lifecycle == {}  # original snapshot untouched (RSM-I9)
    assert r2.identity == r.identity  # unnamed blocks carry over
    assert r2 is not r

    r3 = r2.evolve(failure=r2.failure + ({"family": "task.failed"},))
    assert r3.failure == ({"family": "task.failed"},) and r2.failure == ()

    try:
        r.evolve(bogus_block={"x": 1})
        raise SystemExit("unknown block accepted")
    except ValueError:
        pass

    try:
        r.identity = {}  # frozen dataclass: field reassignment must raise
        raise SystemExit("frozen record allowed field reassignment")
    except AttributeError:
        pass

    print("record selftest ok")
