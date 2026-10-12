"""Real Docker adapter using the docker CLI (no shell, fixed argument lists).
This is Docker, NOT Eclipse ioFog."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Callable, Optional

from app.adapters.orchestrator.base import ActionResult, OpStatus, Orchestrator, WorkloadStatus
from app.core.models import Provenance

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
Runner = Callable[[list[str], float], tuple[int, str, str]]


def default_runner(args: list[str], timeout_s: float) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s, shell=False)
    except FileNotFoundError:
        return 127, "", "docker executable not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout_s}s"
    return p.returncode, p.stdout, p.stderr


class DockerLocalOrchestrator(Orchestrator):
    name = "docker_local"
    provenance = Provenance.REAL

    def __init__(self, runner: Optional[Runner] = None, docker_bin: str = "docker", query_timeout_s: float = 10.0):
        self._run = runner or default_runner
        self._bin = docker_bin
        self._qt = query_timeout_s

    def _valid(self, name: str) -> bool:
        return bool(_NAME_RE.match(name))

    def inspect_workload(self, workload_id: str) -> WorkloadStatus:
        st = WorkloadStatus(workload_id=workload_id, provenance=self.provenance)
        if not self._valid(workload_id):
            st.error = "invalid container name"
            return st
        rc, out, err = self._run([self._bin, "inspect", workload_id], self._qt)
        if rc != 0:
            if "No such object" in err or "No such container" in err:
                return st                      # genuinely absent: found=False, no error
            st.error = (err.strip() or f"docker inspect exited {rc}")[:300]
            return st
        try:
            data = json.loads(out)[0]
            state = data["State"]
        except (ValueError, IndexError, KeyError) as exc:
            st.error = f"unparseable docker inspect output: {exc}"
            return st
        st.found = True
        st.running = bool(state.get("Running"))
        st.exit_code = state.get("ExitCode")
        st.oom_killed = bool(state.get("OOMKilled"))
        st.started_at = state.get("StartedAt")
        st.health = (state.get("Health") or {}).get("Status")
        st.image = (data.get("Config") or {}).get("Image")
        return st

    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult:
        if not self._valid(workload_id):
            return ActionResult(OpStatus.FAILED, "invalid container name", self.provenance)
        # `docker restart` also starts a stopped container.
        rc, out, err = self._run([self._bin, "restart", "-t", "5", workload_id], timeout_s)
        if rc == 0:
            return ActionResult(OpStatus.OK, f"docker restart {workload_id} succeeded", self.provenance)
        return ActionResult(OpStatus.FAILED, (err.strip() or f"exit {rc}")[:300], self.provenance)

    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult:
        if not self._valid(workload_id):
            return ActionResult(OpStatus.FAILED, "invalid container name", self.provenance)
        rc, out, err = self._run([self._bin, "logs", "--tail", str(int(tail)), workload_id], self._qt)
        if rc != 0:
            return ActionResult(OpStatus.FAILED, (err.strip() or f"exit {rc}")[:300], self.provenance)
        return ActionResult(OpStatus.OK, (out + err)[-4000:], self.provenance)
