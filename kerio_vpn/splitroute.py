"""Split tunneling: per-profile lists of destinations that bypass the VPN
("exclude") or are forced into it ("include").

kvpncsvc installs its routes in the main table (a full tunnel is
0.0.0.0/1 + 128.0.0.0/1 via the VPN gateway). More specific routes win, so
an excluded network gets a route via the physical uplink and an included one
a route via the VPN interface. All our routes carry their own routing
protocol number so they can be removed without touching anyone else's.

Kept free of GUI imports; the root helper uses `parse_network`.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Iterable, List, Tuple

ROUTE_PROTO = "233"
MAX_ENTRIES = 512
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*\.?$")


def parse_network(text: str) -> ipaddress.IPv4Network:
    """IPv4 address or CIDR -> network. Raises ValueError."""
    net = ipaddress.ip_network(text.strip(), strict=False)
    if net.version != 4:
        raise ValueError("IPv6 is not carried by the Kerio tunnel")
    if net.prefixlen == 0:
        raise ValueError("0.0.0.0/0 cannot be used here")
    return net


def classify(entry: str) -> Tuple[str, str]:
    """Return ("net", "a.b.c.d/n") or ("host", "name"). Raises ValueError."""
    entry = entry.strip()
    if not entry:
        raise ValueError("Empty entry")
    if ":" in entry:
        raise ValueError("IPv6 is not carried by the Kerio tunnel")
    if all(c.isdigit() or c in "./" for c in entry):
        try:
            return "net", str(parse_network(entry))
        except ValueError:
            raise ValueError("Not a valid IP address, network or domain")
    if not _HOST_RE.match(entry):
        raise ValueError("Not a valid IP address, network or domain")
    return "host", entry.rstrip(".").lower()


def resolve(entries: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Expand entries to IPv4 networks. Returns (networks, unresolved names)."""
    nets: List[str] = []
    failed: List[str] = []
    for entry in entries:
        try:
            kind, value = classify(entry)
        except ValueError:
            continue
        if kind == "net":
            nets.append(value)
            continue
        try:
            infos = socket.getaddrinfo(value, None, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            failed.append(value)
            continue
        nets.extend("%s/32" % info[4][0] for info in infos)
    seen = []
    for n in nets:
        if n not in seen:
            seen.append(n)
    return seen[:MAX_ENTRIES], failed
