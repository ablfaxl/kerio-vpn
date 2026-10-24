"""Connections page: list, add, edit, duplicate, delete, import/export profiles."""

from __future__ import annotations

import time
from typing import Optional

from gi.repository import Gtk, Pango

from .. import kvc, secretstore
from ..i18n import _
from ..profiles import Profile, ProfileStore
from .dialogs import ProfileDialog
from .widgets import confirm, message, page_header


class ProfileRow(Gtk.ListBoxRow):
    def __init__(self, page, profile: Profile, active: bool, default: bool):
        super().__init__()
        self.profile = profile
        box = Gtk.Box(spacing=10)
        box.get_style_context().add_class("kvp-profile-row")
        icon = Gtk.Image.new_from_icon_name("kvp-connected" if active else "kvp-disconnected",
                                            Gtk.IconSize.DND)
        icon.set_pixel_size(32)
        box.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(spacing=8)
        name = Gtk.Label(label=profile.name, xalign=0)
        name.get_style_context().add_class("kvp-profile-name")
        top.pack_start(name, False, False, 0)
        for flag, label in ((active, _("Active")), (default, _("Default"))):
            if flag:
                b = Gtk.Label(label=label)
                b.get_style_context().add_class("kvp-badge")
                top.pack_start(b, False, False, 0)
        text.pack_start(top, False, False, 0)
        sub = Gtk.Label(label="%s @ %s" % (profile.username, profile.address), xalign=0)
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.get_style_context().add_class("dim-label")
        text.pack_start(sub, False, False, 0)
        if profile.last_connected:
            last = Gtk.Label(xalign=0, label=_("Last connected %s") % time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(profile.last_connected)))
            last.get_style_context().add_class("dim-label")
            text.pack_start(last, False, False, 0)
        box.pack_start(text, True, True, 0)

        connect = Gtk.Button(label=_("Connect"))
        connect.set_valign(Gtk.Align.CENTER)
        connect.connect("clicked", lambda _b: page.win.connect_profile(profile))
        box.pack_start(connect, False, False, 0)
        edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        edit.set_tooltip_text(_("Edit"))
        edit.set_valign(Gtk.Align.CENTER)
        edit.connect("clicked", lambda _b: page.edit(profile))
        box.pack_start(edit, False, False, 0)

        menu = Gtk.Menu()
        for label, cb in ((_("Set as default"), page.set_default),
                          (_("Duplicate"), page.duplicate),
                          (_("Split tunneling…"), page.split_tunneling),
                          (_("Check server certificate"), page.win.check_certificate),
                          (_("Forget saved password"), page.forget_password),
                          (_("Delete"), page.delete)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, f=cb: f(profile))
            menu.append(item)
        menu.show_all()
        more = Gtk.MenuButton(popup=menu)
        more.set_image(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        more.set_valign(Gtk.Align.CENTER)
        box.pack_start(more, False, False, 0)
        self.add(box)


class ProfilesPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, border_width=24)
        self.win = win
        self.ctrl = win.ctrl
        self.store: ProfileStore = win.ctrl.store

        head = Gtk.Box(spacing=8)
        head.pack_start(page_header(_("Connections"), _(
            "Your VPN servers and accounts. Double-click a connection to edit it.")),
            True, True, 0)
        add = Gtk.Button(label=_("Add connection…"))
        add.set_image(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON))
        add.set_always_show_image(True)
        add.set_valign(Gtk.Align.CENTER)
        add.get_style_context().add_class("suggested-action")
        add.connect("clicked", lambda _b: self.add())
        menu = Gtk.Menu()
        for label, cb in ((_("Import current system configuration"), self.import_system),
                          (_("Import from file…"), self.import_file),
                          (_("Export…"), self.export_file)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, f=cb: f())
            menu.append(item)
        menu.show_all()
        more = Gtk.MenuButton(popup=menu, valign=Gtk.Align.CENTER)
        more.set_image(Gtk.Image.new_from_icon_name("document-open-symbolic",
                                                    Gtk.IconSize.BUTTON))
        more.set_tooltip_text(_("Import / export"))
        head.pack_end(more, False, False, 0)
        head.pack_end(add, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("frame")
        placeholder = Gtk.Label(label=_("No connections yet. Click “Add connection…” to "
                                        "create one."), margin=32, wrap=True)
        placeholder.get_style_context().add_class("dim-label")
        placeholder.show()
        self.list.set_placeholder(placeholder)
        self.list.set_activate_on_single_click(False)
        self.list.connect("row-activated", lambda _l, row: self.edit(row.profile))
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.add(self.list)
        self.pack_start(scroller, True, True, 0)
        note = Gtk.Label(xalign=0, wrap=True, label=_(
            "The Kerio client for Linux keeps one connection at a time. Connecting to "
            "another profile replaces the active one."))
        note.get_style_context().add_class("dim-label")
        self.pack_start(note, False, False, 0)
        self.refresh()

    def refresh(self) -> None:
        for row in self.list.get_children():
            row.destroy()
        active = self.ctrl.active_profile
        for p in self.store.profiles:
            self.list.add(ProfileRow(self, p, active is not None and active.id == p.id,
                                     p.id == self.ctrl.settings.default_profile))
        self.list.show_all()
        self.ctrl.emit("profiles-changed")

    def _save(self, profile: Profile, password: Optional[str]) -> None:
        if password and profile.save_password:
            if not secretstore.store(profile.id, profile.name, password):
                message(self.win, _("The password could not be saved in the keyring"),
                        _("You will be asked for it when connecting."),
                        Gtk.MessageType.WARNING)
        elif not profile.save_password:
            secretstore.clear(profile.id)
        if not self.ctrl.settings.default_profile:
            self.ctrl.settings.default_profile = profile.id
            self.ctrl.settings.save()
        self.store.upsert(profile)
        self.refresh()

    def add(self, template: Optional[Profile] = None, password: Optional[str] = None) -> None:
        dlg = ProfileDialog(self.win, None)
        if template:
            dlg.name.set_text(template.name)
            dlg.server.set_text(template.server)
            dlg.port.set_value(template.port)
            dlg.username.set_text(template.username)
            dlg.fingerprint.set_text(template.fingerprint)
            if password:
                dlg.password.set_text(password)
        if dlg.run() == Gtk.ResponseType.OK:
            profile, pw = dlg.result()
            dlg.destroy()
            self._save(profile, pw)
            self.win.dashboard.select_profile(profile.id)
            return
        dlg.destroy()

    def edit(self, profile: Profile) -> None:
        dlg = ProfileDialog(self.win, profile)
        if dlg.run() == Gtk.ResponseType.OK:
            updated, pw = dlg.result()
            dlg.destroy()
            self._save(updated, pw)
            return
        dlg.destroy()

    def duplicate(self, profile: Profile) -> None:
        copy = Profile(name=_("%s (copy)") % profile.name, server=profile.server,
                       port=profile.port, username=profile.username,
                       fingerprint=profile.fingerprint, save_password=profile.save_password)
        self.add(copy)

    def delete(self, profile: Profile) -> None:
        if not confirm(self.win, _("Delete “%s”?") % profile.name,
                       _("The profile and its saved password will be removed. The active "
                         "VPN configuration of the system is not changed."),
                       _("Delete"), destructive=True):
            return
        secretstore.clear(profile.id)
        self.store.remove(profile.id)
        if self.ctrl.settings.default_profile == profile.id:
            self.ctrl.settings.default_profile = ""
            self.ctrl.settings.save()
        self.refresh()

    def split_tunneling(self, profile: Profile) -> None:
        self.win.show_page("routing")
        self.win.routing_page.select_profile(profile.id)

    def set_default(self, profile: Profile) -> None:
        self.ctrl.settings.default_profile = profile.id
        self.ctrl.settings.save()
        self.refresh()

    def forget_password(self, profile: Profile) -> None:
        secretstore.clear(profile.id)
        message(self.win, _("Saved password removed"), "", Gtk.MessageType.INFO)

    def import_system(self) -> None:
        def done(result, err):
            if err:
                if not getattr(err, "cancelled", False):
                    message(self.win, _("Could not read the system configuration"), str(err))
                return
            cfg = (result or {}).get("config")
            if not cfg:
                message(self.win, _("No Kerio VPN configuration found"),
                        _("%s does not contain a connection.") % kvc.CONFIG_PATH,
                        Gtk.MessageType.INFO)
                return
            tpl = Profile(name=cfg.get("server", "VPN"), server=cfg.get("server", ""),
                          port=int(cfg.get("port") or kvc.DEFAULT_PORT),
                          username=cfg.get("username", ""),
                          fingerprint=cfg.get("fingerprint", ""))
            self.add(tpl, cfg.get("password") or None)
        self.ctrl.import_system_config(done)

    def import_file(self) -> None:
        dlg = Gtk.FileChooserNative.new(_("Import connections"), self.win,
                                        Gtk.FileChooserAction.OPEN, _("Import"), _("Cancel"))
        flt = Gtk.FileFilter()
        flt.set_name("JSON")
        flt.add_pattern("*.json")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            try:
                items = ProfileStore.read_import(dlg.get_filename())
            except (OSError, ValueError) as e:
                message(self.win, _("Import failed"), str(e))
                items = []
            for p in items:
                p.save_password = secretstore.available()
                self.store.upsert(p)
            if items:
                message(self.win, _("%d connection(s) imported") % len(items),
                        _("Passwords are not included in exported files; you will be asked "
                          "for them when connecting."), Gtk.MessageType.INFO)
            self.refresh()
        dlg.destroy()

    def export_file(self) -> None:
        if not self.store.profiles:
            return
        dlg = Gtk.FileChooserNative.new(_("Export connections"), self.win,
                                        Gtk.FileChooserAction.SAVE, _("Export"), _("Cancel"))
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name("kerio-vpn-connections.json")
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            try:
                self.store.export(dlg.get_filename())
            except OSError as e:
                message(self.win, _("Export failed"), str(e))
        dlg.destroy()
