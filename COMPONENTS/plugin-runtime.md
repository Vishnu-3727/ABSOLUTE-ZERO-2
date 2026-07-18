# Plugin Runtime — Component Specification

## Purpose
Plugin Runtime discovers, loads, isolates, versions, and health-tracks plugins/tools/skills, and
owns the **capability registry** plus a **reliability score that heals over time**. It is how the
system stays model- and tool-agnostic and extensible without the Kernel knowing about any specific
tool. It supports V1's proven CLI-engine surface (every tool a stdlib CLI with JSON out) while
adding the isolation and reliability tracking V1 lacked, so a flaky or malicious plugin degrades
gracefully instead of silently corrupting decisions.

## Responsibilities
- Discover available plugins/tools/skills and register their declared capabilities.
- Load, version, and isolate plugins; enforce compatibility and interface contracts.
- Track per-plugin health and reliability; update scores from observed outcomes; heal scores over time.
- Serve the capability registry (read) to Capability Planning and Context Management.
- Quarantine unhealthy plugins and surface health changes as events.

## Owns
- The capability registry (declared capabilities → plugin bindings, versions).
- Plugin load/isolation/versioning policy.
- Reliability scoring model and its healing/decay behavior.

## Never Owns
- **Process spawning** — a plugin's actual execution goes through Execution (Law 3); Plugin Runtime
  manages metadata/lifecycle/isolation policy, not spawning.
- **Durable writes** — registry/score persistence via Storage.
- **The bus** — Communication only.
- **Repository retrieval** — Repository Memory only.
- **Planning/matching decisions** — Capability Planning consumes the registry and decides.

## Inputs
- Plugin discovery sources (declared manifests, install locations).
- `plugin.lifecycle.changed` (from Lifecycle) — authoritative plugin state transitions.
- `reliability.updated` (from Learning) — outcome-derived reliability signal.
- Process outcome events used to inform health (`exec.failed`, `exec.timeout`).

## Outputs
- The capability registry (via direct query API + change events).
- Per-plugin health/reliability status.

## Events Published
- `plugin.registered` — a plugin and its capabilities entered the registry.
- `plugin.loaded` — a plugin is loaded and available for use.
- `plugin.unloaded` — a plugin removed/quarantined/unloaded.
- `plugin.health.changed` — a plugin's health/reliability crossed a threshold.

## Events Consumed
- `plugin.lifecycle.changed` (Lifecycle)
- `reliability.updated` (Learning)
- `exec.failed`, `exec.timeout` (Execution) — evidence for health.

## Dependencies
- **Lifecycle** — owns plugin state machine; Plugin Runtime enacts registry/load effects of transitions.
- **Learning** — supplies healed reliability priors from closed traces.
- **Execution** — actually runs plugin processes; supplies failure evidence.
- **Storage** — persists registry and reliability scores.
- **Communication / Observability** — transport and universal telemetry consumer.

## Failure Modes
- **Malicious/broken plugin** → isolation contains it; repeated `exec.failed`/`exec.timeout`
  drop its reliability and trigger quarantine (`plugin.unloaded` + `plugin.health.changed`).
- **Version conflict** → incompatible plugin refused at load; never silently shadow another capability.
- **Registry drift** → registry is the single source; Capability Planning reads it live, so no
  divergent per-component tool lists (a V1 duplication class).
- **Score thrash** → healing/decay smoothing prevents flapping quarantine on transient blips.

## Performance Goals
- Registry lookup is O(1)/indexed, not a filesystem scan per query.
- Health updates are incremental from outcome events, not periodic full rescans.
- Determinism (Law 6): identical registry + identical outcome history → identical reliability scores and matches.

## Testing Strategy
- Selftest: fixture manifests → asserted registry contents and `plugin.registered`.
- Isolation tests: misbehaving fixture plugin cannot affect others or the host.
- Reliability tests: injected failure/success streams produce expected score movement and quarantine.
- Healing tests: a recovered plugin's score recovers over time (no permanent blacklist from one blip).

## Future Expansion
- Signed plugins and trust tiers; capability-scoped permissions.
- Hot-reload and canary rollout of plugin versions.
- Marketplace/remote plugin sources with provenance.

## Acceptance Criteria
- One registry is the sole capability source; no component maintains its own tool list.
- Reliability scores heal over time and drive quarantine, not one-shot blacklists.
- Plugin execution always routes through Execution.
- All published events consumed by Observability; all consumed events have a named publisher.

## Errata (PRT Phase 5, integration)

This spec predates PRT/00-05 (`PRT/00-architectural-foundation.md` through
`PRT/05-system-integration.md`), which resolved event-canon drift found between this document and
`ARCHITECTURE.md`. Corrections, spec body left otherwise unchanged:

- **(a) Published events canon** — `plugin.discovered`, `plugin.registered`, `plugin.loaded`,
  `plugin.unloaded`, `plugin.health.changed`. `plugin.disabled` never existed in this spec's
  Published list (see above) — it was matrix-side drift only, and is now dead vocabulary; the fact
  it named (barred from eligibility) is exactly what `plugin.health.changed` already announces
  (PRT/05 §4).
- **(b) Events Consumed** — `exec.failed`/`exec.timeout` above are stale draft vocabulary;
  the canonical, Execution-published names are `exec.failed`/`exec.timeout` (PRT/00 §7 D2, PRT/05
  §4). PRT consumes `exec.*` as health evidence, nothing else.
- **(c) Registry contents** — the capability registry additionally carries CP/01's full capability
  metadata (category, facets, lifecycle state, aliases, relationships, verification expectations),
  per `PRT/00-architectural-foundation.md` §3 and `PRT/01-registry-model.md`. Not limited to
  "declared capabilities → plugin bindings, versions" as originally worded above.
- **(d) Quarantine** — an operational state (Unavailable availability rung), never a registry
  mutation and never a version mint (`PRT/00-architectural-foundation.md` §5 errata,
  `PRT/04-health-reliability.md` §7, PRT-H3). The Failure Modes entry above ("triggers quarantine")
  describes an operational-state transition, not a registry write.
- **(e)** `PRT/00-architectural-foundation.md` through `PRT/05-system-integration.md` are the
  authoritative subsystem architecture for Plugin Runtime; this document is the frozen component
  spec they build within and correct where drifted.
