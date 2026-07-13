"""Read-only RSM config snapshot (RSM/03-internal-design.md §2 retention
window, §8 coalescing interval, §11 checkpoint N; RSM/05-implementation-
spec.md M4 "config_view (retention window, checkpoint N)"). Mirrors kernel's
Config View precedent (`src/kernel/config_view.py`): read-only, validated at
construction, no in-place mutation — RSM never writes config, only reads a
resolved snapshot (RSM/05 §1 `config_view` row).

# ponytail: kernel's ConfigView carries routing tables, gates, and a full
# transition-row structure because kernel's config *is* that big. RSM's
# config is three scalars (RSM/05 §1's `config_view` row lists exactly
# three: retention window, coalescing interval, checkpoint N) — a
# lighter read-only wrapper is the right-sized version of the same
# pattern, not a scaled-down copy of kernel's shape. Ceiling: no
# `config.changed`-driven live snapshot swap (kernel's ConfigView is built
# to be replaced wholesale on each event; RSM has no Communication config
# topic yet). Upgrade path: once RSM has a config-carrying event family,
# swap the constructor call site for one driven by that event, same as
# kernel already does — `RsmConfigView` itself does not change.
"""


class RsmConfigView:
    """Immutable snapshot: `retention_window` (RSM/03 §2, eviction gate's
    third precondition — RSM-I11), `checkpoint_n` (RSM/03 §11, "every N
    applied events"), `coalescing_interval` (RSM/03 §8, telemetry — M5
    scope, carried here now so a future M5 doesn't need a second config
    module)."""

    __slots__ = ("_retention_window", "_checkpoint_n", "_coalescing_interval")

    def __init__(self, retention_window, checkpoint_n, coalescing_interval=1):
        if not isinstance(retention_window, (int, float)) or isinstance(retention_window, bool) \
                or retention_window < 0:
            raise ValueError("config_view.bad_retention_window")
        if not isinstance(checkpoint_n, int) or isinstance(checkpoint_n, bool) or checkpoint_n <= 0:
            raise ValueError("config_view.bad_checkpoint_n")
        if not isinstance(coalescing_interval, (int, float)) or isinstance(coalescing_interval, bool) \
                or coalescing_interval < 0:
            raise ValueError("config_view.bad_coalescing_interval")
        object.__setattr__(self, "_retention_window", retention_window)
        object.__setattr__(self, "_checkpoint_n", checkpoint_n)
        object.__setattr__(self, "_coalescing_interval", coalescing_interval)

    def __setattr__(self, name, value):
        raise AttributeError("RsmConfigView is read-only (RSM/03 §2 'RSM never writes config')")

    @property
    def retention_window(self):
        return self._retention_window

    @property
    def checkpoint_n(self):
        return self._checkpoint_n

    @property
    def coalescing_interval(self):
        return self._coalescing_interval


if __name__ == "__main__":
    view = RsmConfigView(retention_window=3600, checkpoint_n=50)
    assert view.retention_window == 3600
    assert view.checkpoint_n == 50
    assert view.coalescing_interval == 1  # default

    try:
        view.retention_window = 10
        raise SystemExit("mutation allowed")
    except AttributeError:
        pass

    for bad_kwargs in (
        {"retention_window": -1, "checkpoint_n": 1},
        {"retention_window": 1, "checkpoint_n": 0},
        {"retention_window": 1, "checkpoint_n": 1.5},
        {"retention_window": 1, "checkpoint_n": 1, "coalescing_interval": -1},
    ):
        try:
            RsmConfigView(**bad_kwargs)
            raise SystemExit("bad config accepted: " + str(bad_kwargs))
        except ValueError:
            pass

    print("config_view selftest ok")
