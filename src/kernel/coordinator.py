"""The Kernel event loop: consume -> dedup -> table lookup -> apply ->
log-before-publish -> emit. Single-threaded, deterministic; every decision
is a table lookup or a boolean (I2). Sole mutator of the Request Ledger (I1).
"""
from . import admission, config_view, envelope, gates, router
from .config_view import ConfigView
from .ledger import Ledger, RequestState, TERMINAL_STATES

LOG_TOPIC = "transition.log"
_SESSION_EVENTS = ("session.wake", "session.sleep")


class Coordinator:
    def __init__(self, bus, config_data, clock=None):
        self.bus = bus
        self.ledger = Ledger()
        self.halted = False
        self.log = []  # durable-log surrogate; Storage persists it in the real system (I16)
        self._configs = {}  # version -> ConfigView  # ponytail: unbounded cache; prune if versions churn
        self._config = None
        self._install(config_data)
        self._clock = clock if clock is not None else (lambda: 0)  # audit only, never in guards (I10)
        self._out_seq = 0  # outbound-only sequence (I9)

    # ------------------------------------------------------------------
    # event loop entry point
    # ------------------------------------------------------------------
    def handle(self, env):
        cfg = self._config
        ok, reason = envelope.validate(env, cfg.inbound_events)
        if not ok:
            # Poison/malformed envelope: reject, fault, keep looping (I22, FI-4).
            self._fault(reason, env if isinstance(env, dict) else None)
            return
        name = env["event_name"]
        if name == "config.changed":
            self._handle_config(env)
            return
        if name in _SESSION_EVENTS:
            self._handle_session(env)
            return
        rid = env["request_id"]
        entry = self.ledger.get(rid)
        if entry is not None and env["event_id"] == entry.last_applied_event_id:
            # Exactly-once effect: duplicate delivery is a no-op record (I8).
            self._log_noop(entry, env, "duplicate")
            return
        if name == "request.received":
            if entry is None:
                self._admit(env)
            else:
                self._fault("transition.unmatched:%s|%s" % (entry.lifecycle_state, name), env)
            return
        if entry is None:
            # D4a: events for unknown ids are faults, never creation triggers.
            self._fault("request.unknown:" + name, env)
            return
        self._apply(entry, name, env)

    # ------------------------------------------------------------------
    # admission + routing (same event processing, phase 3)
    # ------------------------------------------------------------------
    def _admit(self, env):
        rid = env["request_id"]
        if not isinstance(rid, str) or not rid:
            self._fault("request.missing_id", env)
            return
        cfg = self._config
        active = self.ledger.active_count()
        entry = RequestState(
            request_id=rid,
            declared_type=str(env["payload"].get("declared_type", "")),
            lifecycle_state="created",
            config_version=cfg.version,
        )
        self.ledger._create(entry)
        permitted, reason = admission.decide(env, cfg, self.halted, active)
        rows = cfg.rows("created", "request.received")
        row = rows[0] if permitted else rows[-1]
        self._transition(entry, "request.received", env["event_id"], row, permitted,
                         cfg, info={"declared_type": entry.declared_type, "reason": reason})
        if permitted and row.get("chain"):
            target, route_reason = router.route(entry.declared_type, cfg)
            chain_rows = cfg.rows(entry.lifecycle_state, row["chain"])
            chain_row = chain_rows[0] if target is not None else chain_rows[-1]
            self._transition(entry, row["chain"], env["event_id"], chain_row,
                             target is not None, cfg,
                             info={"routing_target": target, "reason": route_reason})

    # ------------------------------------------------------------------
    # generic table application
    # ------------------------------------------------------------------
    def _apply(self, entry, event, env):
        # In-flight requests stay pinned to the snapshot they started under (CF-1, I18).
        cfg = self._configs.get(entry.config_version, self._config)
        rows = cfg.rows(entry.lifecycle_state, event)
        if rows is None:
            # Unmatched (state, event) pair: fault, state unchanged (I4).
            self._fault("transition.unmatched:%s|%s" % (entry.lifecycle_state, event), env)
            return
        row, guard_result = self._pick_row(rows, entry, cfg)
        if row is None:
            self._fault("transition.no_row:%s|%s" % (entry.lifecycle_state, event), env)
            return
        self._transition(entry, event, env["event_id"], row, guard_result, cfg)

    def _pick_row(self, rows, entry, cfg):
        for index, row in enumerate(rows):
            when = row.get("when")
            if when is not None and not self._guard(when, entry, cfg):
                continue
            decision = row.get("decision") or ("permit" if index == 0 else "block")
            return row, decision == "permit"
        return None, False  # every guard failed, no fallthrough: block, never guess (I5)

    def _guard(self, name, entry, cfg):
        if name.startswith("gate:"):
            return gates.evaluate(entry, cfg.gates.get(name[5:], {}))
        if name == "replans_remaining":
            return entry.replan_count < cfg.fault_policy["max_replans"]
        return False  # unknown guard never permits (I5)

    def _do_action(self, action, entry, event, info):
        if action == "record_verdict":
            entry.recorded_verdicts["verification"] = event == "verify.passed"
        elif action == "increment_replan":
            entry.replan_count += 1
        elif action == "set_cancel_flag":
            entry.cancellation_flag = True
        elif action == "set_routing_target":
            entry.routing_target = (info or {}).get("routing_target")

    def _transition(self, entry, event, event_id, row, guard_result, cfg, info=None):
        decision = row.get("decision") or ("permit" if guard_result else "block")
        record = {
            "request_id": entry.request_id,
            "event_id": event_id,  # audit + dedup-state restoration on replay
            "sequence": entry.transition_sequence + 1,
            "prior_state": entry.lifecycle_state,
            "event": event,
            "guard_result": guard_result,
            "next_state": row["next"],
            "config_version": cfg.version,
            "emitted_events": list(row["emit"]),
        }
        if info:
            info = {key: value for key, value in info.items() if value}
        if info:
            record["info"] = info
        for action in row.get("actions", ()):
            self._do_action(action, entry, event, info)
        entry.lifecycle_state = row["next"]
        entry.transition_sequence += 1
        if event_id is not None:
            entry.last_applied_event_id = event_id
        self._log(record)  # log before publish (I7)
        self._publish_row(entry, row, decision, cfg, info)

    # ------------------------------------------------------------------
    # telemetry: transition log + outbound events
    # ------------------------------------------------------------------
    def _log(self, record):
        self.log.append(record)
        self._safe_publish(LOG_TOPIC, record)

    def _log_noop(self, entry, env, verdict):
        self._log({
            "request_id": entry.request_id,
            "event_id": env["event_id"],
            "sequence": entry.transition_sequence,
            "prior_state": entry.lifecycle_state,
            "event": env["event_name"],
            "guard_result": False,
            "next_state": entry.lifecycle_state,
            "config_version": entry.config_version,
            "emitted_events": [],
            "verdict": verdict,
        })

    def _publish_row(self, entry, row, decision, cfg, info):
        for name in row["emit"]:
            payload = self._payload_for(name, entry, decision, row, cfg, info)
            self._emit(name, entry.request_id, payload, cfg)

    def _payload_for(self, name, entry, decision, row, cfg, info):
        rid = entry.request_id
        if name == "gate.enforced":
            return {"request_id": rid, "gate": row.get("gate", ""), "decision": decision}
        if name == "routing.directive":
            return {"request_id": rid, "declared_type": entry.declared_type,
                    "target": entry.routing_target, "config_version": cfg.version}
        if name in ("request.rejected", "request.failed"):
            return {"request_id": rid, "state": entry.lifecycle_state,
                    "reason": (info or {}).get("reason", "")}
        if name == "request.cancelled":
            return {"request_id": rid, "state": "cancelled", "ack": True}
        return {"request_id": rid, "state": entry.lifecycle_state}

    def _emit(self, name, request_id, payload, cfg):
        self._out_seq += 1
        env = envelope.make("out-%d" % self._out_seq, name, request_id,
                            self._clock(), cfg.version, payload)
        self._safe_publish(name, env)

    def _safe_publish(self, topic, message):
        try:
            self.bus.publish(topic, message)
            return True
        except Exception:
            if not self.halted:
                # Degradation ladder level 1: halt admission; the in-memory
                # log retains the record, so nothing is lost (I22).
                self.halted = True
                self._fault("communication.unavailable", None)
            return False

    def _fault(self, reason, env):
        payload = {"reason": reason}
        rid = None
        if isinstance(env, dict):
            payload["event_id"] = env.get("event_id")
            payload["request_id"] = rid = env.get("request_id")
        self._emit("fault.recorded", rid, payload, self._config)

    # ------------------------------------------------------------------
    # configuration and session boundaries
    # ------------------------------------------------------------------
    def _install(self, data):
        view = ConfigView(data)
        self._configs[view.version] = view
        self._config = view

    def _handle_config(self, env):
        snap = env["payload"].get("snapshot")
        ok, reason = config_view.validate(snap)
        if not ok:
            # Ladder level 2: reject snapshot, retain last-good (FI-2).
            self._fault("config.invalid:" + reason, env)
            return
        self._install(snap)
        self._log({
            "request_id": None, "sequence": 0, "prior_state": None,
            "event": "config.changed", "guard_result": True, "next_state": None,
            "config_version": snap["version"], "emitted_events": [],
            "snapshot": snap,
        })

    def _handle_session(self, env):
        name = env["event_name"]
        self._log({
            "request_id": None, "sequence": 0, "prior_state": None,
            "event": name, "guard_result": True, "next_state": None,
            "config_version": self._config.version, "emitted_events": [],
        })
        if name == "session.sleep":
            # ponytail: cleanup/eviction deferred to the session boundary so
            # terminal-state cancellations stay in-table no-ops (CT-2/CT-3).
            for rid in self.ledger.request_ids():
                entry = self.ledger.get(rid)
                if entry.lifecycle_state in TERMINAL_STATES:
                    self._log({
                        "request_id": rid,
                        "sequence": entry.transition_sequence + 1,
                        "prior_state": entry.lifecycle_state,
                        "event": "__cleanup__", "guard_result": True,
                        "next_state": "cleanup",
                        "config_version": entry.config_version,
                        "emitted_events": [],
                    })
                    self.ledger._evict(rid)

    # ------------------------------------------------------------------
    # recovery by replay
    # ------------------------------------------------------------------
    def recover(self, records, published=None):
        """Rebuild the Ledger by replaying transition-log records.

        Every replayed record is recomputed against the rebuilt state and the
        transition table, canonically serialized, and byte-compared to the
        logged record (I17). Deviation = corruption = halt (ladder level 3).

        published: set of (request_id, sequence) pairs already delivered;
        records absent from it get their emissions re-published (D5a, CR-1).
        None means everything was delivered — pure rebuild.
        """
        self.ledger = Ledger()
        self.log = []
        self.halted = False  # restart is idempotent: rebuild from scratch (CR-3)
        for rec in records:
            event = rec.get("event")
            if event == "config.changed":
                snap = rec.get("snapshot")
                ok, _ = config_view.validate(snap)
                if not ok:
                    return self._replay_deviation(rec)
                self._install(snap)
                self.log.append(rec)
                continue
            if event in _SESSION_EVENTS:
                self.log.append(rec)
                continue
            if event == "__cleanup__":
                self.ledger._evict(rec.get("request_id"))
                self.log.append(rec)
                continue
            if "verdict" in rec:
                self.log.append(rec)  # dedup no-ops replay as no-ops (RT-4, I8)
                continue
            rid = rec.get("request_id")
            entry = self.ledger.get(rid)
            # Decisions replay under the logged config version, never the
            # current one (RT-3, I18).
            cfg = self._configs.get(rec.get("config_version"))
            if cfg is None:
                return self._replay_deviation(rec)
            if entry is None:
                if event != "request.received":
                    return self._replay_deviation(rec)
                entry = RequestState(
                    request_id=rid,
                    declared_type=(rec.get("info") or {}).get("declared_type", ""),
                    lifecycle_state="created",
                    config_version=rec["config_version"],
                )
                self.ledger._create(entry)
            rows = cfg.rows(entry.lifecycle_state, event)
            if (rows is None
                    or entry.lifecycle_state != rec.get("prior_state")
                    or rec.get("sequence") != entry.transition_sequence + 1):
                return self._replay_deviation(rec)
            row = rows[0] if rec.get("guard_result") else rows[-1]
            expected = {
                "request_id": rid,
                "event_id": rec.get("event_id"),  # carried: source envelope not in log
                "sequence": entry.transition_sequence + 1,
                "prior_state": entry.lifecycle_state,
                "event": event,
                "guard_result": rec.get("guard_result"),
                "next_state": row["next"],
                "config_version": cfg.version,
                "emitted_events": list(row["emit"]),
            }
            if "info" in rec:
                # ponytail: envelope-derived info is carried, not recomputed —
                # the source envelope is not in the log.
                expected["info"] = rec["info"]
            if envelope.canonical(expected) != envelope.canonical(rec):
                return self._replay_deviation(rec)
            info = rec.get("info")
            for action in row.get("actions", ()):
                self._do_action(action, entry, event, info)
            entry.lifecycle_state = row["next"]
            entry.transition_sequence = rec["sequence"]
            entry.last_applied_event_id = rec.get("event_id")
            self.log.append(rec)
            if published is not None and (rid, rec["sequence"]) not in published:
                decision = row.get("decision") or ("permit" if rec["guard_result"] else "block")
                self._publish_row(entry, row, decision, cfg, info)  # re-emit (CR-1)
        return True

    def _replay_deviation(self, rec):
        self.halted = True  # halt over degrade (I22)
        self._fault("replay.deviation:sequence=%s" % rec.get("sequence"), None)
        return False


if __name__ == "__main__":
    from kernel.bus import Bus
    from kernel.default_config import snapshot

    def _env(event_id, name, rid, payload):
        return envelope.make(event_id, name, rid, 0, None, payload)

    bus = Bus()
    coord = Coordinator(bus, snapshot())
    coord.handle(_env("e1", "request.received", "r1", {"declared_type": "type.alpha"}))
    assert coord.ledger.get("r1").lifecycle_state == "scheduled"
    coord.handle(_env("e2", "plan.created", "r1", {}))
    coord.handle(_env("e3", "verify.passed", "r1", {}))
    coord.handle(_env("e4", "task.completed", "r1", {}))
    assert coord.ledger.get("r1").lifecycle_state == "completed"
    names = [m["event_name"] for topic in ("request.admitted", "routing.directive",
                                           "request.completed")
             for m in bus.messages(topic)]
    assert names == ["request.admitted", "routing.directive", "request.completed"]
    # duplicate is a no-op record
    before = len(coord.log)
    coord.handle(_env("e4", "task.completed", "r1", {}))
    assert coord.log[-1]["verdict"] == "duplicate" and len(coord.log) == before + 1
    # recovery rebuilds byte-identically
    coord2 = Coordinator(Bus(), snapshot())
    assert coord2.recover(list(coord.log)) is True
    assert coord2.ledger.get("r1").lifecycle_state == "completed"
    print("coordinator selftest ok")
