"""PluginRuntime — PRT/05 §1 (execution flow), §2 (cross-subsystem seams),
§4 (event canon), §7 (end-to-end determinism/replay). The composition
root: owns every PRT-internal collaborator, wires them together exactly
along the seams PRT/00-04 already fixed, and exposes the one surface
Execution/WS/CP actually touch (`discover_and_admit`, `bind`,
`handle_event`, `replay_bind`). No hidden state — every collaborator is
either injected or constructed explicitly right here in `__init__`
(PRT-S5/PRT-B1 discipline: nothing ambient influences any decision).

Bus/storage are injected PORTS (PRT/00 C6: persistence via Storage,
transport via Communication, both owned elsewhere); `bus_double.py`/
`storage_double.py` are this phase's test-fixture implementations of those
ports, same as UMS/RSM/CM already ship — this module never reimplements
either subsystem.
"""
import json

from . import admission, discovery, events, lifecycle_legality, persistence, retirement
from . import reliability_bridge
from .binding import BindingContract, resolve as resolve_binding
from .bus_double import BusDouble
from .config_view import ConfigView, DEFAULT as DEFAULT_CONFIG
from .evidence import EvidenceJournal
from .health import HealthManager
from .health_view import HealthSnapshot
from .load_policy import LoadPolicyView, LoadStateTracker
from .registry import Registry
from .storage_double import StorageDouble

_HEALTH_EVIDENCE = frozenset({"exec.completed", "exec.failed", "exec.timeout"})

_SNAPSHOT_ARTIFACT_PREFIX = "prt/health_snapshot/"


class PluginRuntime:
    """One fulfillment loop, one owner each (PRT/00 §1): registry
    authority, provider metadata/load policy, live health/reliability —
    assembled here, never re-derived anywhere else."""

    def __init__(self, bus=None, storage=None, config=None, thresholds=None,
                preferences=None):
        self.bus = bus if bus is not None else BusDouble()
        self.storage = storage if storage is not None else StorageDouble()
        self.config = config if config is not None else ConfigView(dict(DEFAULT_CONFIG))
        self._preferences = dict(preferences or {})

        self.registry = Registry()
        self.journal = EvidenceJournal()

        # The Lifecycle-contract adapter (boundary ruling): a real
        # transition-table machine, not an allow-everything stand-in —
        # separate instances for the two separate state machines (PRT/03
        # Ruling 3 / PRT/04 §3 never share one legality surface).
        self.health_legality = lifecycle_legality.default_health_legality()
        self.load_legality = lifecycle_legality.default_load_legality()

        self.health = HealthManager(self.journal, thresholds=thresholds,
                                    legality=self.health_legality, bus=self.bus)
        self.load_tracker = LoadStateTracker(self.load_legality, bus=self.bus)
        self.policy_view = LoadPolicyView(self.registry, self.config,
                                          tracker=self.load_tracker,
                                          preferences=self._preferences)

    # -- discovery -> admission (PRT/05 §1 steps 1-4 upstream of binding) --

    def discover_and_admit(self, sources):
        """Discover every Declaration from `sources`, then admit each in
        the deterministic content-hash order discovery already fixed
        (PRT-A9). Returns the ordered list of resulting Candidacies."""
        declarations = discovery.discover(sources, self.bus)
        return [admission.admit(self.registry, declaration, self.bus, self.storage)
                for declaration in declarations]

    # -- binding (PRT/05 §1 steps 1-4, PRT/03 §3, PRT-H7) -------------------

    def bind(self, capability_id):
        """Resolve `capability_id` to a provider. The health snapshot is
        taken ONCE, here, at binding start (PRT-H7) — never re-read
        mid-decision. Its raw content is persisted, content-addressed by
        its own hash, so `replay_bind` can reconstruct the exact coordinate
        a later contract cites without ever re-deriving live health."""
        provider_ids = [b.provider_id for b in self.registry.bindings_for(capability_id)]
        snapshot = self.health.snapshot(provider_ids)
        self._persist_snapshot_artifact(snapshot, provider_ids)
        return resolve_binding(self.registry, capability_id, snapshot, self.policy_view)

    def _persist_snapshot_artifact(self, snapshot, provider_ids):
        """Content-addressed persistence of the RAW snapshot data behind
        `snapshot.content_hash` — the artifact `replay_bind` later rereads
        instead of re-deriving live health (PRT-B12/PRT-H8: replay reads a
        record, never the moving world)."""
        data = {pid: dict(snapshot.get(pid)) for pid in provider_ids}
        key = _SNAPSHOT_ARTIFACT_PREFIX + snapshot.content_hash
        if not self.storage.exists(key):
            self.storage.write(key, json.dumps(data, sort_keys=True,
                                               separators=(",", ":")).encode())

    # -- event dispatch (PRT/05 §4 CONSUME set, exhaustively) --------------

    def handle_event(self, message):
        """Dispatch one bus message shaped like events.emit()'s own output
        ({"event_name", "subject_id", "payload"}). Refuses non-canon/dead
        events loudly via events.check_consumed (PRT-S1/S2) before doing
        anything with the payload."""
        event_name = message["event_name"]
        events.check_consumed(event_name)
        payload = message.get("payload", {}) or {}
        subject_id = message.get("subject_id")

        if event_name in _HEALTH_EVIDENCE:
            self.health.record_outcome(subject_id, event_name, payload.get("detail"))
        elif event_name == "reliability.updated":
            reliability_bridge.consume_reliability_update(self.journal, message)
        elif event_name == "plugin.lifecycle.changed":
            self.health_legality.on_lifecycle_event(payload)
            self.load_legality.on_lifecycle_event(payload)
            if payload.get("entity") in ("capability", "provider") and \
                    {"entity", "id", "to_state"} <= payload.keys():
                retirement.enact_lifecycle_event(self.registry, payload)
        return event_name

    def drain_and_handle(self):
        """Pull every pending message off every CONSUMED topic (FIFO,
        canon order) and dispatch each. Returns the event names handled,
        in the order handled."""
        handled = []
        for topic in events.CONSUMED:
            for message in self.bus.drain(topic):
                handled.append(self.handle_event(message))
        return handled

    # -- persistence passthrough (PRT/00 C6) --------------------------------

    def persist(self):
        return persistence.persist_registry(self.registry, self.storage)

    # -- replay (PRT/05 §7: registry version + Binding Contract + evidence/
    # snapshot artifacts -- zero live-world re-queries, ever) --------------

    def replay_bind(self, contract):
        """Reconstruct the exact (registry content, health snapshot) a
        BindingContract cites — both immutable/historical coordinates
        (PRT-S7) — and re-run binding.resolve, asserting it reproduces the
        identical contract. Never reads `self.registry`'s LIVE state or
        `self.health`'s live view; only `at_version` + the persisted
        snapshot artifact."""
        at_version = self.registry.at_version(contract.registry_version)
        raw = self.storage.read(_SNAPSHOT_ARTIFACT_PREFIX + contract.health_snapshot_hash)
        data = json.loads(raw)
        snapshot = HealthSnapshot(data)
        assert snapshot.content_hash == contract.health_snapshot_hash, \
            "runtime.replay_snapshot_hash_mismatch"

        replay_policy_view = LoadPolicyView(at_version, self.config,
                                            tracker=self.load_tracker,
                                            preferences=self._preferences)
        result = resolve_binding(at_version, contract.capability_id, snapshot,
                                 replay_policy_view)
        if isinstance(result, BindingContract):
            assert result.contract_id == contract.contract_id, \
                "runtime.replay_contract_mismatch"
        return result


if __name__ == "__main__":
    from .declarations import build_declaration
    from .discovery import FixtureSource
    from .records import build_binding, build_capability, build_provider

    rt = PluginRuntime()

    cap = build_capability("cap.rt.x", "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    prov_a = build_provider("prov.rt.a", "1.0")
    prov_b = build_provider("prov.rt.b", "1.0")
    decl_a = build_declaration(prov_a, capabilities=(cap,),
                              bindings=(build_binding("cap.rt.x", "prov.rt.a"),))
    decl_b = build_declaration(prov_b, bindings=(build_binding("cap.rt.x", "prov.rt.b"),))

    candidacies = rt.discover_and_admit([FixtureSource([decl_a, decl_b])])
    assert all(c.state == "ADMITTED" for c in candidacies)
    assert len(rt.bus.messages("plugin.registered")) == 2

    # provider still NOT_LOADED / no evidence yet -> both HEALTHY -> tie
    # broken by stable id
    contract = rt.bind("cap.rt.x")
    assert isinstance(contract, BindingContract)
    assert contract.provider_id == "prov.rt.a"  # stable-id tie-break

    # exec.failed evidence, via the dispatcher, degrades then quarantines
    # prov.rt.a -- next bind must pick prov.rt.b instead
    for _ in range(3):
        rt.bus.publish("exec.failed", {"event_name": "exec.failed",
                                       "subject_id": "prov.rt.a", "payload": {}})
    handled = rt.drain_and_handle()
    assert handled.count("exec.failed") == 3
    assert rt.health.state("prov.rt.a") == "QUARANTINED"

    contract2 = rt.bind("cap.rt.x")
    assert contract2.provider_id == "prov.rt.b"

    # full replay: reconstruct contract2 from artifacts alone
    replayed = rt.replay_bind(contract2)
    assert isinstance(replayed, BindingContract)
    assert replayed.contract_id == contract2.contract_id

    # persistence round trip
    rt.persist()
    restored, persisted_version = persistence.load_registry(rt.storage)
    assert persisted_version == rt.registry.current_version
    assert restored.get_capability("cap.rt.x").id == "cap.rt.x"

    # refuses non-canon events, loudly
    try:
        rt.handle_event({"event_name": "plugin.disabled", "subject_id": "x"})
        raise SystemExit("dead vocabulary accepted by runtime dispatcher")
    except ValueError:
        pass

    print("runtime selftest ok")
