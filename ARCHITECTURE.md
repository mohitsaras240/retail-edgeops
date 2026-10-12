# Retail Edge Autopilot — Deep Architecture & Design Decisions

This document details the distributed systems architecture, state machine semantics, telemetry pipelines, and recovery policy engineering underlying Retail Edge Autopilot.

---

## 1. Closed-Loop Incident State Machine

Every incident progresses through a strict, finite-state lifecycle enforced by transitions defined in `app/core/models.py`:

```
 [ DETECTED ] ──> [ DIAGNOSING ] ──> [ AWAITING_APPROVAL ]
                         │                    │
                         │ (Auto-Approved)    │ (Operator Approved)
                         ▼                    ▼
                  [ RECOVERING ] ◄────────────┘
                         │
                         ▼
                  [ VERIFYING ]
                    │        │
      (Passed N)    │        │ (Failed deadline)
                    ▼        ▼
               [ RESOLVED ] [ DIAGNOSING ] ──> [ ESCALATED ] (Terminal)
```

### Key State Invariants
- **No Resolution Without Verification**: Issuing a `docker restart` does NOT resolve an incident. The incident enters `VERIFYING` and requires $N$ consecutive healthy samples across both health probes and canary transactions before transitioning to `RESOLVED`.
- **Operator Approval Gate**: If a workload is running and classified as `CRITICAL` (checkout lane), autonomous restarts are blocked to protect in-flight customer payments. The incident halts in `AWAITING_APPROVAL` with risk explanations.
- **Deduplication & Block List**: Once an incident escalates (e.g. unfixable fault), the workload ID is registered in `_blocked` to suppress flood alarms until the underlying fault is cleared.

---

## 2. Multi-Signal Evidence Scoring & Ranked Diagnosis

Rather than relying on brittle threshold triggers or black-box ML models, diagnosis evaluates multiple evidence signals:

$$\text{Evidence Weight} = w_{\text{lifecycle}} + w_{\text{telemetry}} + w_{\text{topology}} + w_{\text{timeline}}$$

1. **Container Lifecycle Signal**:
   - Exit Code 137 + OOM flag set $\implies$ `out_of_memory` (Score: 90, Confidence: High).
   - Exit Code 137 + OOM flag unset $\implies$ `killed_by_signal` (Score: 82, Confidence: Medium).
   - Container Missing from orchestrator $\implies$ `container_missing` (Score: 95, Confidence: High).
2. **Rolling Telemetry Signal**:
   - P95 latency spikes relative to 300s sliding baseline $\implies$ `latency_spike_degradation`.
   - Continuous 503 health probe failures $\implies$ `unresponsive_process`.
3. **Topology & Dependency Signal**:
   - If a same-store dependency (e.g. sync worker, local database) is failing, `dependency_unavailable` is ranked at score 88, explicitly suppressing container restarts that would cause futile restart loops.
4. **Deployment Timeline Signal**:
   - Container image version updated within 5-minute regression window followed immediately by health failure $\implies$ `bad_deployment` (Score: 92, Confidence: High).

---

## 3. Offline Transaction Resilience Subsystem

Retail stores frequently suffer localized WAN outages. Autopilot guarantees zero transaction loss via a dual-layer architecture:

```
PoS Checkout / Kiosk Terminal
             │
             ▼
Local SQLite Transaction Store (WAL Mode)
   ├── Status: PENDING_SYNC
   ├── Event UUID (Idempotency Key)
   └── Survives Process Crashes & Power Loss
             │
             │ Background Sync Loop (Interval: 5s)
             ▼
Central Cloud Ingestion Service
   ├── Endpoint: POST /central/ingest
   ├── Deduplication: INSERT OR IGNORE ON event_id
   └── Status: SYNCED (Local flag updated upon HTTP 200/201 response)
```

- **Idempotent Ingestion**: Even if network packets are duplicated due to retries, the central database uses the unique `event_id` as a primary key, returning accepted vs duplicate statistics without inflating ledger totals.

---

## 4. Retail-Aware Recovery Policy & Safety Allowlist

Every recovery action is subject to a 5-step safety evaluation in `RecoveryExecutor`:

1. **Allowlist Precondition**: Only `{"restart_workload", "defer_workload", "rollback_workload"}` are permitted. Arbitrary command execution is impossible.
2. **Approval Verification**: Requires human signature if `requires_approval=True`.
3. **Exponential Cooldown**: Enforces backoff:
   $$\text{Cooldown Gap} = \text{base\_backoff} \times 2^{\text{attempts} - 1}$$
4. **Idempotency Check**: If an exited container was already restarted externally or recovered, the restart call is safely skipped (`SKIPPED_ALREADY_HEALTHY`).
5. **Audit Logging**: Every action proposal, rejection, execution, or escalation is written to an immutable append-only JSONL audit log.
