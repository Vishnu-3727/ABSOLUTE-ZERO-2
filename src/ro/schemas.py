"""RO/03 §10 — Output Schema Architecture (RO/05 §10 blueprint group G3+G4).
A minimal OS-owned, versioned registry. Frozen entries keyed by
(schema_id, version), append-only; a request names exactly one schema
version forever (RO-P9). Only mechanical shape (field names + required
keys) is validated here — semantic content validation is downstream, out
of scope (RO/03 §10 "No actual schemas are defined in this document").
"""
from dataclasses import dataclass


class SchemaRefusal(Exception):
    """Base for schema-registry refusals."""


class DuplicateSchemaVersionError(SchemaRefusal):
    """A published (schema_id, version) is immutable (RO/03 §10 Evolution row)."""


class UnknownSchemaError(SchemaRefusal):
    """A request named a schema version the registry never published."""


@dataclass(frozen=True)
class SchemaRecord:
    schema_id: str
    version: int
    required_fields: tuple  # field names the output object must contain


class SchemaRegistry:
    """Append-only. `register` refuses a duplicate (schema_id, version);
    nothing here ever mutates a published entry."""

    def __init__(self):
        self._entries = {}

    def register(self, schema_id, version, required_fields):
        key = (schema_id, version)
        if key in self._entries:
            raise DuplicateSchemaVersionError(
                "schemas.duplicate_version:" + schema_id + ":" + str(version))
        record = SchemaRecord(schema_id=schema_id, version=version,
                               required_fields=tuple(required_fields))
        self._entries[key] = record
        return record

    def get(self, schema_id, version):
        return self._entries.get((schema_id, version))

    def require(self, schema_id, version):
        record = self.get(schema_id, version)
        if record is None:
            raise UnknownSchemaError("schemas.unknown:" + str(schema_id) + ":" + str(version))
        return record


if __name__ == "__main__":
    registry = SchemaRegistry()
    rec = registry.register("ro.schema.summary_v1", 1, ("summary", "citations"))
    assert rec.schema_id == "ro.schema.summary_v1"
    assert registry.get("ro.schema.summary_v1", 1) is rec
    assert registry.get("ro.schema.summary_v1", 2) is None

    try:
        registry.register("ro.schema.summary_v1", 1, ("summary",))
        raise SystemExit("duplicate (schema_id, version) accepted")
    except DuplicateSchemaVersionError:
        pass

    try:
        registry.require("ro.schema.summary_v1", 99)
        raise SystemExit("unknown schema version accepted")
    except UnknownSchemaError:
        pass

    assert registry.require("ro.schema.summary_v1", 1) is rec

    print("schemas selftest ok")
