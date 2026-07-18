"use client";
// The Execution Flow board — the OS pipeline as component cards. Wired
// components show live figures from the selected request; unwired ones are
// dimmed with the honest reason. Nothing here is invented.
import type { RequestView } from "@/lib/types";

type FlowState = "done" | "active" | "standin" | "pending" | "idle";

const STATE_ICON: Record<FlowState, { glyph: string; color: string }> = {
  done: { glyph: "✓", color: "text-emerald-400" },
  active: { glyph: "◉", color: "text-sky-400 animate-pulse" },
  standin: { glyph: "▲", color: "text-amber-400" },
  pending: { glyph: "◌", color: "text-zinc-600" },
  idle: { glyph: "○", color: "text-zinc-500" },
};

interface FlowCard {
  index: number;
  name: string;
  sub: string;
  state: FlowState;
}

function buildCards(request?: RequestView): FlowCard[][] {
  const kernelDone = request?.kernel_state === "completed";
  const runDone = request?.run?.status === "completed";
  const units = request?.workflow ? Object.keys(request.workflow.units).length : 0;
  const succeeded = request?.run
    ? Object.values(request.run.unit_state).filter((s) => s === "succeeded").length
    : 0;
  const idle = !request;
  const on = (done: boolean): FlowState => (idle ? "idle" : done ? "done" : "active");
  return [
    [
      { index: 1, name: "EXEC KERNEL", state: on(kernelDone),
        sub: idle ? "awaiting request" : `ledger: ${request!.kernel_state}` },
      { index: 2, name: "REQ STATE MGR", state: "pending", sub: "not wired · C3" },
      { index: 3, name: "UNIFIED MEM", state: "pending", sub: "not wired · C3" },
      { index: 4, name: "CONTEXT MGR", state: "pending", sub: "not wired · C3" },
    ],
    [
      { index: 5, name: "CAP PLANNER", state: on(!!request?.plan),
        sub: request?.plan
          ? `nodes: ${Object.keys(request.plan.nodes).length} · conf ${request.plan.confidence}`
          : "phase 1 foundation" },
      { index: 6, name: "WORKFLOW SCHED", state: on(runDone),
        sub: request?.workflow ? `units: ${units} · ${succeeded} succeeded` : "—" },
      { index: 7, name: "PLUGIN RUNTIME", state: "pending", sub: "binding via demo seam" },
      { index: 8, name: "REASONING", state: "pending", sub: "not wired · C3" },
    ],
    [
      { index: 9, name: "EXEC ENGINE", state: on(runDone),
        sub: request?.run ? `dispatched: ${units}` : "—" },
      { index: 10, name: "VERIFICATION", state: idle ? "idle" : "standin",
        sub: "auto-pass · VAE pending" },
      { index: 11, name: "EXPERIENCE", state: "pending", sub: "not wired · C3" },
      { index: 12, name: "DONE", state: on(kernelDone && runDone),
        sub: kernelDone && runDone ? "request.completed" : "—" },
    ],
  ];
}

export function FlowBoard({ request }: { request?: RequestView }) {
  const rows = buildCards(request);
  return (
    <div className="relative">
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="relative z-10 mb-3 grid grid-cols-4 gap-3">
          {row.map((card) => {
            const icon = STATE_ICON[card.state];
            const dim = card.state === "pending";
            return (
              <div
                key={card.index}
                className={`rounded-lg border px-3 py-2.5 transition-all ${
                  dim
                    ? "border-zinc-700/40 bg-black/20 opacity-45"
                    : "border-sky-400/30 bg-[rgba(13,25,45,.75)] shadow-[0_0_18px_rgba(56,128,255,.10)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="mono flex h-5 w-5 shrink-0 items-center justify-center rounded border border-sky-400/30 text-[9px] text-sky-300">
                    {card.index}
                  </span>
                  <span className="truncate text-[10px] font-semibold tracking-wider text-[var(--text)]">
                    {card.name}
                  </span>
                  <span className={`ml-auto text-xs ${icon.color}`}>{icon.glyph}</span>
                </div>
                <div className="mono mt-1 truncate pl-7 text-[9px] text-[var(--text-dim)]">
                  {card.sub}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <div className="flex gap-5 pt-1 text-[9px] text-[var(--text-dim)]">
        <span><span className="text-emerald-400">✓</span> Completed</span>
        <span><span className="text-sky-400">◉</span> In Progress</span>
        <span><span className="text-amber-400">▲</span> Stand-in (labeled)</span>
        <span><span className="text-zinc-600">◌</span> Not wired</span>
      </div>
    </div>
  );
}
