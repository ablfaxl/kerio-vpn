#!/usr/bin/env python3
"""Render README screenshots from demo data only.

No real profile, log, state or IP address can appear: configuration and logs live in a
temporary directory, addresses are masked, the service monitor is disabled and every
privileged call is blocked.

Usage:
    xvfb-run -a -s "-screen 0 1280x900x24" python3 tools/screenshots.py docs/screenshots
    GTK_THEME=Adwaita:dark ... python3 tools/screenshots.py docs/screenshots --dark
"""

import json
import os
import random
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
DARK = "--dark" in sys.argv
os.makedirs(OUT, exist_ok=True)

# ---- isolated demo environment -------------------------------------------
os.environ["TZ"] = "UTC"     # no local time zone in any rendered time
time.tzset()
TMP = tempfile.mkdtemp(prefix="kerio-vpn-shots-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
FP = "0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0"
os.makedirs(os.path.join(TMP, "config", "kerio-vpn"))
with open(os.path.join(TMP, "config", "kerio-vpn", "profiles.json"), "w") as f:
    json.dump({"version": 1, "profiles": [
        {"id": "demo-hq", "name": "Headquarters", "server": "vpn.example.com", "port": 4090,
         "username": "jane.doe", "fingerprint": FP, "last_connected": 1767225600,  # 2026-01-01 00:00 UTC
         "split_exclude": ["updates.example.org", "downloads.example.com",
                           "media.example.net"],
         "split_include": ["intranet.example.com"]},
        {"id": "demo-branch", "name": "Branch Office", "server": "branch.example.net",
         "port": 4090, "username": "jane.doe", "fingerprint": FP},
        {"id": "demo-lab", "name": "Lab", "server": "lab.example.org", "port": 4091,
         "username": "lab-admin", "fingerprint": FP},
    ]}, f)
with open(os.path.join(TMP, "config", "kerio-vpn", "settings.json"), "w") as f:
    json.dump({"default_profile": "demo-hq", "killswitch": True, "notifications": False}, f)

# Empty log files: the app must never show real log content in screenshots.
log_dir = os.path.join(TMP, "logs")
os.makedirs(log_dir)
for name in ("debug.log", "error.log"):
    open(os.path.join(log_dir, name), "w").close()

# Addresses are masked in screenshots; no IP address appears in any image.
MASK = "•••.•••.•••.•••"

from kerio_vpn import kvc  # noqa: E402
kvc.DEBUG_LOG = os.path.join(log_dir, "debug.log")
kvc.ERROR_LOG = os.path.join(log_dir, "error.log")

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402
from gi.repository import GLib  # noqa: E402

from kerio_vpn import controller, monitor, privileged, system  # noqa: E402


# ---- hard sandbox: never touch the real system ----------------------------
def _no_privileged(*_args, **_kwargs):
    raise privileged.PrivilegeError("disabled while rendering screenshots", cancelled=True)


privileged.call = _no_privileged
privileged.control = _no_privileged
privileged.configure = _no_privileged
monitor.Monitor.start = lambda self: None          # no polling of the real service
controller.Controller._after_connected = lambda self, snap: None
controller.Controller._watch_sleep = lambda self: None
from kerio_vpn.logparse import (CONNECTED, NOT_INSTALLED, STOPPED, Route,  # noqa: E402
                                TunnelInfo)
from kerio_vpn.monitor import Snapshot  # noqa: E402
from kerio_vpn.ui import app as appmod  # noqa: E402
from kerio_vpn.ui.dialogs import ProfileDialog  # noqa: E402

controller.read_applied = lambda: {"tag": None}
system.daemon_version = lambda: "9.6.1.9306.0.patch1-1"

app = appmod.Application()
state = {"mode": CONNECTED, "n": 0}
random.seed(7)


def snapshot():
    mode = state["mode"]
    state["n"] += 1
    n = state["n"]
    installed = mode != NOT_INSTALLED
    svc = system.ServiceState(installed=installed, loaded=installed,
                              active="active" if mode == CONNECTED else "inactive",
                              enabled="disabled")
    if mode != CONNECTED:
        return Snapshot(state=mode, service=svc)
    info = TunnelInfo(phase=CONNECTED, username="jane.doe", server="vpn.example.com",
                      server_ip="", local_ip=MASK, netmask="24",
                      dns=[MASK], domain="corp.example", full_tunnel=True,
                      routes=[Route(MASK, "255.255.255.0", MASK),
                              Route(MASK, "255.240.0.0", MASK),
                              Route(MASK, "255.255.255.0", MASK)],
                      connected_since=time.time() - 2 * 3600 - 17 * 60 - 42)
    burst = 1.0 + 3.0 * max(0.0, 1 - abs(n - 70) / 25.0)
    rx = random.uniform(180e3, 520e3) * burst
    tx = random.uniform(25e3, 90e3) * burst
    return Snapshot(state=CONNECTED, service=svc, info=info, iface="kvnet",
                    rx_bytes=1_850_000_000 + n * 400_000, tx_bytes=212_000_000 + n * 60_000,
                    rx_rate=rx, tx_rate=tx, latency_ms=18.0)


def emit():
    snap = snapshot()
    app.monitor.snapshot = snap
    app.monitor.emit("changed", snap)


def save(widget, name):
    alloc = widget.get_allocation()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
    widget.draw(cairo.Context(surface))
    path = os.path.join(OUT, name + ".png")
    surface.write_to_png(path)
    print("wrote", path)


def run_shots():
    win = app.window
    win.resize(1180, 800)
    suffix = "-dark" if DARK else ""
    shots = [("dashboard", CONNECTED, "dashboard" + suffix, 120)]
    if not DARK:
        shots += [("connections", CONNECTED, "connections", 2),
                  ("routing", CONNECTED, "split-tunneling", 2),
                  ("settings", CONNECTED, "settings", 2),
                  ("dashboard", NOT_INSTALLED, "install", 2),
                  ("dashboard", STOPPED, "disconnected", 2)]
    steps = []
    for page, mode, name, ticks in shots:
        steps.append(("page", page, mode))
        steps += [("tick",)] * ticks
        steps.append(("save", name))
    if not DARK:
        steps.append(("dialog",))
    steps.append(("quit",))

    def step():
        if not steps:
            return False
        action = steps.pop(0)
        if action[0] == "page":
            state["mode"] = action[2]
            win.show_page(action[1])
        elif action[0] == "tick":
            emit()
        elif action[0] == "save":
            save(win, action[1])
        elif action[0] == "dialog":
            dlg = ProfileDialog(win, app.ctrl.store.get("demo-hq"))
            GLib.timeout_add(600, lambda: (save(dlg, "connection-editor"), dlg.destroy(),
                                           False)[-1])
            steps.insert(0, ("wait",))
        elif action[0] == "wait":
            pass
        elif action[0] == "quit":
            app._quit()
            return False
        GLib.timeout_add(40 if action[0] == "tick" else 900, step)
        return False

    GLib.timeout_add(500, step)
    return False


GLib.timeout_add(2500, run_shots)
app.run([sys.argv[0]])
