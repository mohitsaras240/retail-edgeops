"""Rolling telemetry buffer for tracking sliding time-window metrics per workload.
Calculates statistical metrics (mean, p95 latency, error rates, cpu/memory)
and detects statistical degradation compared to historical baselines.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TelemetryPoint:
    ts: float
    latency_ms: Optional[float]
    status_code: Optional[int]
    ok: bool
    cpu_pct: Optional[float] = None
    mem_pct: Optional[float] = None


class RollingTelemetryBuffer:
    def __init__(self, window_seconds: float = 300.0, max_points: int = 500):
        self.window_seconds = window_seconds
        self.max_points = max_points
        self._buffers: dict[str, deque[TelemetryPoint]] = {}
        self._lock = threading.Lock()

    def record(
        self,
        workload_id: str,
        ts: float,
        latency_ms: Optional[float],
        status_code: Optional[int],
        ok: bool,
        cpu_pct: Optional[float] = None,
        mem_pct: Optional[float] = None,
    ) -> None:
        point = TelemetryPoint(
            ts=ts,
            latency_ms=latency_ms,
            status_code=status_code,
            ok=ok,
            cpu_pct=cpu_pct,
            mem_pct=mem_pct,
        )
        with self._lock:
            if workload_id not in self._buffers:
                self._buffers[workload_id] = deque(maxlen=self.max_points)
            q = self._buffers[workload_id]
            q.append(point)

            # Evict points older than window_seconds
            cutoff = ts - self.window_seconds
            while q and q[0].ts < cutoff:
                q.popleft()

    def metrics(self, workload_id: str, now: Optional[float] = None) -> dict[str, Any]:
        cur_time = now if now is not None else time.time()
        with self._lock:
            q = self._buffers.get(workload_id)
            if not q:
                return {
                    "sample_count": 0,
                    "mean_latency_ms": None,
                    "p95_latency_ms": None,
                    "error_rate": 0.0,
                    "avg_cpu_pct": None,
                    "avg_mem_pct": None,
                    "window_seconds": self.window_seconds,
                }

            # Filter points in active window
            cutoff = cur_time - self.window_seconds
            points = [p for p in q if p.ts >= cutoff]

        if not points:
            return {
                "sample_count": 0,
                "mean_latency_ms": None,
                "p95_latency_ms": None,
                "error_rate": 0.0,
                "avg_cpu_pct": None,
                "avg_mem_pct": None,
                "window_seconds": self.window_seconds,
            }

        latencies = [p.latency_ms for p in points if p.latency_ms is not None and p.ok]
        errors = [p for p in points if not p.ok]
        error_rate = len(errors) / len(points) if points else 0.0

        mean_lat = sum(latencies) / len(latencies) if latencies else None
        p95_lat = None
        if latencies:
            sorted_lat = sorted(latencies)
            idx = int(0.95 * len(sorted_lat))
            idx = min(idx, len(sorted_lat) - 1)
            p95_lat = sorted_lat[idx]

        cpus = [p.cpu_pct for p in points if p.cpu_pct is not None]
        mems = [p.mem_pct for p in points if p.mem_pct is not None]
        avg_cpu = sum(cpus) / len(cpus) if cpus else None
        avg_mem = sum(mems) / len(mems) if mems else None

        return {
            "sample_count": len(points),
            "mean_latency_ms": round(mean_lat, 2) if mean_lat is not None else None,
            "p95_latency_ms": round(p95_lat, 2) if p95_lat is not None else None,
            "error_rate": round(error_rate, 4),
            "avg_cpu_pct": round(avg_cpu, 2) if avg_cpu is not None else None,
            "avg_mem_pct": round(avg_mem, 2) if avg_mem is not None else None,
            "window_seconds": self.window_seconds,
        }

    def detect_latency_spike(
        self,
        workload_id: str,
        current_latency_ms: float,
        multiplier: float = 3.0,
        min_baseline_samples: int = 5,
        min_threshold_ms: float = 200.0,
        now: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """Detects if current_latency_ms is an anomaly compared to the rolling baseline.
        Returns evidence dictionary if spike detected, else None.
        """
        met = self.metrics(workload_id, now=now)
        if met["sample_count"] < min_baseline_samples:
            return None
        baseline = met["mean_latency_ms"]
        if baseline is None or baseline <= 0:
            return None

        # Check if current latency exceeds multiplier * baseline and min threshold
        spike_threshold = max(baseline * multiplier, min_threshold_ms)
        if current_latency_ms >= spike_threshold:
            return {
                "signal": "statistical_latency_spike",
                "current_latency_ms": round(current_latency_ms, 2),
                "baseline_mean_ms": baseline,
                "p95_baseline_ms": met["p95_latency_ms"],
                "spike_threshold_ms": round(spike_threshold, 2),
                "ratio_to_baseline": round(current_latency_ms / baseline, 2),
            }
        return None
