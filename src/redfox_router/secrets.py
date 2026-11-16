"""Resolve backend API keys.

Order: environment variable first (so a daemon/launchd env wins), then macOS
Keychain under `claude-vault.<slug>` (the credential-injector vault convention
used by redfox-team/scripts/provider_secrets.py). Values are never written to a
file or the router DB by this module.
"""
from __future__ import annotations

import os
import subprocess

SERVICE_PREFIX = "claude-vault"


def keychain_get(slug: str) -> str | None:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", f"{SERVICE_PREFIX}.{slug}", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def resolve(env_var: str, key_slug: str) -> str | None:
    """env var, then Keychain."""
    val = os.environ.get(env_var)
    if val and val.strip():
        return val.strip()
    return keychain_get(key_slug)
