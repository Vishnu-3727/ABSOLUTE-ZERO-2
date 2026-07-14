"""PRT discovery — PRT/02 §1 (declarations only, never registry mutation —
PRT-A1) and §6/PRT-A9 (deterministic serialization order for logically
concurrent candidacies: sorted by content_hash, never source order or
wall-clock).

A DiscoverySource is a minimal protocol, not a base class to inherit from:
anything with a `.declarations()` method returning an iterable of
Declaration objects qualifies. FixtureSource below is the only source this
phase implements.
"""
from . import events

# ponytail: real filesystem/manifest scanning DiscoverySources are future
# work (Phase 3+ territory, or a later PRT/02 extension) -- this phase only
# needs a source shape stable enough for admission.py and tests to build
# on. FixtureSource (an in-memory fixed list) is that shape's only
# implementation; a real source just needs the same one method.


class FixtureSource:
    """In-memory DiscoverySource: yields a fixed, pre-built list of
    Declarations. Construction order is irrelevant -- discover() re-orders
    everything by content_hash regardless of which source or what order
    supplied it (PRT-A9)."""

    def __init__(self, declarations=()):
        self._declarations = list(declarations)

    def declarations(self):
        return list(self._declarations)


def discover(sources, bus):
    """Collect every Declaration from every source (read-only: nothing here
    ever touches a registry, PRT-A1). Orders the combined set deterministically
    by content_hash -- never by source order, never by wall-clock arrival
    (PRT-A9) -- publishes plugin.discovered once per declaration in that
    order, and returns the ordered list for admission.py to consume."""
    collected = []
    for source in sources:
        collected.extend(source.declarations())
    ordered = sorted(collected, key=lambda declaration: declaration.content_hash)
    for declaration in ordered:
        events.emit(bus, "plugin.discovered", declaration.provider.id,
                    {"content_hash": declaration.content_hash,
                     "source_class": declaration.source_class})
    return ordered


if __name__ == "__main__":
    from .bus_double import BusDouble
    from .declarations import build_declaration
    from .records import build_provider

    bus = BusDouble()
    decl_a = build_declaration(build_provider("prov.z", "1.0"), source_class="local")
    decl_b = build_declaration(build_provider("prov.a", "1.0"), source_class="remote")
    decl_c = build_declaration(build_provider("prov.m", "1.0"), source_class="built-in")

    # two sources, declarations added in a deliberately non-hash order
    source1 = FixtureSource([decl_a])
    source2 = FixtureSource([decl_b, decl_c])

    ordered = discover([source1, source2], bus)
    assert [d.content_hash for d in ordered] == sorted(d.content_hash for d in (decl_a, decl_b, decl_c))

    # PRT-A1: discovery never mutates a registry -- there isn't one to mutate
    # here at all, which is the point; discover()'s signature has no registry
    # parameter, structurally, not just by convention.

    # deterministic regardless of source order: swapping source order yields
    # the identical result (content-hash sort, never source-arrival order)
    ordered_swapped = discover([source2, source1], bus)
    assert [d.content_hash for d in ordered] == [d.content_hash for d in ordered_swapped]

    # one plugin.discovered event per declaration, in the same sorted order
    discovered_events = bus.messages("plugin.discovered")
    assert len(discovered_events) == 6  # 3 + 3, two discover() calls above
    first_three = [e["payload"]["content_hash"] for e in discovered_events[:3]]
    assert first_three == [d.content_hash for d in ordered]

    # trust class never bypasses anything at discovery -- all three source
    # classes above flowed through the exact same discover() path (PRT-A2)
    assert {d.source_class for d in ordered} == {"local", "remote", "built-in"}

    print("discovery selftest ok")
