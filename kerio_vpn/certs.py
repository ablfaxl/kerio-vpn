"""Fetch the Kerio VPN server certificate to show and pin its fingerprint.

kvpncsvc pins the server by the MD5 fingerprint of its certificate (the same
value the Kerio Control admin console shows under VPN Server properties).
"""

from __future__ import annotations

import hashlib
import shutil
import socket
import ssl
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class CertInfo:
    md5: str
    sha256: str
    subject: str = ""
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    address: str = ""


def _fmt(digest: bytes) -> str:
    return ":".join("%02X" % b for b in digest)


def _describe_with_openssl(der: bytes) -> dict:
    if not shutil.which("openssl"):
        return {}
    try:
        p = subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-subject",
                            "-issuer", "-startdate", "-enddate"],
                           input=der, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in p.stdout.decode(errors="replace").splitlines():
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def fetch(host: str, port: int, timeout: float = 10.0) -> CertInfo:
    """Connect without verification (the cert is usually self-signed) and
    return its fingerprints. Raises OSError / ssl.SSLError on failure."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        # Kerio appliances may still use older ciphers/keys.
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    except (AttributeError, ValueError):
        pass

    with socket.create_connection((host, port), timeout=timeout) as sock:
        peer = sock.getpeername()[0]
        with ctx.wrap_socket(sock, server_hostname=host if not _is_ip(host) else None) as tls:
            der: Optional[bytes] = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("Server did not send a certificate")
    meta = _describe_with_openssl(der)
    return CertInfo(md5=_fmt(hashlib.md5(der).digest()),
                    sha256=_fmt(hashlib.sha256(der).digest()),
                    subject=meta.get("subject", ""), issuer=meta.get("issuer", ""),
                    not_before=meta.get("notBefore", ""), not_after=meta.get("notAfter", ""),
                    address=peer)


def _is_ip(host: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        return True
    except OSError:
        return False


def resolve(host: str, port: int) -> list:
    """All addresses of the server, IPv4 first."""
    seen = []
    for family, _, _, _, sa in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if sa[0] not in seen:
            seen.append(sa[0])
    return sorted(seen, key=lambda a: ":" in a)
