"""Multi-signal, explainable root-cause diagnosis engine.
Computes multi-factor evidence weights (0-100), explicit supporting and counter-evidence,
dependency correlations, confidence bounds, and recommended remediation options.
Scores are heuristic evidence weights, not learned probabilities.
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.models import Incident, ProbeResult
from app.services.incident_detection.detector import (
    CPU_PRESSURE_PCT,
    Detector,
    MEM_PRESSURE_PCT,
    REGRESSION_WINDOW_S,
)


def _cause(
    name: str,
    score: int,
    evidence: list[str],
    steps: list[str],
    counter_evidence: Optional[list[str]] = None,
    confidence: str = "medium",
) -> dict[str, Any]:
    return {
        "cause": name,
        "score": min(100, max(0, score)),
        "confidence": confidence,
        "evidence": evidence,
        "counter_evidence": counter_evidence or [],
        "next_steps": steps,
    }


def diagnose(
    incident: Incident,
    status,
    health: Optional[ProbeResult],
    logs: str = "",
    dependency_health: Optional[dict[str, bool]] = None,
    telemetry_metrics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Diagnoses root cause using multi-signal evidence evaluation."""
    causes: list[dict[str, Any]] = []
    log_errs = [l for l in logs.splitlines() if "Traceback" in l or "ERROR" in l][:3]
    kind = incident.kind

    # ── 1. Deployment Regression ───────────────────────────────────────────────
    if kind == Detector.DEPLOYMENT_REGRESSION:
        ev_items = [e for e in incident.evidence if e.get("signal") == "image_changed"]
        old_v = ev_items[0]["old_version"] if ev_items else "unknown"
        new_v = ev_items[0]["new_version"] if ev_items else "unknown"
        causes.append(
            _cause(
                "bad_deployment",
                92,
                [
                    f"image changed from {old_v} to {new_v}",
                    "health probe started failing immediately following image update",
                    "failure strictly correlated within 5-minute regression window",
                ],
                [
                    "roll back to previous image version",
                    "escalate to release team if rollback is unsupported",
                    "avoid repeated restart — container image contains defect",
                ],
                confidence="high",
            )
        )

    # ── 2. Resource Pressure ──────────────────────────────────────────────────
    elif kind == Detector.RESOURCE_PRESSURE:
        cpu_ev = next((e for e in incident.evidence if e.get("signal") == "cpu_pressure"), None)
        mem_ev = next((e for e in incident.evidence if e.get("signal") == "mem_pressure"), None)
        ev = []
        steps = []
        if cpu_ev:
            ev.append(f"CPU utilization at {cpu_ev['cpu_pct']:.1f}% (threshold {CPU_PRESSURE_PCT}%)")
            steps.append("throttle or pause deferrable background workloads")
        if mem_ev:
            ev.append(f"Memory utilization at {mem_ev['mem_pct']:.1f}% (threshold {MEM_PRESSURE_PCT}%)")
            steps.append("inspect memory leak or pause background sync/analytics tasks")
        causes.append(
            _cause(
                "resource_exhaustion",
                88,
                ev,
                steps or ["inspect host resource distribution"],
                confidence="high",
            )
        )

    # ── 3. Repeated Restarts / Crash Loops ────────────────────────────────────
    elif kind == Detector.REPEATED_RESTARTS:
        rst_ev = next((e for e in incident.evidence if e.get("signal") == "restart_count_increase"), None)
        delta = rst_ev["delta"] if rst_ev else "unknown"
        causes.append(
            _cause(
                "crash_loop",
                85,
                [
                    f"container restarted {delta} times rapidly in current observation window",
                    "workload repeatedly exiting upon initialization",
                ],
                [
                    "inspect initialization container logs",
                    "check environment variables, DB connection strings, and volume permissions",
                ],
                confidence="high",
            )
        )
        if dependency_health:
            unhealthy_deps = [wid for wid, ok in dependency_health.items() if not ok]
            if unhealthy_deps:
                causes.append(
                    _cause(
                        "dependency_unavailable",
                        80,
                        [
                            f"same-store dependent services unhealthy: {unhealthy_deps}",
                            "crash loop likely triggered by connection failure to local service",
                        ],
                        [
                            "recover upstream dependencies before attempting restart",
                            "suppress workload restarts until dependency recovers",
                        ],
                        confidence="high",
                    )
                )

    # ── 4. Sync Backlog ───────────────────────────────────────────────────────
    elif kind == Detector.SYNC_BACKLOG:
        causes.append(
            _cause(
                "network_or_central_unavailable",
                80,
                [
                    "local transaction backlog growing steadily across consecutive ticks",
                    "central ingest endpoint unreachable or not responding with 200/201",
                    "local SQLite transactions preserved safely in offline queue",
                ],
                [
                    "verify store edge WAN / internet connectivity",
                    "inspect central ingest service status",
                    "allow automatic flush once connectivity is restored",
                ],
                confidence="high",
            )
        )
        causes.append(
            _cause(
                "sync_service_overloaded",
                50,
                ["backlog volume exceeding worker sync rate"],
                ["increase sync batch size or worker tick frequency"],
                counter_evidence=["central connectivity may be healthy"],
                confidence="low",
            )
        )

    # ── 5. Standard Crash / Unresponsive ──────────────────────────────────────
    else:
        if not status.found:
            causes.append(
                _cause(
                    "container_missing",
                    95,
                    ["container does not exist in orchestrator inventory"],
                    ["redeploy workload via edge deployment spec"],
                    confidence="high",
                )
            )
        elif not status.running:
            if status.oom_killed:
                causes.append(
                    _cause(
                        "out_of_memory",
                        90,
                        [
                            "container was terminated by kernel OOM-killer",
                            f"exit code {status.exit_code}",
                        ],
                        ["restart container; adjust container memory limits"],
                        confidence="high",
                    )
                )
            elif status.exit_code in (137, 143):
                causes.append(
                    _cause(
                        "killed_by_signal",
                        82,
                        [
                            f"container exited with signal {status.exit_code} (SIGTERM/SIGKILL)",
                            "kernel OOM flag not set",
                        ],
                        ["restart workload; check if external operator issued stop command"],
                        confidence="medium",
                    )
                )
            elif status.exit_code not in (0, None):
                ev = [f"process exited with non-zero exit code {status.exit_code}"]
                ev.extend([f"log snippet: {l[:120]}" for l in log_errs])
                causes.append(
                    _cause(
                        "process_crash",
                        85,
                        ev,
                        ["restart workload; examine exception trace in application logs"],
                        confidence="high",
                    )
                )
            else:
                causes.append(
                    _cause(
                        "clean_exit",
                        60,
                        ["container exited with code 0 (stopped normally)"],
                        ["restart workload; verify if scheduled shutdown was planned"],
                        confidence="low",
                    )
                )
        else:
            # Container is running, but health probe is failing
            ev = ["container status is running", f"health probe failing ({health.error if health else 'no response'})"]
            if status.health:
                ev.append(f"docker health state: {status.health}")

            # Check latency anomaly if metrics available
            if telemetry_metrics and telemetry_metrics.get("p95_latency_ms"):
                ev.append(f"historical p95 latency: {telemetry_metrics['p95_latency_ms']}ms")

            if dependency_health:
                unhealthy_deps = [wid for wid, ok in dependency_health.items() if not ok]
                if unhealthy_deps:
                    causes.append(
                        _cause(
                            "dependency_unavailable",
                            88,
                            [
                                f"same-store dependent services failing: {unhealthy_deps}",
                                "service cannot process transactions without upstream dependency",
                            ],
                            [
                                "restore dependencies first",
                                "do not restart running service — restart will not fix missing dependency",
                            ],
                            confidence="high",
                        )
                    )

            causes.append(
                _cause(
                    "unresponsive_process",
                    72,
                    ev,
                    [
                        "if critical PoS is serving in-flight customers, obtain human approval before restart",
                        "restart service if dependencies are confirmed healthy",
                    ],
                    confidence="medium",
                )
            )

    causes.sort(key=lambda c: -c["score"])
    return {
        "method": "multi_signal_ranked_v3",
        "incident_kind": kind,
        "ranked_causes": causes,
        "note": "scores are explainable heuristic weights (0-100), not probabilities and not learned from data",
        "dependency_health": dependency_health or {},
        "telemetry_metrics": telemetry_metrics or {},
    }
