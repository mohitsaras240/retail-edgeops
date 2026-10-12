import React from "react";
import { StoreViewItem } from "../types/api";
import { Store, AlertCircle, ShieldAlert, Database, CheckCircle2, Clock } from "lucide-react";

interface StoreCardProps {
  store: StoreViewItem;
}

export const StoreCard: React.FC<StoreCardProps> = ({ store }) => {
  const hasEscalated = store.escalated_incidents > 0;
  const hasOpen = store.open_incidents > 0;

  return (
    <div
      className={`rounded-xl border p-4 transition-all ${
        hasEscalated
          ? "bg-rose-950/20 border-rose-800/60 shadow-lg shadow-rose-950/20"
          : hasOpen
          ? "bg-amber-950/20 border-amber-800/60"
          : "bg-slate-900/60 border-slate-800 hover:border-slate-700"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2.5">
          <div
            className={`p-2 rounded-lg ${
              hasEscalated
                ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                : hasOpen
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                : "bg-sky-500/10 text-sky-400 border border-sky-500/20"
            }`}
          >
            <Store className="h-5 w-5" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-100 uppercase tracking-wide text-sm">
              {store.store_id}
            </h3>
            <span className="text-[11px] text-slate-400">
              {store.workloads.length} Managed Workloads
            </span>
          </div>
        </div>

        <div>
          {hasEscalated ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30">
              <ShieldAlert className="h-3 w-3" /> ESCALATED
            </span>
          ) : hasOpen ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
              <AlertCircle className="h-3 w-3" /> ACTIVE INCIDENT
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              <CheckCircle2 className="h-3 w-3" /> HEALTHY
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 my-3 text-center">
        <div className="bg-slate-950/50 rounded-lg p-2 border border-slate-800">
          <div className="text-[10px] text-slate-400 font-medium">PoS Lane</div>
          <div className="text-xs font-semibold mt-0.5 text-slate-200">
            {store.workloads.find((w) => w.kind === "pos")?.running ? (
              <span className="text-emerald-400">Online</span>
            ) : (
              <span className="text-rose-400">Offline</span>
            )}
          </div>
        </div>
        <div className="bg-slate-950/50 rounded-lg p-2 border border-slate-800">
          <div className="text-[10px] text-slate-400 font-medium">Kiosk</div>
          <div className="text-xs font-semibold mt-0.5 text-slate-200">
            {store.workloads.find((w) => w.kind === "kiosk")?.running ? (
              <span className="text-emerald-400">Online</span>
            ) : (
              <span className="text-rose-400">Offline</span>
            )}
          </div>
        </div>
        <div className="bg-slate-950/50 rounded-lg p-2 border border-slate-800">
          <div className="text-[10px] text-slate-400 font-medium">Sync Queue</div>
          <div className="text-xs font-semibold mt-0.5 text-sky-400 flex items-center justify-center gap-1">
            <Database className="h-3 w-3" />
            {store.sync_pending} pending
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-800/80">
        <span>Open Incidents: {store.open_incidents}</span>
        <span className="font-mono text-slate-400">
          Provenance: <span className="text-slate-300">{store.provenance}</span>
        </span>
      </div>
    </div>
  );
};
