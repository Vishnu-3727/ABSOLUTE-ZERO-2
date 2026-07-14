"""PRT retirement enactment — PRT/02 §8, PRT-A4 (Lifecycle decides
post-publication transitions, PRT never originates one; PRT only enacts).

PRT consumes `plugin.lifecycle.changed` (events.py's closed CONSUMED set)
and translates it 1:1 into Phase 1's `lifecycle_transition` mutation
(registry.py) -- the only path a post-publication state change can take
into the registry (PRT/01 §3's "declarations, admitted or refused" +
"Lifecycle's already-decided transition, enacted"). Atomic binding removal
on provider retirement, and the alias-retirement gate for capabilities, are
both already registry.py's job (PRT-A11, KNOWN SEAM closed in registry.py's
Phase 2 extension) -- this module adds no new consistency logic, only the
event-to-mutation translation PRT-I9 requires.

# ponytail: voluntary-withdrawal REQUESTS (PRT/02 §8's "Requested by: the
# source" row) route to Lifecycle entirely outside PRT -- PRT/02 §8 is
# explicit that a source *requests*, never *decides*. This phase has no
# request-side API at all; a source's withdrawal request is Lifecycle's
# concern from the moment it's made. PRT only ever sees the other end: the
# already-decided plugin.lifecycle.changed event this module enacts.
"""
from . import events

REQUIRED_KEYS = ("entity", "id", "to_state")


def enact_lifecycle_event(registry, event):
    """Consume one plugin.lifecycle.changed payload ({"entity": ...,
    "id": ..., "to_state": ...}) and enact it as a registry-side transition.
    Returns the new registry-global version. Raises the same RegistryRefusal
    apply()/lifecycle_transition would on an illegal transition (backward,
    unknown state, or -- the KNOWN SEAM closed in registry.py -- retiring a
    capability while a live alias still targets it)."""
    events.check_consumed("plugin.lifecycle.changed")  # loud on any other name
    missing = [key for key in REQUIRED_KEYS if key not in event]
    if missing:
        raise ValueError("retirement.malformed_lifecycle_event:" + ",".join(missing))
    return registry.apply({
        "kind": "lifecycle_transition",
        "entity": event["entity"],
        "id": event["id"],
        "to_state": event["to_state"],
    })


if __name__ == "__main__":
    from .records import build_binding, build_capability, build_provider
    from .registry import AliasTargetRetirementError, LifecycleTransitionError
    from .registry import Registry

    # provider retirement: atomic binding removal, historical snapshot unaffected
    reg = Registry()
    cap = build_capability("cap.ret.a", "d", "nlp", lifecycle="active",
                           verification_expectations=("x",))
    reg.apply({"kind": "add_capability", "record": cap})
    prov = build_provider("prov.ret.a", "1.0")
    reg.apply({"kind": "add_provider", "record": prov})
    reg.apply({"kind": "lifecycle_transition", "entity": "provider",
              "id": "prov.ret.a", "to_state": "active"})
    reg.apply({"kind": "add_binding", "record": build_binding("cap.ret.a", "prov.ret.a")})
    v_before = reg.current_version
    assert len(reg.bindings_for("cap.ret.a")) == 1

    enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.ret.a",
                                "to_state": "deprecated"})
    v_retire = enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.ret.a",
                                           "to_state": "retired"})
    assert reg.bindings_for("cap.ret.a") == []  # gone, same mutation as retirement
    assert reg.at_version(v_before).bindings_for("cap.ret.a") != []  # history untouched

    # PRT never originates this -- enact_lifecycle_event only ever translates
    # an event that already carries a decided to_state; it never decides one
    # itself (no code path here picks "retired" on its own initiative).

    # illegal transition still refused loudly, same as a direct apply() would
    try:
        enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.ret.a",
                                    "to_state": "active"})
        raise SystemExit("backward transition via lifecycle event accepted")
    except LifecycleTransitionError:
        pass

    # alias-retirement gate: capability retirement refused while a live
    # alias still targets it (KNOWN SEAM, closed in registry.py)
    reg2 = Registry()
    reg2.apply({"kind": "add_capability", "record": build_capability(
        "cap.ret.old", "old", "nlp", verification_expectations=("x",))})
    reg2.apply({"kind": "lifecycle_transition", "entity": "capability",
               "id": "cap.ret.old", "to_state": "active"})
    reg2.apply({"kind": "add_capability", "record": build_capability(
        "cap.ret.new", "new", "nlp", aliases=("cap.ret.old.alias",),
        verification_expectations=("x",))})
    reg2.apply({"kind": "lifecycle_transition", "entity": "capability",
               "id": "cap.ret.new", "to_state": "active"})
    enact_lifecycle_event(reg2, {"entity": "capability", "id": "cap.ret.new",
                                 "to_state": "deprecated"})
    try:
        enact_lifecycle_event(reg2, {"entity": "capability", "id": "cap.ret.new",
                                     "to_state": "retired"})
        raise SystemExit("capability retired despite live alias target")
    except AliasTargetRetirementError:
        pass

    # malformed event refused loudly, before it ever reaches the registry
    try:
        enact_lifecycle_event(reg, {"entity": "provider", "id": "prov.ret.a"})
        raise SystemExit("malformed event (missing to_state) accepted")
    except ValueError:
        pass

    # dead/unknown event name refused via events.py's closed vocabulary --
    # this module's gate is events.check_consumed, called unconditionally
    # (a dispatcher upstream would route by event_name; this asserts the
    # gate itself still refuses if ever called on the wrong name)
    try:
        events.check_consumed("plugin.disabled")
        raise SystemExit("dead vocabulary reached retirement.py unchecked")
    except ValueError:
        pass

    print("retirement selftest ok")
