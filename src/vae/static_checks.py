"""VAE's own bounded static checks (VAE/06 Phase 2: "VAE's own bounded
static checks as pluggable modules"). A static check is VAE's own bounded
self-work (VAE/00 §9) — no delegation, no Execution channel, no I/O, no
clock: a deterministic function of `(artifact_ref, metadata)` to a result
dict.

`StaticCheckRegistry` is an instance, not a module-level global: each
judgment (or test) gets its own closed registration surface rather than
every user of this module sharing one process-wide dict — a name can be
registered once per registry; `run()` refuses an unregistered name. It is
the *pluggability* of what a registry can hold that is the point (VAE/06
Phase 2 blueprint note: "keep minimal, one or two real built-ins, it's the
seam that matters"), not a fixed list.

One real built-in ships pre-registered on every new registry:
`reference_wellformed`, the reference-shape check the blueprint names as
the example — reports whether `artifact_ref` looks like a Storage-backed
reference (non-empty `namespace:id` shape) rather than empty/malformed
input that would make every other check meaningless."""

RESULT_OUTCOMES = ("pass", "fail")


class StaticCheckRefusal(Exception):
    """Base for static_checks.py refusals."""


class DuplicateCheckNameError(StaticCheckRefusal):
    """A check name registered twice in the same registry — the
    registration surface is closed per name, not silently overwritten."""


class UnknownStaticCheckError(StaticCheckRefusal):
    """run() asked for a check name never registered."""


class MalformedCheckResultError(StaticCheckRefusal):
    """A check function returned something outside the closed result shape."""


def _reference_wellformed(artifact_ref, metadata):
    ok = isinstance(artifact_ref, str) and ":" in artifact_ref and all(
        part for part in artifact_ref.split(":", 1))
    return {"outcome": "pass" if ok else "fail", "detail": {"artifact_ref": artifact_ref}}


class StaticCheckRegistry:
    def __init__(self):
        self._checks = {}
        self.register("reference_wellformed", _reference_wellformed)

    def register(self, name, fn):
        if not isinstance(name, str) or not name:
            raise StaticCheckRefusal("static_checks.bad_name:" + repr(name))
        if not callable(fn):
            raise StaticCheckRefusal("static_checks.not_callable:" + repr(fn))
        if name in self._checks:
            raise DuplicateCheckNameError("static_checks.duplicate_name:" + name)
        self._checks[name] = fn

    def registered_names(self):
        return tuple(sorted(self._checks.keys()))

    def run(self, name, artifact_ref, metadata):
        """Run a registered check. `metadata` is whatever reference-shaped
        context the caller has (never artifact content). The check
        function must return a mapping with an "outcome" key in
        RESULT_OUTCOMES; anything else is a loud MalformedCheckResultError,
        never silently coerced."""
        if name not in self._checks:
            raise UnknownStaticCheckError("static_checks.unknown_check:" + str(name))
        result = self._checks[name](artifact_ref, metadata)
        if not isinstance(result, dict) or result.get("outcome") not in RESULT_OUTCOMES:
            raise MalformedCheckResultError("static_checks.malformed_result:" + repr(result))
        return dict(result)


if __name__ == "__main__":
    registry = StaticCheckRegistry()
    assert "reference_wellformed" in registry.registered_names()

    ok = registry.run("reference_wellformed", "artifact:a1", {})
    assert ok["outcome"] == "pass"

    bad = registry.run("reference_wellformed", "not-a-reference", {})
    assert bad["outcome"] == "fail"

    # deterministic: same inputs, same outcome, every call
    assert registry.run("reference_wellformed", "artifact:a1", {}) == ok

    # unregistered check name refused loud
    try:
        registry.run("nonexistent", "artifact:a1", {})
        raise SystemExit("unregistered check name accepted")
    except UnknownStaticCheckError:
        pass

    # duplicate registration refused loud
    try:
        registry.register("reference_wellformed", _reference_wellformed)
        raise SystemExit("duplicate check name registration accepted")
    except DuplicateCheckNameError:
        pass

    # a pluggable check can be added, and a malformed result is refused loud
    def _bad_check(artifact_ref, metadata):
        return {"outcome": "maybe"}

    registry.register("selftest_bad_check", _bad_check)
    try:
        registry.run("selftest_bad_check", "artifact:a1", {})
        raise SystemExit("malformed check result accepted")
    except MalformedCheckResultError:
        pass

    def _custom_check(artifact_ref, metadata):
        return {"outcome": "pass", "detail": metadata}

    registry.register("selftest_custom_check", _custom_check)
    assert registry.run("selftest_custom_check", "artifact:a1", {"k": "v"})["detail"] == {"k": "v"}

    # a second, independent registry starts fresh (no cross-instance leakage)
    other = StaticCheckRegistry()
    assert other.registered_names() == ("reference_wellformed",)

    print("static_checks selftest ok")
