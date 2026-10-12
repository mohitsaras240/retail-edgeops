"""Deterministic detection rules.

Phase 1 rules:  pos_service_crash | pos_service_unresponsive
Phase 2 rules:  repeated_restarts | resource_pressure | sync_backlog_growth |
                deployment_regression
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import EngineConfig
from app.core.models import Criticality, ProbeResult, Severity, WorkloadSpec

# Thresholds (all configurable via EngineConfig extensions in Phase 3; hard-coded here for Phase 2)
RESTART_STORM_THRESHOLD = 3        # restarts since last reset before triggering
CPU_PRESSURE_PCT = 85.0            # % CPU triggers resource_pressure
MEM_PRESSURE_PCT = 90.0            # % memory triggers resource_pressure
SYNC_BACKLOG_TICKS = 4             # consecutive ticks of growing backlog before triggering
REGRESSION_WINDOW_S = 300.0        # image change + health fail within this window → regression


@dataclass
class Detection:
    kind: str
    severity: Severity
    evidence: list[dict[str, Any]]


class Detector:
    # Phase 1 kinds
    CRASH = "pos_service_crash"
    UNRESPONSIVE = "pos_service_unresponsive"
    # Phase 2 kinds
    REPEATED_RESTARTS = "repeated_restarts"
    RESOURCE_PRESSURE = "resource_pressure"
    SYNC_BACKLOG = "sync_backlog_growth"
    DEPLOYMENT_REGRESSION = "deployment_regression"

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._bad: dict[tuple[str, str], int] = {}            # (workload_id, kind) → bad-sample counter
        # Phase 2 state
        self._last_restart_count: dict[str, int] = {}         # workload_id → restart count at last eval
        self._restart_storm: dict[str, int] = {}              # incremental restarts seen this window
        self._sync_backlog_prev: dict[str, int] = {}          # workload_id → last pending count
        self._sync_growing_ticks: dict[str, int] = {}         # consecutive ticks backlog is growing
        self._image_versions: dict[str, tuple[str, float]] = {}  # workload_id → (version, first_seen_ts)
        self._now: float = 0.0                                 # set by evaluate; used in helpers

    @staticmethod
    def would_trigger(spec: WorkloadSpec, status, health: Optional[ProbeResult]) -> bool:
        """Stateless: does this single sample still satisfy a trigger condition?"""
        if status.error:
            return False
        if not status.found or not status.running:
            return True
        return health is None or not health.ok

    def evaluate(self, spec: WorkloadSpec, status, health: Optional[ProbeResult],
                 sync_pending: Optional[int] = None,
                 now: Optional[float] = None) -> Optional[Detection]:
        """Evaluate all rules; return first triggered Detection or None.

        `sync_pending` is the current pending transaction count for the sync workload
        associated with this workload's store. Only used for the sync_backlog rule.
        """
        self._now = now or time.time()
        if status.error:      # monitoring failure, not a workload failure
            return None

        # ── Phase 1: crash / unresponsive ──────────────────────────────────────────
        if not status.found or not status.running:
            return self._count_and_fire(
                spec, self.CRASH,
                [{"signal": "container_state", "found": status.found, "running": status.running,
                  "exit_code": status.exit_code, "oom_killed": status.oom_killed}],
                severity=(Severity.CRITICAL if spec.criticality == Criticality.CRITICAL else Severity.HIGH))

        if health is not None and not health.ok:
            # ── Phase 2: deployment regression takes priority over generic unresponsive ─
            reg = self._check_deployment_regression(spec, status, health)
            if reg:
                return reg
            return self._count_and_fire(
                spec, self.UNRESPONSIVE,
                [{"signal": "health_probe", "ok": False, "status_code": health.status_code,
                  "error": health.error},
                 {"signal": "container_state", "running": True, "docker_health": status.health}],
                severity=Severity.HIGH)

        # ── Healthy so far: clear crash/unresponsive bad-sample counters ──────────
        for k in (self.CRASH, self.UNRESPONSIVE):
            self._bad.pop((spec.id, k), None)
        if status.image_version:
            hist = self._image_versions.get(spec.id)
            if hist is None or hist[0] != status.image_version:
                self._image_versions[spec.id] = (status.image_version, self._now, status.image_version)

        # ── Phase 2: restart storm (running + healthy, but restarting a lot) ─────
        rst = self._check_repeated_restarts(spec, status)
        if rst:
            return rst

        # ── Phase 2: resource pressure ────────────────────────────────────────────
        rp = self._check_resource_pressure(spec, status)
        if rp:
            return rp

        # ── Phase 2: sync backlog (pass-through from engine) ─────────────────────
        if sync_pending is not None:
            sb = self._check_sync_backlog(spec, sync_pending)
            if sb:
                return sb
        else:
            self._sync_growing_ticks.pop(spec.id, None)
            self._sync_backlog_prev.pop(spec.id, None)

        return None

    # ---------------------------------------------------------------- helpers
    def _count_and_fire(self, spec: WorkloadSpec, kind: str, evidence: list[dict],
                        severity: Severity) -> Optional[Detection]:
        other = self.UNRESPONSIVE if kind == self.CRASH else self.CRASH
        self._bad.pop((spec.id, other), None)
        n = self._bad.get((spec.id, kind), 0) + 1
        self._bad[(spec.id, kind)] = n
        if n < self.cfg.fail_threshold:
            return None
        self._bad[(spec.id, kind)] = 0
        evidence.append({"signal": "consecutive_bad_samples", "count": n})
        return Detection(kind, severity, evidence)

    def _check_repeated_restarts(self, spec: WorkloadSpec, status) -> Optional[Detection]:
        """Detect a restart storm: restart_count increments >RESTART_STORM_THRESHOLD since last check."""
        prev = self._last_restart_count.get(spec.id)
        cur = status.restart_count
        self._last_restart_count[spec.id] = cur
        if prev is None:
            return None
        delta = cur - prev
        if delta <= 0:
            self._restart_storm.pop(spec.id, None)
            return None
        storm = self._restart_storm.get(spec.id, 0) + delta
        self._restart_storm[spec.id] = storm
        if storm < RESTART_STORM_THRESHOLD:
            return None
        self._restart_storm.pop(spec.id, None)
        sev = Severity.HIGH if spec.criticality == Criticality.CRITICAL else Severity.MEDIUM
        return Detection(self.REPEATED_RESTARTS, sev,
                         [{"signal": "restart_count_increase", "delta": delta,
                           "total_accumulated": storm, "threshold": RESTART_STORM_THRESHOLD}])

    def _check_resource_pressure(self, spec: WorkloadSpec, status) -> Optional[Detection]:
        """Detect CPU or memory breach. Skipped if stats are not available."""
        if status.cpu_pct is None and status.mem_pct is None:
            return None
        cpu_breach = status.cpu_pct is not None and status.cpu_pct >= CPU_PRESSURE_PCT
        mem_breach = status.mem_pct is not None and status.mem_pct >= MEM_PRESSURE_PCT
        if not cpu_breach and not mem_breach:
            self._bad.pop((spec.id, self.RESOURCE_PRESSURE), None)
            return None
        evidence = []
        if cpu_breach:
            evidence.append({"signal": "cpu_pressure", "cpu_pct": status.cpu_pct,
                              "threshold_pct": CPU_PRESSURE_PCT})
        if mem_breach:
            evidence.append({"signal": "mem_pressure", "mem_pct": status.mem_pct,
                              "threshold_pct": MEM_PRESSURE_PCT})
        if status.stats_age_s is not None:
            evidence.append({"signal": "stats_age_s", "value": status.stats_age_s})
        # Use the fail_threshold counter for resource pressure too (avoids single-sample spikes)
        return self._count_resource(spec, evidence)

    def _count_resource(self, spec: WorkloadSpec, evidence: list[dict]) -> Optional[Detection]:
        n = self._bad.get((spec.id, self.RESOURCE_PRESSURE), 0) + 1
        self._bad[(spec.id, self.RESOURCE_PRESSURE)] = n
        if n < self.cfg.fail_threshold:
            return None
        self._bad[(spec.id, self.RESOURCE_PRESSURE)] = 0
        sev = (Severity.HIGH if spec.criticality == Criticality.CRITICAL
               else Severity.MEDIUM if spec.criticality == Criticality.IMPORTANT
               else Severity.LOW)
        evidence.append({"signal": "consecutive_pressure_samples", "count": n})
        return Detection(self.RESOURCE_PRESSURE, sev, evidence)

    def _check_sync_backlog(self, spec: WorkloadSpec, pending: int) -> Optional[Detection]:
        """Detect a growing sync backlog (sync workloads or store-level metric)."""
        prev = self._sync_backlog_prev.get(spec.id, pending)
        self._sync_backlog_prev[spec.id] = pending
        if pending > prev:
            ticks = self._sync_growing_ticks.get(spec.id, 0) + 1
            self._sync_growing_ticks[spec.id] = ticks
        else:
            self._sync_growing_ticks.pop(spec.id, None)
            return None
        if self._sync_growing_ticks.get(spec.id, 0) < SYNC_BACKLOG_TICKS:
            return None
        self._sync_growing_ticks[spec.id] = 0
        return Detection(self.SYNC_BACKLOG, Severity.MEDIUM,
                         [{"signal": "sync_pending_growing", "current_pending": pending,
                           "previous": prev, "consecutive_growth_ticks": SYNC_BACKLOG_TICKS}])

    def _check_deployment_regression(self, spec: WorkloadSpec, status, health: ProbeResult) -> Optional[Detection]:
        """Detect: image version changed recently AND health probe is now failing."""
        ver = status.image_version
        if ver is None:
            return None
        hist = self._image_versions.get(spec.id)
        if hist is None:
            self._image_versions[spec.id] = (ver, self._now, ver)
            return None
        # hist is (cur_version, first_seen_ts, baseline_version)
        cur_v, first_seen_ts, baseline_v = hist
        if ver != cur_v:
            # A new version just arrived
            self._image_versions[spec.id] = (ver, self._now, cur_v)
            baseline_v = cur_v
            first_seen_ts = self._now
        if ver == baseline_v:
            return None
        age = self._now - first_seen_ts
        if age > REGRESSION_WINDOW_S:
            return None
        return Detection(self.DEPLOYMENT_REGRESSION, Severity.HIGH,
                         [{"signal": "image_changed", "old_version": baseline_v, "new_version": ver,
                           "image_age_s": round(age, 1)},
                          {"signal": "health_probe_failing", "status_code": health.status_code,
                           "error": health.error}])
