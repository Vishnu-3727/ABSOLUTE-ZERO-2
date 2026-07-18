"use client";
// Replay reads the persisted Communication log (the same byte-identical
// sequence the OS replays from) — same rendering as the live feed.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Panel } from "@/components/Panel";

const REPLAYABLE = ["transition.log", "request.admitted", "plan.created",
  "workflow.created", "task.scheduled", "task.started", "task.completed",
  "verify.requested", "verify.passed", "exec.started", "exec.completed",
  "request.completed"];

export default function ReplayPage() {
  const [topic, setTopic] = useState("transition.log");
  const [cursor, setCursor] = useState(0);
  const { data: records } = useQuery({
    queryKey: ["replay", topic],
    queryFn: () => api.replay(topic),
  });
  const visible = (records ?? []).slice(0, cursor || undefined);

  return (
    <div className="flex h-full flex-col gap-3">
      <Panel
        title="Replay — persisted publish sequence"
        right={
          <div className="flex items-center gap-2">
            <select
              value={topic}
              onChange={(e) => { setTopic(e.target.value); setCursor(0); }}
              className="mono rounded border border-sky-500/20 bg-black/40 px-2 py-1 text-[11px]"
            >
              {REPLAYABLE.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input
              type="range"
              min={0}
              max={records?.length ?? 0}
              value={cursor || records?.length || 0}
              onChange={(e) => setCursor(Number(e.target.value))}
            />
            <span className="mono text-[10px] text-[var(--text-dim)]">
              {cursor || records?.length || 0}/{records?.length ?? 0}
            </span>
          </div>
        }
      >
        <div className="text-[10px] text-[var(--text-dim)]">
          Byte-identical persisted sequence from Storage
          (<span className="mono">communication/log/{topic}/…</span>) — the exact
          records the OS itself replays. Scrub to reconstruct any point in time.
        </div>
      </Panel>

      <Panel title={`${topic} — ${visible.length} records`} className="min-h-0 flex-1">
        <div className="mono max-h-full space-y-0.5 overflow-auto text-[10px]">
          {visible.map((record, index) => (
            <details key={index} className="border-b border-sky-500/5 py-0.5">
              <summary className="cursor-pointer truncate text-[var(--text-dim)]">
                <span className="mr-2 text-sky-300">[{index}]</span>
                {JSON.stringify(record).slice(0, 160)}
              </summary>
              <pre className="overflow-auto py-1 pl-8 text-[9px] text-emerald-300/70">
                {JSON.stringify(record, null, 2)}
              </pre>
            </details>
          ))}
          {!visible.length && (
            <div className="py-6 text-center text-[var(--text-dim)]">
              Nothing persisted on this topic yet.
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
