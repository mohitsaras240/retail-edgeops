"""Retail-aware recovery policy.

Evaluates multi-factor risk:
- Incident severity & root-cause confidence
- Workload criticality (Critical checkout lane vs Important kiosk vs Deferrable sync)
- Reversibility of proposed recovery action
- Disruption to active in-flight checkouts

Selects bounded safe recovery actions:
restart_workload | defer_workload | rollback_workload | escalate
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import EngineConfig
from app.core.models import Criticality, Incident, Severity, WorkloadSpec
from app.services.incident_detection.detector import Detector

RESTARTABLE = {
    "process_crash",
    "killed_by_signal",
    "clean_exit",
    "out_of_memory",
    "unresponsive_process",
    "crash_loop",
}


@dataclass
class PolicyDecision:
    action: str  # "restart_workload" | "defer_workload" | "rollback_workload" | "escalate"
    requires_approval: bool
    reversible: bool
    reason: str
    rationale: list[str] = field(default_factory=list)
    risk_level: str = "LOW"  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    estimated_disruption: str = "none"


def decide(incident: Incident, spec: WorkloadSpec, status, diagnosis: dict[str, Any], cfg: EngineConfig) -> PolicyDecision:
    ranked = diagnosis.get("ranked_causes", [])
    top = ranked[0]["cause"] if ranked else "unknown"
    confidence = ranked[0].get("confidence", "medium") if ranked else "low"

    why = [
        f"top cause: {top} (confidence={confidence})",
        f"workload criticality: {spec.criticality.value}",
        f"recovery attempts: {incident.attempts}/{cfg.max_attempts}",
    ]
    kind = incident.kind

    # ── 1. Budget Exhausted: Always Escalate ───────────────────────────────────
    if incident.attempts >= cfg.max_attempts:
        why.append("budget exhausted: automatic recovery attempts failed to verify health")
        return PolicyDecision(
            action="escalate",
            requires_approval=False,
            reversible=True,
            reason="retry budget exhausted; automatic recovery did not verify",
            rationale=why,
            risk_level="HIGH",
            estimated_disruption="escalated to edge on-call engineer",
        )

    # ── 2. Deployment Regression -> Rollback ───────────────────────────────────
    if kind == Detector.DEPLOYMENT_REGRESSION or top == "bad_deployment":
        why.append("bad deployment: restart will not resolve defect present in current image")
        why.append("rollback reverts workload container to verified previous digest")
        why.append("NOTE: docker_local orchestrator will honestly return UNSUPPORTED and trigger escalation")
        return PolicyDecision(
            action="rollback_workload",
            requires_approval=True,
            reversible=True,
            reason="deployment regression: rolling back image to previous version",
            rationale=why,
            risk_level="HIGH",
            estimated_disruption="temporary 5-10s restart during image rollback",
        )

    # ── 3. Resource Pressure ──────────────────────────────────────────────────
    if kind == Detector.RESOURCE_PRESSURE or top == "resource_exhaustion":
        if spec.criticality == Criticality.DEFERRABLE:
            why.append("deferrable workload: pause sheds CPU/RAM without impacting active checkout lanes")
            return PolicyDecision(
                action="defer_workload",
                requires_approval=False,
                reversible=True,
                reason="resource pressure: pausing deferrable workload to free resources",
                rationale=why,
                risk_level="LOW",
                estimated_disruption="none: checkout lanes unaffected",
            )
        elif spec.criticality == Criticality.IMPORTANT:
            why.append("important kiosk workload under host resource pressure")
            why.append("escalate to prevent uncoordinated kiosk terminations")
            return PolicyDecision(
                action="escalate",
                requires_approval=False,
                reversible=True,
                reason="resource pressure on important workload: manual intervention required",
                rationale=why,
                risk_level="MEDIUM",
                estimated_disruption="advisory: kiosk operating under host stress",
            )
        else:  # CRITICAL PoS
            why.append("CRITICAL checkout service under host resource pressure: escalate immediately")
            return PolicyDecision(
                action="escalate",
                requires_approval=False,
                reversible=True,
                reason="resource pressure on critical checkout service: escalate",
                rationale=why,
                risk_level="CRITICAL",
                estimated_disruption="high risk of checkout delays; human inspection needed",
            )

    # ── 4. Dependency Unavailable -> Do Not Restart in a Loop ─────────────────
    if top == "dependency_unavailable":
        why.append("dependent upstream service is failing; restarting dependent service will cause restart loop")
        why.append("escalating incident until upstream dependency is restored")
        return PolicyDecision(
            action="escalate",
            requires_approval=False,
            reversible=True,
            reason="dependency unavailable: restarting would cause a crash loop",
            rationale=why,
            risk_level="HIGH",
            estimated_disruption="service waiting for upstream dependency",
        )

    # ── 5. Sync Backlog -> Network Issue (Do Not Restart) ─────────────────────
    if kind == Detector.SYNC_BACKLOG:
        why.append("sync backlog indicates store edge WAN / central endpoint reachability issue")
        why.append("local SQLite storage is durable; transactions are protected from loss")
        return PolicyDecision(
            action="escalate",
            requires_approval=False,
            reversible=True,
            reason="sync backlog: check store-to-central connectivity",
            rationale=why,
            risk_level="MEDIUM",
            estimated_disruption="none: offline transactions buffered safely locally",
        )

    # ── 6. Unrestartable Causes ───────────────────────────────────────────────
    if top not in RESTARTABLE:
        why.append(f"cause '{top}' is not safe for automated restart")
        return PolicyDecision(
            action="escalate",
            requires_approval=False,
            reversible=True,
            reason=f"no safe automatic action for cause '{top}'",
            rationale=why,
            risk_level="HIGH",
            estimated_disruption="operator intervention required",
        )

    if not spec.stateless:
        why.append("stateful workloads cannot be automatically restarted without data verification")
        return PolicyDecision(
            action="escalate",
            requires_approval=False,
            reversible=True,
            reason="restarting a stateful workload is not auto-approved",
            rationale=why,
            risk_level="HIGH",
            estimated_disruption="stateful service requires manual operator supervision",
        )

    # ── 7. Restart Action Risk & Approval Evaluation ──────────────────────────
    if cfg.approval_mode == "always":
        needs_approval = True
        why.append("approval_mode=always: all actions require operator confirmation")
        risk_level = "MEDIUM"
        disruption = "restart pending operator confirmation"
    elif cfg.approval_mode == "never":
        needs_approval = False
        why.append("approval_mode=never: fully autonomous recovery mode")
        risk_level = "LOW"
        disruption = "brief 2-5s process restart"
    elif status.found and status.running:
        needs_approval = True
        why.append("workload is currently running and serving customer traffic")
        why.append("restart would interrupt in-flight checkout transactions; operator approval required")
        risk_level = "HIGH" if spec.criticality == Criticality.CRITICAL else "MEDIUM"
        disruption = "in-flight checkout disruption risk if restarted while serving"
    else:
        needs_approval = False
        why.append("workload is already down or exited; restart cannot worsen customer checkout status")
        risk_level = "LOW"
        disruption = "service already down; restart brings back lane capability"

    if top == "out_of_memory":
        why.append("OOM may recur after restart if memory leak persists; bounded by max_attempts")

    return PolicyDecision(
        action="restart_workload",
        requires_approval=needs_approval,
        reversible=True,
        reason=f"restart is a reversible fix for '{top}'",
        rationale=why,
        risk_level=risk_level,
        estimated_disruption=disruption,
    )
