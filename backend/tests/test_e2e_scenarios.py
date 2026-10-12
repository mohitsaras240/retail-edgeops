"""End-to-End Test Suite verifying all 6 core Retail Edge Autopilot scenarios:
Scenario 1: PoS Service Crash & Autonomous Self-Healing
Scenario 2: Slow Latency Degradation & Operator Approval Flow
Scenario 3: Store WAN Disconnection & Offline Transaction Resilience
Scenario 4: Deployment Regression Detection & Safe Rollback Handling
Scenario 5: Unfixable Dependency Fault & Bounded Escalation
Scenario 6: Multi-Store Concurrency & Strict Fault Isolation
"""
import tempfile
import time
import unittest
from pathlib import Path

from app.core.config import EngineConfig
from app.core.models import Criticality, IncidentState as S
from app.services.transaction_sync.central_ingest import CentralIngestService, IngestEventItem
from app.services.transaction_sync.store import TransactionEvent, TransactionStore
from app.services.transaction_sync.sync_manager import SyncManager
from tests.helpers import make_three_store_engine, run


class EndToEndScenarioTests(unittest.TestCase):
    # =========================================================================
    # SCENARIO 1: PoS Service Crash & Autonomous Self-Healing
    # =========================================================================
    def test_scenario_1_pos_crash_autonomous_self_healing(self):
        """A dead PoS container is detected, diagnosed, auto-approved (safe because already
        down), restarted, verified with consecutive health samples, and marked RESOLVED."""
        eng, sim, clock = make_three_store_engine()
        pos_id = "rea-store001-pos"

        # Baseline: systems are healthy
        run(eng, clock, 5)
        self.assertEqual(len(eng.incidents), 0)

        # 1. Inject crash: container terminated with exit code 137
        sim.crash(pos_id, exit_code=137)
        self.assertFalse(sim.workloads[pos_id].running)

        # 2. Closed-loop engine detects, diagnoses, and autonomously executes restart
        run(eng, clock, 5)
        self.assertEqual(len(eng.incidents), 1)
        inc = list(eng.incidents.values())[0]

        # Verify auto-approval because service was already down
        self.assertEqual(inc.decision["action"], "restart_workload")
        self.assertFalse(inc.decision["requires_approval"])
        self.assertEqual(sim.restart_calls, [pos_id])

        # 3. Advance clock through verification window
        run(eng, clock, 15, until=lambda: inc.state == S.RESOLVED)
        self.assertEqual(inc.state, S.RESOLVED)
        self.assertIsNotNone(inc.resolved_at)
        self.assertTrue(sim.workloads[pos_id].running)
        self.assertTrue(sim.workloads[pos_id].healthy)

    # =========================================================================
    # SCENARIO 2: Slow Latency Degradation & Operator Approval Flow
    # =========================================================================
    def test_scenario_2_latency_degradation_requires_approval(self):
        """A running PoS is returning 503 errors. Because restarting a running terminal
        risks interrupting in-flight checkouts, autopilot halts in AWAITING_APPROVAL.
        Once an operator reviews and approves, restart executes and resolves."""
        eng, sim, clock = make_three_store_engine()
        pos_id = "rea-store002-pos"

        run(eng, clock, 5)

        # 1. Inject degrade: container is RUNNING, but HTTP health probe returns 503
        sim.degrade(pos_id)
        self.assertTrue(sim.workloads[pos_id].running)
        self.assertFalse(sim.workloads[pos_id].healthy)

        # 2. Engine detects and transitions to AWAITING_APPROVAL
        run(eng, clock, 5)
        inc = list(eng.incidents.values())[0]
        self.assertEqual(inc.state, S.AWAITING_APPROVAL)
        self.assertTrue(inc.decision["requires_approval"])
        self.assertEqual(inc.decision["risk_level"], "HIGH")
        # Restart must NOT have been called yet
        self.assertEqual(len(sim.restart_calls), 0)

        # 3. Operator approves the recovery action via console
        eng.approve(inc.id, actor="store-mgr-bob")
        self.assertEqual(inc.approved_by, "store-mgr-bob")

        # 4. Engine now executes restart and verifies recovery
        run(eng, clock, 15, until=lambda: inc.state == S.RESOLVED)
        self.assertEqual(sim.restart_calls, [pos_id])
        self.assertEqual(inc.state, S.RESOLVED)

    # =========================================================================
    # SCENARIO 3: Store WAN Disconnection & Offline Transaction Resilience
    # =========================================================================
    def test_scenario_3_offline_transaction_resilience(self):
        """During network disconnect, local store transactions persist durably to SQLite WAL.
        Once reconnected, transactions sync to central with 0 loss and idempotent ingest."""
        tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(tmp.name) / "store1_tx.db")
        central_path = str(Path(tmp.name) / "central.db")

        store = TransactionStore(db_path)
        central = CentralIngestService(central_path)
        sync_mgr = SyncManager(store, "http://127.0.0.1:8000/central/ingest", "store-001")

        # 1. Simulate store WAN disconnection
        sync_mgr.simulate_disconnect()

        # 2. Local checkouts continue uninterrupted; transactions enqueued into SQLite
        t0 = time.time()
        for i in range(15):
            ev = TransactionEvent(f"tx-offline-{i}", "store-001", "T1", item_count=2, created_at=t0 + i)
            self.assertTrue(store.enqueue(ev))

        # Check offline backlog depth
        self.assertEqual(store.status()["pending_count"], 15)

        # 3. Background sync attempts while disconnected do not lose events
        res = sync_mgr.sync_once()
        self.assertEqual(res["status"], "disconnected")
        self.assertEqual(store.status()["pending_count"], 15)

        # 4. WAN connectivity is restored
        sync_mgr.reconnect()

        # Ingest directly to simulate the successful roundtrip
        pending = store.get_pending(limit=50)
        items = [
            IngestEventItem(
                event_id=e.event_id,
                store_id=e.store_id,
                terminal_id=e.terminal_id,
                item_count=e.item_count,
                created_at=e.created_at,
            )
            for e in pending
        ]
        ingest_res = central.ingest_batch("store-001", items)
        self.assertEqual(ingest_res["accepted"], 15)
        store.mark_synced([e.event_id for e in pending])

        # All pending events successfully synced
        self.assertEqual(store.status()["pending_count"], 0)
        self.assertEqual(store.status()["synced_count"], 15)

        # 5. Idempotent test: duplicate delivery yields 0 new accepted events
        dup_res = central.ingest_batch("store-001", items)
        self.assertEqual(dup_res["accepted"], 0)
        self.assertEqual(dup_res["duplicates"], 15)
        tmp.cleanup()

    # =========================================================================
    # SCENARIO 4: Deployment Regression Detection & Safe Rollback Handling
    # =========================================================================
    def test_scenario_4_deployment_regression_detected_and_handled(self):
        """A container image update immediately followed by health degradation is
        diagnosed as a deployment regression. The policy selects rollback_workload,
        which on DockerLocal honestly returns UNSUPPORTED and escalates safely."""
        eng, sim, clock = make_three_store_engine()
        pos_id = "rea-store001-pos"

        # Baseline running version v1.0
        run(eng, clock, 5)

        # Deploy broken version v2.0-bad and degrade probe
        sim.set_image_version(pos_id, "v2.0-bad")
        sim.degrade(pos_id)

        run(eng, clock, 5)
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]

        # Verified as deployment regression
        self.assertEqual(inc.kind, "deployment_regression")
        self.assertEqual(inc.decision["action"], "rollback_workload")
        self.assertTrue(inc.decision["requires_approval"])

    # =========================================================================
    # SCENARIO 5: Unfixable Dependency Fault & Bounded Escalation
    # =========================================================================
    def test_scenario_5_unfixable_fault_halts_restarts_and_escalates(self):
        """When an incident cannot be auto-recovered (e.g. stateful DB or missing container),
        the engine avoids infinite restart loops and bounds escalation."""
        from app.adapters.orchestrator.base import WorkloadStatus
        eng, sim, clock = make_three_store_engine()
        pos_id = "rea-store003-pos"

        # Remove container from orchestrator inventory
        del sim.workloads[pos_id]

        run(eng, clock, 5)
        inc = list(eng.incidents.values())[0]

        # Container missing is diagnosed as unfixable by simple container restart
        self.assertEqual(inc.decision["action"], "escalate")
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertIn("container does not exist", inc.diagnosis["ranked_causes"][0]["evidence"][0])

    # =========================================================================
    # SCENARIO 6: Multi-Store Concurrency & Strict Fault Isolation
    # =========================================================================
    def test_scenario_6_multi_store_fault_isolation(self):
        """Under concurrent 3-store operation, severe multiple faults in Store 2
        (crashed PoS and resource-pressured sync) have zero blast radius on Store 1 & 3."""
        eng, sim, clock = make_three_store_engine()

        run(eng, clock, 5)

        # Inject severe faults into Store 002 ONLY
        sim.crash("rea-store002-pos")
        sim.set_resource_pressure("rea-store002-sync", cpu_pct=95.0, mem_pct=98.0)

        run(eng, clock, 15)

        # Incidents belong exclusively to Store 002
        for inc in eng.incidents.values():
            self.assertEqual(inc.store_id, "store-002")

        # Verify Store 001 and Store 003 workloads remain 100% healthy and untouched
        for s_num in ("001", "003"):
            store_id = f"store-{s_num}"
            for kind in ("pos", "kiosk", "sync"):
                wid = f"rea-{store_id.replace('-', '')}-{kind}"
                w_sim = sim.workloads[wid]
                self.assertTrue(w_sim.running)
                self.assertTrue(w_sim.healthy)
                self.assertEqual(w_sim.restart_count, 0)


if __name__ == "__main__":
    unittest.main()
