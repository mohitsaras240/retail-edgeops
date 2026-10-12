"""Safe recovery executor: allowlist, approval check, backoff/cooldown, dry-run,
idempotency precondition, timeout, audit. Never runs arbitrary commands.

Phase 1: restart_workload
Phase 2: rollback_workload | defer_workload (both may return UNSUPPORTED; result recorded honestly)
"""
from __future__ import annotations

from dataclasses import asdict

from app.adapters.orchestrator.base import OpStatus, Orchestrator
from app.core.config import EngineConfig
from app.core.models import ActionRecord, Incident, WorkloadSpec, new_id
from app.services.incident_detection.detector import Detector
from app.services.recovery_executor.audit import AuditLog

ALLOWED_ACTIONS = frozenset({"restart_workload", "rollback_workload", "defer_workload"})


class RecoveryExecutor:
    def __init__(self, orchestrator: Orchestrator, audit: AuditLog, cfg: EngineConfig):
        self.orch, self.audit, self.cfg = orchestrator, audit, cfg
        self._last_action_at: dict[str, float] = {}

    def execute(self, inc: Incident, decision, spec: WorkloadSpec, now: float) -> ActionRecord:
        rec = ActionRecord(id=new_id(), incident_id=inc.id, action=decision.action, workload_id=spec.id,
                           proposed_at=now, approved_by=inc.approved_by, provenance=self.orch.provenance,
                           dry_run=self.cfg.dry_run)

        def finish(status: str, detail: str, audit: bool = True) -> ActionRecord:
            rec.status, rec.detail = status, detail
            if audit:
                self.audit.append("recovery_action", asdict(rec), ts=now)
            return rec

        # Allowlist check
        if decision.action not in ALLOWED_ACTIONS:
            return finish("REJECTED", f"action '{decision.action}' is not on the allowlist")

        # Approval check
        if decision.requires_approval and not inc.approved_by:
            return finish("REJECTED", "approval required but not granted")

        # Backoff / cooldown
        if inc.attempts > 0:
            gap = self.cfg.base_backoff_s * (2 ** (inc.attempts - 1))
            last = self._last_action_at.get(spec.id)
            if last is not None and now - last < gap:
                return finish("COOLDOWN", f"backoff: {gap:.0f}s required between attempts", audit=False)

        # Dry-run
        if self.cfg.dry_run:
            return finish("DRY_RUN", "dry-run: action not executed")

        # ── Dispatch to orchestrator ────────────────────────────────────────────────────
        if decision.action == "restart_workload":
            # Idempotency: first attempt only — don't restart something that already recovered
            if inc.kind == Detector.CRASH and inc.attempts == 0:
                st = self.orch.inspect_workload(spec.id)
                if st.error is None and st.found and st.running:
                    return finish("SKIPPED_ALREADY_HEALTHY", "container already running; restart skipped")
            result = self.orch.restart_workload(spec.id, self.cfg.action_timeout_s)

        elif decision.action == "rollback_workload":
            # Rollback is UNSUPPORTED on docker_local; the result is recorded honestly.
            result = self.orch.rollback_workload(spec.id)

        elif decision.action == "defer_workload":
            # Pause a deferrable workload to free resources.
            result = self.orch.pause_workload(spec.id)

        else:
            # Should never reach here due to allowlist check above.
            return finish("REJECTED", f"unhandled action: {decision.action}")

        rec.executed_at = now
        self._last_action_at[spec.id] = now

        if result.status == OpStatus.OK:
            return finish("EXECUTED", result.detail)
        if result.status == OpStatus.UNSUPPORTED:
            # Honestly report that the orchestrator does not support this operation.
            return finish("REJECTED", f"unsupported by orchestrator: {result.detail}")
        return finish("FAILED", result.detail)
