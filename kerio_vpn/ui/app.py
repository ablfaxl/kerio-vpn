"""Gtk.Application: single instance, actions, notifications, tray."""

from __future__ import annotations

import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify
except (ValueError, ImportError):
    Notify = None

from .. import APP_ID, APP_NAME, VERSION, installer, privileged  # noqa: E402
from ..controller import Controller  # noqa: E402
from ..i18n import _  # noqa: E402
from ..logparse import (CONNECTED, CONNECTING, NOT_INSTALLED, RECONNECTING, STARTING,  # noqa: E402
                        STOPPED)
from ..monitor import Monitor  # noqa: E402
from ..profiles import ProfileStore, Settings  # noqa: E402
from . import autostart  # noqa: E402
from .tray import Tray  # noqa: E402
from .widgets import ICON_DIR, error_label, load_css  # noqa: E402
from .window import MainWindow  # noqa: E402


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("minimized", ord("m"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, _("Start hidden in the tray"), None)
        self.add_main_option("connect", ord("c"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.STRING, _("Connect a profile by name"), "NAME")
        self.add_main_option("connect-default", 0, GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, _("Connect the default profile"), None)
        self.add_main_option("disconnect", ord("d"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, _("Disconnect the VPN"), None)
        self.add_main_option("version", ord("v"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, _("Show version"), None)
        self.window = None
        self.tray = None
        self.ctrl = None
        self._notification = None
        self._skip_autoconnect = False

    # ------------------------------------------------------------ startup
    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.IconTheme.get_default().append_search_path(ICON_DIR)
        load_css()
        GLib.set_application_name(APP_NAME)

        settings = Settings.load()
        settings.autostart_login = autostart.is_enabled()
        self.monitor = Monitor(settings.log_max_lines)
        self.ctrl = Controller(settings, ProfileStore(), self.monitor)
        self.ctrl.connect("state", self._on_state)
        self.ctrl.connect("auth-failed", lambda _c, _p: self.notify(
            _("VPN login failed"), error_label(161), "kvp-error"))

        for name, cb in (("show", self._show), ("toggle", self._toggle), ("quit", self._quit),
                         ("about", self._about), ("diagnostics", self._diagnostics)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        if Notify is not None:
            Notify.init(APP_NAME)
        self.tray = Tray(self, self.ctrl)
        self.monitor.start()
        self._first_snapshot = self.monitor.connect("changed", self._on_first_snapshot)
        self.hold()

    def _on_first_snapshot(self, monitor, snap):
        monitor.disconnect(self._first_snapshot)
        s = self.ctrl.settings
        if snap.state == NOT_INSTALLED:
            GLib.idle_add(self._offer_client_install)
            return
        if s.connect_on_start and snap.state == STOPPED and not self._skip_autoconnect:
            profile = self.ctrl.default_profile()
            if profile:
                self.ctrl.connect_profile(profile)
        elif snap.state == STOPPED and privileged.helper_installed():
            self.ctrl.probe_killswitch()

    def _offer_client_install(self) -> bool:
        from . import widgets
        if self.window is None:
            return True     # command line not processed yet; try again shortly
        self.window.present()
        self.window.show_page("dashboard")
        reason = installer.supported()
        if reason:
            widgets.message(self.window, _("Kerio VPN Client is not available"), reason)
        elif widgets.confirm(self.window, _("Install the Kerio VPN Client?"), _(
                "Kerio VPN needs the official Kerio Control VPN Client service. It will be "
                "downloaded from Kerio and installed; administrator rights are required."),
                _("Install")):
            self.window.dashboard.install(None)
        return False

    def do_command_line(self, command_line):
        opts = command_line.get_options_dict().end().unpack()
        if opts.get("version"):
            command_line.print_literal("%s %s\n" % (APP_NAME, VERSION))
            return 0
        first = self.window is None
        self._skip_autoconnect = bool(opts.get("disconnect") or opts.get("connect")
                                      or opts.get("connect-default"))
        if first:
            self.window = MainWindow(self, self.ctrl)
            self.window.connect("delete-event", self._on_delete)
        if opts.get("disconnect"):
            self.ctrl.disconnect()
        elif opts.get("connect-default"):
            profile = self.ctrl.default_profile()
            if profile:
                self.connect_profile(profile)
        elif opts.get("connect"):
            name = opts["connect"]
            profile = next((p for p in self.ctrl.store.profiles
                            if p.name == name or p.id == name), None)
            if profile:
                self.connect_profile(profile)
            else:
                command_line.print_literal(_("Unknown profile: %s") % name + "\n")
        hidden = opts.get("minimized") or (first and self.ctrl.settings.start_minimized)
        if not (hidden and self.tray.available) or not first:
            if not opts.get("minimized"):
                self.window.present()
        return 0

    # ------------------------------------------------------------ actions
    def connect_profile(self, profile):
        if self.window:
            self.window.connect_profile(profile)
        else:
            self.ctrl.connect_profile(profile)

    def _show(self, *_a):
        self.window.present()

    def _toggle(self, *_a):
        state = self.ctrl.snapshot.state
        if state in (CONNECTED, CONNECTING, RECONNECTING, STARTING):
            self.ctrl.disconnect()
        else:
            profile = self.ctrl.default_profile()
            if profile:
                self.connect_profile(profile)
            else:
                self._show()

    def _on_delete(self, win, _event):
        if self.ctrl.settings.close_to_tray and self.tray.available:
            win.hide()
            return True
        self._quit()
        return True

    def _quit(self, *_a):
        self.monitor.stop()
        if Notify is not None:
            Notify.uninit()
        self.release()
        self.quit()

    def _about(self, *_a):
        self.window.present()
        self.window.show_page("about")

    def _diagnostics(self, *_a):
        self.window.present()
        self.window.show_diagnostics()

    # ------------------------------------------------------------ notifications
    def notify(self, title: str, body: str, icon: str = "kerio-vpn") -> None:
        if Notify is None or not self.ctrl.settings.notifications:
            return
        try:
            if self._notification is None:
                self._notification = Notify.Notification.new(title, body, icon)
            else:
                self._notification.update(title, body, icon)
            self._notification.show()
        except GLib.Error:
            pass

    def _on_state(self, _ctrl, snap, prev):
        profile = self.ctrl.active_profile
        name = profile.name if profile else snap.info.server
        if snap.state == CONNECTED:
            self.notify(_("VPN connected"), _("Connected to %(name)s (%(ip)s)") % {
                "name": name, "ip": snap.info.local_ip}, "kvp-connected")
        elif prev == CONNECTED and snap.state == RECONNECTING:
            self.notify(_("VPN connection lost"),
                        error_label(snap.info.last_error_code) or _("Reconnecting…"),
                        "kvp-error")
        elif prev in (CONNECTED, RECONNECTING) and snap.state == STOPPED:
            self.notify(_("VPN disconnected"), name or "", "kvp-disconnected")


def main(argv=None) -> int:
    app = Application()
    return app.run(sys.argv if argv is None else argv)
