"""Client side of the root helper (see helper.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

INSTALLED_LIBEXEC = "/usr/lib/kerio-vpn/libexec"
_SOURCE_LIBEXEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "libexec")

# pkexec exit codes
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORIZED = 127


class PrivilegeError(Exception):
    def __init__(self, message: str, cancelled: bool = False):
        super().__init__(message)
        self.cancelled = cancelled


def _helper_path(level: str) -> str:
    name = "kerio-vpn-" + level
    installed = os.path.join(INSTALLED_LIBEXEC, name)
    if os.path.exists(installed):
        return installed
    return os.path.join(_SOURCE_LIBEXEC, name)


def helper_installed() -> bool:
    """True when the packaged helper (with its polkit policy) is present."""
    return os.path.exists(os.path.join(INSTALLED_LIBEXEC, "kerio-vpn-control"))


def call(level: str, action: str, args: Optional[Dict[str, Any]] = None,
         timeout: float = 90) -> Dict[str, Any]:
    """Run one helper action as root. Blocking - call from a worker thread."""
    path = _helper_path(level)
    if os.geteuid() == 0:
        cmd = [path, action]
    else:
        if not shutil.which("pkexec"):
            raise PrivilegeError("pkexec (polkit) is not installed")
        cmd = ["pkexec", path, action]
    try:
        p = subprocess.run(cmd, input=json.dumps(args or {}), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PrivilegeError("The operation timed out")
    except OSError as e:
        raise PrivilegeError(str(e))

    line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
    try:
        reply = json.loads(line) if line else None
    except ValueError:
        reply = None
    if reply is None:
        if p.returncode in (PKEXEC_DISMISSED, PKEXEC_NOT_AUTHORIZED):
            raise PrivilegeError("Authorization was cancelled or denied", cancelled=True)
        raise PrivilegeError((p.stderr or "").strip() or "Helper failed (exit %d)" % p.returncode)
    if not reply.get("ok"):
        raise PrivilegeError(reply.get("error") or "Operation failed")
    return reply


def control(action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return call("control", action, args)


def configure(action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return call("configure", action, args)
