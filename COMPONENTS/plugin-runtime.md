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
- Process outcome events used to inform health (`process.failed`, `process.timeout`).

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
- `process.failed`, `process.timeout` (Execution) — evidence for health.

## Dependencies
- **Lifecycle** — owns plugin state machine; Plugin Runtime enacts registry/load effects of transitions.
- **Learning** — supplies healed reliability priors from closed traces.
- **Execution** — actually runs plugin processes; supplies failure evidence.
- **Storage** — persists registry and reliability scores.
- **Communication / Observability** — transport and universal telemetry consumer.

## Failure Modes
- **Malicious/broken plugin** → isolation contains it; repeated `process.failed`/`process.timeout`
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
