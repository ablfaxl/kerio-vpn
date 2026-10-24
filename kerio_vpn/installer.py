"""Locate, download and install the official Kerio Control VPN Client package.

Kerio does not publish an apt repository. The official software archive lists
the current release, and the package itself is served from Kerio's CDN. Every
download uses normal certificate verification; if that fails, the user is
pointed to the official download page and can install a downloaded file.
"""

from __future__ import annotations

import os
import re
import shutil
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import PACKAGE, VERSION, kvc, system

ARCHIVE_URL = "https://download.kerio.com/archive/"
ARCHIVE_FILES_URL = "https://download.kerio.com/archive/download.php"
DOWNLOAD_PAGE = ("https://gfi.ai/products-and-solutions/network-security-solutions/"
                 "keriocontrol/resources/vpn")
# Used when the archive cannot be parsed.
FALLBACK_URL = ("https://cdn.kerio.com/dwn/control/control-9.6.1-9306/"
                "kerio-control-vpnclient-9.6.1-9306-p1-linux-amd64.deb")
ALLOWED_HOSTS = ("cdn.kerio.com", "download.kerio.com")
MAX_SIZE = 200 * 1024 * 1024
USER_AGENT = "%s/%s" % (PACKAGE, VERSION)

_VERSION_RE = re.compile(r'version1\s*=\s*new Array\(\s*""\s*,\s*"([^"]+)"')
_HREF_RE = re.compile(r'href="(https?://[^"]+/kerio-control-vpnclient-[^"]+-linux(-amd64)?\.deb)"')


class InstallError(Exception):
    pass


@dataclass
class Release:
    label: str
    url: str

    @property
    def filename(self) -> str:
        return os.path.basename(urllib.parse.urlparse(self.url).path)


def supported() -> Optional[str]:
    """None when this system can run the Kerio client, else a reason."""
    if not shutil.which("dpkg") or not shutil.which("apt-get"):
        return "The Kerio VPN Client is only available for Debian and Ubuntu based systems."
    rc, out, _ = system.run(["dpkg", "--print-architecture"])
    if out.strip() != "amd64":
        return "The Kerio VPN Client for Linux is only available for 64-bit x86 (amd64)."
    return None


def _open(url: str, data: Optional[bytes] = None, timeout: float = 30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def _check_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise InstallError("Unexpected download host: %s" % parsed.hostname)
    # Always download over verified HTTPS, even if the archive lists http://.
    return urllib.parse.urlunparse(parsed._replace(scheme="https"))


def latest_release() -> Release:
    """Ask the official archive for the newest Kerio Control release."""
    try:
        with _open(ARCHIVE_URL) as r:
            page = r.read(2_000_000).decode("utf-8", "replace")
        m = _VERSION_RE.search(page)
        if not m:
            raise InstallError("version list not found")
        label = m.group(1)
        form = urllib.parse.urlencode({"product": "Kerio Control", "version": label}).encode()
        with _open(ARCHIVE_FILES_URL, data=form) as r:
            files = r.read(2_000_000).decode("utf-8", "replace")
        for href, amd64 in _HREF_RE.findall(files):
            if amd64:
                return Release(re.sub(r"\s+", " ", label.split("(")[0]).strip(),
                               _check_url(href))
        raise InstallError("no Linux package in release %s" % label)
    except (OSError, InstallError):
        return Release("9.6.1 Patch 1", FALLBACK_URL)


def download(release: Release, dest_dir: str,
             progress: Optional[Callable[[int, int], None]] = None) -> str:
    url = _check_url(release.url)
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    path = os.path.join(dest_dir, release.filename)
    tmp = path + ".part"
    try:
        with _open(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            if total > MAX_SIZE:
                raise InstallError("Package is unexpectedly large")
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_SIZE:
                    raise InstallError("Package is unexpectedly large")
                f.write(chunk)
                if progress:
                    progress(done, total)
    except ssl.SSLError as e:
        _cleanup(tmp)
        raise InstallError(
            "The Kerio download server's certificate could not be verified (%s). For your "
            "safety the package was not downloaded. Download it from the official page and "
            "choose “Install from file…”." % getattr(e, "reason", e))
    except urllib.error.URLError as e:
        _cleanup(tmp)
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLError):
            raise InstallError(
                "The Kerio download server's certificate could not be verified. For your "
                "safety the package was not downloaded. Download it from the official page "
                "and choose “Install from file…”.")
        raise InstallError("Download failed: %s" % reason)
    except (OSError, InstallError):
        _cleanup(tmp)
        raise
    os.replace(tmp, path)
    return path


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, PACKAGE)


def package_info(path: str) -> dict:
    """Read Package/Version/Architecture from a .deb without installing it."""
    rc, out, err = system.run(["dpkg-deb", "-f", path, "Package", "Version", "Architecture"])
    if rc != 0:
        raise InstallError("Not a valid Debian package: %s" % (err.strip() or path))
    info = {}
    for line in out.splitlines():
        key, _, value = line.partition(":")
        info[key.strip()] = value.strip()
    if info.get("Package") != kvc.DEB_PACKAGE:
        raise InstallError("This file is not the Kerio Control VPN Client package "
                           "(%s)." % (info.get("Package") or "unknown"))
    return info
