"""Environment check. Run: python scripts/setup_check.py"""
import shutil
import subprocess
import sys


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def main() -> int:
    ok = True
    print(f"python  : {sys.version.split()[0]}", "OK" if sys.version_info >= (3, 12) else "WARN (3.12+ intended)")
    for tool in ("docker", "git", "node"):
        print(f"{tool:8}: {shutil.which(tool) or 'NOT FOUND'}")
    rc, out = run(["docker", "info", "--format", "{{.ServerVersion}} {{.OperatingSystem}}"])
    print("docker daemon:", out if rc == 0 else f"NOT REACHABLE ({out[:120]})")
    ok &= rc == 0
    rc, out = run(["docker", "compose", "version"])
    print("compose :", out if rc == 0 else "NOT FOUND")
    ok &= rc == 0
    print("\nioFog   : not integrated yet (Phase 0 found v3.8/3.9 needs edgelet; Windows support unverified)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
