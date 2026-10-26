"""macOS integration for the official Kerio Control VPN Client.

The vendor client owns the tunnel and authentication protocol.  We intentionally
do not duplicate its proprietary password encryption or modify its root-owned
persistent configuration.  This module provides safe discovery and native UI
entry points around the installed client.
"""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

from . import kvc

INSTALL_DIR = "/usr/local/kerio/vpnclient"
STATUS_APP = os.path.join(INSTALL_DIR, "KVpnClientStatus.app")
PREFPANE_CANDIDATES = (
    "/Library/PreferencePanes/Kerio Control VPN Client.prefPane",
    "/Library/PreferencePanes/Kerio VPN Client.prefPane",
)


@dataclass(frozen=True)
class NativeConnection:
    name: str
    server: str
    username: str
    persistent: bool = False


def installed() -> bool:
    return os.path.isfile(kvc.DAEMON)


def read_connections(path: str = kvc.CONFIG_PATH) -> List[NativeConnection]:
    """Read non-secret metadata from the vendor-owned per-user configuration."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    result = []
    for node in root.findall("./connections/connection"):
        def value(tag: str) -> str:
            el = node.find(tag)
            return (el.text or "").strip() if el is not None else ""
        server = value("server")
        if server:
            result.append(NativeConnection(
                name=value("description") or server,
                server=server,
                username=value("username"),
                persistent=value("persistent") in ("1", "true", "yes"),
            ))
    return result


def open_client() -> None:
    """Open the vendor UI, which is the supported connect/disconnect controller."""
    targets = [p for p in PREFPANE_CANDIDATES if os.path.exists(p)]
    target = targets[0] if targets else STATUS_APP
    if not os.path.exists(target):
        raise RuntimeError("Kerio Control VPN Client is not installed")
    subprocess.run(["open", target], check=True)


def reveal_logs() -> None:
    os.makedirs(kvc.LOG_DIR, mode=0o700, exist_ok=True)
    subprocess.run(["open", kvc.LOG_DIR], check=True)
