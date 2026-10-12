# Live Demonstration & Evaluator Reproduction Guide

This guide describes how to run and demonstrate the Retail Edge Autopilot platform during live technical interviews, product walkthroughs, or system evaluations.

---

## Part 1: Automated Scenario Demonstration (CLI)

The CLI demo runner executes all 6 core scenarios with formatted progress output and step-by-step state verification:

```powershell
# Run all 6 scenarios in sequence
.venv\Scripts\python scripts/run_demo.py --scenario all

# Or run individual scenarios:
.venv\Scripts\python scripts/run_demo.py --scenario 1  # PoS Crash & Auto-Recovery
.venv\Scripts\python scripts/run_demo.py --scenario 2  # Degraded Service & Approval Gate
.venv\Scripts\python scripts/run_demo.py --scenario 3  # Offline Transactions & Reconnect
.venv\Scripts\python scripts/run_demo.py --scenario 4  # Bad Deployment Rollback Detection
.venv\Scripts\python scripts/run_demo.py --scenario 5  # Unfixable Fault Bounded Escalation
.venv\Scripts\python scripts/run_demo.py --scenario 6  # Multi-Store Isolation (0 Blast Radius)
```

---

## Part 2: Interactive Web Dashboard Demonstration

### Step 1: Start Backend and Frontend
**Terminal 1 (Backend Engine):**
```powershell
$env:AUTOPILOT_ORCHESTRATOR = "iofog"
$env:IOFOG_CONTROLLER_URL = "http://localhost:54321"   # Your ioFog controller URL
$env:IOFOG_AUTH_TOKEN = "your-iofog-user-or-api-token"  # Optional auth token
cd d:\retail-edge-autopilot-phase1\retail-edge-autopilot\backend
D:\retail-edge-autopilot-phase1\retail-edge-autopilot\.venv\Scripts\python -m uvicorn app.api.routes:build_app --factory --port 8000 --host 127.0.0.1
```

**Terminal 2 (Web Dashboard):**
```powershell
cd frontend
npm run dev
```
Open **`http://localhost:5173`** in Chrome / Edge.

### Step 2: Key Dashboard Features to Highlight
1. **Provenance Banner**: Notice the top badge identifying the execution adapter mode (`Real Execution` or `Simulation Adapter`), approval policy (`prompt`), and dry-run flag.
2. **Distributed Store Cards**: Review the 3 store cards (`store-001`, `store-002`, `store-003`). Point out that each card tracks PoS lane online/offline status, kiosk status, and offline SQLite sync backlog.
3. **Workload Table**: Shows all 9 workloads with container running states, health probe latency (ms), CPU/Memory telemetry, and restart counters.
4. **Offline Resilience Card**: Shows central total transactions received and per-store pending sync queues.

### Step 3: Trigger Live Faults & Operator Approval
Open a 3rd terminal to inject live faults using `scripts/inject_fault.py`:

```powershell
# 1. Trigger Latency / Degraded State in Store 1 PoS
.venv\Scripts\python scripts/inject_fault.py --scenario degrade --port 18081

# Observe the Dashboard:
# - Incident opens in state AWAITING_APPROVAL.
# - Notice warning: "Workload is serving live traffic - operator confirmation required".
# - Click "Inspect Evidence" to examine ranked root causes and confidence ratings.
# - Click "Approve Recovery" -> Watch Autopilot restart the service and verify recovery.

# 2. Clear Degraded State
.venv\Scripts\python scripts/inject_fault.py --scenario clear --port 18081

# 3. Simulate Store Sync Network Block
.venv\Scripts\python scripts/inject_fault.py --scenario block_sync --port 18083
# Notice backlog accumulation in store-001 card without customer transaction loss.

# 4. Restore Store Sync Network
.venv\Scripts\python scripts/inject_fault.py --scenario unblock_sync --port 18083
# Notice pending backlog draining back to 0 as events sync to central ingest.
```

---

## Part 3: Automated Test Suite Verification

Run the comprehensive test suite to prove system correctness:

```powershell
.venv\Scripts\python -m pytest backend\tests\ -v --tb=short
```

Expected result:
```
======================= 92 passed, 1 warning in 10.98s =======================
```
