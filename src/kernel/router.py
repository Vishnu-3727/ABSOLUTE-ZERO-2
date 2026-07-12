"""Static router: pure function, declared type -> owning component.

Table lookup only (I3): no content inspection, no inference, no fallback.
Unknown type or a non-scalar table entry (multiple owners) is a rejection —
ambiguity never routes (I6).
"""


def route(declared_type, config):
    """Return (target, reason). target is None on rejection."""
    target = config.routing_table.get(declared_type)
    if target is None:
        return None, "routing.unknown_type"
    if not isinstance(target, str):
        # Multiple/structured owners in the table = ambiguous. Never guess.
        return None, "routing.ambiguous_type"
    return target, ""


if __name__ == "__main__":
    from kernel.config_view import ConfigView
    from kernel.default_config import snapshot
    data = snapshot()
    data["routing_table"]["type.multi"] = ["planning", "scheduling"]
    cfg = ConfigView(data)
    assert route("type.alpha", cfg) == ("planning", "")
    assert route("type.unknown", cfg) == (None, "routing.unknown_type")
    assert route("type.multi", cfg) == (None, "routing.ambiguous_type")
    # DT-3: static forever — same answer every time.
    assert all(route("type.alpha", cfg) == ("planning", "") for _ in range(1000))
    print("router selftest ok")
