"""Deterministic detection rules (Phase 1: service down / service unresponsive)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import EngineConfig
from app.core.models import Criticality, ProbeResult, Severity, WorkloadSpec


@dataclass
class Detection:
    kind: str
    severity: Severity
    evidence: list[dict[str, Any]]


class Detector:
    CRASH = "pos_service_crash"
    UNRESPONSIVE = "pos_service_unresponsive"

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._bad: dict[tuple[str, str], int] = {}

    @staticmethod
    def would_trigger(spec: WorkloadSpec, status, health: Optional[ProbeResult]) -> bool:
        """Stateless: does this single sample still satisfy a trigger condition?"""
        if status.error:
            return False
        if not status.found or not status.running:
            return True
        return health is None or not health.ok

    def evaluate(self, spec: WorkloadSpec, status, health: Optional[ProbeResult]) -> Optional[Detection]:
        if status.error:      # monitoring failure, not a workload failure: never open a workload incident
            return None
        if not status.found or not status.running:
            kind = self.CRASH
            ev = [{"signal": "container_state", "found": status.found, "running": status.running,
                   "exit_code": status.exit_code, "oom_killed": status.oom_killed}]
        elif health is not None and not health.ok:
            kind = self.UNRESPONSIVE
            ev = [{"signal": "health_probe", "ok": False, "status_code": health.status_code, "error": health.error},
                  {"signal": "container_state", "running": True, "docker_health": status.health}]
        else:
            for k in (self.CRASH, self.UNRESPONSIVE):
                self._bad.pop((spec.id, k), None)
            return None
        other = self.UNRESPONSIVE if kind == self.CRASH else self.CRASH
        self._bad.pop((spec.id, other), None)
        n = self._bad.get((spec.id, kind), 0) + 1
        self._bad[(spec.id, kind)] = n
        if n < self.cfg.fail_threshold:
            return None
        self._bad[(spec.id, kind)] = 0
        sev = Severity.CRITICAL if (kind == self.CRASH and spec.criticality == Criticality.CRITICAL) else Severity.HIGH
        ev.append({"signal": "consecutive_bad_samples", "count": n})
        return Detection(kind, sev, ev)
