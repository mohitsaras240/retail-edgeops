import React from "react";
import { SyncAggregateStatus } from "../types/api";
import { Database, ArrowUpRight, CheckCheck, RefreshCw } from "lucide-react";

interface SyncStatusCardProps {
  syncStatus: SyncAggregateStatus | null;
}

export const SyncStatusCard: React.FC<SyncStatusCardProps> = ({ syncStatus }) => {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <Database className="h-4 w-4 text-sky-400" />
          <h2 className="text-sm font-semibold text-slate-100 tracking-tight">
            Offline Transaction Resilience & Central Ingest
          </h2>
        </div>
        <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1">
          <CheckCheck className="h-3.5 w-3.5" /> Durable SQLite WAL
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-2 text-xs">
        <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-2.5">
          <div className="text-[11px] text-slate-400 font-medium">Central Ingested Total</div>
          <div className="text-base font-bold text-slate-100 mt-1 font-mono">
            {syncStatus?.central_stats?.total_transactions ?? 0}
          </div>
        </div>

        <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-2.5">
          <div className="text-[11px] text-slate-400 font-medium">Distinct Ingest Stores</div>
          <div className="text-base font-bold text-slate-100 mt-1 font-mono">
            {syncStatus?.central_stats?.distinct_stores ?? 0}
          </div>
        </div>

        {Object.entries(syncStatus?.stores || {}).map(([storeId, pending]) => (
          <div key={storeId} className="bg-slate-950/60 border border-slate-800 rounded-lg p-2.5">
            <div className="text-[11px] text-slate-400 uppercase font-medium">{storeId} Backlog</div>
            <div
              className={`text-base font-bold mt-1 font-mono ${
                pending > 20
                  ? "text-amber-400"
                  : pending > 0
                  ? "text-sky-400"
                  : "text-emerald-400"
              }`}
            >
              {pending} pending
            </div>
          </div>
        ))}
      </div>

      <p className="text-[11px] text-slate-400 mt-2">
        Local PoS transactions are committed durably to store SQLite files before asynchronous background sync to central data warehouse.
      </p>
    </div>
  );
};
