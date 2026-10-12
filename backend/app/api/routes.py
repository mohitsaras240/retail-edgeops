"""FastAPI layer. NOT executed in the authoring sandbox (FastAPI unavailable there);
tests/test_api.py runs it where FastAPI is installed."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.adapters.orchestrator.docker_local import DockerLocalOrchestrator
from app.core.config import config_from_env, load_workloads
from app.services.engine import AutopilotEngine, EngineError
from app.services.telemetry.prober import HttpProber

log = logging.getLogger("autopilot")
REPO_ROOT = Path(__file__).resolve().parents[3]


class ApprovalBody(BaseModel):
    actor: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    reason: str = Field(default="", max_length=200)


def build_engine_from_env() -> AutopilotEngine:
    cfg = config_from_env()
    workloads = load_workloads(Path(os.environ.get("AUTOPILOT_WORKLOADS_FILE", REPO_ROOT / "config" / "workloads.json")))
    audit = Path(os.environ.get("AUTOPILOT_AUDIT_FILE", REPO_ROOT / "data" / "audit.jsonl"))
    audit.parent.mkdir(parents=True, exist_ok=True)
    return AutopilotEngine(workloads, DockerLocalOrchestrator(), HttpProber(cfg.probe_timeout_s), cfg, audit_path=audit)


def create_app(engine: AutopilotEngine, api_key: Optional[str] = None, run_loop: bool = True) -> FastAPI:
    key = api_key if api_key is not None else os.environ.get("AUTOPILOT_API_KEY", "")
    if len(key) < 16 or key == "change-me-to-a-long-random-value":
        raise RuntimeError("AUTOPILOT_API_KEY must be set to a random value of at least 16 characters")

    async def loop() -> None:
        while True:
            try:
                await asyncio.to_thread(engine.tick)
            except Exception:                      # keep monitoring alive, but never hide the failure
                log.exception("engine tick failed")
            await asyncio.sleep(engine.cfg.tick_interval_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(loop()) if run_loop else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Retail Edge Autopilot", version="0.1.0", lifespan=lifespan)

    def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), key.encode()):
            raise HTTPException(status_code=401, detail="missing or invalid API key")

    def wrap(fn):
        try:
            return fn()
        except EngineError as exc:
            raise HTTPException(status_code=404 if exc.code == "not_found" else 409, detail=str(exc))

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "orchestrator": engine.orch.name, "provenance": engine.orch.provenance.value,
                "dry_run": engine.cfg.dry_run, "approval_mode": engine.cfg.approval_mode}

    @app.get("/api/workloads", dependencies=[Depends(require_key)])
    def workloads() -> list:
        return engine.workloads_view()

    @app.get("/api/incidents", dependencies=[Depends(require_key)])
    def incidents() -> list:
        return engine.incidents_view()

    @app.get("/api/incidents/{incident_id}", dependencies=[Depends(require_key)])
    def incident(incident_id: str) -> dict:
        return wrap(lambda: engine.incident_view(incident_id))

    @app.post("/api/incidents/{incident_id}/approve", dependencies=[Depends(require_key)])
    def approve(incident_id: str, body: ApprovalBody) -> dict:
        wrap(lambda: engine.approve(incident_id, body.actor))
        return engine.incident_view(incident_id)

    @app.post("/api/incidents/{incident_id}/reject", dependencies=[Depends(require_key)])
    def reject(incident_id: str, body: ApprovalBody) -> dict:
        wrap(lambda: engine.reject(incident_id, body.actor, body.reason))
        return engine.incident_view(incident_id)

    @app.get("/api/audit", dependencies=[Depends(require_key)])
    def audit() -> list:
        return engine.audit.entries()

    return app
