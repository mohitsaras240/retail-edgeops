"""In-memory SIMULATED orchestrator for tests and offline demos.
Every result is tagged Provenance.SIMULATED."""
from __future__ import annotations

from dataclasses import dataclass

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


class SimulationOrchestrator(Orchestrator):
    name = "simulation"
    provenance = Provenance.SIMULATED

    def __init__(self) -> None:
        self.workloads: dict[str, SimWorkload] = {}
        self.daemon_down = False
        self.restart_calls: list[str] = []

    def add(self, workload_id: str, **kw) -> SimWorkload:
        self.workloads[workload_id] = SimWorkload(**kw)
        return self.workloads[workload_id]

    # fault injection (simulated)
    def crash(self, workload_id: str, exit_code: int = 137, oom: bool = False) -> None:
        w = self.workloads[workload_id]
        w.running, w.healthy, w.exit_code, w.oom_killed = False, False, exit_code, oom

    def degrade(self, workload_id: str) -> None:
        self.workloads[workload_id].healthy = False

    def inspect_workload(self, workload_id: str) -> WorkloadStatus:
        st = WorkloadStatus(workload_id=workload_id, provenance=self.provenance)
        if self.daemon_down:
            st.error = "simulated orchestrator unreachable"
            return st
        w = self.workloads.get(workload_id)
        if w is None:
            return st
        st.found, st.running, st.exit_code, st.oom_killed = True, w.running, w.exit_code, w.oom_killed
        return st

    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult:
        w = self.workloads.get(workload_id)
        if w is None:
            return ActionResult(OpStatus.FAILED, "no such simulated workload", self.provenance)
        self.restart_calls.append(workload_id)
        w.restart_count += 1
        w.running = True
        if w.restart_fixes_fault:
            w.healthy, w.exit_code, w.oom_killed = True, 0, False
        return ActionResult(OpStatus.OK, f"simulated restart of {workload_id}", self.provenance)

    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult:
        return ActionResult(OpStatus.OK, "", self.provenance)
