"""Phase 1 demo against the REAL Docker container (requires `docker compose up -d --build`).
Runs the engine in-process, injects a fault, and prints the incident timeline.

  python scripts/run_phase1_demo.py crash
  python scripts/run_phase1_demo.py degrade --auto-approve     # needs approval; flag auto-approves as 'demo-cli'
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.orchestrator.docker_local import DockerLocalOrchestrator  # noqa: E402
from app.core.config import EngineConfig, load_workloads  # noqa: E402
from app.core.models import IncidentState as S  # noqa: E402
from app.services.engine import AutopilotEngine  # noqa: E402
from app.services.telemetry.prober import HttpProber  # noqa: E402


def stats(base):
    with urllib.request.urlopen(base + "/stats", timeout=3) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fault", choices=["crash", "degrade"])
    ap.add_argument("--auto-approve", action="store_true")
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args()

    specs = load_workloads(ROOT / "config" / "workloads.json")
    spec = specs[0]
    base = spec.health_url.rsplit("/health", 1)[0]
    cfg = EngineConfig(base_backoff_s=3, verify_deadline_s=40)
    eng = AutopilotEngine(specs, DockerLocalOrchestrator(), HttpProber(cfg.probe_timeout_s), cfg)

    eng.tick(); eng.tick()
    if eng.monitoring_errors:
        print("monitoring error (is Docker running / compose up?):", eng.monitoring_errors)
        return 2
    for _ in range(5):
        urllib.request.urlopen(urllib.request.Request(base + "/transaction", data=b'{"item_count":2}', method="POST",
                               headers={"Content-Type": "application/json"}), timeout=3).read()
    before = stats(base)
    print("[real docker] baseline:", before)

    subprocess.run([sys.executable, str(ROOT / "scripts" / "inject_fault.py"), a.fault], check=True)
    t0 = time.time()
    approved = False
    while time.time() - t0 < a.timeout:
        time.sleep(1)
        eng.tick()
        for inc in eng.incidents.values():
            if inc.state == S.AWAITING_APPROVAL and a.auto_approve and not approved:
                eng.approve(inc.id, "demo-cli"); approved = True
        if eng.incidents and all(not i.is_open for i in eng.incidents.values()):
            break
    for inc in eng.incidents.values():
        print(f"\nincident {inc.id} [{inc.provenance.value}] {inc.kind} -> {inc.state.value}")
        print("  top cause:", inc.diagnosis["ranked_causes"][0]["cause"] if inc.diagnosis else None)
        print("  decision :", inc.decision and inc.decision["reason"])
        for t in inc.timeline:
            print(f"  +{t['ts'] - inc.detected_at:5.1f}s {t['state']:18} {t['note']}")
        if inc.verification:
            for c in inc.verification["checks"]:
                print("  check", c["name"], "PASS" if c["passed"] else "FAIL", c["observed"])
        if inc.escalation_reason:
            print("  ESCALATED:", inc.escalation_reason)
    if not eng.incidents:
        print("no incident was detected within the timeout")
    try:
        after = stats(base)
        print("\n[real docker] after:", after)
        print("transactions persisted across restart:", after["transactions_total"] >= before["transactions_total"])
    except OSError as exc:
        print("service unreachable after demo:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
