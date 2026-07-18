"""CP registry view — CP's one vocabulary door (CP/05 registry side;
CP/01 §9 read-only). Id resolution through alias chains; lifecycle
semantics: active = matchable; deprecated = matchable with the replacement
pointer RECORDED (never silently swapped); retired = tombstone, never
matchable for new plans; unknown = None (a typed gap is the caller's
move, never an invented id). Every resolution stamps the registry
version. No mutation path exists on this surface (CP-IMPL 4).
"""

_MAX_ALIAS_HOPS = 8  # alias cycles are a registry defect, fail loud


class RegistryViewRefusal(Exception):
    """Registry inconsistency (alias cycle) — pipeline aborts."""


class RegistryView:
    def __init__(self, registry):
        self._registry = registry
        self.registry_version = registry.version

    def resolve(self, name):
        """name/alias -> resolution dict or None (unknown ability).

        {"capability_id", "lifecycle", "matchable", "replacement" | None,
         "registry_version"} — deprecated stays matchable with its
        replacement recorded; retired is a tombstone (matchable=False)."""
        seen = []
        current = name
        for _ in range(_MAX_ALIAS_HOPS):
            record = self._registry.get(current)
            if record is not None:
                lifecycle = record["lifecycle"]
                return {"capability_id": record["capability_id"],
                        "lifecycle": lifecycle,
                        "matchable": lifecycle in ("active", "deprecated"),
                        "replacement": record["replacement"],
                        "registry_version": self.registry_version}
            target = self._registry.resolve_alias(current)
            if target is None:
                return None
            if target in seen:
                raise RegistryViewRefusal("cp.registry.alias_cycle:" + name)
            seen.append(target)
            current = target
        raise RegistryViewRefusal("cp.registry.alias_chain_too_long:" + name)

    def relations_of(self, capability_id):
        return self._registry.relations_of(capability_id)


if __name__ == "__main__":
    from .registry_double import RegistryDouble

    reg = (RegistryDouble(version=7)
           .add("cap.read", relations=(("requires", "cap.fs"),))
           .add("cap.fs")
           .add("cap.old", lifecycle="deprecated", replacement="cap.read")
           .add("cap.gone", lifecycle="retired")
           .alias("read-files", "cap.read").alias("rf", "read-files")
           .alias("loop-a", "loop-b").alias("loop-b", "loop-a"))
    view = RegistryView(reg)
    hit = view.resolve("rf")  # alias chain rf -> read-files -> cap.read
    assert hit["capability_id"] == "cap.read" and hit["matchable"]
    assert hit["registry_version"] == 7
    dep = view.resolve("cap.old")
    assert dep["matchable"] and dep["replacement"] == "cap.read"
    tomb = view.resolve("cap.gone")
    assert tomb["matchable"] is False  # retired tombstone
    assert view.resolve("cap.never") is None  # unknown: caller gaps it
    assert view.relations_of("cap.read") == (("requires", "cap.fs"),)
    try:
        view.resolve("loop-a")
        raise SystemExit("alias cycle accepted")
    except RegistryViewRefusal:
        pass
    print("registry_view selftest ok")
