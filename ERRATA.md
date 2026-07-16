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

## C3 — reading of SGPE INV-6 ("Effective Policy frozen") vs mid-request grants

**Phase 4 design: 2026-07-16.** `SGPE/00-architecture-blueprint.md` INV-6
freezes a request's Effective Policy at admission; SGPE/00 §3.5's approval
loop lets a running request obtain grants after a REQUIRE_APPROVAL. Both are
canon and reconcile per `SGPE/04-resolver-grant-ledger.md` §2.3: what is
frozen is the *binding rule* — `(snapshot version, admission ledger position
P₀, request id)` — not the slice's row count. The slice grows in exactly one
way: Ledger appends scope-bound to *this request id* (answers to asks the
request itself raised, and their revocations). No snapshot activation and no
principal/project-width append after P₀ ever enters a running request's
world. Every consultation stamps the ledger position it used, so replay is
exact. INV-6 should be read with this refinement; SGPE/04 §2.3 is the
authoritative wording.
