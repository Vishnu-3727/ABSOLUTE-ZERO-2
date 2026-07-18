"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Panel } from "@/components/Panel";

export default function StoragePage() {
  const { data: namespaces } = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const { data: blob } = useQuery({
    queryKey: ["storage-read", selectedKey],
    queryFn: () => api.storageRead(selectedKey!),
    enabled: !!selectedKey,
  });

  return (
    <div className="grid h-full grid-cols-12 gap-3">
      <Panel title="Namespace Explorer (owner-scoped, ERRATA C7)" className="col-span-5">
        <div className="max-h-[80vh] overflow-auto">
          {namespaces &&
            Object.entries(namespaces).map(([namespace, keys]) => (
              <details key={namespace} open className="mb-2">
                <summary className="panel-title cursor-pointer">
                  {namespace}/ · {keys.length} keys
                </summary>
                <div className="mt-1 space-y-0.5 pl-2">
                  {keys.map((key) => (
                    <button
                      key={key}
                      onClick={() => setSelectedKey(key)}
                      className={`mono block w-full truncate rounded px-1.5 py-0.5 text-left text-[10px] ${
                        selectedKey === key
                          ? "bg-sky-500/15 text-sky-300"
                          : "text-[var(--text-dim)] hover:bg-sky-500/8"
                      }`}
                    >
                      {key}
                    </button>
                  ))}
                </div>
              </details>
            ))}
        </div>
      </Panel>

      <Panel title="Blob Inspector (sha256-verified read)" className="col-span-7">
        {blob ? (
          <>
            <div className="mono mb-2 text-[10px] text-[var(--text-dim)]">
              {blob.key} · {blob.bytes} bytes · checksum verified by Storage on read
            </div>
            <pre className="max-h-[75vh] overflow-auto rounded bg-black/40 p-3 text-[10px] text-emerald-300/80">
              {blob.preview}
            </pre>
          </>
        ) : (
          <div className="text-xs text-[var(--text-dim)]">Select a key.</div>
        )}
      </Panel>
    </div>
  );
}
