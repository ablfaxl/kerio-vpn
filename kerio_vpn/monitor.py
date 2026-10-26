"""Background monitor that turns service state, logs and interface counters
into a single Snapshot for the UI. All blocking work happens off the GTK
main loop; results are delivered with GLib.idle_add."""

from __future__ import annotations

import copy
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

from gi.repository import GLib, GObject

from . import kvc, logparse, system
from .logtail import LogTail
from .logparse import (CONNECTED, CONNECTING, DISCONNECTING, NOT_INSTALLED, RECONNECTING,
                       STARTING, STOPPED, LogLine, TunnelInfo)

POLL_INTERVAL = 1.0
LATENCY_INTERVAL = 10.0
INITIAL_TAIL = 4 * 1024 * 1024
@dataclass
class Snapshot:
    state: str = STOPPED
    service: system.ServiceState = field(default_factory=system.ServiceState)
    info: TunnelInfo = field(default_factory=TunnelInfo)
    iface: Optional[str] = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_rate: float = 0.0
    tx_rate: float = 0.0
    latency_ms: Optional[float] = None
    uplink: Optional[tuple] = None
    logs_readable: bool = True
    timestamp: float = 0.0

    @property
    def connected_for(self) -> Optional[float]:
        if self.state == CONNECTED and self.info.connected_since:
            return max(0.0, time.time() - self.info.connected_since)
        return None


_IP4_RE = re.compile(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)")


def _iface_ipv4(name: str) -> str:
    rc, out, _ = system.run(["ip", "-o", "-4", "addr", "show", "dev", name], timeout=2)
    m = _IP4_RE.search(out)
    return m.group(1) if m else ""


class Monitor(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "log-lines": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "error-lines": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, max_lines: int = 5000):
        super().__init__()
        self.snapshot = Snapshot()
        self.lines_all: Deque[LogLine] = deque(maxlen=max_lines)
        self.lines_important: Deque[LogLine] = deque(maxlen=max_lines)
        self.error_lines: Deque[str] = deque(maxlen=1000)
        self._tracker = logparse.StateTracker()
        self._debug = LogTail(kvc.DEBUG_LOG)
        self._errors = LogTail(kvc.ERROR_LOG)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._prev_counters = None
        self._latency: Optional[float] = None
        self._threads: List[threading.Thread] = []
        self.server_port = kvc.DEFAULT_PORT

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        for target in (self._poll_loop, self._latency_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        """Poll right away (after a user action)."""
        self._wake.set()

    # ------------------------------------------------------------ polling
    def _load_initial(self) -> None:
        raw = self._debug.initial(INITIAL_TAIL)
        parsed = [logparse.parse_line(r) for r in raw]
        start = 0
        for i in range(len(parsed) - 1, -1, -1):
            if logparse.P_STARTED.search(parsed[i].message):
                start = i
                break
        self._tracker.feed_many(parsed[start:])
        self._remember(parsed)
        self.error_lines.extend(self._errors.initial(256 * 1024))

    def _remember(self, parsed: List[LogLine]) -> None:
        with self._lock:
            self.lines_all.extend(parsed)
            self.lines_important.extend(p for p in parsed if not p.noisy)

    def _poll_loop(self) -> None:
        try:
            self._load_initial()
        except Exception:
            pass
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # never let the monitor die
                print("monitor:", e)
            self._wake.wait(POLL_INTERVAL)
            self._wake.clear()

    def _tick(self) -> None:
        raw = self._debug.read_new()
        parsed = [logparse.parse_line(r) for r in raw]
        self._tracker.feed_many(parsed)
        if parsed:
            self._remember(parsed)
            GLib.idle_add(self.emit, "log-lines", parsed)
        err = self._errors.read_new()
        if err:
            self.error_lines.extend(err)
            GLib.idle_add(self.emit, "error-lines", err)

        service = system.service_state()
        info = copy.deepcopy(self._tracker.info)
        snap = Snapshot(service=service, info=info, logs_readable=self._debug.readable,
                        timestamp=time.time())
        snap.state = self._derive_state(service, info)

        if service.running:
            snap.iface = system.guess_vpn_interface(info.if_index)
        if snap.iface:
            counters = system.interface_counters(snap.iface)
            if counters:
                snap.rx_bytes, snap.tx_bytes = counters
                now = time.monotonic()
                if self._prev_counters and self._prev_counters[0] == snap.iface:
                    _, t0, rx0, tx0 = self._prev_counters
                    dt = max(now - t0, 0.001)
                    snap.rx_rate = max(0.0, (snap.rx_bytes - rx0) / dt)
                    snap.tx_rate = max(0.0, (snap.tx_bytes - tx0) / dt)
                self._prev_counters = (snap.iface, now, snap.rx_bytes, snap.tx_bytes)
            if not snap.logs_readable and service.running:
                ip = _iface_ipv4(snap.iface)
                if ip:
                    snap.state = CONNECTED
                    snap.info.local_ip = ip
        else:
            self._prev_counters = None
        snap.latency_ms = self._latency if snap.state == CONNECTED else None
        if snap.state == CONNECTED:
            snap.uplink = system.uplink(snap.iface)
        self.snapshot = snap
        GLib.idle_add(self.emit, "changed", snap)

    @staticmethod
    def _derive_state(service: system.ServiceState, info: TunnelInfo) -> str:
        if not service.installed:
            return NOT_INSTALLED
        if service.active in ("inactive", "failed", "unknown", ""):
            return STOPPED
        if service.active == "deactivating":
            return DISCONNECTING
        if service.active == "activating":
            return STARTING
        if info.phase == STOPPED:
            return CONNECTING
        return info.phase

    def _latency_loop(self) -> None:
        while not self._stop.is_set():
            snap = self.snapshot
            target = None
            if snap.state == CONNECTED:
                target = snap.info.dns[0] if snap.info.dns else None
                if not target and snap.info.routes:
                    target = snap.info.routes[0].gateway
            latency = system.ping(target) if target else None
            if latency is None and target and snap.info.server_ip:
                # The VPN DNS may not answer ICMP; measure the server instead.
                latency = system.tcp_latency(snap.info.server_ip, self.server_port)
            self._latency = latency
            self._stop.wait(LATENCY_INTERVAL if target else 2.0)

    # ------------------------------------------------------------ access
    def recent_lines(self, include_noise: bool) -> List[LogLine]:
        with self._lock:
            return list(self.lines_all if include_noise else self.lines_important)


__all__ = ["Monitor", "Snapshot", "CONNECTED", "CONNECTING", "DISCONNECTING", "NOT_INSTALLED",
           "RECONNECTING", "STARTING", "STOPPED"]
