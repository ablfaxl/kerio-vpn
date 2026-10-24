"""Main window: header bar, sidebar navigation and pages."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from gi.repository import Gdk, Gtk

from .. import APP_NAME, VERSION, kvc, secretstore
from ..controller import AUTH_ERROR, Controller
from ..i18n import _
from ..logparse import STOPPED
from ..profiles import Profile
from .about import AboutPage
from .connections import ProfilesPage
from .dashboard import DashboardPage
from .dialogs import PasswordDialog, fetch_certificate_async
from .logs import LogsPage
from .routing import RoutingPage
from .settings_page import SettingsPage
from .widgets import STATE_STYLE, confirm, error_label, message, state_label


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, name: str, icon: str, label: str):
        super().__init__()
        self.name = name
        box = Gtk.Box(spacing=12, border_width=10)
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        box.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        self.add(box)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, ctrl: Controller):
        super().__init__(application=app, title=APP_NAME)
        self.ctrl = ctrl
        self.busy_message = ""
        self.set_default_size(1060, 740)
        self.set_size_request(780, 560)
        self.set_icon_name("kerio-vpn")

        # A real title bar: draggable, with minimize / maximize / close.
        self.header = Gtk.HeaderBar(show_close_button=True, title=APP_NAME)
        menu = Gtk.Menu()
        for label, action in ((_("Diagnostics report…"), "app.diagnostics"),
                              (_("About"), "app.about"), (_("Quit"), "app.quit")):
            item = Gtk.MenuItem(label=label)
            item.set_action_name(action)
            menu.append(item)
        menu.show_all()
        mbtn = Gtk.MenuButton(popup=menu)
        mbtn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        self.header.pack_end(mbtn)
        self.set_titlebar(self.header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=120, hexpand=True)
        self.connections_page = None
        self.dashboard = DashboardPage(self)
        self.connections_page = ProfilesPage(self)
        self.routing_page = RoutingPage(self)
        self.logs_page = LogsPage(ctrl.monitor, ctrl.settings)
        self.settings_page = SettingsPage(self)
        self.about_page = AboutPage(self)
        pages = (("dashboard", "network-vpn-symbolic", _("Dashboard"), self.dashboard),
                 ("connections", "network-server-symbolic", _("Connections"),
                  self.connections_page),
                 ("routing", "network-workgroup-symbolic", _("Split tunneling"),
                  self.routing_page),
                 ("logs", "utilities-terminal-symbolic", _("Logs"), self.logs_page),
                 ("settings", "emblem-system-symbolic", _("Settings"), self.settings_page),
                 ("about", "help-about-symbolic", _("About"), self.about_page))

        # --- sidebar
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("kvp-sidebar")
        side.set_size_request(220, -1)
        brand = Gtk.Box(spacing=10, border_width=14)
        logo = Gtk.Image.new_from_icon_name("kerio-vpn", Gtk.IconSize.DND)
        logo.set_pixel_size(36)
        brand.pack_start(logo, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=APP_NAME, xalign=0)
        title.get_style_context().add_class("kvp-brand")
        names.pack_start(title, False, False, 0)
        ver = Gtk.Label(label=_("Version %s") % VERSION, xalign=0)
        ver.get_style_context().add_class("dim-label")
        ver.get_style_context().add_class("kvp-small")
        names.pack_start(ver, False, False, 0)
        brand.pack_start(names, True, True, 0)
        side.pack_start(brand, False, False, 0)

        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE)
        self.nav.get_style_context().add_class("kvp-nav")
        for name, icon, label, widget in pages:
            self.stack.add_named(widget, name)
            self.nav.add(SidebarRow(name, icon, label))
        self.nav.connect("row-selected", self._on_nav)
        self.stack.connect("notify::visible-child-name", lambda st, _p: self.show_page(
            st.get_visible_child_name()))
        side.pack_start(self.nav, True, True, 0)

        status = Gtk.Box(spacing=8, border_width=14)
        self.status_dot = Gtk.Label(label="●")
        self.status_text = Gtk.Label(xalign=0)
        self.status_text.get_style_context().add_class("kvp-small")
        status.pack_start(self.status_dot, False, False, 0)
        status.pack_start(self.status_text, True, True, 0)
        side.pack_end(status, False, False, 0)

        body = Gtk.Box()
        body.pack_start(side, False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        body.pack_start(self.stack, True, True, 0)
        self.add(body)

        ctrl.connect("profiles-changed", lambda _c: self.dashboard.refresh_profiles())
        ctrl.monitor.connect("changed", lambda _m, snap: self._on_snapshot(snap))
        ctrl.connect("busy", self._on_busy)
        ctrl.connect("error", lambda _c, t, d: message(self, t, d))
        ctrl.connect("need-password", lambda _c, p, r: self.ask_password(p, r))
        ctrl.connect("auth-failed", self._on_auth_failed)
        ctrl.connect("ssl-problem", lambda _c, p: p and self.check_certificate(p))
        ctrl.connect("state", lambda _c, _s, _p: self.connections_page.refresh())
        self.connect("key-press-event", self._on_key)

        # Show everything, including the title bar (it is not a child of the window).
        body.show_all()
        self.header.show_all()
        self.nav.select_row(self.nav.get_row_at_index(0))
        self._on_snapshot(ctrl.snapshot)

    # ------------------------------------------------------------ navigation
    def show_page(self, name: str) -> None:
        for row in self.nav.get_children():
            if row.name == name:
                if self.nav.get_selected_row() is not row:
                    self.nav.select_row(row)
                return

    def _on_nav(self, _nav, row) -> None:
        if row is not None:
            self.stack.set_visible_child_name(row.name)

    def _on_key(self, _w, event) -> bool:
        """Ctrl+1 … Ctrl+6 switch pages."""
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            index = event.keyval - Gdk.KEY_1
            if 0 <= index < len(self.nav.get_children()):
                self.nav.select_row(self.nav.get_row_at_index(index))
                return True
        return False

    # ------------------------------------------------------------ state
    def _on_snapshot(self, snap) -> None:
        self.dashboard.update(snap)
        label = state_label(snap.state)
        active = self.ctrl.active_profile
        if active and snap.state != STOPPED:
            label = "%s — %s" % (label, active.name)
        self.header.set_subtitle(label)
        self.status_text.set_text(label)
        kind, _icon = STATE_STYLE.get(snap.state, ("idle", ""))
        ctx = self.status_dot.get_style_context()
        for k in ("ok", "busy", "warning", "error", "idle"):
            ctx.remove_class("kvp-dot-" + k)
        ctx.add_class("kvp-dot-" + kind)

    def _on_busy(self, _c, busy: bool, msg: str) -> None:
        self.busy_message = msg if busy else ""
        self.dashboard.update(self.ctrl.snapshot)

    def _on_auth_failed(self, _c, profile: Optional[Profile]) -> None:
        if profile:
            self.present()
            self.ask_password(profile, _("The server rejected the username or password. "
                                         "Retrying was stopped to protect your account."))
        else:
            message(self, _("Authentication failed"), error_label(AUTH_ERROR))

    # ------------------------------------------------------------ actions
    def connect_profile(self, profile: Profile) -> None:
        self.dashboard.select_profile(profile.id)
        self.show_page("dashboard")
        self.ctrl.connect_profile(profile)

    def ask_password(self, profile: Profile, reason: str) -> None:
        pw, remember = PasswordDialog(self, profile, reason).ask()
        if pw:
            profile.save_password = remember
            profile.secret_rev = uuid.uuid4().hex
            self.ctrl.store.upsert(profile)
            if not remember:
                secretstore.clear(profile.id)
            self.ctrl.connect_profile(profile, password=pw, remember=remember)

    def check_certificate(self, profile: Profile) -> None:
        def done(md5):
            if md5 and md5 != kvc.normalize_fingerprint(profile.fingerprint):
                profile.fingerprint = md5
                self.ctrl.store.upsert(profile)
                if confirm(self, _("Fingerprint updated"),
                           _("Reconnect now with the new fingerprint?"), _("Reconnect")):
                    self.ctrl.connect_profile(profile)
            elif md5:
                message(self, _("The certificate matches the saved fingerprint"),
                        md5, Gtk.MessageType.INFO)
        fetch_certificate_async(self, profile.server, profile.port, profile.fingerprint, done)

    def report_done(self, success_text: str):
        def done(_result, err):
            if err:
                if not getattr(err, "cancelled", False):
                    message(self, _("Operation failed"), str(err))
            else:
                message(self, success_text, "", Gtk.MessageType.INFO)
        return done

    def show_diagnostics(self) -> None:
        from ..diagnostics import build_report
        text = build_report(self.ctrl.monitor)
        dlg = Gtk.Dialog(title=_("Diagnostics report"), transient_for=self, modal=True)
        dlg.set_default_size(760, 540)
        dlg.add_button(_("Copy"), 1)
        dlg.add_button(_("Save…"), 2)
        dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        view = Gtk.TextView(editable=False, monospace=True)
        view.get_buffer().set_text(text)
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.add(view)
        dlg.get_content_area().pack_start(sc, True, True, 0)
        dlg.show_all()
        while True:
            res = dlg.run()
            if res == 1:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            elif res == 2:
                fc = Gtk.FileChooserNative.new(_("Save report"), dlg, Gtk.FileChooserAction.SAVE,
                                               _("Save"), _("Cancel"))
                fc.set_current_name("kerio-vpn-diagnostics-%s.txt" % time.strftime("%Y%m%d-%H%M"))
                fc.set_do_overwrite_confirmation(True)
                if fc.run() == Gtk.ResponseType.ACCEPT:
                    with open(fc.get_filename(), "w", encoding="utf-8") as f:
                        f.write(text)
                fc.destroy()
            else:
                break
        dlg.destroy()
