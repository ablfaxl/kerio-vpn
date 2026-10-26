"""Knowledge about the Kerio Control VPN Client daemon (kvpncsvc).

This module is imported by the root helper, so it must stay free of GUI
dependencies and must treat every input as untrusted.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape

IS_MACOS = sys.platform == "darwin"

CONFIG_PATH = (os.path.expanduser("~/.kerio/vpnclient/user.cfg") if IS_MACOS
               else "/etc/kerio-kvc.conf")
LOG_DIR = (os.path.expanduser("~/.kerio/vpnclient/logs") if IS_MACOS
           else "/var/log/kerio-kvc")
DEBUG_LOG = LOG_DIR + "/debug.log"
ERROR_LOG = LOG_DIR + "/error.log"
DAEMON = ("/usr/local/kerio/vpnclient/kvpncsvc" if IS_MACOS else "/usr/sbin/kvpncsvc")
SERVICE = "com.kerio.kvpncsvc" if IS_MACOS else "kerio-kvc.service"
INIT_SCRIPT = ("/Library/LaunchDaemons/com.kerio.kvpncsvc.plist" if IS_MACOS
               else "/etc/init.d/kerio-kvc")
DEB_PACKAGE = "kerio-control-vpnclient"
DEFAULT_PORT = 4090
RESOLV_CONF = "/etc/resolv.conf"
RESOLV_BACKUP = "/etc/resolv.conf.kvpnbackup"

# The Debian postinst of kerio-control-vpnclient XORs every password byte with 85.
XOR_KEY = 85

# libVPN error codes as they appear in error.log / debug.log.
ERROR_CODES = {
    120: "ssl",
    142: "peer_closed",
    145: "timeout",
    146: "network",
    161: "auth",
    191: "resolve",
}

_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_FINGERPRINT = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){15}$")


class ValidationError(ValueError):
    """Raised with a machine readable `field` when a value is not acceptable."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def xor_encode(password: str) -> str:
    return "XOR:" + "".join("%02x" % (b ^ XOR_KEY) for b in password.encode("utf-8"))


def xor_decode(value: str) -> str:
    if not value.startswith("XOR:"):
        return value
    raw = value[4:]
    try:
        data = bytes(int(raw[i:i + 2], 16) ^ XOR_KEY for i in range(0, len(raw), 2))
    except ValueError:
        return ""
    return data.decode("utf-8", errors="replace")


def normalize_fingerprint(fp: str) -> str:
    """Accept 'aa:bb..', 'AABB..' or 'aa bb ..' and return 'AA:BB:..'."""
    hexchars = re.sub(r"[^0-9A-Fa-f]", "", fp or "")
    if len(hexchars) != 32:
        return (fp or "").strip().upper()
    return ":".join(hexchars[i:i + 2] for i in range(0, 32, 2)).upper()


def split_server(server: str, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    """Split 'host:port' or '[v6]:port' the way the Debian wizard does."""
    server = (server or "").strip()
    if server.startswith("["):
        host, _, rest = server[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif server.count(":") == 1:
        host, port = server.split(":")
    else:
        host, port = server, ""
    if port:
        try:
            return host, int(port)
        except ValueError:
            raise ValidationError("server", "Invalid port in server address")
    return host, default_port


def validate_host(host: str) -> str:
    host = (host or "").strip()
    if not host:
        raise ValidationError("server", "Server address is required")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    name = host[:-1] if host.endswith(".") else host
    if len(name) > 253 or not all(_HOST_LABEL.match(p) for p in name.split(".")):
        raise ValidationError("server", "Server must be a valid host name or IP address")
    return host


def validate_port(port) -> int:
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValidationError("port", "Port must be a number")
    if not 1 <= port <= 65535:
        raise ValidationError("port", "Port must be between 1 and 65535")
    return port


def _no_control_chars(value: str, field: str, label: str, maxlen: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(field, label + " is invalid")
    if len(value) > maxlen:
        raise ValidationError(field, label + " is too long")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError(field, label + " contains invalid characters")
    return value


def validate_username(username: str) -> str:
    username = _no_control_chars((username or "").strip(), "username", "Username", 256)
    if not username:
        raise ValidationError("username", "Username is required")
    return username


def validate_password(password: str) -> str:
    password = _no_control_chars(password or "", "password", "Password", 1024)
    if not password:
        raise ValidationError("password", "Password is required")
    return password


def validate_fingerprint(fp: str) -> str:
    fp = normalize_fingerprint(fp)
    if not _FINGERPRINT.match(fp):
        raise ValidationError(
            "fingerprint",
            "Fingerprint must be 16 hex byte pairs (MD5), e.g. AB:CD:...",
        )
    return fp


@dataclass
class KvcConfig:
    server: str
    port: int
    username: str
    password: str
    fingerprint: str
    active: bool = True

    def validated(self) -> "KvcConfig":
        return KvcConfig(
            server=validate_host(self.server),
            port=validate_port(self.port),
            username=validate_username(self.username),
            password=validate_password(self.password),
            fingerprint=validate_fingerprint(self.fingerprint),
            active=bool(self.active),
        )


def render_config(cfg: KvcConfig) -> str:
    """Render the exact layout written by the official Debian wizard."""
    cfg = cfg.validated()
    return (
        "<config>\n"
        "  <connections>\n"
        '    <connection type="persistent">\n'
        "      <server>%s</server>\n"
        "      <port>%d</port>\n"
        "      <username>%s</username>\n"
        "      <password>%s</password>\n"
        "      <fingerprint>%s</fingerprint>\n"
        "      <active>%d</active>\n"
        "    </connection>\n"
        "  </connections>\n"
        "</config>\n"
    ) % (
        escape(cfg.server),
        cfg.port,
        escape(cfg.username),
        xor_encode(cfg.password),
        escape(cfg.fingerprint),
        1 if cfg.active else 0,
    )


def parse_config(text: str) -> Optional[KvcConfig]:
    """Parse /etc/kerio-kvc.conf. Returns None when no connection is defined."""
    root = ET.fromstring(text)
    conn = root.find("./connections/connection")
    if conn is None:
        return None

    def get(tag: str, default: str = "") -> str:
        el = conn.find(tag)
        return (el.text or "").strip() if el is not None else default

    try:
        port = int(get("port", str(DEFAULT_PORT)) or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return KvcConfig(
        server=get("server"),
        port=port,
        username=get("username"),
        password=xor_decode(get("password")),
        fingerprint=get("fingerprint"),
        active=get("active", "1") != "0",
    )


def describe_error(code: Optional[int]) -> str:
    return ERROR_CODES.get(code or 0, "unknown")
