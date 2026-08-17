"""Small boundary for loading the database admin secret securely."""

from __future__ import annotations

import os
import subprocess
import sys

KEYCHAIN_SERVICE = "Bolt Hole Admin Token"


def get_admin_token() -> str:
    """Prefer the environment; on macOS fall back to the user's Keychain."""
    token = os.getenv("BOLT_ADMIN_TOKEN", "").strip()
    if token or sys.platform != "darwin":
        return token
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.getenv("USER", ""),
             "-s", KEYCHAIN_SERVICE, "-w"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
