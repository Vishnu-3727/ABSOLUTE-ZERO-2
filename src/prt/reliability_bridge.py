"""PRT/Learning reliability seam — PRT/04 §4 (historical knowledge input),
§5, §9, PRT-H10: one direction only, Learning -> PRT. `reliability.updated`
bus messages become priors entries in an EvidenceJournal (health.py folds
them into its reliability figure; it never computes them, PRT-H10).

The other direction (PRT -> Learning) is already satisfied by events.py's
existing publish set landing on the bus for Observability to carry onward —
nothing to write here (ponytail: no code needed for a direction that's
just "publish and let the bus/Observability do their job").

# ponytail: wire payload shape ({"provider_id", "prior", "priors_version"})
# is this module's own invented shape — PRT/04 fixes the INPUT CLASS
# (provider_id -> healed prior + priors_version), never a wire format.
# One provider per message is the simplest reading of the singular seam;
# upgrade path if Learning ever batches: loop `payload["priors"].items()`
# instead of a single provider_id/prior pair.
"""
from . import events


def consume_reliability_update(journal, message):
    """One `reliability.updated` bus message -> one priors journal entry.
    Validates the message's own event_name via events.check_consumed (closed
    CONSUME set, PRT/05 §4) before touching the payload — a dead/invented
    name is refused loudly, never silently folded in. Returns the
    provider_id folded."""
    events.check_consumed(message.get("event_name"))
    payload = message.get("payload", {})
    provider_id = payload["provider_id"]
    prior = payload["prior"]
    priors_version = payload["priors_version"]
    journal.append_priors(provider_id, prior, priors_version)
    return provider_id


def drain_reliability_updates(bus, journal):
    """Pull every pending `reliability.updated` message off the bus and fold
    each into the journal, in FIFO arrival order. Returns the list of
    provider_ids updated, same order."""
    return [consume_reliability_update(journal, message)
            for message in bus.drain("reliability.updated")]


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .evidence import EvidenceJournal

    bus = BusDouble()
    journal = EvidenceJournal()

    bus.publish("reliability.updated", {
        "event_name": "reliability.updated", "subject_id": "prov.x",
        "payload": {"provider_id": "prov.x", "prior": 0.83, "priors_version": 4}})

    updated = drain_reliability_updates(bus, journal)
    assert updated == ["prov.x"]
    entry = journal.entries_for("prov.x")[0]
    assert entry["type"] == "priors" and entry["prior"] == 0.83
    assert entry["priors_version"] == 4

    # drained: nothing left to consume twice
    assert drain_reliability_updates(bus, journal) == []

    # dead/unknown event name refused, loud, same discipline as events.py
    try:
        consume_reliability_update(journal, {"event_name": "process.failed", "payload": {}})
        raise SystemExit("dead event name accepted")
    except ValueError:
        pass

    print("reliability_bridge selftest ok")
