import React, { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { ProvenanceBanner } from "./components/ProvenanceBanner";
import { StoreCard } from "./components/StoreCard";
import { WorkloadTable } from "./components/WorkloadTable";
import { IncidentList } from "./components/IncidentList";
import { IncidentDetailModal } from "./components/IncidentDetailModal";
import { SyncStatusCard } from "./components/SyncStatusCard";
import { AuditTimeline } from "./components/AuditTimeline";
import { api } from "./services/api";
import {
  AuditEntry,
  IncidentItem,
  StoreViewItem,
  SyncAggregateStatus,
  SystemHealth,
  WorkloadViewItem,
} from "./types/api";

export function App() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [stores, setStores] = useState<StoreViewItem[]>([]);
  const [workloads, setWorkloads] = useState<WorkloadViewItem[]>([]);
  const [incidents, setIncidents] = useState<IncidentItem[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncAggregateStatus | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<IncidentItem | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const [h, s, w, inc, sync, aud] = await Promise.all([
        api.getHealth(),
        api.getStores(),
        api.getWorkloads(),
        api.getIncidents(),
        api.getSyncStatus(),
        api.getAudit(),
      ]);

      setHealth(h);
      setStores(s);
      setWorkloads(w);
      setIncidents(inc);
      setSyncStatus(sync);
      setAudit(aud);
      setLastUpdated(new Date());
      setError(null);
    } catch (err: any) {
      console.error("Dashboard refresh error:", err);
      setError(err.message || "Failed to connect to Autopilot backend");
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2500); // 2.5s live polling
    return () => clearInterval(interval);
  }, []);

  const handleApprove = async (id: string) => {
    try {
      await api.approveIncident(id, "operator-web");
      await fetchData();
    } catch (err: any) {
      alert(`Approval error: ${err.message}`);
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.rejectIncident(id, "operator-web", "Operator declined recovery action");
      await fetchData();
    } catch (err: any) {
      alert(`Rejection error: ${err.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header health={health} lastUpdated={lastUpdated} />

      {health && (
        <ProvenanceBanner
          provenance={health.provenance}
          approvalMode={health.approval_mode}
          dryRun={health.dry_run}
        />
      )}

      {error && (
        <div className="bg-rose-950/80 border-b border-rose-800 text-rose-300 text-xs px-4 py-2 text-center">
          Connection Notice: {error} (Ensure backend is running on http://127.0.0.1:8000)
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Stores Overview Grid */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
              Distributed Edge Stores ({stores.length})
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {stores.map((store) => (
              <StoreCard key={store.store_id} store={store} />
            ))}
          </div>
        </section>

        {/* Offline Sync Status */}
        <section>
          <SyncStatusCard syncStatus={syncStatus} />
        </section>

        {/* Incidents Management & Operator Controls */}
        <section>
          <IncidentList
            incidents={incidents}
            onSelectIncident={(inc) => setSelectedIncident(inc)}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        </section>

        {/* Workload Inventory & Telemetry Table */}
        <section>
          <WorkloadTable workloads={workloads} />
        </section>

        {/* Audit Trail */}
        <section>
          <AuditTimeline entries={audit} />
        </section>
      </main>

      {/* Incident Detail Modal */}
      {selectedIncident && (
        <IncidentDetailModal
          incident={selectedIncident}
          onClose={() => setSelectedIncident(null)}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      <footer className="border-t border-slate-900 bg-slate-950 py-4 text-center text-xs text-slate-500">
        Retail Edge Autopilot • Self-Healing EdgeOps Platform • Real & Simulated Provenance Transparently Tagged
      </footer>
    </div>
  );
}

export default App;
