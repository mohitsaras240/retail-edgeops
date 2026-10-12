from __future__ import annotations

from app.core.config import EngineConfig
from app.core.models import Criticality, ProbeResult, WorkloadSpec
from app.adapters.orchestrator.simulation import SimulationOrchestrator
from app.services.engine import AutopilotEngine


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float = 1.0) -> None:
        self.t += dt


class SimProber:
    """Probe results derived from the simulated workload state."""
    def __init__(self, sim: SimulationOrchestrator):
        self.sim = sim

    def _ok(self, spec):
        w = self.sim.workloads[spec.id]
        return w.running and w.healthy

    def probe_health(self, spec):
        ok = self._ok(spec)
        return ProbeResult(ok, 5.0 if ok else None, 200 if ok else 503, None if ok else "unhealthy", 0.0)

    def probe_canary(self, spec):
        ok = self._ok(spec)
        return ProbeResult(ok, 8.0 if ok else None, 201 if ok else 503, None if ok else "unhealthy", 0.0)


def spec(wid: str, store: str, crit=Criticality.CRITICAL) -> WorkloadSpec:
    return WorkloadSpec(id=wid, store_id=store, kind="pos", criticality=crit,
                        health_url="http://x/health", transaction_url="http://x/transaction")


def make_engine(workloads=("pos-a",), **cfg):
    sim = SimulationOrchestrator()
    specs = []
    for i, w in enumerate(workloads):
        sim.add(w)
        specs.append(spec(w, f"store-{i}"))
    clock = FakeClock()
    base = dict(base_backoff_s=2.0, verify_deadline_s=10.0, approval_timeout_s=100.0)
    base.update(cfg)
    eng = AutopilotEngine(specs, sim, SimProber(sim), EngineConfig(**base), clock=clock)
    return eng, sim, clock


def run(eng, clock, steps: int, dt: float = 1.0, until=None):
    for _ in range(steps):
        clock.advance(dt)
        eng.tick()
        if until and until():
            return
