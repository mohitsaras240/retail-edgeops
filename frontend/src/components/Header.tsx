import React from "react";
import { SystemHealth } from "../types/api";
import { Activity, ShieldCheck, Terminal, Cpu } from "lucide-react";

interface HeaderProps {
  health: SystemHealth | null;
  lastUpdated: Date;
}

export const Header: React.FC<HeaderProps> = ({ health, lastUpdated }) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-sky-500/10 text-sky-400 p-2 rounded-lg border border-sky-500/20">
            <Terminal className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-lg font-bold text-slate-100 tracking-tight">
                Retail Edge Autopilot
              </h1>
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                Phase 4 Console
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Autonomous Self-Healing EdgeOps for Distributed Retail PoS & Kiosks
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          <div className="hidden md:flex items-center space-x-2 text-xs">
            <span className="text-slate-400">Orchestrator:</span>
            <span className="font-mono text-slate-200 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
              {health?.orchestrator || "connecting..."}
            </span>
          </div>

          <div className="flex items-center space-x-1.5 text-xs text-slate-400">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>Live ({lastUpdated.toLocaleTimeString()})</span>
          </div>
        </div>
      </div>
    </header>
  );
};
