"""Eclipse ioFog Orchestrator Adapter.
Interacts with the Eclipse ioFog Controller REST API (v3) to inspect,
restart, and manage microservices on distributed edge nodes.
Explicitly sets provenance=Provenance.REAL (or SIMULATED if in test fixture) and
never reports fake successes.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters.orchestrator.base import ActionResult, OpStatus, Orchestrator, WorkloadStatus
from app.core.models import Provenance

log = logging.getLogger("autopilot.iofog")


class IoFogClient:
    """HTTP client communicating with the Eclipse ioFog Controller v3 REST API."""

    def __init__(
        self,
        controller_url: str = "http://localhost:54321",
        auth_token: Optional[str] = None,
        timeout_s: float = 10.0,
        opener: Optional[Callable[[Request, float], tuple[int, bytes]]] = None,
    ):
        self.controller_url = controller_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout_s = timeout_s
        self._opener = opener or self._default_opener

    def _default_opener(self, req: Request, timeout_s: float) -> tuple[int, bytes]:
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            return e.code, e.read()
        except URLError as e:
            raise ConnectionError(f"ioFog Controller connection failed: {e.reason}") from e

    def _request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> tuple[int, dict[str, Any]]:
        url = f"{self.controller_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.auth_token:
            headers["Authorization"] = self.auth_token

        req = Request(url, data=data, headers=headers, method=method)
        status, raw_bytes = self._opener(req, self.timeout_s)
        try:
            parsed = json.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
        except Exception:
            parsed = {"raw": raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""}
        return status, parsed

    def get_microservice(self, microservice_uuid: str) -> tuple[int, dict[str, Any]]:
        return self._request("GET", f"/api/v3/microservices/{microservice_uuid}")

    def list_microservices(self) -> tuple[int, dict[str, Any]]:
        return self._request("GET", "/api/v3/microservices")

    def stop_microservice(self, microservice_uuid: str) -> tuple[int, dict[str, Any]]:
        return self._request("PATCH", f"/api/v3/microservices/{microservice_uuid}/stop")

    def start_microservice(self, microservice_uuid: str) -> tuple[int, dict[str, Any]]:
        return self._request("PATCH", f"/api/v3/microservices/{microservice_uuid}/start")

    def rebuild_microservice(self, microservice_uuid: str) -> tuple[int, dict[str, Any]]:
        return self._request("PATCH", f"/api/v3/microservices/{microservice_uuid}/rebuild")


class IoFogOrchestrator(Orchestrator):
    """Orchestrator implementation targeting Eclipse ioFog.
    
    Translates Autopilot workload IDs to ioFog microservice UUIDs / names,
    executes lifecycle actions through the ioFog Controller API, and
    maps ioFog status to WorkloadStatus.
    """
    name = "eclipse_iofog"
    provenance = Provenance.REAL

    def __init__(
        self,
        client: Optional[IoFogClient] = None,
        uuid_mapping: Optional[Mapping[str, str]] = None,
        provenance: Provenance = Provenance.REAL,
    ):
        self._client = client or IoFogClient()
        self._uuid_map: dict[str, str] = dict(uuid_mapping or {})
        self.provenance = provenance

    def register_workload_uuid(self, workload_id: str, microservice_uuid: str) -> None:
        self._uuid_map[workload_id] = microservice_uuid

    def _resolve_uuid(self, workload_id: str) -> str:
        return self._uuid_map.get(workload_id, workload_id)

    def inspect_workload(self, workload_id: str) -> WorkloadStatus:
        st = WorkloadStatus(workload_id=workload_id, provenance=self.provenance)
        uuid = self._resolve_uuid(workload_id)
        try:
            status_code, data = self._client.get_microservice(uuid)
        except ConnectionError as ce:
            st.error = str(ce)
            return st
        except Exception as ex:
            st.error = f"ioFog Controller error: {ex}"
            return st

        if status_code == 404:
            st.found = False
            return st
        if status_code != 200:
            msg = data.get("message", str(data))
            st.error = f"ioFog Controller returned HTTP {status_code}: {msg}"
            return st

        st.found = True
        ms_status = str(data.get("status", "")).upper()
        st.running = ms_status in ("RUNNING", "OK", "DEPLOYED")
        st.image = data.get("images", {}).get("x86") or data.get("image")
        st.image_version = data.get("catalogItemId") or (st.image.split(":")[-1] if st.image else None)
        
        if "health" in data:
            st.health = str(data["health"]).lower()
        else:
            st.health = "healthy" if st.running else "unhealthy"

        metrics = data.get("metrics") or {}
        st.cpu_pct = metrics.get("cpu")
        st.mem_pct = metrics.get("memory")
        return st

    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult:
        uuid = self._resolve_uuid(workload_id)
        try:
            stop_code, stop_resp = self._client.stop_microservice(uuid)
            if stop_code not in (200, 204):
                msg = stop_resp.get("message", str(stop_resp))
                return ActionResult(
                    OpStatus.FAILED,
                    f"iofog stop failed (HTTP {stop_code}): {msg}",
                    self.provenance,
                )

            start_code, start_resp = self._client.start_microservice(uuid)
            if start_code in (200, 204):
                return ActionResult(
                    OpStatus.OK,
                    f"iofog restart {workload_id} ({uuid}) succeeded",
                    self.provenance,
                )
            msg = start_resp.get("message", str(start_resp))
            return ActionResult(
                OpStatus.FAILED,
                f"iofog start failed (HTTP {start_code}): {msg}",
                self.provenance,
            )
        except ConnectionError as ce:
            return ActionResult(OpStatus.FAILED, f"iofog controller unreachable: {ce}", self.provenance)
        except Exception as ex:
            return ActionResult(OpStatus.FAILED, f"iofog restart error: {ex}", self.provenance)

    def pause_workload(self, workload_id: str) -> ActionResult:
        uuid = self._resolve_uuid(workload_id)
        try:
            status_code, resp = self._client.stop_microservice(uuid)
            if status_code in (200, 204):
                return ActionResult(
                    OpStatus.OK,
                    f"iofog pause (stop) {workload_id} ({uuid}) succeeded",
                    self.provenance,
                )
            msg = resp.get("message", str(resp))
            return ActionResult(
                OpStatus.FAILED,
                f"iofog pause failed (HTTP {status_code}): {msg}",
                self.provenance,
            )
        except Exception as ex:
            return ActionResult(OpStatus.FAILED, f"iofog pause error: {ex}", self.provenance)

    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult:
        uuid = self._resolve_uuid(workload_id)
        try:
            status_code, data = self._client.get_microservice(uuid)
            if status_code == 200:
                name = data.get("name", uuid)
                ms_status = data.get("status")
                agent_uuid = data.get("agentUuid")
                summary = f"Microservice: {name} Status: {ms_status} Agent: {agent_uuid}"
                return ActionResult(OpStatus.OK, summary, self.provenance)
            return ActionResult(
                OpStatus.FAILED,
                f"iofog get_logs failed (HTTP {status_code})",
                self.provenance,
            )
        except Exception as ex:
            return ActionResult(OpStatus.FAILED, f"iofog get_logs error: {ex}", self.provenance)