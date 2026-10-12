"""Rule-based, explainable diagnosis. `score` is a heuristic evidence weight (0-100),
NOT a probability, and nothing here is learned from data."""
from __future__ import annotations

from typing import Any, Optional

from app.core.models import Incident, ProbeResult


def _cause(name: str, score: int, evidence: list[str], steps: list[str]) -> dict[str, Any]:
    return {"cause": name, "score": score, "evidence": evidence, "next_steps": steps}


def diagnose(incident: Incident, status, health: Optional[ProbeResult], logs: str = "") -> dict[str, Any]:
    causes: list[dict[str, Any]] = []
    log_errs = [l for l in logs.splitlines() if "Traceback" in l or "ERROR" in l][:3]
    if not status.found:
        causes.append(_cause("container_missing", 90, ["container does not exist"],
                             ["redeploy the workload (not automated in Phase 1)"]))
    elif not status.running:
        if status.oom_killed:
            causes.append(_cause("out_of_memory", 85, ["container was OOM-killed"],
                                 ["restart, then investigate memory limits / leak"]))
        elif status.exit_code in (137, 143):
            causes.append(_cause("killed_by_signal", 80,
                                 [f"exit code {status.exit_code} (SIGKILL/SIGTERM)", "not OOM-killed"],
                                 ["restart; check whether something stopped it externally"]))
        elif status.exit_code not in (0, None):
            ev = [f"exited with code {status.exit_code}"] + [f"log: {l[:120]}" for l in log_errs]
            causes.append(_cause("process_crash", 80, ev, ["restart; inspect logs for the crash cause"]))
        else:
            causes.append(_cause("clean_exit", 60, ["container exited with code 0"],
                                 ["restart; confirm it was not stopped on purpose"]))
    else:
        ev = ["container running", f"health probe failing ({health.error if health else 'no probe'})"]
        if status.health:
            ev.append(f"docker health: {status.health}")
        causes.append(_cause("unresponsive_process", 70, ev,
                             ["restart; check dependencies if it recurs"]))
    causes.sort(key=lambda c: -c["score"])
    return {"method": "rule_based_v1", "ranked_causes": causes,
            "note": "scores are heuristic evidence weights, not probabilities",
            "dependency_check": "not implemented in Phase 1"}
