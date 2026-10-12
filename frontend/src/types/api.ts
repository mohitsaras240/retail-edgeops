export type Provenance = "real" | "simulated";
export type Criticality = "critical" | "important" | "deferrable";
export type Severity = "low" | "medium" | "high" | "critical";

export type IncidentState =
  | "DETECTED"
  | "DIAGNOSING"
  | "AWAITING_APPROVAL"
  | "RECOVERING"
  | "VERIFYING"
  | "RESOLVED"
  | "ESCALATED";

export interface WorkloadStatus {
  workload_id: string;
  provenance: Provenance;
  found: boolean;
  running: boolean;
  health: string | null;
  exit_code: number | null;
  oom_killed: boolean;
  started_at: string | null;
  image: string | null;
  error: string | null;
  restart_count: number;
  cpu_pct: number | null;
  mem_pct: number | null;
  image_version: string | null;
  stats_age_s: number | null;
}

export interface WorkloadViewItem {
  id: string;
  store_id: string;
  kind: string;
  criticality: Criticality;
  provenance: Provenance;
  orchestrator: string;
  monitoring_error: string | null;
  suppressed_by_escalated_incident: string | null;
  status: WorkloadStatus | null;
  health_probe: {
    ok: boolean;
    latency_ms: number | null;
    status_code: number | null;
    error: string | null;
    ts: number;
  } | null;
}

export interface StoreWorkloadItem {
  id: string;
  kind: string;
  criticality: Criticality;
  running: boolean | null;
  health_ok: boolean | null;
  cpu_pct: number | null;
  mem_pct: number | null;
  restart_count: number;
  open_incident: boolean;
}

export interface StoreViewItem {
  store_id: string;
  workloads: StoreWorkloadItem[];
  open_incidents: number;
  escalated_incidents: number;
  sync_pending: number;
  provenance: Provenance;
}

export interface RankedCause {
  cause: string;
  score: number;
  confidence: "high" | "medium" | "low";
  evidence: string[];
  counter_evidence: string[];
  next_steps: string[];
}

export interface DiagnosisReport {
  method: string;
  incident_kind: string;
  ranked_causes: RankedCause[];
  note: string;
  dependency_health: Record<string, boolean>;
  telemetry_metrics: Record<string, any>;
}

export interface PolicyDecision {
  action: string;
  requires_approval: boolean;
  reversible: boolean;
  reason: string;
  rationale: string[];
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  estimated_disruption: string;
}

export interface IncidentTimelineEvent {
  ts: number;
  event: string;
  state: IncidentState;
  note: string;
}

export interface IncidentItem {
  id: string;
  workload_id: string;
  store_id: string;
  kind: string;
  severity: Severity;
  detected_at: number;
  evidence: Record<string, any>[];
  provenance: Provenance;
  state: IncidentState;
  state_since: number;
  attempts: number;
  approved_by: string | null;
  recurrence_of: string | null;
  resolved_at: number | null;
  escalation_reason: string | null;
  diagnosis: DiagnosisReport | null;
  decision: PolicyDecision | null;
  verification: Record<string, any> | null;
  actions: Record<string, any>[];
  timeline: IncidentTimelineEvent[];
}

export interface AuditEntry {
  ts: number;
  event: string;
  [key: string]: any;
}

export interface SystemHealth {
  status: string;
  orchestrator: string;
  provenance: Provenance;
  dry_run: boolean;
  approval_mode: string;
}

export interface SyncAggregateStatus {
  stores: Record<string, number>;
  central_stats: {
    total_transactions: number;
    distinct_stores: number;
  };
}
