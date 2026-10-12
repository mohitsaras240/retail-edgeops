import json
from urllib.request import Request
import pytest

from app.adapters.orchestrator.base import OpStatus
from app.adapters.orchestrator.iofog import IoFogClient, IoFogOrchestrator
from app.core.models import Provenance


def make_mock_opener(responses: dict[tuple[str, str], tuple[int, dict]]):
    """Factory creating an opener mock that matches (method, path) to (status_code, body)."""
    def _opener(req: Request, timeout_s: float) -> tuple[int, bytes]:
        method = req.get_method()
        url = req.full_url
        path = url.replace("http://localhost:54321", "")
        key = (method, path)
        if key in responses:
            code, payload = responses[key]
            return code, json.dumps(payload).encode("utf-8")
        return 404, json.dumps({"message": f"Endpoint not found: {key}"}).encode("utf-8")
    return _opener


def test_iofog_client_requests():
    responses = {
        ("GET", "/api/v3/microservices/uuid-123"): (200, {
            "uuid": "uuid-123",
            "name": "store001-pos",
            "status": "RUNNING",
            "images": {"x86": "pos:v1"},
            "metrics": {"cpu": 12.5, "memory": 45.0},
        }),
        ("PATCH", "/api/v3/microservices/uuid-123/stop"): (204, {}),
        ("PATCH", "/api/v3/microservices/uuid-123/start"): (204, {}),
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    code, data = client.get_microservice("uuid-123")
    assert code == 200
    assert data["status"] == "RUNNING"

    code, _ = client.stop_microservice("uuid-123")
    assert code == 204

    code, _ = client.start_microservice("uuid-123")
    assert code == 204


def test_iofog_orchestrator_inspect_healthy():
    responses = {
        ("GET", "/api/v3/microservices/uuid-pos"): (200, {
            "uuid": "uuid-pos",
            "name": "store001-pos",
            "status": "RUNNING",
            "health": "healthy",
            "images": {"x86": "pos:v2.1"},
            "metrics": {"cpu": 15.0, "memory": 30.0},
        })
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    orch = IoFogOrchestrator(client=client, uuid_mapping={"store001-pos": "uuid-pos"})

    status = orch.inspect_workload("store001-pos")
    assert status.found is True
    assert status.running is True
    assert status.health == "healthy"
    assert status.cpu_pct == 15.0
    assert status.mem_pct == 30.0
    assert status.provenance == Provenance.REAL
    assert status.error is None


def test_iofog_orchestrator_inspect_not_found():
    client = IoFogClient(opener=make_mock_opener({}))
    orch = IoFogOrchestrator(client=client)

    status = orch.inspect_workload("unknown-workload")
    assert status.found is False
    assert status.running is False
    assert status.error is None


def test_iofog_orchestrator_restart_success():
    responses = {
        ("PATCH", "/api/v3/microservices/uuid-kiosk/stop"): (204, {}),
        ("PATCH", "/api/v3/microservices/uuid-kiosk/start"): (204, {}),
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    orch = IoFogOrchestrator(client=client)

    result = orch.restart_workload("uuid-kiosk", timeout_s=10.0)
    assert result.status == OpStatus.OK
    assert "succeeded" in result.detail
    assert result.provenance == Provenance.REAL


def test_iofog_orchestrator_restart_stop_failed():
    responses = {
        ("PATCH", "/api/v3/microservices/uuid-kiosk/stop"): (500, {"message": "Agent unreachable"}),
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    orch = IoFogOrchestrator(client=client)

    result = orch.restart_workload("uuid-kiosk", timeout_s=10.0)
    assert result.status == OpStatus.FAILED
    assert "iofog stop failed" in result.detail
    assert "Agent unreachable" in result.detail


def test_iofog_orchestrator_pause():
    responses = {
        ("PATCH", "/api/v3/microservices/uuid-sync/stop"): (204, {}),
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    orch = IoFogOrchestrator(client=client)

    result = orch.pause_workload("uuid-sync")
    assert result.status == OpStatus.OK
    assert "pause (stop)" in result.detail


def test_iofog_orchestrator_get_logs():
    responses = {
        ("GET", "/api/v3/microservices/uuid-sync"): (200, {
            "name": "sync-service",
            "status": "RUNNING",
            "agentUuid": "agent-store001",
        }),
    }
    client = IoFogClient(opener=make_mock_opener(responses))
    orch = IoFogOrchestrator(client=client)

    result = orch.get_logs("uuid-sync")
    assert result.status == OpStatus.OK
    assert "Microservice: sync-service Status: RUNNING" in result.detail