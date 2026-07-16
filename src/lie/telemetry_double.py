"""In-memory Observability TEST DOUBLE -- LIE's own copy of the sink
pattern `vae/telemetry.py`'s `TelemetrySinkDouble` establishes. Phase 1's
only telemetry producer is the Admission Gate's rejection records (LIE/04
§6 friction R1: "rejection records are operational telemetry, owned by
Observability like all runtime records -- never ledger content"). This
double stands in for that sink: `record(kind, payload)` appends, nothing
more -- no signal-family taxonomy is Phase 1 material (that is VAE/04 §8's
pattern for VAE, not something this phase reinvents for LIE)."""


class ObservabilityDouble:
    def __init__(self):
        self._records = []  # list of (kind, payload) in emission order

    def record(self, kind, payload):
        if not isinstance(kind, str) or not kind:
            raise TypeError("observability.bad_kind:" + repr(kind))
        if not isinstance(payload, dict):
            raise TypeError("observability.bad_payload:" + repr(payload))
        self._records.append((kind, dict(payload)))

    def all(self):
        return tuple(self._records)

    def by_kind(self, kind):
        return tuple(payload for k, payload in self._records if k == kind)


if __name__ == "__main__":
    sink = ObservabilityDouble()
    sink.record("admission_rejected", {"identity": "episode:e1", "reason": "trace_not_closed"})
    sink.record("admission_rejected", {"identity": "episode:e2", "reason": "unknown_facet:x"})

    assert len(sink.all()) == 2
    rejections = sink.by_kind("admission_rejected")
    assert len(rejections) == 2
    assert rejections[0]["identity"] == "episode:e1"

    try:
        sink.record("", {})
        raise SystemExit("empty kind accepted")
    except TypeError:
        pass
    try:
        sink.record("k", "not a dict")
        raise SystemExit("non-mapping payload accepted")
    except TypeError:
        pass

    print("telemetry_double selftest ok")
