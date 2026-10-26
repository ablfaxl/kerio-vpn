"""Unprivileged queries about the host: service state, interfaces, logs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import kvc

SYS_NET = "/sys/class/net"


def has_systemd() -> bool:
    return os.path.isdir("/run/systemd/system")


def run(cmd: List[str], timeout: float = 5.0, stdin: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                           timeout=timeout, env=dict(os.environ, LC_ALL="C"))
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "%s: not found" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "%s: timed out" % cmd[0]


@dataclass
class ServiceState:
    installed: bool = False
    loaded: bool = False
    active: str = "inactive"      # active|inactive|activating|deactivating|failed|unknown
    sub: str = ""
    enabled: str = "disabled"    # enabled|disabled|static|...
    main_pid: int = 0

    @property
    def running(self) -> bool:
        return self.active in ("active", "activating", "reloading")


def daemon_installed() -> bool:
    return os.path.exists(kvc.DAEMON)


def daemon_version() -> str:
    if sys.platform == "darwin":
        info = "/usr/local/kerio/vpnclient/KVpnClientStatus.app/Contents/Info.plist"
        rc, out, _ = run(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleShortVersionString", info])
        return out.strip() if rc == 0 else ""
    rc, out, _ = run(["dpkg-query", "-W", "-f=${Version}", kvc.DEB_PACKAGE])
    return out.strip() if rc == 0 else ""


def _pgrep_daemon() -> int:
    rc, out, _ = run(["pgrep", "-x", "kvpncsvc"], timeout=2)
    if rc == 0 and out.split():
        return int(out.split()[0])
    return 0


def service_state() -> ServiceState:
    st = ServiceState(installed=daemon_installed())
    if not st.installed:
        return st
    if sys.platform == "darwin":
        rc, out, err = run(["launchctl", "print", "system/" + kvc.SERVICE], timeout=3)
        st.loaded = rc == 0
        text = out + "\n" + err
        pid_match = re.search(r"\bpid\s*=\s*(\d+)", text)
        state_match = re.search(r"\bstate\s*=\s*(\w+)", text)
        st.main_pid = int(pid_match.group(1)) if pid_match else _pgrep_daemon()
        state = state_match.group(1).lower() if state_match else ""
        st.active = "active" if st.main_pid or state == "running" else "inactive"
        st.enabled = "enabled" if st.loaded else "disabled"
        return st
    if not has_systemd():
        pid = _pgrep_daemon()
        st.loaded = os.path.exists(kvc.INIT_SCRIPT)
        st.active = "active" if pid else "inactive"
        st.main_pid = pid
        st.enabled = "unknown"
        return st
    rc, out, _ = run(["systemctl", "show", kvc.SERVICE, "-p", "LoadState",
                      "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState",
                      "-p", "MainPID"], timeout=3)
    if rc != 0:
        st.active = "unknown"
        return st
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    st.loaded = props.get("LoadState") == "loaded"
    st.active = props.get("ActiveState", "unknown")
    st.sub = props.get("SubState", "")
    st.enabled = props.get("UnitFileState", "") or "disabled"
    try:
        st.main_pid = int(props.get("MainPID", "0"))
    except ValueError:
        st.main_pid = 0
    if not st.main_pid and st.active == "active":
        st.main_pid = _pgrep_daemon()
    return st


def interface_by_index(index: Optional[int]) -> Optional[str]:
    if index is None:
        return None
    if sys.platform == "darwin":
        rc, out, _ = run(["ifconfig", "-l"], timeout=2)
        for name in out.split():
            rc, detail, _ = run(["ifconfig", name], timeout=2)
            m = re.search(r"\bindex\s+(\d+)\b", detail)
            if rc == 0 and m and int(m.group(1)) == index:
                return name
        return None
    try:
        for name in os.listdir(SYS_NET):
            try:
                with open(os.path.join(SYS_NET, name, "ifindex")) as f:
                    if int(f.read().strip()) == index:
                        return name
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return None


def guess_vpn_interface(index: Optional[int]) -> Optional[str]:
    name = interface_by_index(index)
    if name:
        return name
    if sys.platform == "darwin":
        rc, out, _ = run(["ifconfig", "-l"], timeout=2)
        candidates = [n for n in out.split() if n.startswith(("kvnet", "utun"))]
        return candidates[-1] if candidates else None
    try:
        for name in sorted(os.listdir(SYS_NET)):
            if name.startswith("kvnet"):
                return name
    except OSError:
        pass
    return None


def interface_counters(name: str) -> Optional[Tuple[int, int]]:
    if sys.platform == "darwin":
        rc, out, _ = run(["netstat", "-ibn", "-I", name], timeout=2)
        for line in reversed(out.splitlines()):
            parts = line.split()
            if parts and parts[0] == name and len(parts) >= 10:
                try:
                    return int(parts[6]), int(parts[9])
                except (ValueError, IndexError):
                    pass
        return None
    base = os.path.join(SYS_NET, name, "statistics")
    try:
        with open(base + "/rx_bytes") as f:
            rx = int(f.read())
        with open(base + "/tx_bytes") as f:
            tx = int(f.read())
        return rx, tx
    except (OSError, ValueError):
        return None


def interface_up(name: str) -> bool:
    if sys.platform == "darwin":
        rc, out, _ = run(["ifconfig", name], timeout=2)
        return rc == 0 and "UP" in out.splitlines()[0] if out else False
    try:
        with open(os.path.join(SYS_NET, name, "operstate")) as f:
            return f.read().strip() in ("up", "unknown")
    except OSError:
        return False


_PING_RE = re.compile(r"time[=<]([\d.]+) ?ms")


def ping(host: str, timeout: int = 2) -> Optional[float]:
    if not shutil.which("ping"):
        return None
    args = (["ping", "-n", "-c", "1", "-W", str(timeout * 1000), host]
            if sys.platform == "darwin" else
            ["ping", "-n", "-c", "1", "-W", str(timeout), host])
    rc, out, _ = run(args, timeout=timeout + 2)
    if rc != 0:
        return None
    m = _PING_RE.search(out)
    return float(m.group(1)) if m else None


def nameservers() -> List[str]:
    if sys.platform == "darwin":
        rc, out, _ = run(["scutil", "--dns"], timeout=3)
        return list(dict.fromkeys(re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", out)))
    servers = []
    try:
        with open(kvc.RESOLV_CONF) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    servers.append(parts[1])
    except OSError:
        pass
    return servers


def resolved_active() -> bool:
    if not shutil.which("resolvectl"):
        return False
    rc, out, _ = run(["systemctl", "is-active", "systemd-resolved"], timeout=2)
    return out.strip() == "active"


def default_route_interfaces() -> List[str]:
    if sys.platform == "darwin":
        rc, out, _ = run(["route", "-n", "get", "default"], timeout=2)
        m = re.search(r"interface:\s*(\S+)", out)
        return [m.group(1)] if m else []
    rc, out, _ = run(["ip", "-o", "route", "show", "default"], timeout=2)
    names = []
    for line in out.splitlines():
        parts = line.split()
        if "dev" in parts:
            names.append(parts[parts.index("dev") + 1])
    return names


def uplink(exclude_iface: Optional[str]) -> Optional[Tuple[str, str]]:
    """(gateway, device) of the physical default route, ignoring the VPN."""
    rc, out, _ = run(["ip", "-4", "route", "show", "default"], timeout=2)
    best = None
    for line in out.splitlines():
        parts = line.split()
        if "via" not in parts or "dev" not in parts:
            continue
        dev = parts[parts.index("dev") + 1]
        if dev == exclude_iface or dev.startswith("kvnet"):
            continue
        metric = int(parts[parts.index("metric") + 1]) if "metric" in parts else 0
        if best is None or metric < best[0]:
            best = (metric, parts[parts.index("via") + 1], dev)
    return (best[1], best[2]) if best else None


def tcp_latency(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    import socket
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.monotonic() - start) * 1000.0
    except OSError:
        return None


def tun_available() -> bool:
    if sys.platform == "darwin":
        return daemon_installed()
    return os.path.exists("/dev/net/tun")


def check_environment() -> Dict[str, Tuple[bool, str]]:
    """Return {check: (ok, detail)} for the System page."""
    ver = daemon_version()
    st = service_state()
    if sys.platform == "darwin":
        return {
            "daemon": (daemon_installed(), ver or kvc.DAEMON),
            "service": (st.loaded, kvc.INIT_SCRIPT),
            "vpn-interface": (bool(guess_vpn_interface(None)), "kvnet/utun"),
            "logs": (os.access(kvc.DEBUG_LOG, os.R_OK), kvc.DEBUG_LOG),
        }
    checks = {
        "daemon": (daemon_installed(), ver or kvc.DAEMON),
        "service": (st.loaded, kvc.SERVICE if has_systemd() else kvc.INIT_SCRIPT),
        "tun": (tun_available(), "/dev/net/tun"),
        "pkexec": (bool(shutil.which("pkexec")), shutil.which("pkexec") or "pkexec"),
        "logs": (os.access(kvc.DEBUG_LOG, os.R_OK), kvc.DEBUG_LOG),
        "nft": (bool(shutil.which("nft") or os.path.exists("/usr/sbin/nft")), "nftables"),
        "resolved": (resolved_active(), "systemd-resolved"),
    }
    return checks
