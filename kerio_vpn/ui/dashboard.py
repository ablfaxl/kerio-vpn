"""Dashboard: state, quick connect, live statistics, traffic chart, details."""

from __future__ import annotations

import os
from typing import Optional

from gi.repository import Gtk

from .. import installer, kvc, system
from ..controller import AUTH_ERROR, SSL_ERROR
from ..i18n import _
from ..logparse import (CONNECTED, CONNECTING, DISCONNECTING, NOT_INSTALLED, RECONNECTING,
                        STARTING, STOPPED)
from ..monitor import Snapshot
from ..profiles import Profile
from .widgets import (STATE_STYLE, InfoGrid, StatTile, StatusOrb, TrafficChart, card,
                      error_label, fmt_bytes, message, fmt_duration, fmt_rate, icon_button,
                      state_label)

ACTIVE_STATES = (STARTING, CONNECTING, CONNECTED, RECONNECTING)

# infobar response ids
R_PASSWORD, R_CERT, R_STOP, R_DNS, R_KILLSWITCH = range(1, 6)


class DashboardPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.ctrl = win.ctrl
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, border_width=24)
        self.add(body)

        self.infobar = Gtk.InfoBar(show_close_button=False)
        self.infobar_label = Gtk.Label(xalign=0, wrap=True)
        self.infobar.get_content_area().pack_start(self.infobar_label, True, True, 0)
        self.infobar.connect("response", self._on_infobar)
        self.infobar.set_no_show_all(True)
        self._infobar_key = None
        body.pack_start(self.infobar, False, False, 0)

        # ---- shown when kerio-control-vpnclient is missing
        inst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        msg = Gtk.Label(wrap=True, xalign=0, label=_(
            "Kerio VPN uses the official Kerio Control VPN Client service, which is not "
            "installed on this computer yet. It can be installed automatically."))
        inst.pack_start(msg, False, False, 0)
        self.install_status = Gtk.Label(wrap=True, xalign=0)
        self.install_status.get_style_context().add_class("kvp-detail")
        inst.pack_start(self.install_status, False, False, 0)
        ib = Gtk.Box(spacing=8)
        self.install_btn = Gtk.Button(label=_("Install automatically"))
        self.install_btn.get_style_context().add_class("suggested-action")
        self.install_btn.connect("clicked", lambda _b: self.install(None))
        ib.pack_start(self.install_btn, False, False, 0)
        from_file = Gtk.Button(label=_("Install from file…"))
        from_file.connect("clicked", lambda _b: self._install_from_file())
        ib.pack_start(from_file, False, False, 0)
        page = Gtk.Button(label=_("Open download page"))
        page.get_style_context().add_class("flat")
        page.connect("clicked", lambda _b: Gtk.show_uri_on_window(
            win, installer.DOWNLOAD_PAGE, Gtk.get_current_event_time()))
        ib.pack_start(page, False, False, 0)
        inst.pack_start(ib, False, False, 0)
        self.install_card = card(inst, _("Kerio VPN Client required"))
        self.install_card.set_no_show_all(True)
        body.pack_start(self.install_card, False, False, 0)

        # ---- hero
        hero = Gtk.Box(spacing=22)
        hero.get_style_context().add_class("kvp-hero")
        self.orb = StatusOrb(96)
        hero.pack_start(self.orb, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                       valign=Gtk.Align.CENTER)
        self.state_lbl = Gtk.Label(xalign=0)
        self.state_lbl.get_style_context().add_class("kvp-state")
        self.detail_lbl = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        self.detail_lbl.get_style_context().add_class("kvp-detail")
        text.pack_start(self.state_lbl, False, False, 0)
        text.pack_start(self.detail_lbl, False, False, 0)
        hero.pack_start(text, True, True, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                           valign=Gtk.Align.CENTER)
        pick = Gtk.Box(spacing=4)
        pick.get_style_context().add_class("linked")
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.set_size_request(200, -1)
        self.profile_combo.connect("changed", lambda _c: self.update(self.ctrl.snapshot))
        pick.pack_start(self.profile_combo, True, True, 0)
        self.edit_btn = icon_button("document-edit-symbolic", _("Edit this connection"),
                                    self._edit_selected)
        pick.pack_start(self.edit_btn, False, False, 0)
        pick.pack_start(icon_button("list-add-symbolic", _("Add connection…"),
                                    lambda: win.connections_page.add()), False, False, 0)
        controls.pack_start(pick, False, False, 0)
        btn_row = Gtk.Box(spacing=8)
        self.main_btn = Gtk.Button(label=_("Connect"))
        self.main_btn.get_style_context().add_class("kvp-big-button")
        self.main_btn.connect("clicked", self._on_main)
        btn_row.pack_start(self.main_btn, True, True, 0)
        self.spinner = Gtk.Spinner()
        btn_row.pack_start(self.spinner, False, False, 0)
        controls.pack_start(btn_row, False, False, 0)
        hero.pack_end(controls, False, False, 0)
        body.pack_start(hero, False, False, 0)

        # ---- tiles
        tiles = Gtk.Box(spacing=12, homogeneous=True)
        self.t_down = StatTile(_("Download"), "go-down-symbolic", "down")
        self.t_up = StatTile(_("Upload"), "go-up-symbolic", "up")
        self.t_rx = StatTile(_("Received"), "document-save-symbolic")
        self.t_tx = StatTile(_("Sent"), "document-send-symbolic")
        self.t_time = StatTile(_("Duration"), "preferences-system-time-symbolic")
        self.t_ping = StatTile(_("Latency"), "network-wireless-signal-good-symbolic")
        for t in (self.t_down, self.t_up, self.t_rx, self.t_tx, self.t_time, self.t_ping):
            tiles.pack_start(t, True, True, 0)
        body.pack_start(tiles, False, False, 0)

        # ---- chart + details
        row = Gtk.Grid(column_spacing=16)
        self.chart = TrafficChart()
        chart_card = card(self.chart, _("Traffic"))
        chart_card.set_hexpand(True)
        row.attach(chart_card, 0, 0, 1, 1)
        self.grid = InfoGrid()
        for key, title in (("server", _("Server")), ("user", _("Username")),
                           ("ip", _("VPN address")), ("dns", _("DNS servers")),
                           ("domain", _("DNS domain")), ("mode", _("Routing")),
                           ("iface", _("Interface")), ("split", _("Split tunneling"))):
            self.grid.add_row(key, title)
        details = card(self.grid, _("Connection details"))
        details.set_size_request(360, -1)
        details.set_hexpand(False)
        row.attach(details, 1, 0, 1, 1)
        body.pack_start(row, False, False, 0)

        # ---- routes
        self.routes = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.routes.get_style_context().add_class("kvp-mono")
        manage = Gtk.Button(label=_("Split tunneling…"))
        manage.get_style_context().add_class("flat")
        manage.connect("clicked", lambda _b: win.show_page("routing"))
        body.pack_start(card(self.routes, _("Routes through the VPN"), manage), False, False, 0)

        # ---- empty state
        self.empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lbl = Gtk.Label(wrap=True, xalign=0, label=_(
            "No VPN connection is configured yet. Add one, or import the configuration "
            "that is already set up for the Kerio client on this computer."))
        self.empty.pack_start(lbl, False, False, 0)
        er = Gtk.Box(spacing=8)
        add = Gtk.Button(label=_("Add connection…"))
        add.get_style_context().add_class("suggested-action")
        add.connect("clicked", lambda _b: win.connections_page.add())
        imp = Gtk.Button(label=_("Import current system configuration"))
        imp.connect("clicked", lambda _b: win.connections_page.import_system())
        er.pack_start(add, False, False, 0)
        er.pack_start(imp, False, False, 0)
        self.empty.pack_start(er, False, False, 0)
        self.empty_card = card(self.empty, _("Get started"))
        self.empty_card.set_no_show_all(True)
        body.pack_start(self.empty_card, False, False, 0)
        body.reorder_child(self.empty_card, 2)

        self.refresh_profiles()

    # ------------------------------------------------------------ client install
    def install(self, path: Optional[str]) -> None:
        self.install_btn.set_sensitive(False)

        def done(result, err):
            self.install_btn.set_sensitive(True)
            if err:
                if getattr(err, "cancelled", False):
                    self.install_status.set_text("")
                    return
                self.install_status.set_text(str(err))
                message(self.win, _("Kerio VPN Client could not be installed"), str(err))
                return
            self.install_status.set_text(_("Installed version %s.") % result.get("version", ""))
            self.ctrl.monitor.poke()
        self.ctrl.install_client(path, done, self.install_status.set_text)

    def _install_from_file(self) -> None:
        dlg = Gtk.FileChooserNative.new(_("Choose the Kerio VPN Client package"), self.win,
                                        Gtk.FileChooserAction.OPEN, _("Install"), _("Cancel"))
        flt = Gtk.FileFilter()
        flt.set_name(_("Debian package (.deb)"))
        flt.add_pattern("*.deb")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.install(dlg.get_filename())
        dlg.destroy()

    # ------------------------------------------------------------ profiles
    def refresh_profiles(self) -> None:
        current = self.profile_combo.get_active_id()
        self.profile_combo.remove_all()
        for p in self.ctrl.store.profiles:
            self.profile_combo.append(p.id, p.name)
        default = self.ctrl.default_profile()
        want = current if self.ctrl.store.get(current) else (default.id if default else None)
        if want:
            self.profile_combo.set_active_id(want)
        has = bool(self.ctrl.store.profiles)
        if has:
            self.empty_card.hide()
        else:
            self.empty_card.set_no_show_all(False)
            self.empty_card.show_all()
        self.profile_combo.set_sensitive(has)
        self.edit_btn.set_sensitive(has)

    def selected_profile(self) -> Optional[Profile]:
        return self.ctrl.store.get(self.profile_combo.get_active_id())

    def select_profile(self, pid: str) -> None:
        self.profile_combo.set_active_id(pid)

    def _edit_selected(self) -> None:
        p = self.selected_profile()
        if p:
            self.win.connections_page.edit(p)

    # ------------------------------------------------------------ actions
    def _on_main(self, _btn) -> None:
        snap = self.ctrl.snapshot
        selected = self.selected_profile()
        active = self.ctrl.active_profile
        if snap.state in ACTIVE_STATES and (not selected or not active
                                            or selected.id == active.id):
            self.ctrl.disconnect()
        elif selected:
            self.win.connect_profile(selected)
        else:
            self.win.connections_page.add()

    def _set_infobar(self, key, kind=None, text="", buttons=()) -> None:
        if key is None:
            self.infobar.hide()
            self._infobar_key = None
            return
        if key == self._infobar_key:
            return
        self._infobar_key = key
        for child in self.infobar.get_action_area().get_children():
            child.destroy()
        for label, rid in buttons:
            self.infobar.add_button(label, rid)
        self.infobar.set_message_type(kind)
        self.infobar_label.set_text(text)
        self.infobar.set_no_show_all(False)
        self.infobar.show_all()

    def _on_infobar(self, _bar, rid) -> None:
        profile = self.ctrl.active_profile or self.selected_profile()
        if rid == R_PASSWORD and profile:
            self.win.ask_password(profile, "")
        elif rid == R_CERT and profile:
            self.win.check_certificate(profile)
        elif rid == R_STOP:
            self.ctrl.disconnect()
        elif rid == R_DNS:
            self.ctrl.repair_dns(self.win.report_done(_("DNS settings were restored.")))
        elif rid == R_KILLSWITCH:
            self.ctrl.disable_killswitch()
        self._infobar_key = None
        self.infobar.hide()

    # ------------------------------------------------------------ update
    def update(self, snap: Snapshot) -> None:
        info = snap.info
        kind, _icon = STATE_STYLE.get(snap.state, ("idle", ""))
        if snap.state == RECONNECTING and info.last_error_code:
            kind = "warning"
        self.orb.set_kind(kind)
        ctx = self.state_lbl.get_style_context()
        for k in ("ok", "busy", "warning", "error", "idle"):
            ctx.remove_class(k)
        ctx.add_class(kind)
        self.state_lbl.set_text(state_label(snap.state))
        missing = snap.state == NOT_INSTALLED
        if missing != self.install_card.get_visible():
            if missing:
                self.install_card.set_no_show_all(False)
                self.install_card.show_all()
            else:
                self.install_card.hide()

        active = self.ctrl.active_profile
        selected = self.selected_profile()
        running = snap.state in ACTIVE_STATES
        if snap.state == NOT_INSTALLED:
            detail = _("Install the Kerio VPN Client to start using this application.")
        elif snap.state == CONNECTED:
            detail = _("Securely connected to %s") % (active.name if active else info.server)
        elif snap.state == RECONNECTING and info.last_error_code:
            detail = error_label(info.last_error_code)
        elif snap.state in (CONNECTING, STARTING):
            detail = _("Contacting %s…") % (info.server or (active.address if active else ""))
        elif snap.state == STOPPED and snap.service.active == "failed":
            detail = _("The VPN service failed. See the Logs page for details.")
        elif not self.ctrl.store.profiles:
            detail = _("Add a connection to get started.")
        else:
            detail = _("Choose a connection and press Connect.")
        if self.ctrl.busy and self.win.busy_message:
            detail = self.win.busy_message
        self.detail_lbl.set_text(detail)

        switching = running and selected and active and selected.id != active.id
        ctx = self.main_btn.get_style_context()
        ctx.remove_class("suggested-action")
        ctx.remove_class("destructive-action")
        if switching:
            self.main_btn.set_label(_("Switch to this connection"))
            ctx.add_class("suggested-action")
        elif running:
            self.main_btn.set_label(_("Disconnect"))
            ctx.add_class("destructive-action")
        elif snap.state == DISCONNECTING:
            self.main_btn.set_label(_("Disconnecting…"))
        else:
            self.main_btn.set_label(_("Connect") if self.ctrl.store.profiles
                                    else _("Add connection…"))
            ctx.add_class("suggested-action")
        self.main_btn.set_sensitive(not self.ctrl.busy and snap.state not in (
            NOT_INSTALLED, DISCONNECTING))
        if self.ctrl.busy or snap.state in (STARTING, CONNECTING, DISCONNECTING):
            self.spinner.start()
        else:
            self.spinner.stop()

        connected = snap.state == CONNECTED
        shown = active if running else (selected or active)
        if not running:
            info = type(info)()  # details of an old session are not useful
        server = info.server or (shown.address if shown else "")
        if info.server_ip and info.server_ip != info.server:
            server += " (%s)" % info.server_ip
        self.grid.set("server", server)
        self.grid.set("user", info.username or (shown.username if shown else ""))
        self.grid.set("ip", "%s/%s" % (info.local_ip, info.netmask)
                      if connected and info.local_ip else "")
        self.grid.set("dns", ", ".join(info.dns) if connected else "")
        self.grid.set("domain", info.domain if connected else "")
        self.grid.set("mode", (_("All traffic through VPN") if info.is_full_tunnel
                               else _("Only company networks")) if connected else "")
        self.grid.set("iface", snap.iface or "")
        if shown and (shown.split_exclude or shown.split_include):
            split = _("%(ex)d bypass, %(in)d forced") % {
                "ex": len(shown.split_exclude), "in": len(shown.split_include)}
        else:
            split = _("Off")
        self.grid.set("split", split)

        if connected and snap.iface:
            self.t_down.set(fmt_rate(snap.rx_rate))
            self.t_up.set(fmt_rate(snap.tx_rate))
            self.t_rx.set(fmt_bytes(snap.rx_bytes))
            self.t_tx.set(fmt_bytes(snap.tx_bytes))
            self.chart.push(snap.rx_rate, snap.tx_rate)
        else:
            for t in (self.t_down, self.t_up, self.t_rx, self.t_tx):
                t.set("")
            if snap.state not in ACTIVE_STATES:
                self.chart.clear()
        self.t_time.set(fmt_duration(snap.connected_for) if connected else "")
        self.t_ping.set("%.0f ms" % snap.latency_ms if snap.latency_ms is not None
                        else "")

        if connected and info.routes:
            self.routes.set_text("\n".join(
                "%-20s %s" % (r, _("on-link") if r.gateway == "0.0.0.0" else "→ " + r.gateway)
                for r in info.routes))
        else:
            self.routes.set_text(_("Routes appear here while connected."))
        self._update_banners(snap)

    def _update_banners(self, snap: Snapshot) -> None:
        info = snap.info
        if snap.state == RECONNECTING and info.last_error_code == AUTH_ERROR:
            self._set_infobar(("auth", info.last_error_ts), Gtk.MessageType.ERROR,
                              error_label(AUTH_ERROR),
                              [(_("Enter password"), R_PASSWORD), (_("Stop"), R_STOP)])
        elif snap.state == RECONNECTING and info.last_error_code == SSL_ERROR:
            self._set_infobar("ssl", Gtk.MessageType.WARNING, error_label(SSL_ERROR),
                              [(_("Check certificate"), R_CERT), (_("Stop"), R_STOP)])
        elif snap.state == RECONNECTING and info.consecutive_errors >= 3:
            self._set_infobar(("err", info.last_error_code), Gtk.MessageType.WARNING,
                              _("Still trying to connect (%(n)d attempts): %(err)s") % {
                                  "n": info.consecutive_errors,
                                  "err": error_label(info.last_error_code)},
                              [(_("Stop"), R_STOP)])
        elif snap.state == STOPPED and self.ctrl.killswitch_active:
            self._set_infobar("ks", Gtk.MessageType.ERROR, _(
                "The kill switch is blocking all internet traffic because the VPN is not "
                "connected."), [(_("Disable kill switch"), R_KILLSWITCH)])
        elif not snap.logs_readable and snap.service.running:
            self._set_infobar("logs", Gtk.MessageType.INFO, _(
                "Kerio logs are not readable by your user, so details are limited."))
        elif (snap.state == STOPPED and snap.service.installed
              and any(ns.startswith("10.") for ns in system.nameservers())
              and os.path.exists(kvc.RESOLV_BACKUP)):
            self._set_infobar("dns", Gtk.MessageType.WARNING, _(
                "The VPN is off but DNS still points to the VPN server. Internet names may "
                "not resolve."), [(_("Repair DNS"), R_DNS)])
        elif snap.state in (CONNECTED, STOPPED):
            self._set_infobar(None)
