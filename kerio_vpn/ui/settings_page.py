"""Settings page."""

from __future__ import annotations

from gi.repository import GLib, Gtk

from .. import kvc, system
from ..i18n import _
from . import autostart
from .widgets import message


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.ctrl = win.ctrl
        self.s = win.ctrl.settings
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, border_width=18)
        self.add(outer)

        def section(title):
            box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            box.get_style_context().add_class("frame")
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
            outer.pack_start(lbl, False, False, 0)
            outer.pack_start(box, False, False, 0)
            return box

        def row(box, title, subtitle, widget):
            r = Gtk.Box(spacing=12, border_width=10)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t.pack_start(Gtk.Label(label=title, xalign=0, wrap=True), False, False, 0)
            if subtitle:
                sub = Gtk.Label(label=subtitle, xalign=0, wrap=True, max_width_chars=70)
                sub.get_style_context().add_class("dim-label")
                t.pack_start(sub, False, False, 0)
            r.pack_start(t, True, True, 0)
            widget.set_valign(Gtk.Align.CENTER)
            r.pack_start(widget, False, False, 0)
            box.add(r)
            return widget

        def switch(box, attr, title, subtitle="", on_change=None):
            sw = Gtk.Switch(active=bool(getattr(self.s, attr)))

            def changed(w, _p):
                setattr(self.s, attr, w.get_active())
                self.s.save()
                if on_change:
                    on_change(w.get_active())
            sw.connect("notify::active", changed)
            return row(box, title, subtitle, sw)

        g = section(_("General"))
        switch(g, "autostart_login", _("Start with my session"),
               _("Open in the system tray when you log in."), autostart.set_enabled)
        switch(g, "start_minimized", _("Start minimized to tray"))
        switch(g, "close_to_tray", _("Keep running in the tray when the window is closed"))
        switch(g, "notifications", _("Show desktop notifications"))

        c = section(_("Connection"))
        switch(c, "connect_on_start", _("Connect when the application starts"),
               _("Uses the default connection."))
        switch(c, "stop_on_auth_failure", _("Stop retrying after a failed login"),
               _("The Kerio client retries forever; repeated wrong passwords can lock "
                 "your account."))
        switch(c, "reconnect_after_resume", _("Reconnect after suspend"),
               _("Restart the tunnel when the computer wakes up."))
        self.boot = Gtk.Switch(active=self.ctrl.snapshot.service.enabled == "enabled")
        self._boot_guard = False
        self.boot.connect("notify::active", self._on_boot)
        row(c, _("Start VPN at system boot"),
            _("Connects before anyone logs in, with the active connection. "
              "Requires administrator rights."), self.boot)

        sec = section(_("Security"))
        switch(sec, "killswitch", _("Kill switch"),
               _("Block internet traffic outside the VPN if the tunnel drops unexpectedly. "
                 "Turned off again when you disconnect manually."),
               lambda _a: self.ctrl.apply_killswitch_setting())
        switch(sec, "killswitch_allow_lan", _("Allow local network while blocked"),
               _("Printers, NAS and other devices on your LAN stay reachable."),
               lambda _a: self.ctrl.apply_killswitch_setting())

        dns = section(_("DNS"))
        resolved = system.resolved_active()
        sw = switch(dns, "dns_resolved", _("Register VPN DNS with systemd-resolved"),
                    _("Needed on systems that use systemd-resolved so internal names "
                      "resolve.") if resolved else
                    _("systemd-resolved is not running; the Kerio client manages "
                      "/etc/resolv.conf itself."))
        sw.set_sensitive(resolved)
        sw = switch(dns, "dns_route_all", _("Send all DNS queries through the VPN"),
                    _("Prevents DNS leaks. Otherwise only the VPN domain uses VPN DNS."))
        sw.set_sensitive(resolved)
        repair = Gtk.Button(label=_("Repair"))
        repair.connect("clicked", lambda _b: self.ctrl.repair_dns(
            win.report_done(_("DNS settings were restored."))))
        row(dns, _("Repair DNS"), _("Restore normal DNS if it is still pointing at the VPN "
                                    "after a crash."), repair)

        sysbox = section(_("System"))
        self.checks = Gtk.Grid(column_spacing=12, row_spacing=4, border_width=10)
        sysbox.add(self.checks)
        restart = Gtk.Button(label=_("Restart"))
        restart.connect("clicked", lambda _b: self.ctrl.restart_service())
        row(sysbox, _("Restart VPN service"), kvc.SERVICE, restart)
        diag = Gtk.Button(label=_("Create…"))
        diag.connect("clicked", lambda _b: win.show_diagnostics())
        row(sysbox, _("Diagnostics report"),
            _("Collects state and logs (without passwords) for your administrator."), diag)
        self.connect("map", lambda _w: self.refresh_checks())

    def refresh_checks(self) -> None:
        for child in self.checks.get_children():
            child.destroy()
        names = {
            "daemon": _("Kerio VPN client"), "service": _("Service"),
            "tun": _("TUN device"), "pkexec": _("Polkit (pkexec)"),
            "logs": _("Log access"), "nft": _("nftables (kill switch)"),
            "resolved": _("systemd-resolved"),
        }
        for i, (key, (ok, detail)) in enumerate(system.check_environment().items()):
            mark = Gtk.Label(label="✔" if ok else "✘")
            mark.get_style_context().add_class("kvp-check-ok" if ok else "kvp-check-fail")
            self.checks.attach(mark, 0, i, 1, 1)
            self.checks.attach(Gtk.Label(label=names.get(key, key), xalign=0), 1, i, 1, 1)
            d = Gtk.Label(label=detail, xalign=0, selectable=True)
            d.get_style_context().add_class("dim-label")
            self.checks.attach(d, 2, i, 1, 1)
        self.checks.show_all()
        self._boot_guard = True
        self.boot.set_active(self.ctrl.snapshot.service.enabled == "enabled")
        self._boot_guard = False

    def _on_boot(self, sw, _p) -> None:
        if self._boot_guard:
            return
        want = sw.get_active()

        def done(_r, err):
            if err and not getattr(err, "cancelled", False):
                message(self.win, _("Could not change start at boot"), str(err))
            self._boot_guard = True
            sw.set_active(system.service_state().enabled == "enabled")
            self._boot_guard = False
        self.ctrl.set_start_at_boot(want, done)
