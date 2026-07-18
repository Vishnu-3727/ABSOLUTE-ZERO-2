"use client";
// Mission-control dashboard. Layout mirrors the reference design; every
// figure is real OS data (kernel ledger, bus, vault, artifacts). No
// invented metrics — anything unwired is shown dimmed with its reason.
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { CommandBar } from "@/components/CommandBar";
import { FlowBoard } from "@/components/FlowBoard";
import { Panel, StatusPill } from "@/components/Panel";
import { Timeline } from "@/components/Timeline";
import { TopBar } from "@/components/TopBar";
import { useUi } from "@/stores/ui";

const QUICK_ACTIONS = [
  { label: "Workflows", href: "/workflow", glyph: "⬡" },
  { label: "Requests", href: "/requests", glyph: "▤" },
  { label: "Storage", href: "/storage", glyph: "▣" },
  { label: "Bus", href: "/bus", glyph: "⇄" },
  { label: "Replay", href: "/replay", glyph: "↺" },
];

export default function Dashboard() {
  const { data: system } = useQuery({ queryKey: ["system"], queryFn: api.system });
  const liveFeed = useUi((s) => s.liveFeed);
  const latest = system?.requests.at(-1) ?? undefined;
  const successRate =
    system?.success_rate == null ? "—" : `${(system.success_rate * 100).toFixed(1)}%`;

  return (
    <div className="flex h-full flex-col gap-3">
      <TopBar system={system} latest={latest} />

      <div className="grid min-h-0 flex-1 grid-cols-12 gap-3">
        <Panel
          title="Execution Flow"
          className="col-span-8"
          right={
            <span className="text-[9px] text-[var(--text-dim)]">
              real-time state of the operating system pipeline
            </span>
          }
        >
          <FlowBoard request={latest} />
        </Panel>

        <div className="col-span-4 flex min-h-0 flex-col gap-3">
          <Panel
            title="System Overview"
            right={
              <span className="flex items-center gap-1 text-[9px] text-emerald-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" /> LIVE
              </span>
            }
          >
            <div className="grid grid-cols-3 gap-3">
              <div>
                <div className="text-[9px] uppercase tracking-wider text-[var(--text-dim)]">Requests</div>
                <div className="mono glow text-2xl text-sky-300">
                  {system?.requests.length ?? 0}
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase tracking-wider text-[var(--text-dim)]">Success Rate</div>
                <div className="mono glow text-2xl text-emerald-400">{successRate}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase tracking-wider text-[var(--text-dim)]">Bus Topics</div>
                <div className="mono glow text-2xl text-sky-300">
                  {system?.components.communication.topics ?? "—"}
                </div>
              </div>
            </div>
            <div className="mono mt-3 truncate text-[9px] text-[var(--text-dim)]">
              vault {system?.components.storage.vault ?? "—"}
            </div>
            <div className="mt-2 border-t border-sky-500/10 pt-2 text-[9px] text-[var(--text-dim)]">
              NOT YET WIRED: {system?.unwired.join(" · ") ?? "—"}
            </div>
          </Panel>

          <Panel title="Recent Activity" className="min-h-0 flex-1">
            <div className="mono max-h-full space-y-1 overflow-auto text-[9px]">
              {liveFeed.slice(-14).reverse().map((event) => (
                <div key={event.seq} className="flex gap-2 border-b border-sky-500/5 pb-1">
                  <span className="shrink-0 text-[var(--text-dim)]">
                    {event.observed_at
                      ? new Date(event.observed_at * 1000).toLocaleTimeString()
                      : `#${event.seq}`}
                  </span>
                  <span className="truncate text-sky-300">{event.topic}</span>
                </div>
              ))}
              {!liveFeed.length && (
                <div className="py-4 text-center text-[var(--text-dim)]">
                  Waiting for events…
                </div>
              )}
            </div>
          </Panel>
        </div>

        <Panel
          title="Execution Timeline"
          className="col-span-8"
          right={latest?.run && <StatusPill state={latest.run.status} />}
        >
          <Timeline request={latest} />
        </Panel>

        <Panel title="Quick Actions" className="col-span-4">
          <div className="grid grid-cols-5 gap-2">
            {QUICK_ACTIONS.map((action) => (
              <Link
                key={action.label}
                href={action.href}
                className="flex flex-col items-center gap-1 rounded border border-sky-500/20 bg-sky-500/5 py-3 text-sky-300 transition-colors hover:bg-sky-500/15"
              >
                <span className="text-lg">{action.glyph}</span>
                <span className="text-[8px] uppercase tracking-wider">{action.label}</span>
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      <CommandBar />
    </div>
  );
}
