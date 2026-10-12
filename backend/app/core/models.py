"""Core domain types. Standard library only so the logic is testable anywhere."""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Provenance(str, enum.Enum):
    """Whether data or an action comes from a real system or a simulation."""
    REAL = "real"
    SIMULATED = "simulated"


class Criticality(str, enum.Enum):
    CRITICAL = "critical"        # transaction processing / checkout
    IMPORTANT = "important"      # sync, inventory
    DEFERRABLE = "deferrable"    # analytics, reporting


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentState(str, enum.Enum):
    DETECTED = "DETECTED"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECOVERING = "RECOVERING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


S = IncidentState
TRANSITIONS: dict[IncidentState, set[IncidentState]] = {
    S.DETECTED: {S.DIAGNOSING, S.ESCALATED},
    S.DIAGNOSING: {S.AWAITING_APPROVAL, S.RECOVERING, S.ESCALATED},
    S.AWAITING_APPROVAL: {S.RECOVERING, S.ESCALATED},
    S.RECOVERING: {S.VERIFYING, S.ESCALATED},
    # Failed verification goes back to DIAGNOSING so the policy re-decides
    # (retry, or escalate when the retry budget is spent).
    S.VERIFYING: {S.RESOLVED, S.DIAGNOSING, S.ESCALATED},
    S.RESOLVED: set(),
    S.ESCALATED: set(),
}
TERMINAL_STATES = {S.RESOLVED, S.ESCALATED}


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class WorkloadSpec:
    id: str                      # also the container name for docker_local
    store_id: str
    kind: str                    # e.g. "pos"
    criticality: Criticality
    health_url: str
    transaction_url: str
    stateless: bool = True


@dataclass
class ProbeResult:
    ok: bool
    latency_ms: Optional[float]
    status_code: Optional[int]
    error: Optional[str]
    ts: float


@dataclass
class Sample:
    ts: float
    status: Any                  # WorkloadStatus (adapters.orchestrator.base)
    health: Optional[ProbeResult]
    canary: Optional[ProbeResult]


@dataclass
class ActionRecord:
    id: str
    incident_id: str
    action: str
    workload_id: str
    proposed_at: float
    approved_by: Optional[str]
    provenance: Provenance
    dry_run: bool
    status: str = "PROPOSED"     # EXECUTED FAILED REJECTED DRY_RUN COOLDOWN SKIPPED_ALREADY_HEALTHY
    executed_at: Optional[float] = None
    detail: str = ""


@dataclass
class Incident:
    id: str
    workload_id: str
    store_id: str
    kind: str
    severity: Severity
    detected_at: float
    evidence: list[dict[str, Any]]
    provenance: Provenance
    state: IncidentState = IncidentState.DETECTED
    state_since: float = 0.0
    attempts: int = 0
    approved_by: Optional[str] = None
    recurrence_of: Optional[str] = None
    resolved_at: Optional[float] = None
    escalation_reason: Optional[str] = None
    diagnosis: Optional[dict[str, Any]] = None
    decision: Optional[dict[str, Any]] = None
    verification: Optional[dict[str, Any]] = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.state_since:
            self.state_since = self.detected_at
        if not self.timeline:
            self.timeline.append({"ts": self.detected_at, "event": "detected", "state": self.state.value,
                                  "note": f"{self.kind} on {self.workload_id}"})

    @property
    def is_open(self) -> bool:
        return self.state not in TERMINAL_STATES

    def note(self, ts: float, event: str, note: str) -> None:
        self.timeline.append({"ts": ts, "event": event, "state": self.state.value, "note": note})

    def transition(self, new: IncidentState, ts: float, note: str = "") -> None:
        if new not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {new.value} is not allowed")
        self.state = new
        self.state_since = ts
        self.timeline.append({"ts": ts, "event": "state_change", "state": new.value, "note": note})
