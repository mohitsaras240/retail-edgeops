import React from "react";
import { IncidentItem } from "../types/api";
import { AlertCircle, ShieldAlert, CheckCircle2, ChevronRight, RefreshCw, Eye } from "lucide-react";

interface IncidentListProps {
  incidents: IncidentItem[];
  onSelectIncident: (incident: IncidentItem) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export const IncidentList: React.FC<IncidentListProps> = ({
  incidents,
  onSelectIncident,
  onApprove,
  onReject,
}) => {
  const openIncidents = incidents.filter(
    (i) => i.state !== "RESOLVED" && i.state !== "ESCALATED"
  );
  const resolvedOrEscalated = incidents.filter(
    (i) => i.state === "RESOLVED" || i.state === "ESCALATED"
  );

  const getSeverityBadge = (sev: string) => {
    switch (sev.toLowerCase()) {
      case "critical":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      case "high":
        return "bg-orange-500/10 text-orange-400 border-orange-500/20";
      case "medium":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      default:
        return "bg-slate-500/10 text-slate-400 border-slate-500/20";
    }
  };

  const getStateBadge = (state: string) => {
    switch (state) {
      case "RESOLVED":
        return "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
      case "ESCALATED":
        return "bg-rose-500/20 text-rose-300 border-rose-500/30";
      case "AWAITING_APPROVAL":
        return "bg-amber-500/20 text-amber-300 border-amber-500/30 animate-pulse";
      case "RECOVERING":
      case "VERIFYING":
        return "bg-sky-500/20 text-sky-300 border-sky-500/30";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <AlertCircle className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-slate-100 tracking-tight">
            Incident Management & Lifecycle State Machine
          </h2>
        </div>
        <div className="flex items-center space-x-2 text-xs">
          <span className="text-amber-400 font-semibold">{openIncidents.length} Active</span>
          <span className="text-slate-500">|</span>
          <span className="text-slate-400">{incidents.length} Total</span>
        </div>
      </div>

      <div className="divide-y divide-slate-800/60">
        {incidents.length === 0 ? (
          <div className="py-8 text-center text-slate-400 text-xs">
            <CheckCircle2 className="h-8 w-8 text-emerald-400 mx-auto mb-2 opacity-80" />
            No active incidents detected. All retail workloads are operating within health thresholds.
          </div>
        ) : (
          incidents.map((inc) => {
            const isApprovalPending = inc.state === "AWAITING_APPROVAL";

            return (
              <div
                key={inc.id}
                className="p-4 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row items-start md:items-center justify-between gap-3 text-xs"
              >
                <div className="flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-bold text-slate-200">
                      {inc.id}
                    </span>
                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${getSeverityBadge(
                        inc.severity
                      )}`}
                    >
                      {inc.severity}
                    </span>
                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${getStateBadge(
                        inc.state
                      )}`}
                    >
                      {inc.state}
                    </span>
                    <span className="font-mono text-slate-400 text-[11px]">
                      {inc.workload_id} ({inc.store_id})
                    </span>
                  </div>

                  <div className="text-slate-300">
                    <strong className="text-slate-100 font-medium">Issue:</strong>{" "}
                    {inc.kind.replace(/_/g, " ")}
                    {inc.diagnosis?.ranked_causes?.[0] && (
                      <span className="text-slate-400 ml-2">
                        • Top Diagnosis:{" "}
                        <strong className="text-sky-400">
                          {inc.diagnosis.ranked_causes[0].cause} (
                          {inc.diagnosis.ranked_causes[0].score}% match)
                        </strong>
                      </span>
                    )}
                  </div>

                  {inc.decision && (
                    <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
                      <span className="text-slate-500">Proposed Action:</span>
                      <span className="font-mono text-slate-200 font-semibold bg-slate-800 px-1.5 py-0.5 rounded border border-slate-700">
                        {inc.decision.action}
                      </span>
                      <span>• Risk: <strong className="text-slate-300">{inc.decision.risk_level}</strong></span>
                      <span>• Disruption: {inc.decision.estimated_disruption}</span>
                    </div>
                  )}
                </div>

                <div className="flex items-center space-x-2 self-end md:self-center shrink-0">
                  {isApprovalPending && (
                    <div className="flex items-center space-x-2 mr-2">
                      <button
                        onClick={() => onApprove(inc.id)}
                        className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium text-xs shadow-sm transition-colors"
                      >
                        Approve Recovery
                      </button>
                      <button
                        onClick={() => onReject(inc.id)}
                        className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded font-medium text-xs shadow-sm transition-colors"
                      >
                        Reject
                      </button>
                    </div>
                  )}

                  <button
                    onClick={() => onSelectIncident(inc)}
                    className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 font-medium text-xs transition-colors"
                  >
                    <Eye className="h-3.5 w-3.5" /> Inspect Evidence
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
