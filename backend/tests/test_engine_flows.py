import unittest

from app.core.models import IncidentState as S
from tests.helpers import make_engine, run


def only(eng):
    incs = list(eng.incidents.values())
    assert len(incs) == 1, f"expected 1 incident, got {len(incs)}"
    return incs[0]


class CrashRecoveryTests(unittest.TestCase):
    def test_crash_detected_restarted_and_verified(self):
        eng, sim, clock = make_engine()
        run(eng, clock, 3)
        self.assertEqual(eng.incidents, {})                 # healthy: nothing opened
        sim.crash("pos-a")
        run(eng, clock, 20, until=lambda: any(i.state == S.RESOLVED for i in eng.incidents.values()))
        inc = only(eng)
        self.assertEqual(inc.state, S.RESOLVED)
        self.assertEqual(sim.restart_calls, ["pos-a"])
        self.assertTrue(inc.verification["passed"])
        self.assertTrue(all(c["passed"] for c in inc.verification["checks"]))
        states = [t["state"] for t in inc.timeline if t["event"] == "state_change"]
        self.assertEqual(states, ["DIAGNOSING", "RECOVERING", "VERIFYING", "RESOLVED"])
        self.assertEqual(inc.diagnosis["ranked_causes"][0]["cause"], "killed_by_signal")
        self.assertEqual(inc.provenance.value, "simulated")

    def test_single_bad_sample_does_not_open_incident(self):
        eng, sim, clock = make_engine(fail_threshold=3)
        sim.crash("pos-a")
        run(eng, clock, 2)
        self.assertEqual(eng.incidents, {})

    def test_restart_issued_is_not_resolution(self):
        # restart "succeeds" but service stays unhealthy: must not be marked RESOLVED
        eng, sim, clock = make_engine()
        sim.add("pos-a", restart_fixes_fault=False)
        sim.crash("pos-a")
        run(eng, clock, 8)
        inc = only(eng)
        self.assertEqual(inc.state, S.VERIFYING)
        self.assertNotEqual(inc.state, S.RESOLVED)
        self.assertEqual(len(sim.restart_calls), 1)


class UnresponsiveAndApprovalTests(unittest.TestCase):
    def test_running_but_unhealthy_waits_for_approval_then_recovers(self):
        eng, sim, clock = make_engine()
        sim.degrade("pos-a")
        run(eng, clock, 20)
        inc = only(eng)                                       # dedup: still exactly one incident
        self.assertEqual(inc.state, S.AWAITING_APPROVAL)
        self.assertEqual(sim.restart_calls, [])               # nothing executed without approval
        eng.approve(inc.id, "alice")
        run(eng, clock, 20, until=lambda: inc.state == S.RESOLVED)
        self.assertEqual(inc.state, S.RESOLVED)
        self.assertEqual(inc.approved_by, "alice")
        self.assertEqual(inc.actions[0]["approved_by"], "alice")

    def test_reject_escalates_without_acting(self):
        eng, sim, clock = make_engine()
        sim.degrade("pos-a")
        run(eng, clock, 5)
        inc = only(eng)
        eng.reject(inc.id, "bob", "not now")
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertEqual(sim.restart_calls, [])

    def test_approval_timeout_escalates(self):
        eng, sim, clock = make_engine(approval_timeout_s=5.0)
        sim.degrade("pos-a")
        run(eng, clock, 15)
        self.assertEqual(only(eng).state, S.ESCALATED)

    def test_cannot_approve_in_wrong_state(self):
        eng, sim, clock = make_engine()
        sim.crash("pos-a")
        run(eng, clock, 20, until=lambda: any(i.state == S.RESOLVED for i in eng.incidents.values()))
        from app.services.engine import EngineError
        with self.assertRaises(EngineError):
            eng.approve(only(eng).id, "mallory")


class FailureAndEscalationTests(unittest.TestCase):
    def test_unfixable_fault_is_bounded_then_escalated(self):
        eng, sim, clock = make_engine(max_attempts=2, approval_mode="never")
        sim.add("pos-a", restart_fixes_fault=False)
        sim.crash("pos-a")
        run(eng, clock, 80, until=lambda: any(not i.is_open for i in eng.incidents.values()))
        inc = only(eng)
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertEqual(len(sim.restart_calls), 2)           # exactly max_attempts, no restart loop
        run(eng, clock, 40)
        self.assertEqual(len(sim.restart_calls), 2)           # and it stays that way
        self.assertIn("retry budget", inc.escalation_reason)
        self.assertFalse(inc.verification["passed"])           # failure evidence preserved
        self.assertTrue(any(e["event"] == "verification_failed" for e in eng.audit.entries()))

    def test_second_attempt_needs_its_own_approval(self):
        # first restart is auto-approved (service was down); the retry targets a running-but-unhealthy
        # service, so the earlier auto-approval must NOT carry over
        eng, sim, clock = make_engine(max_attempts=3)
        sim.add("pos-a", restart_fixes_fault=False)
        sim.crash("pos-a")
        run(eng, clock, 40, until=lambda: any(i.state == S.AWAITING_APPROVAL for i in eng.incidents.values()))
        inc = only(eng)
        self.assertEqual(inc.state, S.AWAITING_APPROVAL)
        self.assertIsNone(inc.approved_by)
        self.assertEqual(len(sim.restart_calls), 1)

    def test_escalated_incident_suppresses_duplicates_until_healthy(self):
        eng, sim, clock = make_engine(max_attempts=1, approval_mode="never")
        sim.add("pos-a", restart_fixes_fault=False)
        sim.crash("pos-a")
        run(eng, clock, 60)
        self.assertEqual(only(eng).state, S.ESCALATED)         # 60 ticks of a persisting fault: still one incident
        sim.workloads["pos-a"].healthy = True                  # operator fixes it by hand
        run(eng, clock, 3)
        sim.degrade("pos-a")                                   # a new, separate failure
        run(eng, clock, 6)
        self.assertEqual(len(eng.incidents), 2)

    def test_dry_run_escalates_without_acting(self):
        eng, sim, clock = make_engine(dry_run=True)
        sim.crash("pos-a")
        run(eng, clock, 6)
        inc = only(eng)
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertEqual(inc.actions[0]["status"], "DRY_RUN")
        self.assertEqual(sim.restart_calls, [])

    def test_orchestrator_outage_is_not_misreported_as_service_crash(self):
        eng, sim, clock = make_engine()
        sim.daemon_down = True
        run(eng, clock, 10)
        self.assertEqual(eng.incidents, {})
        self.assertIn("pos-a", eng.monitoring_errors)
        sim.daemon_down = False
        run(eng, clock, 2)
        self.assertEqual(eng.monitoring_errors, {})

    def test_missing_container_escalates_instead_of_restarting(self):
        eng, sim, clock = make_engine()
        del sim.workloads["pos-a"]                             # container no longer exists
        run(eng, clock, 5)
        inc = only(eng)
        self.assertEqual(inc.state, S.ESCALATED)
        self.assertEqual(sim.restart_calls, [])


class IsolationTests(unittest.TestCase):
    def test_fault_in_one_store_does_not_touch_others(self):
        eng, sim, clock = make_engine(workloads=("pos-a", "pos-b", "pos-c"))
        sim.crash("pos-b")
        run(eng, clock, 20, until=lambda: any(i.state == S.RESOLVED for i in eng.incidents.values()))
        inc = only(eng)
        self.assertEqual((inc.workload_id, inc.store_id, inc.state), ("pos-b", "store-1", S.RESOLVED))
        self.assertEqual(sim.restart_calls, ["pos-b"])
        for other in ("pos-a", "pos-c"):
            self.assertEqual(sim.workloads[other].restart_count, 0)
            self.assertTrue(sim.workloads[other].running)
        self.assertTrue(all(a["workload_id"] == "pos-b" for i in eng.incidents.values() for a in i.actions))

    def test_recurrence_is_linked_not_hidden(self):
        eng, sim, clock = make_engine()
        sim.crash("pos-a")
        run(eng, clock, 20, until=lambda: any(i.state == S.RESOLVED for i in eng.incidents.values()))
        first = only(eng)
        sim.crash("pos-a")
        run(eng, clock, 20, until=lambda: len(eng.incidents) == 2)
        second = [i for i in eng.incidents.values() if i.id != first.id][0]
        self.assertEqual(second.recurrence_of, first.id)


if __name__ == "__main__":
    unittest.main()
