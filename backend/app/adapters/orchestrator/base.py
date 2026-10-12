"""Orchestrator abstraction. Every operation reports an explicit status; an
operation an adapter cannot perform returns UNSUPPORTED, never a fake success."""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.core.models import Provenance


class OpStatus(str, enum.Enum):
    OK = "ok"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass
class ActionResult:
    status: OpStatus
    detail: str
    provenance: Provenance


@dataclass
class WorkloadStatus:
    workload_id: str
    provenance: Provenance
    found: bool = False
    running: bool = False
    health: Optional[str] = None       # container health: healthy/unhealthy/starting/None (no healthcheck)
    exit_code: Optional[int] = None
    oom_killed: bool = False
    started_at: Optional[str] = None
    image: Optional[str] = None
    error: Optional[str] = None        # set when the orchestrator itself could not be queried


class Orchestrator(ABC):
    name: str
    provenance: Provenance

    @abstractmethod
    def inspect_workload(self, workload_id: str) -> WorkloadStatus: ...

    @abstractmethod
    def restart_workload(self, workload_id: str, timeout_s: float) -> ActionResult: ...

    @abstractmethod
    def get_logs(self, workload_id: str, tail: int = 50) -> ActionResult: ...

    def rollback_workload(self, workload_id: str) -> ActionResult:
        return ActionResult(OpStatus.UNSUPPORTED, f"{self.name}: rollback is not implemented", self.provenance)
