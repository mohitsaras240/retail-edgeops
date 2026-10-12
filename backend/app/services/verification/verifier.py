"""Independent recovery verification. 'Restart issued' never counts as recovered."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import EngineConfig
from app.core.models import Sample, WorkloadSpec
from app.services.incident_detection.detector import Detector


@dataclass
class VerificationResult:
    passed: bool
    pending: bool
    checks: list[dict[str, Any]]
    metrics: dict[str, Any]
    evaluated_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Verifier:
    def __init__(self, cfg: EngineConfig, detector: Detector):
        self.cfg, self.detector = cfg, detector

    def evaluate(self, spec: WorkloadSpec, samples: list[Sample], now: float) -> VerificationResult:
        n = self.cfg.verify_required_ok
        if len(samples) < n:
            return VerificationResult(False, True, [], {"samples": len(samples), "required": n}, now)
        recent = samples[-n:]
        checks: list[dict[str, Any]] = []

        def add(name: str, passed: bool, observed: Any, threshold: Any = None) -> None:
            checks.append({"name": name, "passed": bool(passed), "observed": observed, "threshold": threshold})

        add("container_running", all(s.status.found and s.status.running and not s.status.error for s in recent),
            [s.status.running for s in recent])
        add("docker_health", all(s.status.health in (None, "healthy") for s in recent),
            [s.status.health for s in recent], "healthy or no healthcheck")
        add("health_endpoint_ok", all(s.health is not None and s.health.ok for s in recent),
            [None if s.health is None else s.health.status_code for s in recent])
        lat = [s.health.latency_ms for s in recent if s.health and s.health.latency_ms is not None]
        add("latency_ms_max", bool(lat) and max(lat) <= self.cfg.verify_latency_ms,
            round(max(lat), 1) if lat else None, self.cfg.verify_latency_ms)
        add("canary_transaction_ok", all(s.canary is not None and s.canary.ok for s in recent),
            [None if s.canary is None else s.canary.status_code for s in recent])
        last = recent[-1]
        add("trigger_cleared", not self.detector.would_trigger(spec, last.status, last.health), None)
        clat = [s.canary.latency_ms for s in recent if s.canary and s.canary.latency_ms is not None]
        metrics = {"samples_evaluated": n,
                   "health_latency_ms_mean": round(sum(lat) / len(lat), 2) if lat else None,
                   "health_latency_ms_max": round(max(lat), 2) if lat else None,
                   "canary_latency_ms_mean": round(sum(clat) / len(clat), 2) if clat else None}
        return VerificationResult(all(c["passed"] for c in checks), False, checks, metrics, now)
