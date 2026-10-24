"""Plain-text diagnostics report for support requests. Never contains passwords."""

from __future__ import annotations

import platform
import time

from . import VERSION, system
from .monitor import Monitor


def _section(title: str, body: str) -> str:
    return "== %s ==\n%s\n" % (title, body.rstrip() or "(empty)")


def build_report(monitor: Monitor) -> str:
    snap = monitor.snapshot
    info = snap.info
    parts = ["Kerio VPN %s diagnostics — %s\n" % (
        VERSION, time.strftime("%Y-%m-%d %H:%M:%S %z"))]

    os_name = ""
    try:
        with open("/etc/os-release") as f:
            os_name = next((l.split("=", 1)[1].strip().strip('"') for l in f
                            if l.startswith("PRETTY_NAME=")), "")
    except OSError:
        pass
    parts.append(_section("System", "OS: %s\nKernel: %s\nPython: %s" % (
        os_name, platform.release(), platform.python_version())))

    checks = system.check_environment()
    parts.append(_section("Checks", "\n".join(
        "%-9s %-4s %s" % (k, "OK" if ok else "FAIL", d) for k, (ok, d) in checks.items())))

    svc = snap.service
    parts.append(_section("State", "\n".join([
        "state: %s" % snap.state,
        "service: active=%s sub=%s enabled=%s pid=%s" % (svc.active, svc.sub, svc.enabled,
                                                         svc.main_pid),
        "daemon: %s" % info.daemon_version,
        "server: %s (%s) user: %s" % (info.server, info.server_ip, info.username),
        "vpn ip: %s/%s dns: %s domain: %s" % (info.local_ip, info.netmask,
                                               ", ".join(info.dns), info.domain),
        "full tunnel: %s routes: %s" % (info.is_full_tunnel,
                                        ", ".join(str(r) for r in info.routes)),
        "interface: %s rx=%d tx=%d latency=%s" % (snap.iface, snap.rx_bytes, snap.tx_bytes,
                                                 snap.latency_ms),
        "last error: %s (%s) x%d" % (info.last_error_code, info.last_error_text,
                                     info.consecutive_errors),
    ])))

    for title, cmd in (("Addresses", ["ip", "-br", "addr"]),
                       ("Routes", ["ip", "route"]),
                       ("DNS", ["cat", "/etc/resolv.conf"])):
        _rc, out, err = system.run(cmd)
        parts.append(_section(title, out or err))

    lines = monitor.recent_lines(include_noise=False)[-300:]
    parts.append(_section("debug.log (last 300 relevant lines)",
                          "\n".join(l.raw for l in lines)))
    parts.append(_section("error.log (last 50 lines)",
                          "\n".join(list(monitor.error_lines)[-50:])))
    return "\n".join(parts)
