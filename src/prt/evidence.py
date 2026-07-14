"""PRT evidence journal — PRT/04 §4 (closed input classes), §8 (append-only
history), PRT-H6/PRT-H9.

EvidenceJournal is an ordered, append-only sequence of typed observations —
the raw material health.py folds into current health state. Three entry
kinds, exactly PRT-H9's closed input-class table:

* live observation  — an execution outcome event (`exec.completed` /
  `exec.failed` / `exec.timeout`, validated against events.py's CONSUMED
  set) for one provider, with an optional free-form detail.
* administrative act — force_quarantine / force_release / disable / enable,
  a deliberate, recorded operator act, never silent (PRT/04 §7): always
  carries the acting actor + a reason.
* priors update      — one healed reliability prior for one provider, from
  a `reliability.updated` payload, carrying its declared priors_version
  (PRT-H10).

No wall-clock stamps: ordering is the append sequence itself (PRT-H1's
"ordered evidence history" needs order, never time). No mutation surface —
append + iterate (`entries`, `entries_for`) + slice (`upto`) only; a
correction is always a *new* entry (PRT-H6), never an edit to a prior one.
"""
import hashlib
import json

_LIVE_KINDS = ("exec.completed", "exec.failed", "exec.timeout")
_ADMIN_KINDS = ("force_quarantine", "force_release", "disable", "enable")


class EvidenceJournal:
    """Append-only. Every accessor returns a copy or an immutable view —
    there is no way for a caller to reach in and edit a past entry."""

    def __init__(self):
        self._entries = []

    def append_live(self, provider_id, kind, detail=None):
        from . import events
        events.check_consumed(kind)  # loud on anything outside the CONSUMED set
        if kind not in _LIVE_KINDS:
            raise ValueError("evidence.not_a_live_kind:" + str(kind))
        return self._append({"type": "live", "provider_id": provider_id,
                             "kind": kind, "detail": detail})

    def append_admin(self, provider_id, kind, actor, reason):
        if kind not in _ADMIN_KINDS:
            raise ValueError("evidence.unknown_admin_kind:" + str(kind))
        if not actor or not reason:
            # PRT/04 §7: explicit, never silent — actor + reason are mandatory.
            raise ValueError("evidence.admin_act_requires_actor_and_reason")
        return self._append({"type": "admin", "provider_id": provider_id,
                             "kind": kind, "actor": actor, "reason": reason})

    def append_priors(self, provider_id, prior, priors_version):
        return self._append({"type": "priors", "provider_id": provider_id,
                             "prior": float(prior), "priors_version": priors_version})

    def _append(self, entry):
        entry["seq"] = len(self._entries)
        self._entries.append(entry)
        return entry["seq"]

    def entries(self):
        """Every entry, append order — a tuple copy, never the live list."""
        return tuple(dict(e) for e in self._entries)

    def entries_for(self, provider_id):
        return tuple(dict(e) for e in self._entries if e["provider_id"] == provider_id)

    def upto(self, seq):
        """Slice: every entry with seq <= the given one — replay-at-a-point."""
        return tuple(dict(e) for e in self._entries if e["seq"] <= seq)

    def __len__(self):
        return len(self._entries)

    @property
    def content_hash(self):
        """Canonical-form hash over the full history — a replay assertion
        coordinate (PRT-H1): same entries, same order -> same hash."""
        payload = [dict(e) for e in self._entries]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    j = EvidenceJournal()
    s0 = j.append_live("prov.a", "exec.failed")
    s1 = j.append_admin("prov.a", "disable", actor="op.1", reason="maintenance")
    s2 = j.append_priors("prov.a", 0.7, priors_version=1)
    assert (s0, s1, s2) == (0, 1, 2)
    assert len(j) == 3

    # no mutation surface: entries()/entries_for() return copies
    got = j.entries()
    got[0]["kind"] = "tampered"
    assert j.entries()[0]["kind"] == "exec.failed"

    # ordering is append order, not any embedded field
    assert [e["seq"] for e in j.entries()] == [0, 1, 2]
    assert [e["provider_id"] for e in j.entries_for("prov.a")] == ["prov.a"] * 3

    # slice: upto() is a prefix, never a filter on later entries
    assert len(j.upto(1)) == 2

    # a correction is a new entry, never an edit
    j.append_admin("prov.a", "enable", actor="op.1", reason="fixed")
    assert len(j) == 4
    assert j.entries()[1]["kind"] == "disable"  # the old entry is untouched

    # determinism: identical entries, identical hash
    j2 = EvidenceJournal()
    j2.append_live("prov.a", "exec.failed")
    j2.append_admin("prov.a", "disable", actor="op.1", reason="maintenance")
    j2.append_priors("prov.a", 0.7, priors_version=1)
    j2.append_admin("prov.a", "enable", actor="op.1", reason="fixed")
    assert j.content_hash == j2.content_hash

    # closed input classes: dead/unknown live kind refused, loud
    try:
        j.append_live("prov.a", "exec.bogus")
        raise SystemExit("unknown live kind accepted")
    except ValueError:
        pass
    try:
        j.append_admin("prov.a", "bogus_act", actor="op.1", reason="x")
        raise SystemExit("unknown admin kind accepted")
    except ValueError:
        pass
    try:
        j.append_admin("prov.a", "disable", actor="", reason="")
        raise SystemExit("silent admin act accepted")
    except ValueError:
        pass

    print("evidence selftest ok")
