"""Per-user login autostart (XDG autostart .desktop file)."""

from __future__ import annotations

import os
import shutil
import sys

from .. import APP_NAME

FILE_NAME = "kerio-vpn.desktop"
LEGACY_FILE_NAME = "kerio-vpn-panel.desktop"   # releases before 1.1


def _path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", FILE_NAME)


def _command() -> str:
    exe = shutil.which("kerio-vpn")
    if exe:
        return exe
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "bin", "kerio-vpn")
    return launcher if os.path.exists(launcher) else "%s -m kerio_vpn" % sys.executable


def is_enabled() -> bool:
    legacy = os.path.join(os.path.dirname(_path()), LEGACY_FILE_NAME)
    if os.path.exists(legacy):
        os.unlink(legacy)
        set_enabled(True)
    return os.path.exists(_path())


def set_enabled(enabled: bool) -> None:
    path = _path()
    if not enabled:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=%s --minimized\n"
                "Icon=kerio-vpn\nX-GNOME-Autostart-enabled=true\n"
                "X-GNOME-Autostart-Delay=3\nNoDisplay=true\n" % (APP_NAME, _command()))
