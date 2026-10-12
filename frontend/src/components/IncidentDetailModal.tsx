import React from "react";
import { IncidentItem } from "../types/api";
import {
  X,
  ShieldCheck,
  AlertTriangle,
  Clock,
  Layers,
  Activity,
  CheckCircle2,
  HelpCircle,
} from "lucide-react";

interface IncidentDetailModalProps {
  incident: IncidentItem;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({
  incident,
  onClose,
  onApprove,
  onReject,
}) => {
  const isAwaitingApproval = incident.state === "AWAITING_APPROVAL";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-3xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xs font-mono font-bold text-sky-400 bg-sky-950 px-2 py-0.5 rounded border border-sky-800">
                {incident.id}
              </span>
              <h2 className="text-base font-bold text-slate-100">
                Incident Root-Cause Diagnosis & Audit Record
              </h2>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Workload: <strong className="text-slate-200 font-mono">{incident.workload_id}</strong> (Store: {incident.store_id})
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto space-y-6 text-xs">
          {/* Status & Recovery State Machine Banner */}
          <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] text-slate-400 font-medium">Lifecycle State</div>
              <div className="text-sm font-bold text-sky-400 mt-0.5">
                {incident.state}
              </div>
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">Severity</div>
              <div className="text-sm font-bold text-amber-400 mt-0.5 uppercase">
                {incident.severity}
              </div>
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">Recovery Attempts</div>
              <div className="text-sm font-bold text-slate-200 mt-0.5">
                {incident.attempts}
              </div>
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">Provenance</div>
              <div className="text-sm font-mono text-emerald-400 mt-0.5 uppercase">
                {incident.provenance}
              </div>
            </div>
          </div>

          {/* Operator Action Controls (if approval pending) */}
          {isAwaitingApproval && (
            <div className="bg-amber-950/30 border border-amber-800/80 rounded-xl p-4">
              <div className="flex items-center space-x-2 text-amber-300 font-semibold mb-2">
                <AlertTriangle className="h-4 w-4" />
                <span>Operator Approval Required for Recovery Action</span>
              </div>
              <p className="text-slate-300 text-xs mb-3">
                {incident.decision?.reason || "Autonomous recovery action requires confirmation before execution."}
              </p>
              <div className="flex items-center space-x-3">
                <button
                  onClick={() => {
                    onApprove(incident.id);
                    onClose();
                  }}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium text-xs transition-colors"
                >
                  Approve Recovery Action
                </button>
                <button
                  onClick={() => {
                    onReject(incident.id);
                    onClose();
                  }}
                  className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg font-medium text-xs transition-colors"
                >
                  Reject & Escalate
                </button>
              </div>
            </div>
          )}

          {/* Ranked Root-Cause Diagnosis */}
          <div>
            <h3 className="font-semibold text-slate-200 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <Layers className="h-4 w-4 text-sky-400" /> Ranked Root-Cause Hypotheses & Evidence Weights
            </h3>

            {incident.diagnosis?.ranked_causes?.length ? (
              <div className="space-y-3">
                {incident.diagnosis.ranked_causes.map((c, i) => (
                  <div
                    key={c.cause}
                    className={`rounded-xl border p-3.5 ${
                      i === 0
                        ? "bg-slate-950/80 border-sky-800/60 shadow-md shadow-sky-950/20"
                        : "bg-slate-950/40 border-slate-800"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-2">
                        <span className="font-semibold text-slate-100 font-mono text-sm">
                          {i + 1}. {c.cause}
                        </span>
                        <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                          {c.confidence} Confidence
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-sm font-bold text-sky-400">
                          {c.score}% Match
                        </span>
                      </div>
                    </div>

                    <div className="mt-2 space-y-1">
                      <div className="text-[11px] text-slate-400 font-medium">Supporting Evidence:</div>
                      <ul className="list-disc list-inside space-y-0.5 text-slate-300 text-[11px]">
                        {c.evidence.map((ev, idx) => (
                          <li key={idx}>{ev}</li>
                        ))}
                      </ul>
                    </div>

                    {c.next_steps?.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-800/80">
                        <div className="text-[11px] text-slate-400 font-medium">Prescribed Action:</div>
                        <ul className="list-disc list-inside space-y-0.5 text-slate-300 text-[11px]">
                          {c.next_steps.map((step, idx) => (
                            <li key={idx}>{step}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-slate-400 py-3 italic">
                Diagnosis data pending evidence aggregation...
              </div>
            )}

            <p className="text-[11px] text-slate-500 mt-2 italic flex items-center gap-1">
              <HelpCircle className="h-3 w-3" />
              {incident.diagnosis?.note ||
                "Scores are explainable heuristic weights (0-100), not learned probabilities."}
            </p>
          </div>

          {/* Policy Decision & Rationale */}
          {incident.decision && (
            <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4">
              <h3 className="font-semibold text-slate-200 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4 text-emerald-400" /> Recovery Policy Decision
              </h3>
              <div className="space-y-1.5 text-slate-300">
                <div>
                  <strong>Action:</strong>{" "}
                  <span className="font-mono text-sky-400 font-semibold bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                    {incident.decision.action}
                  </span>
                </div>
                <div>
                  <strong>Risk Level:</strong> {incident.decision.risk_level} •{" "}
                  <strong>Disruption:</strong> {incident.decision.estimated_disruption}
                </div>
                <div>
                  <strong>Decision Reason:</strong> {incident.decision.reason}
                </div>
                <div className="pt-1">
                  <div className="text-slate-400 font-medium text-[11px]">Policy Rationale:</div>
                  <ul className="list-disc list-inside text-slate-300 text-[11px]">
                    {incident.decision.rationale?.map((r, idx) => (
                      <li key={idx}>{r}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* Chronological Incident Timeline */}
          <div>
            <h3 className="font-semibold text-slate-200 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-slate-400" /> Closed-Loop Execution Timeline
            </h3>
            <div className="border-l-2 border-slate-800 ml-2 pl-4 space-y-3">
              {incident.timeline?.map((t, idx) => (
                <div key={idx} className="relative">
                  <div className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-sky-500"></div>
                  <div className="flex items-center space-x-2 text-[11px]">
                    <span className="font-mono text-slate-400">
                      {new Date(t.ts * 1000).toLocaleTimeString()}
                    </span>
                    <span className="font-bold text-slate-200 uppercase">
                      [{t.event}]
                    </span>
                    <span className="text-sky-400 font-mono">({t.state})</span>
                  </div>
                  <p className="text-slate-300 text-[11px] mt-0.5">{t.note}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
