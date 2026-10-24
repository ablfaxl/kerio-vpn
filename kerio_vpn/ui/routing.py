"""Split tunneling page: destinations that bypass the VPN or always use it."""

from __future__ import annotations

import re

from gi.repository import Gtk, Pango

from .. import splitroute
from ..i18n import _, ngettext
from ..logparse import CONNECTED
from .widgets import card, confirm, icon_button, page_header

_SPLIT_RE = re.compile(r"[\s,;]+")


class RuleList(Gtk.Box):
    """Entry + list editor for one list attribute of the selected profile."""

    def __init__(self, page, attr: str, placeholder: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.page = page
        self.attr = attr

        row = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(placeholder_text=placeholder, hexpand=True)
        self.entry.connect("activate", lambda _e: self._add())
        self.entry.connect("changed", lambda _e: self.error.hide())
        add = Gtk.Button(label=_("Add"))
        add.connect("clicked", lambda _b: self._add())
        row.pack_start(self.entry, True, True, 0)
        row.pack_start(add, False, False, 0)
        self.pack_start(row, False, False, 0)

        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.get_style_context().add_class("kvp-check-fail")
        self.error.set_no_show_all(True)
        self.pack_start(self.error, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("frame")
        empty = Gtk.Label(label=_("No entries"), margin=16)
        empty.get_style_context().add_class("dim-label")
        empty.show()
        self.list.set_placeholder(empty)
        scroller = Gtk.ScrolledWindow(min_content_height=160, vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.list)
        self.pack_start(scroller, True, True, 0)

        bottom = Gtk.Box(spacing=6)
        self.count = Gtk.Label(xalign=0)
        self.count.get_style_context().add_class("dim-label")
        bottom.pack_start(self.count, True, True, 0)
        clear = Gtk.Button(label=_("Remove all"))
        clear.get_style_context().add_class("flat")
        clear.connect("clicked", lambda _b: self._clear())
        bottom.pack_end(clear, False, False, 0)
        self.pack_start(bottom, False, False, 0)

    def _clear(self) -> None:
        if self._entries() and confirm(self.get_toplevel(), _("Remove all entries?"),
                                       _("This list will be emptied."), _("Remove all"),
                                       destructive=True):
            self._set([])

    def _entries(self):
        profile = self.page.profile()
        return list(getattr(profile, self.attr)) if profile else []

    def _set(self, entries) -> None:
        profile = self.page.profile()
        if not profile:
            return
        setattr(profile, self.attr, entries)
        self.page.save(profile)

    def _add(self) -> None:
        if not self.page.profile():
            return
        current = self._entries()
        bad = []
        for token in _SPLIT_RE.split(self.entry.get_text().strip()):
            if not token:
                continue
            try:
                kind, value = splitroute.classify(token)
            except ValueError as e:
                bad.append("%s: %s" % (token, _(str(e))))
                continue
            if value not in current:
                current.append(value)
        if bad:
            self.error.set_text("\n".join(bad))
            self.error.show()
        else:
            self.entry.set_text("")
        self._set(current)

    def refresh(self) -> None:
        for child in self.list.get_children():
            child.destroy()
        entries = self._entries()
        for value in entries:
            kind = splitroute.classify(value)[0] if _valid(value) else "net"
            box = Gtk.Box(spacing=10, border_width=6)
            icon = "network-workgroup-symbolic" if kind == "net" else "web-browser-symbolic"
            box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            lbl = Gtk.Label(label=value, xalign=0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.get_style_context().add_class("kvp-mono")
            box.pack_start(lbl, True, True, 0)
            kind_lbl = Gtk.Label(label=_("Domain") if kind == "host" else _("Network"))
            kind_lbl.get_style_context().add_class("dim-label")
            box.pack_start(kind_lbl, False, False, 0)
            rm = icon_button("user-trash-symbolic", _("Remove"),
                             lambda v=value: self._set([e for e in self._entries() if e != v]))
            rm.get_style_context().add_class("flat")
            box.pack_start(rm, False, False, 0)
            self.list.add(box)
        self.list.show_all()
        self.count.set_text(ngettext("%d entry", "%d entries", len(entries)) % len(entries))
        self.set_sensitive(self.page.profile() is not None)


def _valid(value: str) -> bool:
    try:
        splitroute.classify(value)
        return True
    except ValueError:
        return False


class RoutingPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.ctrl = win.ctrl
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, border_width=24)
        self.add(outer)

        head = Gtk.Box(spacing=12)
        head.pack_start(page_header(_("Split tunneling"), _(
            "Choose which destinations skip the VPN and which always use it. Enter IP "
            "addresses, networks in CIDR notation or domain names; several can be pasted "
            "at once.")), True, True, 0)
        self.combo = Gtk.ComboBoxText(valign=Gtk.Align.CENTER)
        self.combo.connect("changed", lambda _c: self.refresh_lists())
        head.pack_end(self.combo, False, False, 0)
        outer.pack_start(head, False, False, 0)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.get_style_context().add_class("kvp-detail")
        outer.pack_start(self.status, False, False, 0)

        cols = Gtk.Box(spacing=16, homogeneous=True)
        self.exclude = RuleList(self, "split_exclude", _("IP address, network (CIDR) or domain"))
        self.include = RuleList(self, "split_include", _("IP address, network (CIDR) or domain"))
        cols.pack_start(card(self._with_hint(self.exclude, _(
            "Traffic to these destinations goes directly through your normal internet "
            "connection, even when the VPN routes all traffic.")), _("Bypass the VPN")),
            True, True, 0)
        cols.pack_start(card(self._with_hint(self.include, _(
            "Traffic to these destinations always goes through the VPN, in addition to the "
            "networks the server provides.")), _("Always through the VPN")), True, True, 0)
        outer.pack_start(cols, True, True, 0)

        note = Gtk.Label(xalign=0, wrap=True, label=_(
            "Rules are stored per connection and applied automatically every time it "
            "connects. Domain names are resolved when the rules are applied and refreshed "
            "every 10 minutes. With the kill switch on, bypassed destinations stay reachable."))
        note.get_style_context().add_class("dim-label")
        outer.pack_start(note, False, False, 0)

        self.ctrl.connect("profiles-changed", lambda _c: self.refresh())
        self.connect("map", lambda _w: self.refresh())

    @staticmethod
    def _with_hint(widget, hint):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        lbl = Gtk.Label(label=hint, xalign=0, wrap=True)
        lbl.get_style_context().add_class("dim-label")
        box.pack_start(lbl, False, False, 0)
        box.pack_start(widget, True, True, 0)
        return box

    def profile(self):
        return self.ctrl.store.get(self.combo.get_active_id())

    def save(self, profile) -> None:
        self.ctrl.store.upsert(profile)
        self.refresh_lists()
        active = self.ctrl.active_profile
        if active and active.id == profile.id:
            self.ctrl.apply_routes_now()

    def select_profile(self, pid: str) -> None:
        self.refresh()
        self.combo.set_active_id(pid)

    def refresh(self) -> None:
        current = self.combo.get_active_id()
        self.combo.remove_all()
        for p in self.ctrl.store.profiles:
            self.combo.append(p.id, p.name)
        active = self.ctrl.active_profile
        want = current or (active.id if active else None)
        if not (want and self.combo.set_active_id(want)) and self.ctrl.store.profiles:
            self.combo.set_active(0)
        self.refresh_lists()

    def refresh_lists(self) -> None:
        self.exclude.refresh()
        self.include.refresh()
        profile = self.profile()
        active = self.ctrl.active_profile
        if not profile:
            text = _("Add a connection first.")
        elif self.ctrl.snapshot.state == CONNECTED and active and active.id == profile.id:
            text = "● " + (self.ctrl.route_status or _("Rules are applied to the active "
                                                        "connection."))
        else:
            text = _("Rules will be applied when “%s” connects.") % profile.name
        self.status.set_text(text)
