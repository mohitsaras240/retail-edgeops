import unittest

from app.core.models import IncidentState as S
from tests.helpers import make_three_store_engine, run


class MultiStoreIsolationAndExtendedRulesTests(unittest.TestCase):
    def test_three_stores_running_healthy(self):
        eng, sim, clock = make_three_store_engine()
        run(eng, clock, 5)
        self.assertEqual(len(eng.specs), 9)
        self.assertEqual(len(eng.incidents), 0)
        stores_view = eng.stores_view()
        self.assertEqual(len(stores_view), 3)
        for s in stores_view:
            self.assertEqual(len(s["workloads"]), 3)
            self.assertEqual(s["open_incidents"], 0)

    def test_store_fault_isolation(self):
        eng, sim, clock = make_three_store_engine()
        # Crash PoS in Store 002 only
        sim.crash("rea-store002-pos")
        run(eng, clock, 20, until=lambda: any(i.state == S.RESOLVED for i in eng.incidents.values()))

        # Check incidents
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.store_id, "store-002")
        self.assertEqual(inc.workload_id, "rea-store002-pos")
        self.assertEqual(inc.state, S.RESOLVED)

        # Confirm restart targeted only store-002 pos
        self.assertEqual(sim.restart_calls, ["rea-store002-pos"])

        # Check Store 001 and Store 003 workloads were completely untouched
        for s_num in ("001", "003"):
            for kind in ("pos", "kiosk", "sync"):
                wid = f"rea-store{s_num}-{kind}"
                self.assertEqual(sim.workloads[wid].restart_count, 0)
                self.assertTrue(sim.workloads[wid].running)

    def test_kiosk_incident_isolated_within_store(self):
        eng, sim, clock = make_three_store_engine()
        # Degrade Kiosk in Store 001
        sim.degrade("rea-store001-kiosk")
        run(eng, clock, 10)

        # Kiosk is running but unhealthy -> awaiting approval
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.workload_id, "rea-store001-kiosk")
        self.assertEqual(inc.state, S.AWAITING_APPROVAL)

        # PoS in the same store remains completely unaffected and healthy
        pos_status = sim.workloads["rea-store001-pos"]
        self.assertTrue(pos_status.running)
        self.assertTrue(pos_status.healthy)

        # Approve and resolve kiosk
        eng.approve(inc.id, "store-manager-alice")
        run(eng, clock, 20, until=lambda: inc.state == S.RESOLVED)
        self.assertEqual(inc.state, S.RESOLVED)

    def test_resource_pressure_pauses_deferrable_sync_workload(self):
        eng, sim, clock = make_three_store_engine()
        # Inject CPU/Memory pressure into store 001's deferrable sync service
        sync_wid = "rea-store001-sync"
        sim.set_resource_pressure(sync_wid, cpu_pct=92.0, mem_pct=95.0)

        run(eng, clock, 10, until=lambda: len(eng.incidents) > 0)
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.kind, "resource_pressure")
        self.assertEqual(inc.workload_id, sync_wid)
        # Deferrable policy decision should be defer_workload (pause)
        self.assertEqual(inc.decision["action"], "defer_workload")
        self.assertFalse(inc.decision["requires_approval"])
        # Should have called pause_workload
        self.assertEqual(sim.pause_calls, [sync_wid])
        self.assertTrue(sim.workloads[sync_wid].paused)

    def test_resource_pressure_on_critical_pos_escalates(self):
        eng, sim, clock = make_three_store_engine()
        pos_wid = "rea-store001-pos"
        sim.set_resource_pressure(pos_wid, cpu_pct=95.0, mem_pct=98.0)

        run(eng, clock, 10, until=lambda: len(eng.incidents) > 0)
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.kind, "resource_pressure")
        # Critical workload under pressure should escalate rather than pause checkout
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertIn("escalate", inc.escalation_reason)

    def test_deployment_regression_detected_and_escalated_safely(self):
        eng, sim, clock = make_three_store_engine()
        pos_wid = "rea-store001-pos"

        # Advance clock to establish baseline image version
        run(eng, clock, 5)

        # Update image version to v2.0-bad and degrade health
        sim.set_image_version(pos_wid, "v2.0-bad")
        sim.degrade(pos_wid)

        run(eng, clock, 10, until=lambda: len(eng.incidents) > 0)
        incs = list(eng.incidents.values())
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.kind, "deployment_regression")
        self.assertEqual(inc.decision["action"], "rollback_workload")
        self.assertTrue(inc.decision["requires_approval"])

    def test_sync_backlog_growth_detection(self):
        eng, sim, clock = make_three_store_engine()
        store_id = "store-001"

        # Progressively report growing sync backlog for store-001 across ticks
        for pending_count in (10, 25, 40, 60, 85):
            eng.report_sync_status(store_id, pending_count)
            clock.advance(1.0)
            eng.tick()

        incs = [i for i in eng.incidents.values() if i.kind == "sync_backlog_growth"]
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0].store_id, store_id)
        self.assertEqual(incs[0].state, S.ESCALATED)


if __name__ == "__main__":
    unittest.main()
