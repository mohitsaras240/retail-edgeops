import React from "react";
import { WorkloadViewItem } from "../types/api";
import { Server, Activity, AlertTriangle, CheckCircle, PauseCircle } from "lucide-react";

interface WorkloadTableProps {
  workloads: WorkloadViewItem[];
  onSelectWorkload?: (workloadId: string) => void;
}

export const WorkloadTable: React.FC<WorkloadTableProps> = ({ workloads }) => {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Server className="h-4 w-4 text-sky-400" />
          <h2 className="text-sm font-semibold text-slate-100 tracking-tight">
            Workload Inventory & Real-Time Telemetry
          </h2>
        </div>
        <span className="text-xs text-slate-400">
          {workloads.length} Managed Workloads
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-800 text-left text-xs">
          <thead className="bg-slate-950/60 text-slate-400 font-medium">
            <tr>
              <th className="px-4 py-3">Workload ID</th>
              <th className="px-4 py-3">Store</th>
              <th className="px-4 py-3">Kind / Role</th>
              <th className="px-4 py-3">Criticality</th>
              <th className="px-4 py-3">Container State</th>
              <th className="px-4 py-3">Health Probe</th>
              <th className="px-4 py-3">CPU / Mem</th>
              <th className="px-4 py-3">Restarts</th>
              <th className="px-4 py-3">Provenance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-slate-200">
            {workloads.map((w) => {
              const isRunning = w.status?.running ?? false;
              const isHealthy = w.health_probe?.ok ?? false;
              const hasIncident = !!w.suppressed_by_escalated_incident;

              return (
                <tr key={w.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 font-mono font-medium text-slate-100">
                    {w.id}
                  </td>
                  <td className="px-4 py-3 uppercase text-slate-400 font-mono text-[11px]">
                    {w.store_id}
                  </td>
                  <td className="px-4 py-3">
                    <span className="capitalize px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium border border-slate-700">
                      {w.kind}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full ${
                        w.criticality === "critical"
                          ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                          : w.criticality === "important"
                          ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                          : "bg-slate-800 text-slate-400 border border-slate-700"
                      }`}
                    >
                      {w.criticality}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {isRunning ? (
                      <span className="inline-flex items-center gap-1.5 text-emerald-400">
                        <CheckCircle className="h-3.5 w-3.5" /> Running
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-rose-400 font-semibold">
                        <AlertTriangle className="h-3.5 w-3.5" /> Exited
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isHealthy ? (
                      <span className="text-emerald-400 font-mono">
                        200 OK ({w.health_probe?.latency_ms?.toFixed(1) || 0}ms)
                      </span>
                    ) : (
                      <span className="text-rose-400 font-mono">
                        {w.health_probe?.status_code
                          ? `${w.health_probe.status_code} FAIL`
                          : "Unreachable"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-300">
                    {w.status?.cpu_pct !== null && w.status?.cpu_pct !== undefined ? (
                      <span>
                        {w.status.cpu_pct.toFixed(1)}% /{" "}
                        {w.status.mem_pct?.toFixed(1) || 0}%
                      </span>
                    ) : (
                      <span className="text-slate-500">n/a</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px]">
                    <span
                      className={
                        (w.status?.restart_count || 0) > 0
                          ? "text-amber-400 font-semibold"
                          : "text-slate-400"
                      }
                    >
                      {w.status?.restart_count || 0}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${
                        w.provenance === "real"
                          ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                          : "bg-slate-800 text-slate-400 border border-slate-700"
                      }`}
                    >
                      {w.provenance}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
