import time
import unittest

from app.core.config import EngineConfig
from app.core.models import Criticality, Incident, IncidentState as S, ProbeResult, Severity, WorkloadSpec
from app.services.diagnosis.rules import diagnose
from app.services.recovery_policy.policy import decide
from app.services.telemetry.rolling_buffer import RollingTelemetryBuffer
from tests.helpers import make_three_store_engine, run


def make_spec(wid="pos-1", store="store-001", crit=Criticality.CRITICAL, stateless=True):
    return WorkloadSpec(
        id=wid,
        store_id=store,
        kind="pos",
        criticality=crit,
        health_url=f"http://{wid}/health",
        transaction_url=f"http://{wid}/transaction",
        stateless=stateless,
    )


class Phase3RollingTelemetryTests(unittest.TestCase):
    def test_rolling_telemetry_aggregations(self):
        buf = RollingTelemetryBuffer(window_seconds=60.0)
        t0 = 1000.0
        # Record 10 healthy samples with varying latencies
        for i in range(10):
            buf.record("pos-1", ts=t0 + i, latency_ms=10.0 + i * 2, status_code=200, ok=True, cpu_pct=25.0, mem_pct=40.0)

        # Record 2 failing samples
        buf.record("pos-1", ts=t0 + 10, latency_ms=None, status_code=503, ok=False, cpu_pct=30.0, mem_pct=45.0)
        buf.record("pos-1", ts=t0 + 11, latency_ms=None, status_code=503, ok=False, cpu_pct=30.0, mem_pct=45.0)

        m = buf.metrics("pos-1", now=t0 + 15)
        self.assertEqual(m["sample_count"], 12)
        self.assertAlmostEqual(m["error_rate"], 2 / 12, places=2)
        self.assertIsNotNone(m["mean_latency_ms"])
        self.assertIsNotNone(m["p95_latency_ms"])
        self.assertGreater(m["p95_latency_ms"], m["mean_latency_ms"])

    def test_statistical_latency_spike_detection(self):
        buf = RollingTelemetryBuffer(window_seconds=60.0)
        t0 = 1000.0
        # Establish stable 15ms baseline over 10 points
        for i in range(10):
            buf.record("pos-1", ts=t0 + i, latency_ms=15.0, status_code=200, ok=True)

        # Normal latency: no spike
        spike = buf.detect_latency_spike("pos-1", current_latency_ms=25.0, now=t0 + 11)
        self.assertIsNone(spike)

        # 500ms latency spike (exceeds 3x baseline and 200ms minimum threshold)
        spike = buf.detect_latency_spike("pos-1", current_latency_ms=520.0, now=t0 + 12)
        self.assertIsNotNone(spike)
        self.assertEqual(spike["signal"], "statistical_latency_spike")
        self.assertEqual(spike["current_latency_ms"], 520.0)
        self.assertGreater(spike["ratio_to_baseline"], 10.0)


class Phase3MultiSignalDiagnosisTests(unittest.TestCase):
    def test_multi_signal_ranked_cause_ordering(self):
        inc = Incident(
            id="inc-1",
            workload_id="pos-1",
            store_id="store-001",
            kind="pos_service_unresponsive",
            severity=Severity.HIGH,
            detected_at=1000.0,
            evidence=[{"signal": "health_probe", "ok": False}],
            provenance="simulated",
        )
        from app.adapters.orchestrator.base import WorkloadStatus
        status = WorkloadStatus(workload_id="pos-1", provenance="simulated", found=True, running=True)
        health = ProbeResult(ok=False, latency_ms=None, status_code=503, error="Service Unavailable", ts=1000.0)

        # 1. Without dependencies failing: top cause is unresponsive_process
        d = diagnose(inc, status, health)
        self.assertEqual(d["ranked_causes"][0]["cause"], "unresponsive_process")
        self.assertIn("confidence", d["ranked_causes"][0])

        # 2. When same-store dependency is failing: dependency_unavailable ranks higher
        d_dep = diagnose(inc, status, health, dependency_health={"sync-1": False})
        self.assertEqual(d_dep["ranked_causes"][0]["cause"], "dependency_unavailable")
        self.assertEqual(d_dep["ranked_causes"][0]["confidence"], "high")
        self.assertIn("do not restart", d_dep["ranked_causes"][0]["next_steps"][1])


class Phase3RiskAwarePolicyTests(unittest.TestCase):
    cfg = EngineConfig()

    def test_in_flight_checkout_disruption_requires_approval(self):
        from app.adapters.orchestrator.base import WorkloadStatus
        sp = make_spec("pos-1", "store-001", Criticality.CRITICAL)
        st = WorkloadStatus(workload_id="pos-1", provenance="simulated", found=True, running=True)
        diag = {
            "ranked_causes": [{"cause": "unresponsive_process", "score": 75, "confidence": "medium"}],
            "method": "multi_signal_ranked_v3",
        }
        inc = Incident(
            id="inc-1",
            workload_id="pos-1",
            store_id="store-001",
            kind="pos_service_unresponsive",
            severity=Severity.HIGH,
            detected_at=1000.0,
            evidence=[],
            provenance="simulated",
        )

        decision = decide(inc, sp, st, diag, self.cfg)
        self.assertEqual(decision.action, "restart_workload")
        self.assertTrue(decision.requires_approval)
        self.assertEqual(decision.risk_level, "HIGH")
        self.assertIn("in-flight checkout disruption", decision.estimated_disruption)

    def test_crashed_service_has_low_disruption_risk(self):
        from app.adapters.orchestrator.base import WorkloadStatus
        sp = make_spec("pos-1", "store-001", Criticality.CRITICAL)
        st = WorkloadStatus(workload_id="pos-1", provenance="simulated", found=True, running=False, exit_code=137)
        diag = {
            "ranked_causes": [{"cause": "process_crash", "score": 85, "confidence": "high"}],
            "method": "multi_signal_ranked_v3",
        }
        inc = Incident(
            id="inc-1",
            workload_id="pos-1",
            store_id="store-001",
            kind="pos_service_crash",
            severity=Severity.CRITICAL,
            detected_at=1000.0,
            evidence=[],
            provenance="simulated",
        )

        decision = decide(inc, sp, st, diag, self.cfg)
        self.assertEqual(decision.action, "restart_workload")
        self.assertFalse(decision.requires_approval)
        self.assertEqual(decision.risk_level, "LOW")

    def test_unfixable_dependency_failure_escalates_without_restart(self):
        from app.adapters.orchestrator.base import WorkloadStatus
        sp = make_spec("pos-1", "store-001", Criticality.CRITICAL)
        st = WorkloadStatus(workload_id="pos-1", provenance="simulated", found=True, running=True)
        diag = {
            "ranked_causes": [{"cause": "dependency_unavailable", "score": 90, "confidence": "high"}],
            "method": "multi_signal_ranked_v3",
        }
        inc = Incident(
            id="inc-1",
            workload_id="pos-1",
            store_id="store-001",
            kind="pos_service_unresponsive",
            severity=Severity.HIGH,
            detected_at=1000.0,
            evidence=[],
            provenance="simulated",
        )

        decision = decide(inc, sp, st, diag, self.cfg)
        self.assertEqual(decision.action, "escalate")
        self.assertFalse(decision.requires_approval)
        self.assertIn("dependency unavailable", decision.reason)


class Phase3EngineAndApiIntegrationTests(unittest.TestCase):
    def test_engine_collects_rolling_telemetry(self):
        eng, sim, clock = make_three_store_engine()
        run(eng, clock, 10)

        # Check telemetry for one PoS workload
        m = eng.telemetry_buffer.metrics("rea-store001-pos", now=clock())
        self.assertEqual(m["sample_count"], 10)
        self.assertEqual(m["error_rate"], 0.0)
        self.assertIsNotNone(m["mean_latency_ms"])

    def test_api_diagnosis_and_telemetry_endpoints(self):
        import tempfile
        from fastapi.testclient import TestClient
        from app.api.routes import create_app
        from app.services.transaction_sync.central_ingest import CentralIngestService
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        central_db = str(Path(tmp.name) / "central_p3.db")
        central = CentralIngestService(central_db)
        eng, sim, clock = make_three_store_engine()
        key = "k" * 20
        client = TestClient(create_app(eng, api_key=key, run_loop=False, central_service=central))
        h = {"X-API-Key": key}

        # 1. Warm up telemetry
        run(eng, clock, 5)

        # 2. Query workload telemetry endpoint
        tel_resp = client.get("/api/workloads/rea-store001-pos/telemetry", headers=h)
        self.assertEqual(tel_resp.status_code, 200)
        t_data = tel_resp.json()
        self.assertEqual(t_data["workload_id"], "rea-store001-pos")
        self.assertEqual(t_data["metrics"]["sample_count"], 5)

        # 3. Inject fault and check diagnosis endpoint
        sim.degrade("rea-store001-pos")
        run(eng, clock, 5)
        incs = client.get("/api/incidents", headers=h).json()
        self.assertGreater(len(incs), 0)
        inc_id = incs[0]["id"]

        diag_resp = client.get(f"/api/incidents/{inc_id}/diagnosis", headers=h)
        self.assertEqual(diag_resp.status_code, 200)
        d_data = diag_resp.json()
        self.assertEqual(d_data["incident_id"], inc_id)
        self.assertIsNotNone(d_data["diagnosis"])
        self.assertIsNotNone(d_data["decision"])
        self.assertIn("risk_level", d_data["decision"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
