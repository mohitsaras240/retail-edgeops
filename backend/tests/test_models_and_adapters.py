import json
import unittest

from app.adapters.orchestrator.base import OpStatus
from app.adapters.orchestrator.docker_local import DockerLocalOrchestrator
from app.adapters.orchestrator.simulation import SimulationOrchestrator
from app.core.models import Incident, IncidentState as S, InvalidTransition, Provenance, Severity


def inspect_json(running=True, exit_code=0, oom=False, health="healthy"):
    state = {"Running": running, "ExitCode": exit_code, "OOMKilled": oom, "StartedAt": "t"}
    if health:
        state["Health"] = {"Status": health}
    return json.dumps([{"State": state, "Config": {"Image": "img:1"}}])


class StateMachineTests(unittest.TestCase):
    def _inc(self):
        return Incident("i1", "w", "s", "k", Severity.HIGH, 1.0, [], Provenance.REAL)

    def test_valid_path_to_resolved(self):
        i = self._inc()
        for st in (S.DIAGNOSING, S.RECOVERING, S.VERIFYING, S.RESOLVED):
            i.transition(st, 2.0)
        self.assertFalse(i.is_open)

    def test_cannot_skip_verification(self):
        i = self._inc()
        i.transition(S.DIAGNOSING, 2.0)
        i.transition(S.RECOVERING, 3.0)
        with self.assertRaises(InvalidTransition):
            i.transition(S.RESOLVED, 4.0)

    def test_terminal_states_are_final(self):
        i = self._inc()
        i.transition(S.ESCALATED, 2.0)
        with self.assertRaises(InvalidTransition):
            i.transition(S.DIAGNOSING, 3.0)


class DockerAdapterTests(unittest.TestCase):
    def adapter(self, rc=0, out="", err=""):
        calls = []

        def runner(args, timeout):
            calls.append(args)
            return rc, out, err
        return DockerLocalOrchestrator(runner=runner), calls

    def test_inspect_running_healthy(self):
        a, _ = self.adapter(out=inspect_json())
        st = a.inspect_workload("rea-store001-pos")
        self.assertTrue(st.found and st.running)
        self.assertEqual(st.health, "healthy")
        self.assertEqual(st.provenance, Provenance.REAL)

    def test_inspect_exited_oom(self):
        a, _ = self.adapter(out=inspect_json(running=False, exit_code=137, oom=True, health=None))
        st = a.inspect_workload("c1")
        self.assertFalse(st.running)
        self.assertTrue(st.oom_killed)
        self.assertEqual(st.exit_code, 137)

    def test_missing_container_is_not_an_error(self):
        a, _ = self.adapter(rc=1, err="Error: No such object: c1")
        st = a.inspect_workload("c1")
        self.assertFalse(st.found)
        self.assertIsNone(st.error)

    def test_daemon_down_is_reported_as_error_not_missing(self):
        a, _ = self.adapter(rc=1, err="failed to connect to the docker API")
        st = a.inspect_workload("c1")
        self.assertIsNotNone(st.error)

    def test_garbage_output_is_reported(self):
        a, _ = self.adapter(out="not json")
        self.assertIsNotNone(a.inspect_workload("c1").error)

    def test_restart_uses_fixed_argument_list(self):
        a, calls = self.adapter()
        res = a.restart_workload("c1", 30)
        self.assertEqual(res.status, OpStatus.OK)
        self.assertEqual(calls[0], ["docker", "restart", "-t", "5", "c1"])

    def test_restart_failure_surfaces(self):
        a, _ = self.adapter(rc=1, err="boom")
        self.assertEqual(a.restart_workload("c1", 30).status, OpStatus.FAILED)

    def test_injection_style_names_rejected_without_running_anything(self):
        a, calls = self.adapter()
        for bad in ("c1; rm -rf /", "$(whoami)", "-rf", "a b", ""):
            self.assertEqual(a.restart_workload(bad, 30).status, OpStatus.FAILED)
            self.assertIsNotNone(a.inspect_workload(bad).error)
        self.assertEqual(calls, [])

    def test_rollback_is_explicitly_unsupported(self):
        a, _ = self.adapter()
        self.assertEqual(a.rollback_workload("c1").status, OpStatus.UNSUPPORTED)

    def test_simulation_adapter_is_labelled_simulated(self):
        sim = SimulationOrchestrator()
        sim.add("w")
        self.assertEqual(sim.inspect_workload("w").provenance, Provenance.SIMULATED)
        self.assertEqual(sim.restart_workload("w", 1).provenance, Provenance.SIMULATED)


if __name__ == "__main__":
    unittest.main()
