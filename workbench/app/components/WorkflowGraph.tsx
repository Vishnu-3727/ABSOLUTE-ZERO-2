"use client";
// The one DAG renderer — live view and replay both use it; only the data
// source differs (Workbench charter: no duplicate rendering logic).
import { useMemo } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import type { RunView, WorkflowView } from "@/lib/types";

const STATE_STYLE: Record<string, { border: string; glow: string }> = {
  succeeded: { border: "#34d399", glow: "0 0 14px rgba(52,211,153,.35)" },
  executing: { border: "#38bdf8", glow: "0 0 14px rgba(56,189,248,.45)" },
  failed: { border: "#f87171", glow: "0 0 14px rgba(248,113,113,.4)" },
  pending: { border: "#fbbf24", glow: "none" },
  "not-executed": { border: "#52525b", glow: "none" },
};

export function WorkflowGraph({
  workflow,
  run,
}: {
  workflow: WorkflowView;
  run: RunView | null;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    workflow.levels.forEach((level, levelIndex) => {
      level.forEach((uid, position) => {
        const unit = workflow.units[uid];
        const state = run?.unit_state[uid] ?? "pending";
        const style = STATE_STYLE[state] ?? STATE_STYLE.pending;
        nodes.push({
          id: uid,
          position: { x: position * 240 + levelIndex * 30, y: levelIndex * 130 },
          data: {
            label: (
              <div className="text-left">
                <div className="mono text-[10px] text-sky-300">
                  {unit.capability_id}
                </div>
                <div className="text-[9px] text-zinc-400">
                  {unit.node_id} · {unit.priority_band}
                </div>
                <div className="mono text-[9px] uppercase" style={{ color: style.border }}>
                  {state}
                </div>
              </div>
            ),
          },
          style: {
            background: "rgba(13,25,45,.85)",
            border: `1px solid ${style.border}`,
            borderRadius: 8,
            boxShadow: style.glow,
            color: "#cfe3f7",
            fontSize: 10,
            width: 190,
          },
        });
      });
    });
    const edges: Edge[] = workflow.edges.map(([from, to]) => ({
      id: `${from}-${to}`,
      source: from,
      target: to,
      animated: run?.unit_state[to] === "executing",
      style: { stroke: "rgba(56,128,255,.5)" },
    }));
    return { nodes, edges };
  }, [workflow, run]);

  return (
    <div className="h-full min-h-[360px]">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
        <Background color="rgba(56,128,255,.12)" gap={24} />
        <Controls position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
