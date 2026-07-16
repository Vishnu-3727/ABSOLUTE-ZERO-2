# Errata

Pre-ruled canon corrections against earlier phase documents. Where a later
audit finds a naming conflict, the correction below is canon; the document
named "overridden" is wrong on that point only, nothing else in it changes.

## C1 — event name is `lesson.recorded`

**Audit: 2026-07-16.** VAE/05's cross-subsystem event matrix lists LIE's
lesson-published event as `lesson.learned`. That name is wrong. LIE's own
canon (`LIE/00-architectural-foundation.md` §4.4, carried into
`src/lie/events.py`) names it `lesson.recorded`. LIE naming wins: LIE is the
publisher of this event, VAE/05 is a downstream reference that drifted.
`lesson.learned` does not exist anywhere in this codebase and must be
treated as an invented name if it is ever proposed again.

## C2 — the Advisory Interface (LIE), not UMS, serves lessons

**Audit: 2026-07-16.** `learning.md` and `memory.md` describe UMS as the
component that serves learned lessons to consumers. That is wrong. Per
`LIE/00-architectural-foundation.md` and `LIE/03-operational-lifecycle.md`
§7, the Advisory Interface is the sole component that answers consultations
and serves recommendation objects; UMS is a peer with strict separation
(identifiers cross, content never does — INV-9). LIE naming wins: `learning.md`
and `memory.md` are wrong on this point and should be read as if they named
the Advisory Interface (LIE) instead of UMS.
