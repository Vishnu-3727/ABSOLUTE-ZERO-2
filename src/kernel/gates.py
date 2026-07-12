"""Gate evaluation: pure function, (request_state, gate_def) -> permit bool.

Gate definitions are Config View data; each names a predicate from the
table below. Absence — of a verdict, a predicate, a definition — is always
block, never permit (I5).
"""


def _verdict_true(entry, gate_def):
    # Missing or failed verdict evaluates False: block (I5).
    return entry.recorded_verdicts.get(gate_def.get("verdict", "verification")) is True


PREDICATES = {
    "verdict_true": _verdict_true,
}


def evaluate(entry, gate_def):
    predicate = PREDICATES.get(gate_def.get("check"))
    if predicate is None:
        return False  # unknown check never defaults to permit (I5)
    return predicate(entry, gate_def)


if __name__ == "__main__":
    from kernel.ledger import RequestState
    gate_def = {"check": "verdict_true", "verdict": "verification"}
    entry = RequestState(request_id="r1")
    assert evaluate(entry, gate_def) is False          # missing verdict = block
    entry.recorded_verdicts["verification"] = False
    assert evaluate(entry, gate_def) is False          # failed verdict = block
    entry.recorded_verdicts["verification"] = True
    assert evaluate(entry, gate_def) is True
    assert evaluate(entry, {"check": "nonsense"}) is False
    assert evaluate(entry, {}) is False
    print("gates selftest ok")
