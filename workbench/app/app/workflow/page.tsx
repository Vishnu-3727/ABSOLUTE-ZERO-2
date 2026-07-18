"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Panel, StatusPill } from "@/components/Panel";
import { WorkflowGraph } from "@/components/WorkflowGraph";
import { useUi } from "@/stores/ui";

export default function WorkflowPage() {
  const { data: requests } = useQuery({ queryKey: ["requests"], queryFn: api.requests });
  const selected = useUi((s) => s.selectedRequest);
  const selectRequest = useUi((s) => s.selectRequest);
  const request =
    requests?.find((r) => r.request_id === selected) ?? requests?.at(-1);

  return (
    <div className="flex h-full flex-col gap-3">
      <Panel title="Execution Workflow" right={
        <select
          value={request?.request_id ?? ""}
          onChange={(e) => selectRequest(e.target.value)}
          className="mono rounded border border-sky-500/20 bg-black/40 px-2 py-1 text-[11px]"
        >
          {requests?.map((r) => (
            <option key={r.request_id} value={r.request_id}>
              {r.request_id} — {r.intent}
            </option>
          ))}
        </select>
      }>
        {request?.workflow ? (
          <div className="mono flex flex-wrap gap-x-6 gap-y-1 text-[10px] text-[var(--text-dim)]">
            <span>id <span className="text-sky-300">{request.workflow.workflow_id}</span></span>
            <span>hash <span className="text-sky-300">{request.workflow.hash.slice(0, 16)}…</span></span>
            <span>units {Object.keys(request.workflow.units).length}</span>
            <span>levels {request.workflow.levels.length}</span>
            {request.run && <StatusPill state={request.run.status} />}
          </div>
        ) : (
          <div className="text-xs text-[var(--text-dim)]">No workflow yet.</div>
        )}
      </Panel>
      {request?.workflow && (
        <Panel title="Dependency DAG (canonical levels)" className="min-h-0 flex-1">
          <WorkflowGraph workflow={request.workflow} run={request.run} />
        </Panel>
      )}
    </div>
  );
}
