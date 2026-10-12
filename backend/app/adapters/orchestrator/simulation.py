"""In-memory SIMULATED orchestrator for tests and offline demos.
Every result is tagged Provenance.SIMULATED."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.adapters.orchestrator.base import ActionResult, OpStatus, Orchestrator, WorkloadStatus
from app.core.models import Provenance


@dataclass
class SimWorkload:
    running: bool = True
    healthy: bool = True
    restart_count: int = 0
    exit_code: int = 0
    oom_killed: bool = False
    restart_fixes_fault: bool = True
    # Phase 2: extended telemetry
    cpu_pct: Optional[float] = None
    mem_pct: Optional[float] = None
    image_version: Optional[str] = "v1.0.0"
    paused: bool = False


class SimulationOrchestrator(Orchestrator):
    name = "simulation"
    provenance = Provenance.SIMULATED

    def __init__(self) -> None:
        self.workloads: dict[str, SimWorkload] = {}
        self.daemon_down = False
        self.restart_calls: list[str] = []
        self.pause_calls: list[str] = []

    def add(self, workload_id: str, **kw) -> SimWorkload:
        self.workloads[workload_id] = SimWorkload(**kw)
        return self.workloads[workload_id]

    # ---------------------------------------------------------------- fault injection (simulated)
    def crash(self, workload_id: str, exit_code: int = 137, oom: bool = False) -> None:
        w = self.workloads[workload_id]
        w.running, w.healthy, w.exit_code, w.oom_killed = False, False, exit_code, oom

    def degrade(self, workload_id: str) -> None:
        self.workloads[workload_id].healthy = False

    def set_resource_pressure(self, workload_id: str, cpu_pct: float, mem_pct: float) -> None:
        """Simulate CPU/memory pressure on a workload."""
        w = self.workloads[workload_id]
        w.cpu_pct, w.mem_pct = cpu_pct, mem_pct

    def set_image_version(self, workload_id: str, version: str) -> None:
        """Simulate a deployment by changing the reported image version."""
        self.workloads[workload_id].image_version = version

    def clear_resource_pressure(self, workload_id: str) -> None:
        w = self.workloads[workload_id]
        w.cpu_pct, w.mem_pct = None, None

    # ---------------------------------------------------------------- Orchestrator interface
    def inspect_workload(self, workload_id: str) -> WorkloadStatus:
        st = WorkloadStatus(workload_id=workload_id, provenance=self.provenance)
        if self.daemon_down:
            st.error = "simulated orchestrator unreachable"
            return st
        w = self.workloads.get(workload_id)
        if w is None:
            return st
        st.found = True
        st.running = w.running
        st.exit_code = w.exit_code
        st.oom_killed = w.oom_killed
        st.restart_count = w.restart_count
        st.cpu_pct = w.cpu_pct
        st.mem_pct = w.mem_pct
        st.image_version = w.image_version
        st.stats_age_s = 0.0   # simulated stats are always fresh
        return st

    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult:
        w = self.workloads.get(workload_id)
        if w is None:
            return ActionResult(OpStatus.FAILED, "no such simulated workload", self.provenance)
        self.restart_calls.append(workload_id)
        w.restart_count += 1
        w.running = True
        w.paused = False
        if w.restart_fixes_fault:
            w.healthy, w.exit_code, w.oom_killed = True, 0, False
            w.cpu_pct, w.mem_pct = None, None
        return ActionResult(OpStatus.OK, f"simulated restart of {workload_id}", self.provenance)

    def pause_workload(self, workload_id: str) -> ActionResult:
        w = self.workloads.get(workload_id)
        if w is None:
            return ActionResult(OpStatus.FAILED, "no such simulated workload", self.provenance)
        self.pause_calls.append(workload_id)
        w.paused = True
        return ActionResult(OpStatus.OK, f"simulated pause of {workload_id}", self.provenance)

    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult:
        return ActionResult(OpStatus.OK, "", self.provenance)
