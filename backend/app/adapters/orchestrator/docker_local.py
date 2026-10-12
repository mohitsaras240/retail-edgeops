"""Real Docker adapter using the docker CLI (no shell, fixed argument lists).
This is Docker, NOT Eclipse ioFog."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import threading
from typing import Callable, Optional

from app.adapters.orchestrator.base import ActionResult, OpStatus, Orchestrator, WorkloadStatus
from app.core.models import Provenance

log = logging.getLogger("autopilot.docker")

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
Runner = Callable[[list[str], float], tuple[int, str, str]]

# Phase 2: stats cache — refreshed on a background interval to avoid adding 1 s per workload per tick.
_STATS_INTERVAL = 10.0


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

    def __init__(self, runner: Optional[Runner] = None, docker_bin: str = "docker",
                 query_timeout_s: float = 10.0, stats_interval: float = _STATS_INTERVAL):
        self._run = runner or default_runner
        self._bin = docker_bin
        self._qt = query_timeout_s
        self._stats_interval = stats_interval
        # stats cache: workload_id -> (cpu_pct, mem_pct, refreshed_at)
        self._stats_cache: dict[str, tuple[Optional[float], Optional[float], float]] = {}
        self._stats_lock = threading.Lock()
        self._stats_thread: Optional[threading.Thread] = None
        self._stop_stats = threading.Event()

    def _valid(self, name: str) -> bool:
        return bool(_NAME_RE.match(name))

    # ---------------------------------------------------------------- stats background refresh
    def start_stats_polling(self, workload_ids: list[str]) -> None:
        """Start a background thread that refreshes docker stats every stats_interval seconds."""
        if self._stats_thread and self._stats_thread.is_alive():
            return
        self._stop_stats.clear()
        self._stats_thread = threading.Thread(
            target=self._stats_loop, args=(workload_ids,), daemon=True, name="docker-stats")
        self._stats_thread.start()

    def stop_stats_polling(self) -> None:
        self._stop_stats.set()

    def _stats_loop(self, workload_ids: list[str]) -> None:
        while not self._stop_stats.wait(self._stats_interval):
            self._refresh_stats(workload_ids)

    def _refresh_stats(self, workload_ids: list[str]) -> None:
        """Run `docker stats --no-stream` for given containers; update cache."""
        if not workload_ids:
            return
        rc, out, _ = self._run(
            [self._bin, "stats", "--no-stream", "--format",
             "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}"] + workload_ids,
            self._stats_interval * 0.9)
        if rc != 0:
            return
        now = time.time()
        with self._stats_lock:
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                name, cpu_s, mem_s = parts
                try:
                    cpu = float(cpu_s.rstrip("%"))
                    mem = float(mem_s.rstrip("%"))
                    # Normalize name: docker stats may prefix with '/'
                    wid = name.lstrip("/")
                    self._stats_cache[wid] = (cpu, mem, now)
                except ValueError:
                    pass

    def _get_stats(self, workload_id: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (cpu_pct, mem_pct, age_s) from cache; returns Nones if not cached."""
        with self._stats_lock:
            entry = self._stats_cache.get(workload_id)
        if entry is None:
            return None, None, None
        cpu, mem, ts = entry
        return cpu, mem, round(time.time() - ts, 1)

    # ---------------------------------------------------------------- Orchestrator interface
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
        # Phase 2: restart count from HostConfig RestartPolicy / State
        st.restart_count = int((data.get("RestartCount") or 0))
        # Phase 2: image version — use the RepoDigests short hash if available, else tag
        repo_digests = (data.get("RepoDigests") or [])
        if repo_digests:
            digest = repo_digests[0]
            st.image_version = digest.split("@")[-1][:19] if "@" in digest else digest[-16:]
        elif st.image:
            st.image_version = st.image.split(":")[-1][:32]
        # Phase 2: stats from cache (non-blocking)
        cpu, mem, age = self._get_stats(workload_id)
        st.cpu_pct, st.mem_pct, st.stats_age_s = cpu, mem, age
        return st

    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult:
        if not self._valid(workload_id):
            return ActionResult(OpStatus.FAILED, "invalid container name", self.provenance)
        # `docker restart` also starts a stopped container.
        rc, out, err = self._run([self._bin, "restart", "-t", "5", workload_id], timeout_s)
        if rc == 0:
            return ActionResult(OpStatus.OK, f"docker restart {workload_id} succeeded", self.provenance)
        return ActionResult(OpStatus.FAILED, (err.strip() or f"exit {rc}")[:300], self.provenance)

    def pause_workload(self, workload_id: str) -> ActionResult:
        """Pause a running container using `docker pause`.
        NOTE: docker pause suspends all processes (SIGSTOP); use unpause to resume.
        This is only suitable for DEFERRABLE workloads — pausing a PoS terminal would stop checkouts."""
        if not self._valid(workload_id):
            return ActionResult(OpStatus.FAILED, "invalid container name", self.provenance)
        rc, _, err = self._run([self._bin, "pause", workload_id], self._qt)
        if rc == 0:
            return ActionResult(OpStatus.OK, f"docker pause {workload_id} succeeded", self.provenance)
        return ActionResult(OpStatus.FAILED, (err.strip() or f"exit {rc}")[:300], self.provenance)

    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult:
        if not self._valid(workload_id):
            return ActionResult(OpStatus.FAILED, "invalid container name", self.provenance)
        rc, out, err = self._run([self._bin, "logs", "--tail", str(int(tail)), workload_id], self._qt)
        if rc != 0:
            return ActionResult(OpStatus.FAILED, (err.strip() or f"exit {rc}")[:300], self.provenance)
        return ActionResult(OpStatus.OK, (out + err)[-4000:], self.provenance)
