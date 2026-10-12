"""Script to inject controlled faults into simulated store workloads for demonstration and testing.
Usage:
  python inject_fault.py --scenario crash --workload rea-store001-pos
  python inject_fault.py --scenario degrade --port 18081
  python inject_fault.py --scenario clear --port 18081
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


def inject_http(port: int, path: str, method: str = "POST", payload: dict | None = None) -> None:
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[{resp.status}] Injected {path} into port {port}: {resp.read().decode('utf-8')}")
    except Exception as ex:
        print(f"Failed to inject into {url}: {ex}", file=sys.stderr)
        sys.exit(1)


def kill_container(container_name: str) -> None:
    print(f"Stopping container {container_name} via Docker CLI...")
    res = subprocess.run(["docker", "stop", container_name], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Successfully stopped {container_name}")
    else:
        print(f"Error stopping container: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Inject controlled faults into edge workloads.")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=["crash", "degrade", "clear", "block_sync", "unblock_sync"],
        help="Fault scenario to inject",
    )
    parser.add_argument("--workload", help="Container name for docker kill (e.g. rea-store001-pos)")
    parser.add_argument("--port", type=int, help="Workload host port for HTTP fault injection (e.g. 18081)")

    args = parser.parse_args()

    if args.scenario == "crash":
        if not args.workload:
            print("--workload is required for crash scenario", file=sys.stderr)
            sys.exit(1)
        kill_container(args.workload)
    elif args.scenario == "degrade":
        if not args.port:
            print("--port is required for degrade scenario", file=sys.stderr)
            sys.exit(1)
        inject_http(args.port, "/_fault/degrade")
    elif args.scenario == "clear":
        if not args.port:
            print("--port is required for clear scenario", file=sys.stderr)
            sys.exit(1)
        inject_http(args.port, "/_fault/clear")
    elif args.scenario == "block_sync":
        if not args.port:
            print("--port is required for block_sync scenario", file=sys.stderr)
            sys.exit(1)
        inject_http(args.port, "/_fault/block")
    elif args.scenario == "unblock_sync":
        if not args.port:
            print("--port is required for unblock_sync scenario", file=sys.stderr)
            sys.exit(1)
        inject_http(args.port, "/_fault/unblock")


if __name__ == "__main__":
    main()
