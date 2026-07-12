"""Admission decision: pure function, no state, no side effects.

(envelope, config, halted, active_count) -> (permit, reason).
Schema validity and halt/exhaustion flags only — boolean checks against
Config View data (I2). Capacity policy beyond the exhaustion threshold
belongs to Scheduling backpressure, never here (phase 5).
"""


def decide(env, config, halted, active_count):
    if halted:
        return False, "admission.halted"
    if active_count >= config.fault_policy["max_active_requests"]:
        # Degradation ladder level 4: refuse new admissions, protect active.
        return False, "admission.exhausted"
    required = config.envelope_schemas.get(env["event_name"], [])
    payload = env["payload"]
    for key in required:
        if key not in payload:
            return False, "admission.schema_invalid:" + key
    return True, ""


if __name__ == "__main__":
    from kernel.config_view import ConfigView
    from kernel.default_config import snapshot
    cfg = ConfigView(snapshot())
    env = {"event_name": "request.received", "payload": {"declared_type": "type.alpha"}}
    assert decide(env, cfg, False, 0) == (True, "")
    assert decide(env, cfg, True, 0) == (False, "admission.halted")
    assert decide(env, cfg, False, 1000) == (False, "admission.exhausted")
    bad = {"event_name": "request.received", "payload": {}}
    assert decide(bad, cfg, False, 0) == (False, "admission.schema_invalid:declared_type")
    print("admission selftest ok")
