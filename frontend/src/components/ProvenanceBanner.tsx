import React from "react";
import { Provenance } from "../types/api";
import { Info, AlertTriangle } from "lucide-react";

interface ProvenanceBannerProps {
  provenance: Provenance;
  approvalMode: string;
  dryRun: boolean;
}

export const ProvenanceBanner: React.FC<ProvenanceBannerProps> = ({
  provenance,
  approvalMode,
  dryRun,
}) => {
  const isReal = provenance === "real";

  return (
    <div
      className={`border-b text-xs py-2 px-4 ${
        isReal
          ? "bg-emerald-950/40 border-emerald-800/60 text-emerald-300"
          : "bg-amber-950/40 border-amber-800/60 text-amber-300"
      }`}
    >
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          {isReal ? (
            <Info className="h-4 w-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
          )}
          <span>
            <strong className="uppercase tracking-wide font-semibold">
              {isReal ? "Real Execution" : "Simulation Adapter"} Mode:
            </strong>{" "}
            {isReal
              ? "Docker containers, live probes, and process metrics are executing on this edge host."
              : "In-memory simulation adapter active for offline development and deterministic unit testing."}
          </span>
        </div>

        <div className="flex items-center space-x-3 text-[11px] font-mono">
          <span className="bg-slate-900/60 px-2 py-0.5 rounded border border-slate-700/60">
            Approval: <strong className="text-slate-100">{approvalMode}</strong>
          </span>
          <span
            className={`px-2 py-0.5 rounded border ${
              dryRun
                ? "bg-rose-950 border-rose-800 text-rose-300"
                : "bg-emerald-950 border-emerald-800 text-emerald-300"
            }`}
          >
            Dry Run: {dryRun ? "ENABLED" : "DISABLED"}
          </span>
        </div>
      </div>
    </div>
  );
};
