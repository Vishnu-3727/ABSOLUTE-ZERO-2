"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { useUi } from "@/stores/ui";

export default function BusPage() {
  const { data: topics } = useQuery({ queryKey: ["topics"], queryFn: api.topics });
  const liveFeed = useUi((s) => s.liveFeed);
  const [filter, setFilter] = useState("");

  const filtered = liveFeed.filter(
    (e) => !filter || e.topic.includes(filter),
  );

  return (
    <div className="grid h-full grid-cols-12 gap-3">
      <Panel title={`Vocabulary (${topics?.length ?? 0} topics)`} className="col-span-3">
        <div className="max-h-[80vh] space-y-0.5 overflow-auto">
          {topics?.map((topic) => (
            <button
              key={topic}
              onClick={() => setFilter(filter === topic ? "" : topic)}
              className={`mono block w-full rounded px-2 py-1 text-left text-[10px] ${
                filter === topic ? "bg-sky-500/15 text-sky-300" : "text-[var(--text-dim)] hover:bg-sky-500/8"
              }`}
            >
              {topic}
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        title="Live Stream"
        className="col-span-9"
        right={
          <input
            placeholder="filter topic…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="mono rounded border border-sky-500/20 bg-black/40 px-2 py-1 text-[11px] outline-none"
          />
        }
      >
        <div className="mono max-h-[80vh] space-y-0.5 overflow-auto text-[10px]">
          {filtered.slice(-300).reverse().map((event) => (
            <details key={event.seq} className="border-b border-sky-500/5 py-0.5">
              <summary className="flex cursor-pointer gap-3">
                <span className="w-10 shrink-0 text-[var(--text-dim)]">#{event.seq}</span>
                <span className="w-48 shrink-0 text-sky-300">{event.topic}</span>
                <span className="truncate text-[var(--text-dim)]">
                  {String(event.message.event_id ?? "")}
                </span>
              </summary>
              <pre className="overflow-auto py-1 pl-14 text-[9px] text-emerald-300/70">
                {JSON.stringify(event.message, null, 2)}
              </pre>
            </details>
          ))}
          {!filtered.length && (
            <div className="py-6 text-center text-[var(--text-dim)]">
              No events{filter && ` for "${filter}"`} yet.
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
