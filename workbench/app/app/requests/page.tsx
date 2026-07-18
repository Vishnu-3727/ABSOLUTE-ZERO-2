"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Panel, StatusPill } from "@/components/Panel";
import { useUi } from "@/stores/ui";

export default function RequestsPage() {
  const { data: requests } = useQuery({ queryKey: ["requests"], queryFn: api.requests });
  const selected = useUi((s) => s.selectedRequest);
  const selectRequest = useUi((s) => s.selectRequest);
  const request =
    requests?.find((r) => r.request_id === selected) ?? requests?.at(-1);

  return (
    <div className="grid grid-cols-12 gap-3">
      <Panel title="Requests" className="col-span-4">
        <div className="space-y-1">
          {requests?.map((r) => (
            <button
              key={r.request_id}
              onClick={() => selectRequest(r.request_id)}
              className={`block w-full rounded px-2 py-1.5 text-left text-xs ${
                request?.request_id === r.request_id
                  ? "bg-sky-500/15 text-sky-300"
                  : "hover:bg-sky-500/8"
              }`}
            >
              <span className="mono">{r.request_id}</span> · {r.intent}
            </button>
          ))}
          {!requests?.length && (
            <div className="text-xs text-[var(--text-dim)]">None yet.</div>
          )}
        </div>
      </Panel>

      {request && (
        <>
          <Panel title={`Inspector — ${request.request_id}`} className="col-span-8">
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <div className="panel-title mb-1">Intent</div>
                <div>{request.intent}</div>
                <div className="panel-title mt-3 mb-1">Kernel Lifecycle</div>
                <StatusPill state={request.kernel_state} />
                <div className="panel-title mt-3 mb-1">Goals</div>
                <ul className="mono text-[11px] text-[var(--text-dim)]">
                  {request.goals.map((g) => <li key={g}>· {g}</li>)}
                </ul>
              </div>
              <div>
                <div className="panel-title mb-1">Provenance (honest labels)</div>
                <ul className="space-y-1 text-[10px] text-amber-300/80">
                  {Object.entries(request.provenance).map(([k, v]) => (
                    <li key={k}><span className="uppercase">{k}</span>: {v}</li>
                  ))}
                </ul>
              </div>
            </div>
          </Panel>

          {request.run && (
            <Panel title="Unit States" className="col-span-6">
              <div className="space-y-1">
                {Object.entries(request.run.unit_state).map(([uid, state]) => (
                  <div key={uid} className="flex items-center justify-between text-[11px]">
                    <span className="mono text-[var(--text-dim)]">
                      {request.workflow?.units[uid]?.capability_id ?? uid}
                    </span>
                    <StatusPill state={state} />
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {request.plan && (
            <Panel title="Plan Determinism Tuple" className="col-span-6">
              <div className="mono space-y-1 text-[10px] text-[var(--text-dim)]">
                {Object.entries(request.plan.determinism).map(([k, v]) => (
                  <div key={k}>
                    <span className="text-sky-300">{k}</span> = {String(v)}
                  </div>
                ))}
                <div className="pt-1">
                  <span className="text-sky-300">content_hash</span> = {request.plan.hash}
                </div>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
