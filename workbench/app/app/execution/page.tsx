"use client";
// Execution journal straight from Storage: execution/ namespace records.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { useUi } from "@/stores/ui";

export default function ExecutionPage() {
  const { data: namespaces } = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const liveFeed = useUi((s) => s.liveFeed);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const { data: blob } = useQuery({
    queryKey: ["storage-read", selectedKey],
    queryFn: () => api.storageRead(selectedKey!),
    enabled: !!selectedKey,
  });
  const execEvents = liveFeed.filter((e) => e.topic.startsWith("exec."));

  return (
    <div className="grid grid-cols-12 gap-3">
      <Panel title="Execution Journal (append-only, Storage-owned)" className="col-span-5">
        <div className="max-h-[45vh] space-y-0.5 overflow-auto">
          {namespaces?.execution?.map((key) => (
            <button
              key={key}
              onClick={() => setSelectedKey(key)}
              className={`mono block w-full truncate rounded px-1.5 py-0.5 text-left text-[10px] ${
                selectedKey === key ? "bg-sky-500/15 text-sky-300"
                  : "text-[var(--text-dim)] hover:bg-sky-500/8"
              }`}
            >
              {key}
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Record" className="col-span-7">
        {blob ? (
          <pre className="max-h-[45vh] overflow-auto rounded bg-black/40 p-3 text-[10px] text-emerald-300/80">
            {blob.preview}
          </pre>
        ) : (
          <div className="text-xs text-[var(--text-dim)]">Select a journal entry.</div>
        )}
      </Panel>

      <Panel title="Live exec.* Events" className="col-span-12">
        <div className="mono max-h-[30vh] space-y-0.5 overflow-auto text-[10px]">
          {execEvents.slice(-100).reverse().map((event) => (
            <div key={event.seq} className="flex gap-3 border-b border-sky-500/5 py-0.5">
              <span className="w-32 shrink-0 text-sky-300">{event.topic}</span>
              <span className="truncate text-[var(--text-dim)]">
                {JSON.stringify(event.message.payload)}
              </span>
            </div>
          ))}
          {!execEvents.length && (
            <div className="py-4 text-center text-[var(--text-dim)]">No executions yet.</div>
          )}
        </div>
      </Panel>
    </div>
  );
}
