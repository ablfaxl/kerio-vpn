"""Profile passwords in the desktop keyring (Secret Service / libsecret)."""

from __future__ import annotations

from typing import Optional

try:
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret
except (ImportError, ValueError):
    Secret = None

SCHEMA_NAME = "org.keriovpn.KerioVpn.Password"
LEGACY_SCHEMA_NAME = "org.kvcpanel.KerioVpnPanel.Password"   # releases before 1.1
_SCHEMAS = {}


def _schema(name: str = SCHEMA_NAME):
    if name not in _SCHEMAS and Secret is not None:
        _SCHEMAS[name] = Secret.Schema.new(
            name, Secret.SchemaFlags.NONE, {"profile": Secret.SchemaAttributeType.STRING})
    return _SCHEMAS.get(name)


def available() -> bool:
    return Secret is not None


def store(profile_id: str, label: str, password: str) -> bool:
    if Secret is None:
        return False
    try:
        return Secret.password_store_sync(_schema(), {"profile": profile_id},
                                          Secret.COLLECTION_DEFAULT,
                                          "Kerio VPN: %s" % label, password, None)
    except Exception:
        return False


def lookup(profile_id: str) -> Optional[str]:
    if Secret is None:
        return None
    try:
        value = Secret.password_lookup_sync(_schema(), {"profile": profile_id}, None)
        if value is None:
            value = Secret.password_lookup_sync(_schema(LEGACY_SCHEMA_NAME),
                                                {"profile": profile_id}, None)
        return value
    except Exception:
        return None


def clear(profile_id: str) -> None:
    if Secret is None:
        return
    for name in (SCHEMA_NAME, LEGACY_SCHEMA_NAME):
        try:
            Secret.password_clear_sync(_schema(name), {"profile": profile_id}, None)
        except Exception:
            pass
