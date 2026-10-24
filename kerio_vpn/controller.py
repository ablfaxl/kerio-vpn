"""Connection logic, shared by the GUI and the tray. GTK-free (GLib only)."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Optional

from gi.repository import Gio, GLib, GObject

from . import certs, installer, kvc, privileged, secretstore, splitroute, system
from .helper import APPLIED_FILE
from .i18n import _
from .logparse import CONNECTED, RECONNECTING, STOPPED
from .monitor import Monitor, Snapshot
from .profiles import Profile, ProfileStore, Settings

AUTH_ERROR = 161
SSL_ERROR = 120


class NeedPassword(Exception):
    pass


def read_applied() -> Optional[dict]:
    """What the helper last wrote, if /etc/kerio-kvc.conf is still unchanged."""
    try:
        with open(APPLIED_FILE) as f:
            applied = json.load(f)
        st = os.stat(kvc.CONFIG_PATH)
    except (OSError, ValueError):
        return None
    cfg = applied.get("config") or {}
    if (cfg.get("mtime_ns"), cfg.get("size"), cfg.get("ino")) != (
            st.st_mtime_ns, st.st_size, st.st_ino):
        return None
    return applied


def server_ip(store: ProfileStore, profile: Profile) -> str:
    """Resolve the server now; fall back to the last known address (the kill
    switch may be blocking DNS)."""
    try:
        ips = certs.resolve(profile.server, profile.port)
    except OSError:
        ips = list(profile.last_ips)
    if not ips:
        raise RuntimeError(_("Cannot resolve %s") % profile.server)
    if ips != profile.last_ips:
        profile.last_ips = ips[:4]
        store.upsert(profile)
    return ips[0]


def activate_profile(settings: Settings, store: ProfileStore, profile: Profile,
                     password: Optional[str] = None, remember: Optional[bool] = None) -> str:
    """Make `profile` the system VPN connection and start the daemon. Blocking.

    Admin authorization is only needed when /etc/kerio-kvc.conf must change;
    reconnecting the profile that is already configured just (re)starts the
    service. Raises NeedPassword when no password is known."""
    profile.validate()
    server_value = profile.server
    if settings.killswitch:
        # kvpncsvc resolves the name itself, which the kill switch would block.
        server_value = server_ip(store, profile)
    tag = profile.tag(server_value if server_value != profile.server else "")
    applied = read_applied()

    if applied and applied.get("tag") == tag and password is None:
        privileged.control("restart" if system.service_state().running else "start")
        return "started"

    pw = password if password is not None else secretstore.lookup(profile.id)
    if not pw:
        raise NeedPassword()
    privileged.configure("apply", {
        "server": server_value, "port": profile.port,
        "username": profile.username, "password": pw,
        "fingerprint": profile.fingerprint, "tag": tag, "connect": True,
    })
    if password is not None and (remember if remember is not None else profile.save_password):
        secretstore.store(profile.id, profile.name, password)
    return "applied"


def _valid(entry: str) -> bool:
    try:
        splitroute.classify(entry)
        return True
    except ValueError:
        return False


class Controller(GObject.Object):
    __gsignals__ = {
        # (busy: bool, message: str)
        "busy": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
        # (title, detail)
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        # (profile, reason)
        "need-password": (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
        # (profile or None)
        "auth-failed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "ssl-problem": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # (snapshot, previous_state)
        "state": (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
        "profiles-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings: Settings, store: ProfileStore, monitor: Monitor):
        super().__init__()
        self.settings = settings
        self.store = store
        self.monitor = monitor
        self.snapshot = Snapshot()
        self.busy = False
        self.user_disconnect = False
        self._active_id: Optional[str] = None
        self._applied_iface: Optional[str] = None
        self._ks_applied: Optional[tuple] = None
        self._ssl_warned = False
        self._auth_handled_at = 0.0
        self._was_up = False
        self.killswitch_active = False
        self._routes_applied: Optional[tuple] = None
        self.route_status = ""      # last split-tunnel result, shown on the Routing page
        monitor.connect("changed", self._on_snapshot)
        self._watch_sleep()

    # ------------------------------------------------------------ helpers
    def _in_thread(self, message: str, work: Callable, done: Optional[Callable] = None) -> None:
        if self.busy:
            return
        self.busy = True
        self.emit("busy", True, message)

        def runner():
            err = None
            result = None
            try:
                result = work()
            except Exception as e:  # reported to the UI
                err = e

            def finish():
                self.busy = False
                self.emit("busy", False, "")
                self.monitor.poke()
                if done:
                    done(result, err)
                elif err and not getattr(err, "cancelled", False):
                    self.emit("error", message, str(err))
                return False
            GLib.idle_add(finish)
        threading.Thread(target=runner, daemon=True).start()

    @property
    def active_profile(self) -> Optional[Profile]:
        """Profile currently written to /etc/kerio-kvc.conf, if we know it."""
        if self._active_id:
            p = self.store.get(self._active_id)
            if p:
                return p
        applied = read_applied()
        if applied:
            tag = applied.get("tag")
            for p in self.store.profiles:
                candidates = [p.server] + list(p.last_ips)
                if any(p.tag(s if s != p.server else "") == tag for s in candidates):
                    self._active_id = p.id
                    return p
        info = self.snapshot.info
        for p in self.store.profiles:
            if info.username and p.username == info.username and (
                    p.server == info.server or info.server in p.last_ips):
                return p
        return None

    def default_profile(self) -> Optional[Profile]:
        return (self.active_profile or self.store.get(self.settings.default_profile)
                or (self.store.profiles[0] if self.store.profiles else None))

    # ------------------------------------------------------------ actions
    def connect_profile(self, profile: Profile, password: Optional[str] = None,
                        remember: Optional[bool] = None) -> None:
        self.user_disconnect = False
        self._ssl_warned = False

        def work():
            return activate_profile(self.settings, self.store, profile, password, remember)

        def done(result, err):
            if isinstance(err, NeedPassword):
                self.emit("need-password", profile, "")
                return
            if err:
                if not getattr(err, "cancelled", False):
                    self.emit("error", _("Could not connect"), str(err))
                return
            self._active_id = profile.id
            self.settings.default_profile = profile.id
            self.settings.save()

        self._in_thread(_("Connecting to %s…") % profile.name, work, done)

    def disconnect(self) -> None:
        self.user_disconnect = True
        iface = self.snapshot.iface

        def work():
            if iface and self.settings.dns_resolved:
                try:
                    privileged.control("dns-clear", {"iface": iface})
                except privileged.PrivilegeError:
                    pass
            privileged.control("stop")
            privileged.control("killswitch-disable")
            privileged.control("routes-clear")
        self._ks_applied = None
        self._routes_applied = None
        self.killswitch_active = False
        self._applied_iface = None
        self._in_thread(_("Disconnecting…"), work)

    def restart_service(self) -> None:
        self.user_disconnect = False
        self._in_thread(_("Restarting VPN service…"), lambda: privileged.control("restart"))

    def set_start_at_boot(self, enabled: bool, done: Optional[Callable] = None) -> None:
        self._in_thread(_("Changing start at boot…"),
                        lambda: privileged.configure("boot", {"enabled": enabled}), done)

    def repair_dns(self, done: Optional[Callable] = None) -> None:
        self._in_thread(_("Repairing DNS…"), lambda: privileged.control("dns-repair"), done)

    def disable_killswitch(self) -> None:
        self._ks_applied = None
        self.killswitch_active = False
        self._in_thread(_("Disabling kill switch…"),
                        lambda: privileged.control("killswitch-disable"))

    def probe_killswitch(self) -> None:
        """Find out whether firewall rules from an earlier session still block traffic."""
        def work():
            try:
                active = bool(privileged.control("status").get("killswitch"))
            except privileged.PrivilegeError:
                return
            def apply():
                self.killswitch_active = active
                self.monitor.poke()
                return False
            GLib.idle_add(apply)
        threading.Thread(target=work, daemon=True).start()

    def install_client(self, path: Optional[str] = None, done: Optional[Callable] = None,
                       progress: Optional[Callable[[str], None]] = None) -> None:
        """Install kerio-control-vpnclient, downloading the official package unless a
        local .deb is given."""
        def report(text):
            if progress:
                GLib.idle_add(progress, text)

        def work():
            reason = installer.supported()
            if reason:
                raise installer.InstallError(reason)
            pkg = path
            if pkg is None:
                report(_("Looking for the latest Kerio VPN Client…"))
                release = installer.latest_release()

                def on_progress(done_bytes, total):
                    if total:
                        report(_("Downloading %(name)s… %(pct)d%%") % {
                            "name": release.label, "pct": done_bytes * 100 // total})
                pkg = installer.download(release, installer.cache_dir(), on_progress)
            installer.package_info(pkg)
            report(_("Installing… you may be asked for your password."))
            return privileged.configure("install-client", {"path": os.path.abspath(pkg)})
        self._in_thread(_("Installing Kerio VPN Client…"), work, done)

    def import_system_config(self, done: Callable) -> None:
        self._in_thread(_("Reading current configuration…"),
                        lambda: privileged.configure("read-config"), done)

    # ------------------------------------------------------------ reactions
    def _on_snapshot(self, _monitor, snap: Snapshot) -> None:
        prev = self.snapshot.state
        self.snapshot = snap
        info = snap.info
        if snap.state == CONNECTED:
            self._after_connected(snap)
        elif snap.state == STOPPED:
            self._applied_iface = None
            self._routes_applied = None

        if (info.last_error_code == AUTH_ERROR and snap.service.running
                and self.settings.stop_on_auth_failure
                and info.consecutive_errors >= max(1, self.settings.auth_failure_limit)
                and info.last_error_ts and info.last_error_ts > self._auth_handled_at
                and not self.busy):
            self._auth_handled_at = info.last_error_ts
            profile = self.active_profile
            self._in_thread(_("Stopping after failed login…"),
                            lambda: privileged.control("stop"),
                            lambda r, e: self.emit("auth-failed", profile))

        if (info.last_error_code == SSL_ERROR and info.consecutive_errors >= 2
                and not self._ssl_warned and snap.service.running):
            self._ssl_warned = True
            self.emit("ssl-problem", self.active_profile)

        if prev != snap.state:
            self.emit("state", snap, prev)

    def _after_connected(self, snap: Snapshot) -> None:
        if self.busy:
            return
        info = snap.info
        profile = self.active_profile
        if profile and info.server_ip and info.server_ip not in profile.last_ips:
            profile.last_ips = ([info.server_ip] + profile.last_ips)[:4]
            profile.last_connected = time.time()
            self.store.upsert(profile)

        if profile:
            self.monitor.server_port = profile.port
        exclude = list(profile.split_exclude) if profile else []
        include = list(profile.split_include) if profile else []
        has_names = any(splitroute.classify(e)[0] == "host"
                        for e in exclude + include if _valid(e))
        vpn_gw = next((r.gateway for r in info.routes if r.gateway != "0.0.0.0"),
                      info.dns[0] if info.dns else "")
        routes_key = (snap.iface, snap.uplink, tuple(exclude), tuple(include), vpn_gw,
                      int(time.time() // 600) if has_names else 0)
        need_routes = bool(snap.iface) and routes_key != self._routes_applied and (
            exclude or include or self._routes_applied is not None)

        ks_ips = sorted({info.server_ip, *(profile.last_ips if profile else [])} - {""})
        ks_key = (snap.iface, tuple(ks_ips), self.settings.killswitch_allow_lan, tuple(exclude))
        need_ks = (self.settings.killswitch and bool(snap.iface) and bool(ks_ips)
                   and ks_key != self._ks_applied)

        need_dns = (self.settings.dns_resolved and snap.iface and info.dns
                    and self._applied_iface != snap.iface and system.resolved_active())
        if not (need_routes or need_ks or need_dns):
            return
        if need_routes:
            self._routes_applied = routes_key
        if need_ks:
            self._ks_applied = ks_key
            self.killswitch_active = True
        if need_dns:
            self._applied_iface = snap.iface
        settings = self.settings
        uplink = snap.uplink

        def work():
            errors = []
            excluded_nets, failed_names = splitroute.resolve(exclude)
            included_nets, failed2 = splitroute.resolve(include)
            failed_names += failed2

            def call(action, args):
                try:
                    return privileged.control(action, args)
                except privileged.PrivilegeError as e:
                    errors.append("%s: %s" % (action, e))
                    return {}
            status = ""
            if need_routes:
                if excluded_nets and not uplink:
                    errors.append(_("No physical default gateway found for bypass routes"))
                    excluded_nets = []
                reply = call("routes-set", {
                    "exclude": excluded_nets, "include": included_nets,
                    "uplink_gw": uplink[0] if uplink else "",
                    "uplink_dev": uplink[1] if uplink else "",
                    "iface": snap.iface, "vpn_gw": vpn_gw})
                errors.extend(reply.get("failed", []))
                status = _("%(ex)d bypass and %(in)d VPN routes active") % {
                    "ex": len(excluded_nets), "in": len(included_nets)}
                if failed_names:
                    status += " · " + _("could not resolve: %s") % ", ".join(failed_names)
            if need_ks:
                call("killswitch-enable", {
                    "server_ips": ks_ips, "ifaces": [snap.iface, "kvnet*"],
                    "allow_lan": settings.killswitch_allow_lan, "bypass": excluded_nets})
            if need_dns:
                call("dns-set", {"iface": snap.iface, "servers": info.dns,
                                 "domain": info.domain,
                                 "route_all": settings.dns_route_all or info.is_full_tunnel})
            return status, errors

        def done(result, err):
            if err:
                self.emit("error", _("Applying network settings…"), str(err))
                return
            status, errors = result
            if status:
                self.route_status = status
            if errors:
                self.emit("error", _("Some network settings could not be applied"),
                          "\n".join(errors))
            self.emit("profiles-changed")
        self._in_thread(_("Applying network settings…"), work, done)

    def apply_routes_now(self) -> None:
        """Re-apply split tunneling after the user edited the lists."""
        if self._routes_applied is not None:
            # Something is installed: force a refresh, even if the lists are now empty.
            self._routes_applied = ()
        self._ks_applied = None
        if self.snapshot.state == CONNECTED:
            self._after_connected(self.snapshot)

    def apply_killswitch_setting(self) -> None:
        """Called when the user toggles the kill switch in Settings."""
        if not self.settings.killswitch:
            self.disable_killswitch()
        elif self.snapshot.state == CONNECTED:
            self._ks_applied = None
            self._after_connected(self.snapshot)

    # ------------------------------------------------------------ suspend
    def _watch_sleep(self) -> None:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                             "PrepareForSleep", "/org/freedesktop/login1", None,
                             Gio.DBusSignalFlags.NONE, self._on_sleep)

    def _on_sleep(self, _conn, _sender, _path, _iface, _signal, params) -> None:
        going_to_sleep = params.unpack()[0]
        if going_to_sleep:
            self._was_up = self.snapshot.state in (CONNECTED, RECONNECTING)
            return
        if self._was_up and self.settings.reconnect_after_resume:
            GLib.timeout_add_seconds(4, self._resume_restart)

    def _resume_restart(self) -> bool:
        if not self.user_disconnect:
            self._in_thread(_("Reconnecting after resume…"),
                            lambda: privileged.control("restart"), lambda r, e: None)
        return False

    def ssl_check(self, profile: Profile, done: Callable) -> None:
        self._in_thread(_("Checking server certificate…"),
                        lambda: certs.fetch(profile.server, profile.port), done)
