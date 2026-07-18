"""Workflow dispatcher runtime — WS/02 semantics over a frozen artifact.

All runtime state (unit progress, branch selections, workflow status)
lives HERE, never in the artifact (WS-W12, WS/02 §8). Every state change
is one appended journal record (Storage-owned bytes, namespace `ws/`), so
`WorkflowRun.replay()` reconstructs the identical run from the journal —
scheduling decisions are observations, replayable (Law 5/6).

Semantics implemented exactly as locked:
  readiness      pure function of (artifact, runtime state): workflow
                 Active + all predecessors SUCCEEDED + branch selected
                 (WS/02 §2, WS-E1/E5); unselected-branch units never
                 ready (WS-E4)
  completion     SUCCEEDED = exec success AND verify.passed (WS-E3,
                 per-unit verification default); FAILED = exec failure /
                 timeout / verify.failed; NOT-EXECUTED = unselected
                 branch (WS/02 §7)
  failure        a failed predecessor leaves downstream permanently
                 unready — never skipped, never retried here (WS-E9;
                 workflow-level retry = unwritten resilience phase,
                 ERRATA C15 §3; Execution's own bounded attempt-retries
                 are untouched)
  order          dispatch releases ready units in the artifact's
                 canonical total order — WS/02 §5's default policy when
                 no other policy exists; priority/budget policy is the
                 unwritten dispatcher-policy phase, refused not invented
  monotonicity   pending -> executing -> terminal, exactly one terminal
                 outcome per unit (WS-E8), enforced
  branch select  explicit `select_branch`, or the interim default:
                 highest CP rank, servability filter deferred to PRT
                 wiring (ERRATA C15 §4)

Events (ERRATA C15 canon): `workflow.created` on publish;
`task.scheduled` per unit at activation; `task.started` on dispatch;
`verify.requested` after execution success; `task.completed` /
`task.failed` on unit terminal. Late binding: the artifact carries
capability ids only; the injected `binder(unit) -> execution spec` is the
Plugin-Runtime-fulfillment seam (C4) — dispatching without a binder is
refused, fail closed.
"""
import json

PENDING = "pending"
EXECUTING = "executing"
SUCCEEDED = "succeeded"
FAILED = "failed"
NOT_EXECUTED = "not-executed"
TERMINAL = (SUCCEEDED, FAILED, NOT_EXECUTED)

ACTIVE = "active"
COMPLETED = "completed"
STALLED = "failed"        # a CRITICAL/REQUIRED unit failed: replan territory
CANCELLED = "cancelled"

_BLOCKING_BANDS = ("CRITICAL", "REQUIRED")  # WS/02 §10b


class SchedulerRefusal(Exception):
    """Engine-level refusal (illegal transition, missing binder, ...)."""


class WorkflowRun:
    def __init__(self, workflow, storage=None, bus=None, binder=None, engine=None):
        self.workflow = workflow
        self.storage = storage
        self.bus = bus
        self.binder = binder
        self.engine = engine
        self.status = None            # set Active by activate()
        self.unit_state = {uid: PENDING for uid in workflow.units}
        self.exec_ok = set()          # units whose execution succeeded (await verdict)
        self.selected = {}            # group_id -> selected unit_id
        self._journal = None
        self._replaying = False

    # -- journal ----------------------------------------------------------

    def _record(self, kind, **fields):
        if self._replaying or self.storage is None:
            return
        if self._journal is None:
            from storage import Journal
            self._journal = Journal(self.storage, self.workflow.workflow_id)
        doc = {"kind": kind}
        doc.update(fields)
        self._journal.append(json.dumps(doc, sort_keys=True,
                                        separators=(",", ":")).encode())

    def _emit(self, event_name, payload, unit_id=None, seq=0):
        if self.bus is None or self._replaying:
            return
        event_id = "%s:%s:%s" % (self.workflow.workflow_id,
                                 unit_id or "wf", event_name)
        body = {"workflow_id": self.workflow.workflow_id}
        body.update(payload)
        self.bus.publish(event_name, {
            "event_id": event_id, "event_name": event_name,
            "request_id": None, "timestamp": 0, "payload": body})

    # -- lifecycle ----------------------------------------------------------

    def activate(self):
        if self.status is not None:
            raise SchedulerRefusal("ws.activate_twice")
        self.status = ACTIVE
        self._record("activated")
        self._emit("workflow.created", {"content_hash": self.workflow.content_hash})
        for uid in self.workflow.canonical_order:
            self._emit("task.scheduled",
                       {"unit_id": uid,
                        "priority_band": self.workflow.units[uid]["priority_band"]},
                       unit_id=uid)
        for group_id in sorted(self.workflow.groups):
            # interim default (ERRATA C15 §4): highest CP rank, pre-sorted
            self.select_branch(group_id, self.workflow.groups[group_id][0])
        return self

    def cancel(self):
        if self.status != ACTIVE:
            raise SchedulerRefusal("ws.cancel_illegal:" + str(self.status))
        self.status = CANCELLED
        self._record("cancelled")

    def select_branch(self, group_id, unit_id):
        members = self.workflow.groups.get(group_id)
        if members is None or unit_id not in members:
            raise SchedulerRefusal("ws.bad_selection:%s:%s" % (group_id, unit_id))
        if group_id in self.selected:
            raise SchedulerRefusal("ws.reselection:" + group_id)  # C2: once
        self.selected[group_id] = unit_id
        self._record("selected", group=group_id, unit=unit_id)
        for member in members:
            if member != unit_id:
                self._terminal(member, NOT_EXECUTED)  # WS/02 §7, WS-E4

    # -- semantics (pure functions of artifact + runtime state) -------------

    def _branch_allows(self, uid):
        group = self.workflow.units[uid].get("group_id")
        return group is None or self.selected.get(group) == uid

    def ready(self):
        """Deterministic ready set (WS/02 §2), canonical-order sorted."""
        if self.status != ACTIVE:
            return []
        out = []
        for uid in self.workflow.canonical_order:
            if (self.unit_state[uid] == PENDING and self._branch_allows(uid)
                    and all(self.unit_state[p] == SUCCEEDED
                            for p in self.workflow.predecessors(uid))):
                out.append(uid)
        return out

    # -- dispatch + completion ----------------------------------------------

    def dispatch_next(self):
        """Release the first ready unit in canonical order to Execution.
        Returns (unit_id, execution result) or None when nothing is ready."""
        ready = self.ready()
        if not ready:
            return None
        if self.binder is None or self.engine is None:
            raise SchedulerRefusal("ws.no_binder_or_engine")  # fail closed, C4 seam
        uid = ready[0]
        self.unit_state[uid] = EXECUTING
        self._record("dispatched", unit=uid)
        self._emit("task.started", {"unit_id": uid}, unit_id=uid)
        handle = self.engine.submit(self.binder(self.workflow.units[uid]))
        result = self.engine.run(handle)
        self.on_exec_result(uid, result["state"] == "completed")
        return uid, result

    def on_exec_result(self, uid, ok):
        if self.unit_state[uid] != EXECUTING:
            raise SchedulerRefusal("ws.exec_result_illegal:" + self.unit_state[uid])
        self._record("exec_result", unit=uid, ok=bool(ok))
        if not ok:
            self._terminal(uid, FAILED)
            return
        self.exec_ok.add(uid)  # necessary, not sufficient (WS-E3)
        self._emit("verify.requested", {"unit_id": uid}, unit_id=uid)

    def on_verdict(self, uid, passed):
        """`verify.passed`/`verify.failed` for a unit (per-unit gate)."""
        if uid not in self.exec_ok:
            raise SchedulerRefusal("ws.verdict_without_execution:" + uid)
        self.exec_ok.discard(uid)
        self._record("verdict", unit=uid, passed=bool(passed))
        self._terminal(uid, SUCCEEDED if passed else FAILED)

    def _terminal(self, uid, outcome):
        if self.unit_state[uid] in TERMINAL:
            raise SchedulerRefusal("ws.double_terminal:" + uid)  # WS-E8
        self.unit_state[uid] = outcome
        self._record("terminal", unit=uid, outcome=outcome)
        if outcome != NOT_EXECUTED:
            self._emit("task.completed" if outcome == SUCCEEDED else "task.failed",
                       {"unit_id": uid, "outcome": outcome}, unit_id=uid)
        self._settle()

    def _settle(self):
        if self.status != ACTIVE:
            return
        blocking = [uid for uid, unit in self.workflow.units.items()
                    if unit["priority_band"] in _BLOCKING_BANDS]
        if any(self.unit_state[uid] == FAILED for uid in blocking):
            self.status = STALLED  # WS-E9: replan/supersede territory
            self._record("workflow_terminal", status=self.status)
        elif all(self.unit_state[uid] in TERMINAL for uid in self.workflow.units):
            self.status = COMPLETED  # WS/02 §10b
            self._record("workflow_terminal", status=self.status)

    # -- replay ---------------------------------------------------------------

    @classmethod
    def replay(cls, workflow, storage):
        """Rebuild a run purely from its journal — identical artifact +
        identical journal -> identical state (WS/02 §8 deterministic
        progression). Emits nothing, appends nothing."""
        from storage import Journal
        run = cls(workflow, storage=None)
        run._replaying = True
        for raw in Journal(storage, workflow.workflow_id).entries():
            rec = json.loads(raw.decode())
            kind = rec["kind"]
            if kind == "activated":
                run.status = ACTIVE
            elif kind == "cancelled":
                run.status = CANCELLED
            elif kind == "selected":
                run.selected[rec["group"]] = rec["unit"]
            elif kind == "dispatched":
                run.unit_state[rec["unit"]] = EXECUTING
            elif kind == "exec_result" and rec["ok"]:
                run.exec_ok.add(rec["unit"])
            elif kind == "verdict":
                run.exec_ok.discard(rec["unit"])
            elif kind == "terminal":
                run.unit_state[rec["unit"]] = rec["outcome"]
            elif kind == "workflow_terminal":
                run.status = rec["status"]
        return run
