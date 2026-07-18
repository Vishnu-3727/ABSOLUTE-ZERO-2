"""Storage — the durable-byte substrate (COMPONENTS/storage.md; Global
Law 3; ERRATA C7 owner namespaces; C10 custody-not-authority; C13 event
names).

Modules:
  store.py    Store (atomic checksummed writes, exclusive directory lock,
              verified reads, deterministic key iteration) +
              NamespaceHandle (a component's namespace-confined view —
              C7's executable form)
  journal.py  append-only journals + immutable checkpoints + deterministic
              reconstruct(), pure byte mechanics

Storage owns bytes, never meaning: no payload interpretation, no
read/write *authorization* beyond namespace confinement, no routing, no
scheduling, no semantics. Git integration is deferred until Execution
exists (Storage spawns nothing itself — storage.md Never Owns).
"""
from .journal import Journal  # noqa: F401
from .store import (BadKeyError, CorruptionError, KeyExistsError,  # noqa: F401
                    LockHeldError, MissingKeyError, NamespaceHandle,
                    StorageRefusal, Store, WriteFailedError)
