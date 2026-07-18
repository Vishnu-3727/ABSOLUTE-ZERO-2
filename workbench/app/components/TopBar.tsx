"use client";
// Mission-control status strip. Every figure is real: latest request from
// the kernel ledger, event count from the bus, uptime from the gateway.
import { useEffect, useState } from "react";
import type { RequestView, SystemOverview } from "@/lib/types";
import { useUi } from "@/stores/ui";

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-l border-sky-500/15 px-5">
      <div className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)]">
        {label}
      </div>
      <div className="mono mt-0.5 text-xs text-[var(--text)]">{children}</div>
    </div>
  );
}

export function TopBar({
  system,
  latest,
}: {
  system?: SystemOverview;
  latest?: RequestView;
}) {
  const connected = useUi((s) => s.wsConnected);
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const uptime = system
    ? `${Math.floor(system.uptime_seconds / 3600)}h ${Math.floor((system.uptime_seconds % 3600) / 60)}m ${system.uptime_seconds % 60}s`
    : "—";

  return (
    <header className="panel flex items-center px-5 py-3">
      <div className="flex items-center gap-3 pr-4">
        <div className="glow flex h-8 w-8 items-center justify-center rounded border border-sky-400/40 text-sm font-black text-sky-300">
          AZ
        </div>
        <div>
          <div className="glow text-sm font-bold tracking-[0.22em] text-sky-200">
            ABSOLUTE-ZERO
          </div>
          <div className="text-[8px] tracking-[0.3em] text-[var(--text-dim)]">
            AGENTIC OPERATING SYSTEM
          </div>
        </div>
      </div>
      <Cell label="Request ID">
        <span className="text-sky-300">{latest?.request_id ?? "—"}</span>
      </Cell>
      <Cell label="Status">
        <span className={latest?.kernel_state === "completed" ? "text-emerald-400" : "text-sky-400"}>
          ● {(latest?.kernel_state ?? "idle").toUpperCase()}
        </span>
      </Cell>
      <Cell label="Mode">DETERMINISTIC</Cell>
      <Cell label="Events Observed">
        <span className="text-sky-300">{system?.event_count ?? 0}</span>
      </Cell>
      <Cell label="Uptime">{uptime}</Cell>
      <div className="ml-auto flex items-center gap-4">
        <div className="mono text-right">
          <div className="glow text-sm text-sky-200">{now}</div>
          <div className="text-[9px] text-[var(--text-dim)]">gateway clock</div>
        </div>
        <span
          className={`h-2.5 w-2.5 rounded-full ${connected ? "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.8)]" : "bg-red-400"}`}
          title={connected ? "event stream live" : "gateway offline"}
        />
      </div>
    </header>
  );
}
