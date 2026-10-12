import unittest

from app.core.config import EngineConfig
from app.core.models import Criticality, Incident, Provenance, Severity
from app.services.diagnosis.rules import diagnose
from app.services.recovery_executor.audit import AuditLog
from app.services.recovery_executor.executor import RecoveryExecutor
from app.services.recovery_policy.policy import PolicyDecision, decide
from app.adapters.orchestrator.simulation import SimulationOrchestrator
from app.adapters.orchestrator.base import WorkloadStatus
from tests.helpers import spec


def inc(kind="pos_service_crash", attempts=0):
    i = Incident("i1", "pos-a", "s0", kind, Severity.CRITICAL, 1.0, [], Provenance.SIMULATED)
    i.attempts = attempts
    return i


def status(found=True, running=False, exit_code=1, oom=False, health=None):
    return WorkloadStatus("pos-a", Provenance.SIMULATED, found=found, running=running, exit_code=exit_code,
                          oom_killed=oom, health=health)


class DiagnosisTests(unittest.TestCase):
    def top(self, st, health=None, logs=""):
        return diagnose(inc(), st, health, logs)["ranked_causes"][0]["cause"]

    def test_causes(self):
        self.assertEqual(self.top(status(found=False)), "container_missing")
        self.assertEqual(self.top(status(oom=True, exit_code=137)), "out_of_memory")
        self.assertEqual(self.top(status(exit_code=137)), "killed_by_signal")
        self.assertEqual(self.top(status(exit_code=1)), "process_crash")
        self.assertEqual(self.top(status(exit_code=0)), "clean_exit")
        self.assertEqual(self.top(status(running=True)), "unresponsive_process")

    def test_diagnosis_does_not_claim_probabilities(self):
        d = diagnose(inc(), status(), None)
        self.assertIn("not probabilities", d["note"])


class PolicyTests(unittest.TestCase):
    cfg = EngineConfig()

    def d(self, st, attempts=0, cfg=None, stateless=True):
        sp = spec("pos-a", "s0")
        if not stateless:
            sp = type(sp)(**{**sp.__dict__, "stateless": False})
        diag = diagnose(inc(), st, None)
        return decide(inc(attempts=attempts), sp, st, diag, cfg or self.cfg)

    def test_down_service_restart_is_auto_approved(self):
        d = self.d(status(exit_code=137))
        self.assertEqual((d.action, d.requires_approval), ("restart_workload", False))

    def test_running_unhealthy_service_needs_approval(self):
        d = self.d(status(running=True))
        self.assertEqual((d.action, d.requires_approval), ("restart_workload", True))

    def test_always_and_never_modes(self):
        self.assertTrue(self.d(status(exit_code=137), cfg=EngineConfig(approval_mode="always")).requires_approval)
        self.assertFalse(self.d(status(running=True), cfg=EngineConfig(approval_mode="never")).requires_approval)

    def test_missing_container_escalates(self):
        self.assertEqual(self.d(status(found=False)).action, "escalate")

    def test_retry_budget_escalates(self):
        self.assertEqual(self.d(status(exit_code=137), attempts=2).action, "escalate")

    def test_stateful_workload_not_auto_restarted(self):
        self.assertEqual(self.d(status(exit_code=137), stateless=False).action, "escalate")

    def test_dependency_unavailable_escalates_without_restarting(self):
        sp = spec("pos-a", "s0")
        st = status(running=True)
        # Diagnosis reports dependency unavailable
        diag = {"ranked_causes": [{"cause": "dependency_unavailable", "score": 90}], "method": "rule_based_v2"}
        dec = decide(inc(), sp, st, diag, self.cfg)
        self.assertEqual(dec.action, "escalate")
        self.assertIn("dependency unavailable", dec.reason)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.sim = SimulationOrchestrator()
        self.sim.add("pos-a")
        self.sim.crash("pos-a")
        self.audit = AuditLog()
        self.cfg = EngineConfig(base_backoff_s=10.0)
        self.ex = RecoveryExecutor(self.sim, self.audit, self.cfg)
        self.sp = spec("pos-a", "s0")

    def dec(self, action="restart_workload", approval=False):
        return PolicyDecision(action, approval, True, "t")

    def test_allowlist_blocks_arbitrary_actions(self):
        for bad in ("exec_shell", "rm -rf /", "docker_kill", ""):
            rec = self.ex.execute(inc(), self.dec(bad), self.sp, 1.0)
            self.assertEqual(rec.status, "REJECTED")
        self.assertEqual(self.sim.restart_calls, [])

    def test_missing_approval_blocks_execution(self):
        rec = self.ex.execute(inc(), self.dec(approval=True), self.sp, 1.0)
        self.assertEqual(rec.status, "REJECTED")
        self.assertEqual(self.sim.restart_calls, [])

    def test_executes_and_audits(self):
        rec = self.ex.execute(inc(), self.dec(), self.sp, 1.0)
        self.assertEqual(rec.status, "EXECUTED")
        self.assertEqual(self.sim.restart_calls, ["pos-a"])
        self.assertEqual(self.audit.entries()[-1]["status"], "EXECUTED")

    def test_exponential_backoff_between_attempts(self):
        self.ex.execute(inc(), self.dec(), self.sp, 100.0)
        self.assertEqual(self.ex.execute(inc(attempts=1), self.dec(), self.sp, 105.0).status, "COOLDOWN")
        self.assertEqual(self.ex.execute(inc(attempts=1), self.dec(), self.sp, 110.0).status, "EXECUTED")
        self.assertEqual(self.ex.execute(inc(attempts=2), self.dec(), self.sp, 125.0).status, "COOLDOWN")  # needs 20s
        self.assertEqual(self.ex.execute(inc(attempts=2), self.dec(), self.sp, 130.0).status, "EXECUTED")

    def test_dry_run_changes_nothing(self):
        ex = RecoveryExecutor(self.sim, self.audit, EngineConfig(dry_run=True))
        rec = ex.execute(inc(), self.dec(), self.sp, 1.0)
        self.assertEqual(rec.status, "DRY_RUN")
        self.assertEqual(self.sim.restart_calls, [])

    def test_idempotent_when_already_running(self):
        self.sim.workloads["pos-a"].running = True
        rec = self.ex.execute(inc(), self.dec(), self.sp, 1.0)
        self.assertEqual(rec.status, "SKIPPED_ALREADY_HEALTHY")
        self.assertEqual(self.sim.restart_calls, [])

    def test_defer_workload_pauses_workload(self):
        rec = self.ex.execute(inc(), self.dec("defer_workload"), self.sp, 1.0)
        self.assertEqual(rec.status, "EXECUTED")
        self.assertEqual(self.sim.pause_calls, ["pos-a"])
        self.assertTrue(self.sim.workloads["pos-a"].paused)

    def test_rollback_reports_unsupported_on_docker_local(self):
        from app.adapters.orchestrator.docker_local import DockerLocalOrchestrator
        orch = DockerLocalOrchestrator(runner=lambda args, t: (0, "", ""))
        ex = RecoveryExecutor(orch, self.audit, self.cfg)
        rec = ex.execute(inc(), self.dec("rollback_workload"), self.sp, 1.0)
        self.assertEqual(rec.status, "REJECTED")
        self.assertIn("unsupported by orchestrator", rec.detail)


if __name__ == "__main__":
    unittest.main()
