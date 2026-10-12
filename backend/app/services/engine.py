"""Closed-loop engine: Observe -> Detect -> Diagnose -> Decide -> Recover -> Verify."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from app.adapters.orchestrator.base import Orchestrator
from app.core.config import EngineConfig
from app.core.models import Incident, IncidentState as S, Sample, WorkloadSpec, new_id
from app.services.diagnosis.rules import diagnose
from app.services.incident_detection.detector import Detector
from app.services.recovery_executor.audit import AuditLog
from app.services.recovery_executor.executor import RecoveryExecutor
from app.services.recovery_policy.policy import PolicyDecision, decide
from app.services.telemetry.prober import Prober
from app.services.verification.verifier import Verifier


class EngineError(Exception):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message)
        self.code = code


class AutopilotEngine:
    def __init__(self, workloads: list[WorkloadSpec], orchestrator: Orchestrator, prober: Prober,
                 config: Optional[EngineConfig] = None, clock: Callable[[], float] = time.time,
                 audit_path: Optional[Path] = None):
        self.cfg = config or EngineConfig()
        self.specs = {w.id: w for w in workloads}
        self.orch, self.prober, self.clock = orchestrator, prober, clock
        self.detector = Detector(self.cfg)
        self.audit = AuditLog(audit_path)
        self.executor = RecoveryExecutor(orchestrator, self.audit, self.cfg)
        self.verifier = Verifier(self.cfg, self.detector)
        self.incidents: dict[str, Incident] = {}
        self.last_samples: dict[str, Sample] = {}
        self.monitoring_errors: dict[str, str] = {}
        self._decisions: dict[str, PolicyDecision] = {}
        # workload_id -> escalated incident id; suppresses duplicate incidents until the fault clears
        self._blocked: dict[str, str] = {}
        self._verify_samples: dict[str, list[Sample]] = {}
        self._verify_since: dict[str, float] = {}
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- tick
    def tick(self) -> None:
        with self._lock:
            now = self.clock()
            verifying = {i.workload_id for i in self.incidents.values() if i.state == S.VERIFYING}
            for spec in self.specs.values():
                sample = self._collect(spec, now, spec.id in verifying)
                self.last_samples[spec.id] = sample
                self._detect(spec, sample, now)
            for inc in [i for i in self.incidents.values() if i.is_open]:
                self._advance(inc, now)

    def _collect(self, spec: WorkloadSpec, now: float, want_canary: bool) -> Sample:
        status = self.orch.inspect_workload(spec.id)
        health = canary = None
        if status.error is None and status.found and status.running:
            health = self.prober.probe_health(spec)
            if want_canary:
                canary = self.prober.probe_canary(spec)
        return Sample(ts=now, status=status, health=health, canary=canary)

    def _open_for(self, workload_id: str) -> Optional[Incident]:
        return next((i for i in self.incidents.values() if i.workload_id == workload_id and i.is_open), None)

    def _detect(self, spec: WorkloadSpec, sample: Sample, now: float) -> None:
        if sample.status.error:
            self.monitoring_errors[spec.id] = sample.status.error
            return
        self.monitoring_errors.pop(spec.id, None)
        if not self.detector.would_trigger(spec, sample.status, sample.health):
            self._blocked.pop(spec.id, None)             # workload is healthy again: re-arm detection
        det = self.detector.evaluate(spec, sample.status, sample.health)
        # Dedup: one open incident per workload (a restarting service must not spawn new incidents),
        # and an escalated incident keeps suppressing duplicates until the workload is healthy again.
        if det is None or self._open_for(spec.id) or spec.id in self._blocked:
            return
        prior = [i for i in self.incidents.values() if i.workload_id == spec.id and i.kind == det.kind
                 and i.state == S.RESOLVED and i.resolved_at and now - i.resolved_at <= self.cfg.recurrence_window_s]
        inc = Incident(id=new_id(), workload_id=spec.id, store_id=spec.store_id, kind=det.kind, severity=det.severity,
                       detected_at=now, evidence=det.evidence, provenance=self.orch.provenance,
                       recurrence_of=prior[-1].id if prior else None)
        self.incidents[inc.id] = inc
        self.audit.append("incident_detected", {"incident_id": inc.id, "workload_id": spec.id, "kind": det.kind}, ts=now)

    # ------------------------------------------------------- state machine
    def _advance(self, inc: Incident, now: float) -> None:
        spec = self.specs[inc.workload_id]
        if inc.state == S.DETECTED:
            inc.transition(S.DIAGNOSING, now, "collecting evidence")
            self._plan(inc, spec, now)
        elif inc.state == S.AWAITING_APPROVAL:
            if now - inc.state_since > self.cfg.approval_timeout_s:
                self._escalate(inc, now, "approval timed out")
        elif inc.state == S.RECOVERING:
            self._attempt(inc, spec, now)
        elif inc.state == S.VERIFYING:
            self._verify(inc, spec, now)

    def _plan(self, inc: Incident, spec: WorkloadSpec, now: float) -> None:
        sample = self.last_samples[spec.id]
        inc.approved_by = None            # approval is per decision, never carried over to a new one
        logs = self.orch.get_logs(spec.id, 50) if sample.status.found else None
        inc.diagnosis = diagnose(inc, sample.status, sample.health, logs.detail if logs else "")
        decision = decide(inc, spec, sample.status, inc.diagnosis, self.cfg)
        self._decisions[inc.id] = decision
        inc.decision = asdict(decision)
        self.audit.append("policy_decision", {"incident_id": inc.id, **inc.decision}, ts=now)
        if decision.action == "escalate":
            self._escalate(inc, now, decision.reason)
        elif decision.requires_approval:
            inc.transition(S.AWAITING_APPROVAL, now, "restart needs human approval")
        else:
            inc.approved_by = inc.approved_by or "policy:auto"
            inc.transition(S.RECOVERING, now, decision.reason)
            self._attempt(inc, spec, now)

    def _attempt(self, inc: Incident, spec: WorkloadSpec, now: float) -> None:
        rec = self.executor.execute(inc, self._decisions[inc.id], spec, now)
        if rec.status == "COOLDOWN":
            return
        inc.actions.append(asdict(rec))
        if rec.status == "REJECTED":
            self._escalate(inc, now, f"action rejected: {rec.detail}")
        elif rec.status == "DRY_RUN":
            self._escalate(inc, now, "dry-run mode: no action was executed")
        elif rec.status in ("EXECUTED", "SKIPPED_ALREADY_HEALTHY"):
            inc.attempts += 1                 # a skipped cycle also consumes budget, so retries stay bounded
            self._verify_since[inc.id] = now
            self._verify_samples[inc.id] = []
            inc.transition(S.VERIFYING, now, f"action {rec.status}; verifying (not yet resolved)")
        elif rec.status == "FAILED":
            inc.attempts += 1
            inc.note(now, "action_failed", rec.detail)
            if inc.attempts >= self.cfg.max_attempts:
                self._escalate(inc, now, f"action failed {inc.attempts}x: {rec.detail}")

    def _verify(self, inc: Incident, spec: WorkloadSpec, now: float) -> None:
        sample = self.last_samples[spec.id]
        if sample.ts > self._verify_since[inc.id]:       # ignore samples taken before the action
            self._verify_samples[inc.id].append(sample)
        res = self.verifier.evaluate(spec, self._verify_samples[inc.id], now)
        inc.verification = res.to_dict()
        if res.passed:
            inc.resolved_at = now
            inc.transition(S.RESOLVED, now, "verification passed")
            self.audit.append("incident_resolved", {"incident_id": inc.id, "metrics": res.metrics}, ts=now)
        elif now - self._verify_since[inc.id] > self.cfg.verify_deadline_s:
            inc.note(now, "verification_failed", "recovery criteria not met before deadline; evidence kept")
            self.audit.append("verification_failed", {"incident_id": inc.id, "checks": res.checks}, ts=now)
            inc.transition(S.DIAGNOSING, now, "re-diagnosing after failed verification")
            self._plan(inc, spec, now)

    def _escalate(self, inc: Incident, now: float, reason: str) -> None:
        inc.escalation_reason = reason
        self._blocked[inc.workload_id] = inc.id
        inc.transition(S.ESCALATED, now, reason)
        self.audit.append("incident_escalated", {"incident_id": inc.id, "reason": reason}, ts=now)

    # ------------------------------------------------------------ approval
    def approve(self, incident_id: str, actor: str) -> Incident:
        with self._lock:
            inc = self._get(incident_id)
            if inc.state != S.AWAITING_APPROVAL:
                raise EngineError(f"incident is {inc.state.value}, not AWAITING_APPROVAL")
            now = self.clock()
            inc.approved_by = actor
            self.audit.append("approval", {"incident_id": inc.id, "actor": actor}, ts=now)
            inc.transition(S.RECOVERING, now, f"approved by {actor}")
            self._attempt(inc, self.specs[inc.workload_id], now)
            return inc

    def reject(self, incident_id: str, actor: str, reason: str = "") -> Incident:
        with self._lock:
            inc = self._get(incident_id)
            if inc.state != S.AWAITING_APPROVAL:
                raise EngineError(f"incident is {inc.state.value}, not AWAITING_APPROVAL")
            now = self.clock()
            self.audit.append("rejection", {"incident_id": inc.id, "actor": actor, "reason": reason}, ts=now)
            self._escalate(inc, now, f"rejected by {actor}: {reason or 'no reason given'}")
            return inc

    def _get(self, incident_id: str) -> Incident:
        inc = self.incidents.get(incident_id)
        if inc is None:
            raise EngineError("incident not found", code="not_found")
        return inc

    # --------------------------------------------------------------- views
    def workloads_view(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for spec in self.specs.values():
                s = self.last_samples.get(spec.id)
                out.append({"id": spec.id, "store_id": spec.store_id, "kind": spec.kind,
                            "criticality": spec.criticality.value, "provenance": self.orch.provenance.value,
                            "orchestrator": self.orch.name, "monitoring_error": self.monitoring_errors.get(spec.id),
                            "suppressed_by_escalated_incident": self._blocked.get(spec.id),
                            "status": asdict(s.status) if s else None,
                            "health_probe": asdict(s.health) if s and s.health else None})
            return out

    def incidents_view(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(i) for i in sorted(self.incidents.values(), key=lambda i: i.detected_at, reverse=True)]

    def incident_view(self, incident_id: str) -> dict[str, Any]:
        with self._lock:
            return asdict(self._get(incident_id))
