import React from "react";
import { AuditEntry } from "../types/api";
import { History, Shield, Play, CheckCircle } from "lucide-react";

interface AuditTimelineProps {
  entries: AuditEntry[];
}

export const AuditTimeline: React.FC<AuditTimelineProps> = ({ entries }) => {
  const recent = entries.slice(-10).reverse();

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <History className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-100 tracking-tight">
            Immutable Audit Trail & Autopilot Actions
          </h2>
        </div>
        <span className="text-xs text-slate-400 font-mono">
          {entries.length} Audit Events Logged
        </span>
      </div>

      <div className="p-4 space-y-3 max-h-72 overflow-y-auto text-xs">
        {recent.length === 0 ? (
          <div className="text-center py-6 text-slate-500 italic">
            No audit records logged yet.
          </div>
        ) : (
          recent.map((entry, idx) => (
            <div
              key={idx}
              className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80 flex items-start justify-between gap-3"
            >
              <div className="space-y-1">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-[11px] text-sky-400 font-bold uppercase">
                    [{entry.event}]
                  </span>
                  <span className="text-[11px] text-slate-400 font-mono">
                    {new Date(entry.ts * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <div className="text-slate-300 text-[11px]">
                  {entry.action && (
                    <span>
                      Action:{" "}
                      <strong className="text-slate-100 font-mono">
                        {entry.action}
                      </strong>{" "}
                      ({entry.status})
                    </span>
                  )}
                  {entry.kind && (
                    <span>
                      Detected: <strong className="text-slate-100">{entry.kind}</strong>
                    </span>
                  )}
                  {entry.actor && (
                    <span>
                      Approved by: <strong className="text-slate-100">{entry.actor}</strong>
                    </span>
                  )}
                  {entry.reason && (
                    <span className="text-slate-400"> • {entry.reason}</span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
