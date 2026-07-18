"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Panel, StatusPill } from "@/components/Panel";
import { useUi } from "@/stores/ui";

export default function PlannerPage() {
  const { data: requests } = useQuery({ queryKey: ["requests"], queryFn: api.requests });
  const selected = useUi((s) => s.selectedRequest);
  const request =
    requests?.find((r) => r.request_id === selected) ?? requests?.at(-1);
  const plan = request?.plan;

  return (
    <div className="grid grid-cols-12 gap-3">
      <Panel title="Capability Plan (CP Phase-1 artifact)" className="col-span-12">
        {plan ? (
          <div className="mono flex flex-wrap gap-x-6 gap-y-1 text-[10px] text-[var(--text-dim)]">
            <span>plan <span className="text-sky-300">{plan.plan_id}</span></span>
            <span>v{plan.version}</span>
            <span>confidence <span className="text-emerald-400">{plan.confidence}</span></span>
            <span>hash <span className="text-sky-300">{plan.hash.slice(0, 20)}…</span></span>
            <span className="text-amber-300/80">
              discovery: {request?.provenance.discovery}
            </span>
          </div>
        ) : (
          <div className="text-xs text-[var(--text-dim)]">No plan yet.</div>
        )}
      </Panel>

      {plan && (
        <>
          <Panel title="Requirement Nodes" className="col-span-7">
            <table className="w-full text-left text-[11px]">
              <thead className="text-[10px] uppercase text-[var(--text-dim)]">
                <tr>
                  <th className="pb-1">Node</th><th className="pb-1">Capability</th>
                  <th className="pb-1">Origin</th><th className="pb-1">Band</th>
                  <th className="pb-1">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(plan.nodes).map(([nid, node]) => (
                  <tr key={nid} className="border-t border-sky-500/10">
                    <td className="mono py-1 text-sky-300">{nid}</td>
                    <td className="mono py-1">{node.capability_id}</td>
                    <td className="py-1">{node.origin}</td>
                    <td className="py-1"><StatusPill state={node.priority_band.toLowerCase()} /></td>
                    <td className="mono py-1 text-emerald-400">{node.confidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Typed Edges" className="col-span-5">
            <div className="mono space-y-1 text-[10px]">
              {plan.edges.map(([kind, from, to], index) => (
                <div key={index} className="text-[var(--text-dim)]">
                  <span className="text-sky-300">{from}</span>
                  {" —"}<span className="text-amber-300">{kind}</span>{"→ "}
                  <span className="text-sky-300">{to}</span>
                </div>
              ))}
              {!plan.edges.length && <div className="text-[var(--text-dim)]">none</div>}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
