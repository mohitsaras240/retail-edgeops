"""Measured application telemetry: real HTTP probes against a workload."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Protocol

from app.core.models import ProbeResult, WorkloadSpec


class Prober(Protocol):
    def probe_health(self, spec: WorkloadSpec) -> ProbeResult: ...
    def probe_canary(self, spec: WorkloadSpec) -> ProbeResult: ...


class HttpProber:
    def __init__(self, timeout_s: float = 2.0):
        self.timeout_s = timeout_s

    def _call(self, req: urllib.request.Request) -> ProbeResult:
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                resp.read(4096)
                code = resp.status
            return ProbeResult(200 <= code < 300, (time.perf_counter() - t0) * 1000, code, None, time.time())
        except urllib.error.HTTPError as exc:          # server answered with an error status
            return ProbeResult(False, (time.perf_counter() - t0) * 1000, exc.code, f"HTTP {exc.code}", time.time())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            return ProbeResult(False, None, None, f"{type(exc).__name__}: {exc}"[:200], time.time())

    def probe_health(self, spec: WorkloadSpec) -> ProbeResult:
        return self._call(urllib.request.Request(spec.health_url, method="GET"))

    def probe_canary(self, spec: WorkloadSpec) -> ProbeResult:
        """Synthetic canary transaction (flagged canary=true, excluded from business counts)."""
        body = json.dumps({"terminal_id": "CANARY", "item_count": 1, "canary": True}).encode()
        req = urllib.request.Request(spec.transaction_url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        return self._call(req)
