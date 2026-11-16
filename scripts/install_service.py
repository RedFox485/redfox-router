#!/usr/bin/env python3
"""Install the RedFox Router as a launchd service (macOS).

    python3 scripts/install_service.py          # create + load
    python3 scripts/install_service.py uninstall

Serves 127.0.0.1:8787 by default (override with REDFOX_ROUTER_PORT).
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.daniel.redfox-router"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install():
    port = os.environ.get("REDFOX_ROUTER_PORT", "8787")
    (ROOT / "logs").mkdir(exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "uvicorn",
                             "redfox_router.server:app", "--host", "127.0.0.1", "--port", port],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(ROOT / "logs" / "redfox_router.log"),
        "StandardErrorPath": str(ROOT / "logs" / "redfox_router.err"),
        "EnvironmentVariables": {
            "PYTHONPATH": str(ROOT / "src"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", str(Path.home())),
            "REDFOX_ROUTER_PORT": port,
        },
        "WorkingDirectory": str(ROOT),
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist))
    print(f"Wrote {PLIST}")
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    r = subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"launchctl load failed: {r.stderr}", file=sys.stderr)
        return 1
    print(f"Loaded {LABEL} -> http://127.0.0.1:{port}")
    return 0


def uninstall():
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()
        print(f"Removed {PLIST}")
    else:
        print("Plist not found")
    return 0


if __name__ == "__main__":
    sys.exit(uninstall() if len(sys.argv) > 1 and sys.argv[1] == "uninstall" else install())
