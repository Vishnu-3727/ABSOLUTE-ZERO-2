"""PRT candidacy tracking — PRT/02 §2 (pipeline states) and PRT-A12 (every
admission refusal is loud, recorded, and stage-specific; silent drops are
forbidden).

States: DISCOVERED -> CANDIDATE -> VALIDATED -> ADMITTED | REJECTED
(PRT/02 §2 table; Unknown is pre-observation and is never represented here
-- a Candidacy object only exists once a declaration has been collected.
Published is a reader-facing synonym of Admitted, not a fifth state --
PRT/02 §2 is explicit that they are "the same instant").

Not frozen like records.py/declarations.py: a candidacy's whole purpose is
to track state *changing* as it moves through admission (registry.py's
apply() precedent already puts immutability on the content -- Declaration,
records -- never on the thing tracking a mutable process over that
content). REJECTED is terminal (PRT/02 §2 "no resume from where it
failed"): once rejected, this object refuses every further mutation;
resubmitting a corrected declaration means constructing a brand NEW
Candidacy, never reviving this one.

The audit trail (`audit_trail`) is append-only: `_log` only ever grows,
never rewritten, and is exposed as a tuple snapshot so a caller can't
mutate history out from under it.
"""

STATES = ("DISCOVERED", "CANDIDATE", "VALIDATED", "ADMITTED", "REJECTED")
_TERMINAL = ("ADMITTED", "REJECTED")


class CandidacyError(Exception):
    """Raised for an illegal transition on this Candidacy object (mutating
    past a terminal state, or out of pipeline order)."""


class Candidacy:
    def __init__(self, declaration):
        self.declaration = declaration
        self.state = "DISCOVERED"
        self._log = []  # append-only: (stage_name, outcome, detail)
        self.failing_stage = None
        self.refusal = None
        self.minted_version = None

    @property
    def audit_trail(self):
        return tuple(self._log)

    def _guard_not_terminal(self):
        if self.state in _TERMINAL:
            raise CandidacyError(
                "candidacy.terminal_state_no_further_mutation:" + self.state)

    def begin(self):
        """DISCOVERED -> CANDIDATE: the declaration has been collected in
        full and is about to enter the admission pipeline (PRT/02 §3)."""
        self._guard_not_terminal()
        self.state = "CANDIDATE"

    def record_pass(self, stage_name):
        """Append-only audit entry for a stage that did not refuse (PRT-A12
        records outcomes, not only refusals -- an observer can see exactly
        how far a candidacy got)."""
        self._guard_not_terminal()
        self._log.append((stage_name, "passed", None))

    def reject(self, stage_name, refusal):
        """Terminal (PRT/02 §2): later stages are never attempted once one
        has refused. `refusal` is the RegistryRefusal (or admission-stage
        equivalent) that caused it, recorded verbatim, loud (PRT-A12)."""
        self._guard_not_terminal()
        self._log.append((stage_name, "rejected", str(refusal)))
        self.state = "REJECTED"
        self.failing_stage = stage_name
        self.refusal = refusal

    def validate(self):
        """All pre-publication stages (1-8) passed -> VALIDATED, awaiting
        stage 9 (publication)."""
        self._guard_not_terminal()
        if self.state != "CANDIDATE":
            raise CandidacyError("candidacy.validate_requires_candidate_state:" + self.state)
        self.state = "VALIDATED"

    def mark_publication_failed(self):
        """PRT/02 §9's one non-terminal failure: Storage refused the persist.
        No version was minted; state stays exactly VALIDATED (never
        REJECTED) and this candidacy is retryable as-is -- literally the
        same object, same declaration, no new candidacy required."""
        if self.state != "VALIDATED":
            raise CandidacyError(
                "candidacy.publication_failure_requires_validated_state:" + self.state)
        self._log.append(("publication", "storage_refused_retryable", None))

    def admit(self, version):
        """VALIDATED -> ADMITTED: publication minted `version` (PRT/02 §7 --
        "Admitted" and "the version now exists" are the same instant)."""
        if self.state != "VALIDATED":
            raise CandidacyError("candidacy.admit_requires_validated_state:" + self.state)
        self._log.append(("publication", "admitted", version))
        self.state = "ADMITTED"
        self.minted_version = version


if __name__ == "__main__":
    from .declarations import build_declaration
    from .records import build_provider

    decl = build_declaration(build_provider("prov.cand.a", "1.0"))

    # happy path: DISCOVERED -> CANDIDATE -> VALIDATED -> ADMITTED
    c = Candidacy(decl)
    assert c.state == "DISCOVERED"
    c.begin()
    assert c.state == "CANDIDATE"
    for stage in ("identity", "capability", "metadata", "constraint",
                 "relationship", "binding", "compatibility", "consistency"):
        c.record_pass(stage)
    c.validate()
    assert c.state == "VALIDATED"
    c.admit(7)
    assert c.state == "ADMITTED" and c.minted_version == 7
    assert c.audit_trail[-1] == ("publication", "admitted", 7)

    # ADMITTED is terminal: no further mutation of any kind
    try:
        c.record_pass("late")
        raise SystemExit("mutation past ADMITTED allowed")
    except CandidacyError:
        pass

    # rejection path: terminal, stage-specific, loud (PRT-A12)
    c2 = Candidacy(build_declaration(build_provider("prov.cand.b", "1.0")))
    c2.begin()
    c2.record_pass("identity")
    c2.reject("capability", ValueError("admission.unknown_capability:cap.missing"))
    assert c2.state == "REJECTED"
    assert c2.failing_stage == "capability"
    assert "cap.missing" in str(c2.refusal)
    # REJECTED refuses resubmission-in-place -- no "resume from where it failed"
    try:
        c2.validate()
        raise SystemExit("mutation past REJECTED allowed")
    except CandidacyError:
        pass

    # publication-failure path: distinct from REJECTED, stays VALIDATED, retryable
    c3 = Candidacy(build_declaration(build_provider("prov.cand.c", "1.0")))
    c3.begin()
    c3.validate()
    c3.mark_publication_failed()
    assert c3.state == "VALIDATED"  # not REJECTED
    c3.admit(9)  # retry succeeds -- same object, no new candidacy needed
    assert c3.state == "ADMITTED" and c3.minted_version == 9

    print("candidacy selftest ok")
