# Retail Edge Autopilot — Phase 1

Closed-loop recovery for a retail PoS workload: **detect → diagnose → decide → recover → verify**.
An incident is `RESOLVED` only after independent verification, never because a restart was issued.

## Status (honest)

| Component | State |
|---|---|
| Incident state machine, detector, rule-based diagnosis, policy, executor, verifier, engine | Implemented; 51 unit/integration tests pass (run in authoring sandbox, simulated orchestrator + fakes) |
| PoS simulator (stdlib HTTP + SQLite), HTTP prober | Implemented; tested over real localhost HTTP |
| Docker adapter (real `docker inspect/restart/logs`) | Implemented; unit-tested with a fake command runner. **Not yet exercised against a real Docker daemon** |
| FastAPI layer (`app/api/routes.py`) | Written; **not executed yet** (tests skip if FastAPI is absent) |
| Docker image / compose / `run_phase1_demo.py` | Written; **not executed yet** |
| Eclipse ioFog adapter | **Not implemented.** v3.8+ replaces the Java agent with *edgelet*; Windows support and the restart/status REST calls are unverified |
| Multi-store, kiosk, offline sync, dashboard, benchmarks | Later phases |

Known Phase 1 limits: incidents live in memory (SQLite persistence comes in Phase 2); diagnosis has no dependency
check yet, so repeated restarts are bounded only by the retry limit; rollback is explicitly `UNSUPPORTED`.

## Run on Windows (PowerShell, from repo root)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
python scripts\setup_check.py

# 1. unit tests (no Docker needed)
cd backend; python -m pytest -v; cd ..

# 2. real container demo (Docker Desktop running)
docker compose up -d --build
python scripts\run_phase1_demo.py crash
python scripts\run_phase1_demo.py degrade --auto-approve
```

API (optional): copy `.env.example` to `.env`, set a real `AUTOPILOT_API_KEY`, then from `backend\`:
`$env:AUTOPILOT_API_KEY="<key>"; uvicorn app.main:app --host 127.0.0.1 --port 8000`

## Safety design
Recovery actions are allowlisted (`restart_workload` only); no shell strings; container names are validated;
approval is required when the service is up (a restart would interrupt checkouts) and is per decision;
retries use exponential backoff and a hard limit, then escalate; every action is audited.
