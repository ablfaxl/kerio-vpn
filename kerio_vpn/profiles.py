"""Connection profiles and application settings (per user)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
import sys
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List, Optional

from . import PACKAGE, kvc


LEGACY_DIR_NAME = "kerio-vpn-panel"   # used by releases before 1.1


def config_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, PACKAGE)
    legacy = os.path.join(base, LEGACY_DIR_NAME)
    if not os.path.exists(path) and os.path.isdir(legacy):
        shutil.copytree(legacy, path)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _save_json(path: str, data) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        # Keep the broken file for the user instead of silently overwriting it.
        try:
            os.replace(path, path + ".broken-%d" % int(time.time()))
        except OSError:
            pass
        return default


def _from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Profile:
    name: str
    server: str
    port: int = kvc.DEFAULT_PORT
    username: str = ""
    fingerprint: str = ""
    save_password: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    secret_rev: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_ips: List[str] = field(default_factory=list)
    split_exclude: List[str] = field(default_factory=list)
    split_include: List[str] = field(default_factory=list)
    last_connected: float = 0.0
    created: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not self.name.strip():
            raise kvc.ValidationError("name", "Profile name is required")
        kvc.validate_host(self.server)
        kvc.validate_port(self.port)
        kvc.validate_username(self.username)
        kvc.validate_fingerprint(self.fingerprint)

    def tag(self, server_override: str = "") -> str:
        """Identify what was written to /etc/kerio-kvc.conf without the password."""
        blob = json.dumps([self.id, server_override or self.server, int(self.port),
                           self.username, kvc.normalize_fingerprint(self.fingerprint),
                           self.secret_rev])
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def address(self) -> str:
        if self.port == kvc.DEFAULT_PORT:
            return self.server
        return "%s:%d" % (self.server, self.port)


class ProfileStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(config_dir(), "profiles.json")
        self.profiles: List[Profile] = []
        self.load()

    def load(self) -> None:
        data = _load_json(self.path, {"profiles": []})
        self.profiles = []
        for item in data.get("profiles", []):
            try:
                self.profiles.append(_from_dict(Profile, item))
            except TypeError:
                continue

    def save(self) -> None:
        _save_json(self.path, {"version": 1, "profiles": [asdict(p) for p in self.profiles]})

    def get(self, pid: Optional[str]) -> Optional[Profile]:
        return next((p for p in self.profiles if p.id == pid), None)

    def upsert(self, profile: Profile) -> None:
        for i, p in enumerate(self.profiles):
            if p.id == profile.id:
                self.profiles[i] = profile
                break
        else:
            self.profiles.append(profile)
        self.save()

    def remove(self, pid: str) -> None:
        self.profiles = [p for p in self.profiles if p.id != pid]
        self.save()

    def export(self, path: str, ids: Optional[List[str]] = None) -> None:
        keep = ("name", "server", "port", "username", "fingerprint", "split_exclude",
                "split_include")
        items = [{k: getattr(p, k) for k in keep}
                 for p in self.profiles if ids is None or p.id in ids]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"kerio-vpn-profiles": 1, "profiles": items}, f,
                      indent=2, ensure_ascii=False)

    @staticmethod
    def read_import(path: str) -> List[Profile]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("profiles", []) if isinstance(data, dict) else []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            p = Profile(name=str(item.get("name") or item.get("server") or "VPN"),
                        server=str(item.get("server", "")),
                        port=int(item.get("port") or kvc.DEFAULT_PORT),
                        username=str(item.get("username", "")),
                        fingerprint=kvc.normalize_fingerprint(str(item.get("fingerprint", ""))),
                        split_exclude=[str(x) for x in item.get("split_exclude") or []],
                        split_include=[str(x) for x in item.get("split_include") or []])
            try:
                p.validate()
            except kvc.ValidationError:
                continue
            result.append(p)
        return result


@dataclass
class Settings:
    default_profile: str = ""
    connect_on_start: bool = False
    start_minimized: bool = False
    autostart_login: bool = False
    close_to_tray: bool = True
    notifications: bool = True
    stop_on_auth_failure: bool = True
    auth_failure_limit: int = 2
    reconnect_after_resume: bool = True
    killswitch: bool = False
    killswitch_allow_lan: bool = True
    dns_resolved: bool = True
    dns_route_all: bool = False
    log_hide_noise: bool = True
    log_max_lines: int = 5000

    @classmethod
    def load(cls) -> "Settings":
        path = os.path.join(config_dir(), "settings.json")
        data = _load_json(path, {})
        try:
            return _from_dict(cls, data if isinstance(data, dict) else {})
        except TypeError:
            return cls()

    def save(self) -> None:
        _save_json(os.path.join(config_dir(), "settings.json"), asdict(self))

    def as_dict(self) -> Dict:
        return asdict(self)
