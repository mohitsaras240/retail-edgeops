import {
  AuditEntry,
  IncidentItem,
  StoreViewItem,
  SyncAggregateStatus,
  SystemHealth,
  WorkloadViewItem,
} from "../types/api";

const API_BASE = "http://127.0.0.1:8000";
const API_KEY = "k".repeat(20); // Default local development API key

const headers = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
};

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`API Error ${res.status}: ${errorText}`);
  }
  return res.json();
}

export const api = {
  async getHealth(): Promise<SystemHealth> {
    const res = await fetch(`${API_BASE}/api/health`);
    return handleResponse<SystemHealth>(res);
  },

  async getStores(): Promise<StoreViewItem[]> {
    const res = await fetch(`${API_BASE}/api/stores`, { headers });
    return handleResponse<StoreViewItem[]>(res);
  },

  async getWorkloads(): Promise<WorkloadViewItem[]> {
    const res = await fetch(`${API_BASE}/api/workloads`, { headers });
    return handleResponse<WorkloadViewItem[]>(res);
  },

  async getIncidents(): Promise<IncidentItem[]> {
    const res = await fetch(`${API_BASE}/api/incidents`, { headers });
    return handleResponse<IncidentItem[]>(res);
  },

  async getIncident(id: string): Promise<IncidentItem> {
    const res = await fetch(`${API_BASE}/api/incidents/${id}`, { headers });
    return handleResponse<IncidentItem>(res);
  },

  async approveIncident(id: string, actor: string = "operator-console"): Promise<IncidentItem> {
    const res = await fetch(`${API_BASE}/api/incidents/${id}/approve`, {
      method: "POST",
      headers,
      body: JSON.stringify({ actor, reason: "Operator approved via dashboard" }),
    });
    return handleResponse<IncidentItem>(res);
  },

  async rejectIncident(id: string, actor: string = "operator-console", reason: string = "Operator rejected"): Promise<IncidentItem> {
    const res = await fetch(`${API_BASE}/api/incidents/${id}/reject`, {
      method: "POST",
      headers,
      body: JSON.stringify({ actor, reason }),
    });
    return handleResponse<IncidentItem>(res);
  },

  async getSyncStatus(): Promise<SyncAggregateStatus> {
    const res = await fetch(`${API_BASE}/api/sync/status`, { headers });
    return handleResponse<SyncAggregateStatus>(res);
  },

  async getAudit(): Promise<AuditEntry[]> {
    const res = await fetch(`${API_BASE}/api/audit`, { headers });
    return handleResponse<AuditEntry[]>(res);
  },
};
