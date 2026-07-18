"""Communication — the event bus and message-schema authority
(COMPONENTS/communication.md; ARCHITECTURE.md delivery-semantics table;
ROADMAP Phase 0 substrate).

Modules:
  schema.py  the versioned dotted-event vocabulary + per-topic shape rules
             (ERRATA C1 honored: `lesson.recorded`, never `lesson.learned`)
  bus.py     the transport: per-topic FIFO, at-least-once via held queues +
             persist-before-ack through an injected Storage port,
             backpressure signaling, dead-letter + `delivery.failed`,
             sequence-numbered replay log

Ownership boundaries (Never Owns): durable bytes are written only through
the injected Storage port; no process spawning; no domain interpretation —
the bus moves messages and never reads their meaning.
"""
from .bus import (BackpressureError, Bus, BusRefusal,  # noqa: F401
                  DurabilityUnavailableError)
from .schema import ENVELOPE, RECORD, SCHEMA_VERSION, SchemaViolation  # noqa: F401
