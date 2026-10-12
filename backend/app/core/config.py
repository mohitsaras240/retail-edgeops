from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

from app.core.models import Criticality, WorkloadSpec

APPROVAL_MODES = ("risk_based", "always", "never")


@dataclass(frozen=True)
class EngineConfig:
    fail_threshold: int = 2            # consecutive bad samples before an incident is opened
    max_attempts: int = 2              # recovery attempts per incident before escalation
    base_backoff_s: float = 5.0        # gap before attempt n+1 is base * 2**(n-1)
    action_timeout_s: float = 30.0
    verify_required_ok: int = 3        # consecutive healthy samples needed to resolve
    verify_deadline_s: float = 60.0    # give up verifying after this long
    verify_latency_ms: float = 1000.0
    approval_mode: str = "risk_based"
    approval_timeout_s: float = 900.0
    recurrence_window_s: float = 600.0
    probe_timeout_s: float = 2.0
    tick_interval_s: float = 2.0
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.approval_mode not in APPROVAL_MODES:
            raise ValueError(f"approval_mode must be one of {APPROVAL_MODES}")
        if self.max_attempts < 1 or self.verify_required_ok < 1 or self.fail_threshold < 1:
            raise ValueError("max_attempts, verify_required_ok and fail_threshold must be >= 1")


def config_from_env(env: Optional[Mapping[str, str]] = None) -> EngineConfig:
    env = os.environ if env is None else env
    kw: dict = {}
    if "AUTOPILOT_APPROVAL_MODE" in env:
        kw["approval_mode"] = env["AUTOPILOT_APPROVAL_MODE"]
    if "AUTOPILOT_MAX_ATTEMPTS" in env:
        kw["max_attempts"] = int(env["AUTOPILOT_MAX_ATTEMPTS"])
    if "AUTOPILOT_TICK_INTERVAL_S" in env:
        kw["tick_interval_s"] = float(env["AUTOPILOT_TICK_INTERVAL_S"])
    if "AUTOPILOT_DRY_RUN" in env:
        kw["dry_run"] = env["AUTOPILOT_DRY_RUN"].strip().lower() in ("1", "true", "yes")
    return EngineConfig(**kw)


def load_workloads(path: Path) -> list[WorkloadSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = []
    for w in raw["workloads"]:
        for key in ("health_url", "transaction_url"):
            if urlparse(w[key]).scheme not in ("http", "https"):
                raise ValueError(f"workload {w['id']}: {key} must be http(s)")
        specs.append(WorkloadSpec(
            id=w["id"], store_id=w["store_id"], kind=w["kind"],
            criticality=Criticality(w["criticality"]),
            health_url=w["health_url"], transaction_url=w["transaction_url"],
            stateless=bool(w.get("stateless", True)),
        ))
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate workload ids")
    return specs
