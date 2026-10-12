"""Retail-aware recovery policy (Phase 1: restart-or-escalate)."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import EngineConfig
from app.core.models import Criticality, Incident, WorkloadSpec

RESTARTABLE = {"process_crash", "killed_by_signal", "clean_exit", "out_of_memory", "unresponsive_process"}


@dataclass
class PolicyDecision:
    action: str                       # "restart_workload" | "escalate"
    requires_approval: bool
    reversible: bool
    reason: str
    rationale: list[str] = field(default_factory=list)


def decide(incident: Incident, spec: WorkloadSpec, status, diagnosis: dict, cfg: EngineConfig) -> PolicyDecision:
    top = diagnosis["ranked_causes"][0]["cause"] if diagnosis["ranked_causes"] else "unknown"
    why = [f"top cause: {top}", f"criticality: {spec.criticality.value}", f"attempts so far: {incident.attempts}/{cfg.max_attempts}"]
    if incident.attempts >= cfg.max_attempts:
        return PolicyDecision("escalate", False, True, "retry budget exhausted; automatic recovery did not verify", why)
    if top not in RESTARTABLE:
        return PolicyDecision("escalate", False, True, f"no safe automatic action for cause '{top}'", why)
    if not spec.stateless:
        return PolicyDecision("escalate", False, True, "restarting a stateful workload is not auto-approved", why)
    if cfg.approval_mode == "always":
        needs, why_ap = True, "approval_mode=always"
    elif cfg.approval_mode == "never":
        needs, why_ap = False, "approval_mode=never"
    elif status.found and status.running:
        needs, why_ap = True, "workload is up and serving; a restart would interrupt in-flight checkouts"
    else:
        needs, why_ap = False, "workload is already down; a restart cannot make checkout worse"
    why.append(why_ap)
    if top == "out_of_memory":
        why.append("OOM may recur after restart; retry limit bounds this")
    return PolicyDecision("restart_workload", needs, True, f"restart is a reversible fix for '{top}'", why)
