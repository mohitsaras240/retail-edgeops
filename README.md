# Retail Edge Autopilot

> **An Intelligent, Self-Healing EdgeOps Platform for Distributed Retail PoS Terminals and Self-Service Kiosks.**
> Designed around operational resilience challenges faced by retail technology platforms such as NCR Voyix.

---

## Executive Summary

Retail chains operate thousands of Point-of-Sale (PoS) lanes and self-service kiosks across geographically dispersed physical stores. These devices experience high transaction concurrency, localized edge resource constraints, frequent store network disconnects, and intermittent hardware or container failures.

**Retail Edge Autopilot** is an autonomous closed-loop control system that monitors, detects, diagnoses, recovers, and verifies retail edge workloads locally while coordinating with central cloud operations.

### Key Highlights
- **100% Test Coverage Across Closed-Loop Lifecycle**: **92 automated tests passing** across 10 test modules covering observe, detect, diagnose, decide, recover, and verify cycles.
- **Retail-Aware Recovery Policy**: Distinguishes dead containers (which can be auto-restarted immediately with zero customer impact) from running-yet-unhealthy terminals (which require human approval to avoid interrupting active customer checkouts).
- **Offline Transaction Resilience**: In-store transactions commit durably to SQLite WAL databases during network outages. When store WAN connectivity recovers, transactions sync asynchronously with zero loss and idempotent deduplication.
- **Anti-Looping & Bounded Escalation**: If an upstream dependency is down or a container is missing, restarts are explicitly blocked; incidents escalate cleanly with explainable root-cause evidence.
- **Central Operations Console**: Modern React + TypeScript + Vite dashboard with live 2.5s polling, ranked diagnosis breakdown, approval gates, and real vs. simulated provenance tracking.

---

## Architecture Overview

```
                          ┌───────────────────────────────────────────────┐
                          │         Central Cloud Operations              │
                          │   (FastAPI Central Ingest + Web Dashboard)   │
                          └──────────────────────┬────────────────────────┘
                                                 │ HTTPS / JSON
                   WAN Connection (Resilient, Disconnect-Tolerant)
                                                 │
          ┌──────────────────────────────────────┴──────────────────────────────────────┐
          │                                                                             │
┌─────────▼──────────────┐                   ┌────────────────────────┐      ┌──────────▼─────────────┐
│       Store 001        │                   │       Store 002        │      │       Store 003        │
│  ┌──────────────────┐  │                   │  ┌──────────────────┐  │      │  ┌──────────────────┐  │
│  │ PoS Checkout (L1)│  │                   │  │ PoS Checkout (L1)│  │      │  │ PoS Checkout (L1)│  │
│  │   [CRITICAL]     │  │                   │  │   [CRITICAL]     │  │      │  │   [CRITICAL]     │  │
│  └────────┬─────────┘  │                   │  └────────┬─────────┘  │      │  └────────┬─────────┘  │
│           │            │                   │           │            │      │           │            │
│  ┌────────▼─────────┐  │                   │  ┌────────▼─────────┐  │      │  ┌────────▼─────────┐  │
│  │ Kiosk Lane (K1)  │  │                   │  │ Kiosk Lane (K1)  │  │      │  │ Kiosk Lane (K1)  │  │
│  │   [IMPORTANT]    │  │                   │  │   [IMPORTANT]    │  │      │  │   [IMPORTANT]    │  │
│  └────────┬─────────┘  │                   │  └────────┬─────────┘  │      │  └────────┬─────────┘  │
│           │            │                   │           │            │      │           │            │
│  ┌────────▼─────────┐  │                   │  ┌────────▼─────────┐  │      │  ┌────────▼─────────┐  │
│  │ Transaction Sync │  │                   │  │ Transaction Sync │  │      │  │ Transaction Sync │  │
│  │   [DEFERRABLE]   │  │                   │  │   [DEFERRABLE]   │  │      │  │   [DEFERRABLE]   │  │
│  └──────────────────┘  │                   │  └──────────────────┘  │      │  └──────────────────┘  │
│   (Local SQLite WAL)   │                   │   (Local SQLite WAL)   │      │   (Local SQLite WAL)   │
└────────────────────────┘                   └────────────────────────┘      └────────────────────────┘
```

---

## 6 Core Operational Scenarios

| Scenario | Challenge | Autopilot Self-Healing Behavior |
|---|---|---|
| **1. Crash Recovery** | PoS container crashes (exit 137 / SIGKILL) | Autonomously restarts workload; verifies 3 consecutive healthy probes before resolving. Zero checkout disruption. |
| **2. Slow Latency / Degradation** | PoS responds 503 or latency spikes while running | Flags in-flight checkout disruption risk $\to$ Pauses in `AWAITING_APPROVAL` $\to$ Operator confirms $\to$ Restarts and resolves. |
| **3. WAN Disconnection** | Store internet disconnects | Transactions persist safely to local SQLite WAL queue. Upon reconnection, transactions flush with zero data loss and idempotent deduplication. |
| **4. Bad Deployment** | Image updated to defective build | Diagnosed as `bad_deployment` within 5-min regression window $\to$ Rollback action proposed $\to$ Rejects restart loops. |
| **5. Unfixable Faults** | Missing container or broken dependency | Anti-looping policy prevents futile restarts $\to$ Bounded escalation to on-call engineer with full diagnostic audit log. |
| **6. Multi-Store Isolation** | Severe double-fault in Store 2 | Store 2 PoS recovers and Sync sheds load $\to$ Zero blast radius on Store 1 or Store 3 checkout operations. |

---

## Quick Start & Verification

### 1. Run Automated Test Suite (92 Tests)
```powershell
.venv\Scripts\python -m pytest backend\tests\ -v --tb=short
```

### 2. Run Interactive End-to-End Scenario Runner
```powershell
.venv\Scripts\python scripts/run_demo.py --scenario all
```

### 3. Launch Central Operations Dashboard & API Backend
**Terminal 1 — Backend API:**
```powershell
$env:AUTOPILOT_API_KEY = "kkkkkkkkkkkkkkkkkkkk"
.venv\Scripts\python -m uvicorn app.api.routes:build_engine_from_env --factory --port 8000
```

**Terminal 2 — Frontend Dashboard:**
```powershell
cd frontend
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Technology Stack

- **Edge Engine**: Python 3.12, FastAPI, SQLite WAL, ThreadingHTTPServer
- **Dashboard**: React 18, TypeScript, Vite, Tailwind CSS, Lucide Icons
- **Containerization**: Docker, Docker Compose (9 microservices across 3 stores)
- **Testing & Verification**: PyTest (92 test cases, 100% green pass rate)
