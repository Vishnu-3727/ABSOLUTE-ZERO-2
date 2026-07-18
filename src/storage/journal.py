"""Append-only journal + immutable checkpoints over a NamespaceHandle.

Pure byte mechanics (Storage owns no meaning): entries are opaque bytes at
`<ns>/journal/<name>/<seq>`, checkpoints at `<ns>/checkpoint/<name>/<seq>`.
Sequence numbers are monotonic integers; every entry and checkpoint goes
through `write_once`, so history physically cannot mutate. `reconstruct`
is deterministic: latest checkpoint (if any) + every entry after it, in
sequence order, hash-verified by the Store on every read.
"""

_ENTRY_KEY = "%s/journal/%s/%012d"
_CHECK_KEY = "%s/checkpoint/%s/%012d"


class Journal:
    def __init__(self, handle, name):
        self.handle = handle
        self.name = name
        self._next_seq = len(handle.keys("%s/journal/%s" % (handle.name, name)))

    def append(self, data):
        """Append opaque bytes; returns the entry's sequence number."""
        seq = self._next_seq
        self.handle.write_once(_ENTRY_KEY % (self.handle.name, self.name, seq), data)
        self._next_seq = seq + 1
        return seq

    def entries(self, after_seq=-1):
        """All entries with seq > after_seq, in sequence order, verified."""
        out = []
        for seq in range(after_seq + 1, self._next_seq):
            out.append(self.handle.read(_ENTRY_KEY % (self.handle.name, self.name, seq)))
        return out

    def checkpoint(self, seq, data):
        """Immutable checkpoint of the fold-state as of entry `seq`."""
        if not isinstance(seq, int) or isinstance(seq, bool) or not (0 <= seq < self._next_seq):
            raise ValueError("journal.bad_checkpoint_seq:" + repr(seq))
        self.handle.write_once(_CHECK_KEY % (self.handle.name, self.name, seq), data)

    def latest_checkpoint(self):
        """(seq, bytes) of the newest checkpoint, or (None, None)."""
        keys = self.handle.keys("%s/checkpoint/%s" % (self.handle.name, self.name))
        if not keys:
            return None, None
        newest = keys[-1]  # keys() is sorted; zero-padded seqs sort numerically
        return int(newest.rsplit("/", 1)[1]), self.handle.read(newest)

    def reconstruct(self):
        """(checkpoint_bytes | None, [entries after it]) — the deterministic
        replay recipe; same persisted state always yields the same tuple."""
        seq, snap = self.latest_checkpoint()
        return snap, self.entries(after_seq=-1 if seq is None else seq)


if __name__ == "__main__":
    import os
    import tempfile

    from .store import KeyExistsError, Store

    with tempfile.TemporaryDirectory() as tmp:
        with Store(os.path.join(tmp, "vault")) as store:
            journal = Journal(store.namespace("rsm"), "r1")
            assert journal.append(b"e0") == 0
            assert journal.append(b"e1") == 1
            journal.checkpoint(1, b"state-after-1")
            assert journal.append(b"e2") == 2
            snap, tail = journal.reconstruct()
            assert (snap, tail) == (b"state-after-1", [b"e2"])
            try:  # history never mutates
                journal.handle.write_once("rsm/journal/r1/%012d" % 0, b"rewrite")
                raise SystemExit("journal entry overwritten")
            except KeyExistsError:
                pass
            # reopen: sequence resumes deterministically
            journal2 = Journal(store.namespace("rsm"), "r1")
            assert journal2.append(b"e3") == 3
            assert journal2.reconstruct() == (b"state-after-1", [b"e2", b"e3"])
    print("journal selftest ok")
