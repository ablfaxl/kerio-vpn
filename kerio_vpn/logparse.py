"""Parse kvpncsvc logs and derive the tunnel state from them.

kvpncsvc offers no status API, but its debug.log reports every transition of
its internal state machine (VpnFSM).  The patterns below were taken from
kvpncsvc 9.x; unknown lines are ignored so newer versions degrade gracefully.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}

LINE_RE = re.compile(
    r"^\[(\d{2})/(\w{3})/(\d{4}) (\d{2}):(\d{2}):(\d{2})\] (?:\{(\w+)\} )?(.*)$")

# High-volume lines that carry no state information.
NOISE_RE = re.compile(
    r"IP packet .* handled|Last message repeated|VpnFSM: GetStatus\(\)|"
    r"WorkerThread|KVpnExactRouteExists|KVpnGetRoute\(")

_IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
P_STARTED = re.compile(r"Kerio Control VPN Client Service (.+?) started\.")
P_STOPPED = re.compile(r"Kerio Control VPN Client Service (.+?) stopped\.")
P_CONNECT = re.compile(r"Connect\(User: (.*), Server (\S+), id\[")
P_RESOLVED = re.compile(r"server name resolved - " + _IP)
P_RESOLVE_FAIL = re.compile(r"unable to resolve server name")
P_SSL_OK = re.compile(r"SSL connection successfully established")
P_SSL_FAIL = re.compile(r"unable to establish SSL connection - SSL error (\S+)")
P_IPCONFIG = re.compile(
    r"received R_IPCONFIG V\d+ message, IP = " + _IP + "/" + _IP +
    r", DNS = " + _IP + ", " + _IP + r" '([^']*)'")
P_NEWCONN = re.compile(
    r"Creating new VPN connection: local IP " + _IP + "/" + _IP +
    r", DNS " + _IP + ", " + _IP)
P_DEFAULT_ROUTE = re.compile(r"received ROUTES with default route flag")
P_ROUTE = re.compile(r"^Route " + _IP + "/" + _IP + " gw " + _IP)
P_DRIVER = re.compile(r"VPN driver opened, version = \S+, ifIndex = (\d+)")
P_LIBVPN = re.compile(r"Callback StatusChanged called from libVpn\(([^)]*)\)")
P_ENGINE = re.compile(r"(?:Saving and sending|Sending) status to Engine \((\w+)\)")
P_ERRLOG = re.compile(r"libVPN: (.*?)\((\d+)\)\s*$")
P_MAC_CONNECT = re.compile(r'TinyDB RPC Client received notification packet \(select connect\("([^"]+)", "([^"]+)"')
P_MAC_STATUS = re.compile(r"TinyDB RPC Client received status packet \(([^,]+), err: (\d+)\)")

# Tunnel states exposed to the UI.
NOT_INSTALLED = "not-installed"
STOPPED = "stopped"
STARTING = "starting"
CONNECTING = "connecting"
CONNECTED = "connected"
RECONNECTING = "reconnecting"
DISCONNECTING = "disconnecting"


@dataclass
class LogLine:
    raw: str
    ts: Optional[float]
    source: str
    message: str

    @property
    def noisy(self) -> bool:
        return bool(NOISE_RE.search(self.message))

    @property
    def level(self) -> str:
        m = self.message.lower()
        if "error" in m or "failed" in m or "unable" in m or "timeout" in m:
            return "error"
        if "warning" in m or "abort" in m or "closing connection" in m:
            return "warning"
        if self.source in ("info",) or "connected" in m or "established" in m:
            return "info"
        return "debug"


def parse_ts(day: str, mon: str, year: str, hh: str, mm: str, ss: str) -> Optional[float]:
    try:
        return time.mktime((int(year), MONTHS[mon], int(day),
                            int(hh), int(mm), int(ss), 0, 0, -1))
    except (KeyError, ValueError, OverflowError):
        return None


def parse_line(raw: str) -> LogLine:
    raw = raw.rstrip("\r\n")
    m = LINE_RE.match(raw)
    if not m:
        return LogLine(raw, None, "", raw)
    return LogLine(raw, parse_ts(*m.groups()[:6]), m.group(7) or "", m.group(8))


@dataclass
class Route:
    network: str
    netmask: str
    gateway: str

    def __str__(self) -> str:
        try:
            import ipaddress
            prefix = ipaddress.IPv4Network("0.0.0.0/" + self.netmask).prefixlen
            return "%s/%d" % (self.network, prefix)
        except ValueError:
            return "%s/%s" % (self.network, self.netmask)


@dataclass
class TunnelInfo:
    """Everything we know about the current daemon session, from the logs."""
    phase: str = STOPPED            # stopped|connecting|connected|reconnecting|disconnecting
    daemon_version: str = ""
    username: str = ""
    server: str = ""
    server_ip: str = ""
    local_ip: str = ""
    netmask: str = ""
    dns: List[str] = field(default_factory=list)
    domain: str = ""
    full_tunnel: bool = False
    routes: List[Route] = field(default_factory=list)
    if_index: Optional[int] = None
    connected_since: Optional[float] = None
    last_error_code: Optional[int] = None
    last_error_text: str = ""
    last_error_ts: Optional[float] = None
    consecutive_errors: int = 0
    ssl_detail: str = ""
    session_started: Optional[float] = None
    attempt: int = 0

    @property
    def is_full_tunnel(self) -> bool:
        return self.full_tunnel or any(
            r.network in ("0.0.0.0", "128.0.0.0") and r.netmask in ("0.0.0.0", "128.0.0.0")
            for r in self.routes)


class StateTracker:
    """Feeds debug.log lines through a tiny state machine."""

    def __init__(self) -> None:
        self.info = TunnelInfo()

    def reset(self) -> None:
        self.info = TunnelInfo()

    def feed_many(self, lines: Iterable[LogLine]) -> bool:
        changed = False
        for line in lines:
            changed |= self.feed(line)
        return changed

    def feed(self, line: LogLine) -> bool:
        msg = line.message
        if line.noisy:
            return False
        info = self.info

        m = P_MAC_CONNECT.search(msg)
        if m:
            info.server, info.username = m.group(1), m.group(2)
            info.attempt += 1
            info.phase = CONNECTING
            return True

        m = P_MAC_STATUS.search(msg)
        if m:
            status, error = m.group(1).strip().lower(), int(m.group(2))
            if status == "connected":
                info.phase = CONNECTED
                info.connected_since = line.ts or time.time()
                info.consecutive_errors = 0
                info.last_error_code = None
            elif status == "disconnected":
                info.phase = STOPPED
                info.connected_since = None
            elif status in ("connecting", "checking certificate"):
                info.phase = CONNECTING
            if error:
                info.last_error_code = error
                info.last_error_ts = line.ts
                info.consecutive_errors += 1
            return True

        m = P_STARTED.search(msg)
        if m:
            version = m.group(1)
            self.info = TunnelInfo(phase=CONNECTING, daemon_version=version,
                                   session_started=line.ts)
            return True
        if P_STOPPED.search(msg):
            keep = info.daemon_version
            err = (info.last_error_code, info.last_error_text, info.last_error_ts,
                   info.consecutive_errors)
            self.info = TunnelInfo(phase=STOPPED, daemon_version=keep)
            (self.info.last_error_code, self.info.last_error_text,
             self.info.last_error_ts, self.info.consecutive_errors) = err
            return True

        m = P_DRIVER.search(msg)
        if m:
            info.if_index = int(m.group(1))
            return True

        m = P_CONNECT.search(msg)
        if m:
            info.username, info.server = m.group(1), m.group(2)
            info.attempt += 1
            if info.phase != CONNECTED:
                info.phase = RECONNECTING if info.consecutive_errors else CONNECTING
            info.routes = []
            info.full_tunnel = False
            return True

        m = P_RESOLVED.search(msg)
        if m:
            info.server_ip = m.group(1)
            return True

        m = P_SSL_FAIL.search(msg)
        if m:
            info.ssl_detail = m.group(1)
            return True

        m = P_IPCONFIG.search(msg)
        if m:
            info.local_ip, info.netmask = m.group(1), m.group(2)
            info.domain = m.group(5)
            return True

        m = P_NEWCONN.search(msg)
        if m:
            info.local_ip, info.netmask = m.group(1), m.group(2)
            info.dns = [d for d in (m.group(3), m.group(4)) if d != "0.0.0.0"]
            return True

        if P_DEFAULT_ROUTE.search(msg):
            info.full_tunnel = True
            return True

        m = P_ROUTE.search(msg)
        if m and line.source == "vpnCore":
            route = Route(*m.groups())
            if all(r.network != route.network or r.netmask != route.netmask
                   for r in info.routes):
                info.routes.append(route)
            return True

        m = P_LIBVPN.search(msg)
        if m:
            status = m.group(1)
            if status == "connected":
                info.phase = CONNECTED
                info.connected_since = line.ts or time.time()
                info.consecutive_errors = 0
                info.last_error_code = None
                info.last_error_text = ""
            elif status.startswith("error"):
                try:
                    code = int(status.split()[1])
                except (IndexError, ValueError):
                    code = 0
                info.consecutive_errors = (
                    info.consecutive_errors + 1 if code == info.last_error_code else 1)
                info.last_error_code = code
                info.last_error_ts = line.ts
                info.phase = RECONNECTING
                info.connected_since = None
                info.local_ip = ""
            elif status == "abort":
                info.phase = RECONNECTING
                info.connected_since = None
            elif status.startswith("disconnected"):
                info.connected_since = None
                info.local_ip = ""
                if info.phase != DISCONNECTING:
                    info.phase = RECONNECTING if "not disconnecting" in status else CONNECTING
            return True

        m = P_ENGINE.search(msg)
        if m and m.group(1) == "disconnecting":
            info.phase = DISCONNECTING
            return True
        return False


@dataclass
class ErrorEntry:
    ts: Optional[float]
    text: str
    code: Optional[int]


def parse_error_line(raw: str) -> ErrorEntry:
    line = parse_line(raw)
    m = P_ERRLOG.search(line.message)
    if m:
        return ErrorEntry(line.ts, m.group(1).strip(), int(m.group(2)))
    return ErrorEntry(line.ts, line.message, None)
