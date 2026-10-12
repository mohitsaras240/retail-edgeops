"""Inject a REAL fault into the demo PoS container.
  crash   -> docker kill <container>           (real process kill)
  degrade -> POST /_fault/degrade              (service stays up but returns 503)
  clear   -> POST /_fault/clear
"""
import argparse
import re
import subprocess
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fault", choices=["crash", "degrade", "clear"])
    ap.add_argument("--container", default="rea-store001-pos")
    ap.add_argument("--base-url", default="http://127.0.0.1:18081")
    a = ap.parse_args()
    if not re.fullmatch(r"rea-[a-z0-9-]+", a.container):       # only ever touch this project's containers
        print("refusing: container name must match rea-[a-z0-9-]+")
        return 2
    if a.fault == "crash":
        p = subprocess.run(["docker", "kill", a.container], capture_output=True, text=True)
        print(p.stdout.strip() or p.stderr.strip())
        return p.returncode
    req = urllib.request.Request(f"{a.base_url}/_fault/{a.fault}", data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        print(r.status, r.read().decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
