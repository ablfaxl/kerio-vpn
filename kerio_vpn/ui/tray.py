"""System tray indicator (AppIndicator / Ayatana, falling back to GtkStatusIcon)."""

from __future__ import annotations

import os

import gi
from gi.repository import Gio, GLib, Gtk

from .. import APP_NAME
from ..i18n import _
from ..logparse import CONNECTED, CONNECTING, RECONNECTING, STARTING
from .widgets import ICON_DIR, STATE_STYLE, state_label

AppIndicator = None
for _ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(_ns, "0.1")
        AppIndicator = __import__("gi.repository", fromlist=[_ns]).__dict__[_ns]
        break
    except (ValueError, ImportError, KeyError):
        continue


def _tray_host_present() -> bool:
    """AppIndicator icons are invisible without a StatusNotifier host
    (e.g. GNOME without the AppIndicator extension)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "NameHasOwner",
                              GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
                              GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1000, None)
        return reply.unpack()[0]
    except GLib.Error:
        return False


class Tray:
    def __init__(self, app, ctrl):
        self.app = app
        self.ctrl = ctrl
        self.indicator = None
        self._icon = None
        self.menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label=_("Disconnected"))
        self.status_item.set_sensitive(False)
        self.toggle_item = Gtk.MenuItem(label=_("Connect"))
        self.toggle_item.connect("activate", lambda _i: app.activate_action("toggle", None))
        self.profiles_item = Gtk.MenuItem(label=_("Connect to"))
        self.profiles_menu = Gtk.Menu()
        self.profiles_item.set_submenu(self.profiles_menu)
        show = Gtk.MenuItem(label=_("Show window"))
        show.connect("activate", lambda _i: app.activate_action("show", None))
        quit_item = Gtk.MenuItem(label=_("Quit"))
        quit_item.connect("activate", lambda _i: app.activate_action("quit", None))
        for item in (self.status_item, Gtk.SeparatorMenuItem(), self.toggle_item,
                     self.profiles_item, Gtk.SeparatorMenuItem(), show, quit_item):
            self.menu.append(item)
        self.menu.show_all()

        if AppIndicator is not None:
            self.indicator = AppIndicator.Indicator.new(
                "kerio-vpn", "kvp-disconnected",
                AppIndicator.IndicatorCategory.COMMUNICATIONS)
            if os.path.isdir(ICON_DIR):
                self.indicator.set_icon_theme_path(ICON_DIR)
            self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self.indicator.set_menu(self.menu)
            self.indicator.set_title(APP_NAME)
            self.indicator.set_secondary_activate_target(show)
        elif os.environ.get("XDG_SESSION_TYPE") != "wayland":
            # StatusIcon is deprecated but still works on X11 trays.
            self._icon = Gtk.StatusIcon()
            self._icon.set_title(APP_NAME)
            self._icon.connect("activate", lambda _i: app.activate_action("show", None))
            self._icon.connect("popup-menu", lambda icon, button, t: self.menu.popup(
                None, None, Gtk.StatusIcon.position_menu, icon, button, t))
            self._set_icon("kvp-disconnected")

        ctrl.monitor.connect("changed", lambda _m, snap: self.update(snap))
        ctrl.connect("profiles-changed", lambda _c: self.rebuild_profiles())
        self.rebuild_profiles()

    @property
    def available(self) -> bool:
        """Whether an icon is actually visible, so hiding the window is safe.
        Checked live: at login the tray host may appear after us."""
        if self.indicator is not None:
            return _tray_host_present()
        return self._icon is not None and self._icon.is_embedded()

    def _set_icon(self, name: str, desc: str = "") -> None:
        if self.indicator is not None:
            self.indicator.set_icon_full(name, desc)
        elif self._icon is not None:
            path = os.path.join(ICON_DIR, name + ".svg")
            if os.path.exists(path):
                self._icon.set_from_file(path)
            else:
                self._icon.set_from_icon_name("network-vpn")
            self._icon.set_tooltip_text(desc or APP_NAME)

    def rebuild_profiles(self) -> None:
        for child in self.profiles_menu.get_children():
            child.destroy()
        for p in self.ctrl.store.profiles:
            item = Gtk.MenuItem(label=p.name)
            item.connect("activate", lambda _i, prof=p: self.app.connect_profile(prof))
            self.profiles_menu.append(item)
        self.profiles_menu.show_all()
        self.profiles_item.set_visible(len(self.ctrl.store.profiles) > 1)

    def update(self, snap) -> None:
        _kind, icon = STATE_STYLE.get(snap.state, ("idle", "kvp-disconnected"))
        if snap.state == RECONNECTING and snap.info.last_error_code:
            icon = "kvp-error"
        label = state_label(snap.state)
        active = self.ctrl.active_profile
        if active and snap.state == CONNECTED:
            label = "%s — %s" % (label, active.name)
        self.status_item.set_label(label)
        self._set_icon(icon, label)
        running = snap.state in (CONNECTED, CONNECTING, RECONNECTING, STARTING)
        self.toggle_item.set_label(_("Disconnect") if running else _("Connect"))
        self.toggle_item.set_sensitive(not self.ctrl.busy and bool(self.ctrl.store.profiles))
