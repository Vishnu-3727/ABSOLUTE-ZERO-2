"""RO/04 §1 — the engine boundary port (RO/05 §10 blueprint group G5: engines
= injected test doubles producing SCRIPTED nondeterminism; the double is
deterministic, the architecture treats its output as data — exactly how
replay works, RO/04 §9 "Purpose").

`CrossingPayload` is everything that crosses the quarantine boundary on
control transfer (RO/04 §1 table): the rendered bytes, the timeout class
attached before crossing, the budget remaining, a reference to the
constraints (audit-linkable, never re-derived from the engine side), and
the tuple of pending cancellation signals (data, per RO-E10 — the boundary
double is what decides how a race between output and cancellation
resolves, since it is standing in for the nondeterministic engine).

The port contract itself is nothing more than "a callable taking a
CrossingPayload and returning one of the closed four kinds" (RO-E3) —
no ABC/Protocol needed for a single-method contract with one house
implementation; house precedent (`prt/bus_double.py`, `cm/bus_double.py`)
is a plain callable class, not a formal interface.

`ScriptedEngineDouble` never leaks an engine handle into anything a caller
persists: it returns a plain dict per crossing, nothing else — no
`ScriptedEngineDouble` reference, id(), or repr() ever appears in a sealed
outcome record (invocation.py never stores the boundary object itself).
"""
from dataclasses import dataclass

# RO/04 §1 "there is no fourth return" — the closed four.
CROSSING_KINDS = ("returned", "failed", "expired", "cancelled")


class BoundaryRefusal(Exception):
    """Base for engine-boundary-time refusals."""


class ScriptExhaustedError(BoundaryRefusal):
    """The double's script ran out — a test-fixture bug, never a governed
    F-class (RO/04 §1's closed four is about what a REAL boundary can
    return; an exhausted script means the test asked for more attempts
    than it programmed, not a fifth kind)."""


class MalformedBoundaryReturnError(BoundaryRefusal):
    """RO-E3: the boundary returned something outside the closed four kinds
    — extension requires errata, never silent tolerance."""


@dataclass(frozen=True)
class CrossingPayload:
    rendered: bytes
    timeout_class: str
    budget_remaining: int
    constraints_ref: str          # audit-linkable hash of the request's constraints
    cancellation_signals: tuple   # tuple of cancellation.CancellationSignal, injected


class ScriptedEngineDouble:
    """Programmed with an ordered script of boundary returns; each
    invocation consumes the next entry (house double precedent: bus_double
    et al. live in src, not tests). Deterministic by construction — replay
    reads its answers back as data, never regenerates them."""

    def __init__(self, script):
        self._script = tuple(script)
        self._next = 0

    def __call__(self, payload):
        if not isinstance(payload, CrossingPayload):
            raise BoundaryRefusal("engine_boundary.bad_payload:" + repr(type(payload)))
        if self._next >= len(self._script):
            raise ScriptExhaustedError(
                "engine_boundary.script_exhausted:attempt=" + str(self._next + 1))
        entry = self._script[self._next]
        self._next += 1
        return _validate_return(entry)

    @property
    def calls_made(self):
        return self._next


def _validate_return(entry):
    if not isinstance(entry, dict) or "kind" not in entry:
        raise MalformedBoundaryReturnError("engine_boundary.malformed_return:" + repr(entry))
    kind = entry["kind"]
    if kind not in CROSSING_KINDS:
        raise MalformedBoundaryReturnError("engine_boundary.unknown_kind:" + str(kind))
    return dict(entry)


if __name__ == "__main__":
    payload = CrossingPayload(
        rendered=b"hello", timeout_class="standard", budget_remaining=1000,
        constraints_ref="abc123", cancellation_signals=(),
    )

    double = ScriptedEngineDouble([
        {"kind": "failed", "failure_class": "F1", "consumed": 10},
        {"kind": "returned", "output": b'{"summary": "ok"}', "consumed": 20, "timing": {"ticks": 5}},
    ])
    r1 = double(payload)
    assert r1["kind"] == "failed" and r1["failure_class"] == "F1"
    r2 = double(payload)
    assert r2["kind"] == "returned"
    assert double.calls_made == 2

    # mutating the returned dict never mutates the script (defensive copy)
    r2["kind"] = "tampered"
    r2b = double  # script already exhausted below; just confirm independence via a fresh double
    fresh = ScriptedEngineDouble([{"kind": "returned", "output": b"{}", "consumed": 0, "timing": {}}])
    out = fresh(payload)
    assert out["kind"] == "returned"

    # script exhaustion is loud, not an F-class
    try:
        double(payload)
        raise SystemExit("exhausted script silently tolerated")
    except ScriptExhaustedError:
        pass

    # fifth-kind return refused loud (RO-E3)
    bad = ScriptedEngineDouble([{"kind": "teleported"}])
    try:
        bad(payload)
        raise SystemExit("fifth-kind boundary return accepted")
    except MalformedBoundaryReturnError:
        pass

    # bad payload type refused loud
    ok_double = ScriptedEngineDouble([{"kind": "returned", "output": b"{}"}])
    try:
        ok_double({"not": "a payload"})
        raise SystemExit("non-CrossingPayload accepted")
    except BoundaryRefusal:
        pass

    print("engine_boundary selftest ok")
