"""CP registry TEST DOUBLE — in-memory capability catalog honoring CP/01:
ids, lifecycle states (proposed/active/deprecated/retired), aliases, the
four relations, metadata with mandatory verification expectations, and a
registry version. Read-only production surface: the only mutation methods
are the fixture builders tests call before handing the double to a view.
Imported only by tests/selftests (CP-IMPL 4/12).
"""
LIFECYCLES = ("proposed", "active", "deprecated", "retired")
RELATIONS = ("requires", "composes", "alternative-of", "conflicts-with")


class RegistryDouble:
    def __init__(self, version=1):
        self.version = version
        self._caps = {}     # capability_id -> record dict
        self._aliases = {}  # alias -> capability_id

    # -- fixture builders (test-side only) --------------------------------

    def add(self, capability_id, lifecycle="active", replacement=None,
            verification_expectation="selftest", relations=()):
        if lifecycle not in LIFECYCLES:
            raise ValueError("registry.bad_lifecycle:" + lifecycle)
        record = {"capability_id": capability_id, "lifecycle": lifecycle,
                  "replacement": replacement,
                  "verification_expectation": verification_expectation,
                  "relations": []}
        for kind, target in relations:
            if kind not in RELATIONS:
                raise ValueError("registry.bad_relation:" + kind)
            record["relations"].append((kind, target))
        self._caps[capability_id] = record
        return self

    def alias(self, alias, capability_id):
        self._aliases[alias] = capability_id
        return self

    # -- read surface (what registry_view consumes) ------------------------

    def get(self, capability_id):
        return self._caps.get(capability_id)

    def resolve_alias(self, name):
        return self._aliases.get(name)

    def relations_of(self, capability_id):
        record = self._caps.get(capability_id)
        return tuple(record["relations"]) if record else ()


if __name__ == "__main__":
    reg = (RegistryDouble(version=4)
           .add("cap.read")
           .add("cap.old", lifecycle="deprecated", replacement="cap.read")
           .add("cap.gone", lifecycle="retired")
           .alias("read-files", "cap.read"))
    assert reg.get("cap.read")["lifecycle"] == "active"
    assert reg.resolve_alias("read-files") == "cap.read"
    assert reg.get("cap.old")["replacement"] == "cap.read"
    print("registry_double selftest ok")
