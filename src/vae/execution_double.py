"""VAE's own scripted Execution boundary double (VAE/06 Phase 2, VAE/04 §3.1
"VER -> EXE": a direct request/response channel, not a bus event). VAE ships
its own copy rather than importing `ro/engine_boundary.py`'s
`ScriptedEngineDouble` (zero-seam rule beats DRY, VAE/06 "Global laws" table)
even though the shape rhymes: scripted results are deterministic
nondeterminism (RO/05 §10 engine-double pattern) — the double is a pure
function of what was scripted plus an injected `now`, never a clock read.

Two operations model the two things that cross the channel (VAE/04 §3.1
table):

- `dispatch(key, request)` — VAE -> Execution. Returns "dispatched" on
  acknowledgment; raises `ConnectionError` when the test has scripted "no
  acknowledgment" for `key` (VAE/04 §3.4 row 2 — delivery failure, not an
  outcome). Idempotent: calling it again with the same key is the
  "identical re-issue" §3.4 permits when no outcome and no acknowledgment
  exist yet.
- `poll(key, now)` — Execution -> VAE. Returns `None` until the scripted
  result's `arrival_time` is at or before the injected `now`, then the
  scripted result dict every time after (idempotent; a real poll doesn't
  consume the answer). `delegation.py` is the only caller that turns a
  `poll` answer into a state transition; this double never times anything
  out itself — deadlines are `delegation.py`'s and rules-as-data's job."""
from dataclasses import dataclass

# VAE/04 §3.2 "Resulted": success, failure, timeout, or crash are all
# equally ordinary results (V1-H4 containment) — a closed four, mirroring
# how execution outcomes are named elsewhere in the canon.
RESULT_OUTCOMES = ("success", "failure", "timeout", "crash")


class ExecutionDoubleRefusal(Exception):
    """Base for execution_double.py refusals."""


class UnknownResultOutcomeError(ExecutionDoubleRefusal):
    """A scripted result outcome outside the closed four."""


class ExecutionDouble:
    def __init__(self):
        self._no_ack = set()          # keys whose next dispatch() raises (no acknowledgment)
        self._results = {}            # key -> {"arrival_time": num, "outcome": str, "detail": object}
        self.dispatch_log = []        # (key, request) in call order, for test assertions

    def script_no_ack(self, key):
        """Script the NEXT dispatch() of `key` to raise ConnectionError
        instead of acknowledging (VAE/04 §3.4 row 2's delivery failure)."""
        self._no_ack.add(key)

    def script_result(self, key, arrival_time, outcome, detail=None):
        """Script the result `poll(key, now)` will surface once
        `now >= arrival_time`. `outcome` must be one of RESULT_OUTCOMES."""
        if outcome not in RESULT_OUTCOMES:
            raise UnknownResultOutcomeError("execution_double.unknown_outcome:" + repr(outcome))
        self._results[key] = {"arrival_time": arrival_time, "outcome": outcome, "detail": detail}

    def dispatch(self, key, request):
        """VAE -> Execution: send a check request. Raises ConnectionError
        if this key's next dispatch is scripted as unacknowledged; the
        script is consumed so a subsequent dispatch of the same key can
        succeed (mirrors StorageDouble's one-shot scripting)."""
        self.dispatch_log.append((key, dict(request)))
        if key in self._no_ack:
            self._no_ack.discard(key)
            raise ConnectionError("execution.no_acknowledgment:" + str(key))
        return "dispatched"

    def poll(self, key, now):
        """Execution -> VAE: has a result arrived by `now`? Pure function
        of the script and `now` — no clock read, callable any number of
        times with the same answer (idempotent), which is what lets
        judgment.py check for a late result after a delegation has already
        gone terminal without this double inventing new state."""
        entry = self._results.get(key)
        if entry is None or entry["arrival_time"] > now:
            return None
        return {"outcome": entry["outcome"], "detail": entry["detail"]}


if __name__ == "__main__":
    dbl = ExecutionDouble()

    # ordinary dispatch acknowledges
    assert dbl.dispatch("d1", {"check": "structural", "artifact_ref": "artifact:a1"}) == "dispatched"
    assert dbl.dispatch_log == [("d1", {"check": "structural", "artifact_ref": "artifact:a1"})]

    # no result yet
    assert dbl.poll("d1", now=0) is None

    # scripted result surfaces only once now reaches arrival_time
    dbl.script_result("d1", arrival_time=10, outcome="success", detail={"exit": 0})
    assert dbl.poll("d1", now=5) is None
    result = dbl.poll("d1", now=10)
    assert result == {"outcome": "success", "detail": {"exit": 0}}
    # idempotent: polling again at a later now gives the same answer
    assert dbl.poll("d1", now=99) == result

    # unknown outcome refused loud
    try:
        dbl.script_result("d2", arrival_time=1, outcome="teleported")
        raise SystemExit("unknown result outcome accepted")
    except UnknownResultOutcomeError:
        pass

    # scripted no-acknowledgment: dispatch raises, one-shot
    dbl.script_no_ack("d3")
    try:
        dbl.dispatch("d3", {"check": "x"})
        raise SystemExit("unacknowledged dispatch did not raise")
    except ConnectionError:
        pass
    # re-issue (identical request) now succeeds — delivery redundancy, VAE/04 §3.4 row 2
    assert dbl.dispatch("d3", {"check": "x"}) == "dispatched"

    print("execution_double selftest ok")
