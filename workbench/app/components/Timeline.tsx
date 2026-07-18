"use client";
// Execution timeline — the latest run's units in canonical order, straight
// from the workflow artifact + runtime state.
import type { RequestView } from "@/lib/types";

const DOT: Record<string, string> = {
  succeeded: "border-emerald-400 text-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.5)]",
  executing: "border-sky-400 text-sky-400 animate-pulse",
  failed: "border-red-400 text-red-400",
  pending: "border-amber-400/60 text-amber-400",
  "not-executed": "border-zinc-600 text-zinc-600",
};

export function Timeline({ request }: { request?: RequestView }) {
  if (!request?.workflow) {
    return (
      <div className="py-4 text-center text-[10px] text-[var(--text-dim)]">
        No workflow yet — run a request.
      </div>
    );
  }
  const { workflow, run } = request;
  return (
    <div className="flex items-start gap-0 overflow-x-auto py-2">
      {workflow.canonical_order.map((uid, index) => {
        const unit = workflow.units[uid];
        const state = run?.unit_state[uid] ?? "pending";
        return (
          <div key={uid} className="flex items-start">
            {index > 0 && (
              <div className="mt-4 h-px w-8 shrink-0 bg-sky-500/25" />
            )}
            <div className="flex w-24 shrink-0 flex-col items-center text-center">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full border bg-black/40 text-[10px] ${DOT[state] ?? DOT.pending}`}
              >
                {state === "succeeded" ? "✓" : index + 1}
              </div>
              <div className="mono mt-1 w-full truncate text-[8px] text-sky-300">
                {unit.capability_id}
              </div>
              <div className="text-[8px] uppercase text-[var(--text-dim)]">{state}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
