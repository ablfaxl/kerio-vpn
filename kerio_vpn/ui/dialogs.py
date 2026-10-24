"""Profile editor, password prompt and certificate confirmation."""

from __future__ import annotations

import threading
import uuid
from typing import Optional, Tuple

from gi.repository import GLib, Gtk

from .. import certs, kvc, secretstore
from ..i18n import _
from ..profiles import Profile


def _field_label(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=1)
    lbl.get_style_context().add_class("dim-label")
    return lbl


def password_entry() -> Gtk.Entry:
    entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
    entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
    entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, _("Show password"))

    def toggle(e, _pos, _event):
        e.set_visibility(not e.get_visibility())
        e.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY,
            "view-conceal-symbolic" if e.get_visibility() else "view-reveal-symbolic")
    entry.connect("icon-press", toggle)
    return entry


class CertDialog(Gtk.Dialog):
    """Trust-on-first-use confirmation for the server certificate."""

    def __init__(self, parent, info: certs.CertInfo, expected: str = ""):
        super().__init__(title=_("Server certificate"), transient_for=parent, modal=True)
        self.set_default_size(520, -1)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Trust this certificate"), Gtk.ResponseType.OK)
        mismatch = bool(expected) and kvc.normalize_fingerprint(expected) != info.md5
        ok.get_style_context().add_class("destructive-action" if mismatch else "suggested-action")

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        if mismatch:
            warn = Gtk.Label(xalign=0, wrap=True)
            warn.set_markup("<b>%s</b>\n%s" % (
                GLib.markup_escape_text(_("The server certificate has CHANGED.")),
                GLib.markup_escape_text(_(
                    "This happens when the administrator renews the certificate, but it can "
                    "also mean someone is intercepting your connection. Accept it only if "
                    "your administrator confirms the new fingerprint."))))
            warn.get_style_context().add_class("kvp-check-fail")
            box.pack_start(warn, False, False, 0)
        else:
            hint = Gtk.Label(xalign=0, wrap=True, label=_(
                "Compare the MD5 fingerprint with the one shown in Kerio Control "
                "administration (Interfaces → VPN Server → Properties)."))
            box.pack_start(hint, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        rows = [(_("Address"), info.address), (_("Subject"), info.subject),
                (_("Issuer"), info.issuer), (_("Valid until"), info.not_after),
                (_("MD5 fingerprint"), info.md5), (_("SHA-256"), info.sha256)]
        if mismatch:
            rows.insert(4, (_("Expected (MD5)"), kvc.normalize_fingerprint(expected)))
        for i, (k, v) in enumerate(rows):
            grid.attach(_field_label(k), 0, i, 1, 1)
            val = Gtk.Label(label=v or "—", xalign=0, selectable=True, wrap=True)
            val.set_line_wrap_mode(2)  # WORD_CHAR
            if "fingerprint" in k.lower() or "MD5" in k or "SHA" in k:
                val.get_style_context().add_class("kvp-mono")
            grid.attach(val, 1, i, 1, 1)
        box.pack_start(grid, False, False, 0)
        self.show_all()


def fetch_certificate_async(parent, host: str, port: int, expected: str, callback) -> None:
    """Fetch, show CertDialog, call callback(md5 or None)."""

    def work():
        try:
            info = certs.fetch(host, port)
            GLib.idle_add(show, info, None)
        except Exception as e:  # network / TLS errors
            GLib.idle_add(show, None, e)

    def show(info, err):
        if err is not None:
            from .widgets import message
            message(parent, _("Could not get the server certificate"),
                    _("%(host)s:%(port)d — %(error)s") % {"host": host, "port": port,
                                                           "error": err})
            callback(None)
            return False
        dlg = CertDialog(parent, info, expected)
        res = dlg.run()
        dlg.destroy()
        callback(info.md5 if res == Gtk.ResponseType.OK else None)
        return False

    threading.Thread(target=work, daemon=True).start()


class ProfileDialog(Gtk.Dialog):
    def __init__(self, parent, profile: Optional[Profile] = None):
        editing = profile is not None
        super().__init__(title=_("Edit connection") if editing else _("New connection"),
                         transient_for=parent, modal=True)
        self.profile = profile
        self.set_default_size(480, -1)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.save_btn = self.add_button(_("Save"), Gtk.ResponseType.OK)
        self.save_btn.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10, border_width=16)
        self.get_content_area().pack_start(grid, True, True, 0)

        self.name = Gtk.Entry(activates_default=True, placeholder_text=_("e.g. Office"))
        self.server = Gtk.Entry(activates_default=True,
                                placeholder_text=_("vpn.example.com"))
        self.port = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.port.set_value(kvc.DEFAULT_PORT)
        self.username = Gtk.Entry(activates_default=True)
        self.password = password_entry()
        self.password.set_activates_default(True)
        self.save_pw = Gtk.CheckButton(label=_("Remember password in the keyring"))
        self.fingerprint = Gtk.Entry(placeholder_text="AA:BB:CC:…")
        self.fingerprint.get_style_context().add_class("kvp-mono")
        self.detect = Gtk.Button(label=_("Detect"))
        self.detect.set_tooltip_text(_("Download the certificate from the server"))
        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.get_style_context().add_class("kvp-check-fail")

        server_box = Gtk.Box(spacing=6)
        server_box.pack_start(self.server, True, True, 0)
        server_box.pack_start(Gtk.Label(label=_("Port")), False, False, 0)
        server_box.pack_start(self.port, False, False, 0)
        fp_box = Gtk.Box(spacing=6)
        fp_box.pack_start(self.fingerprint, True, True, 0)
        fp_box.pack_start(self.detect, False, False, 0)

        rows = [(_("Name"), self.name), (_("Server"), server_box),
                (_("Username"), self.username), (_("Password"), self.password),
                ("", self.save_pw), (_("Fingerprint"), fp_box)]
        for i, (title, widget) in enumerate(rows):
            grid.attach(_field_label(title), 0, i, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, i, 1, 1)
        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=50, label=_(
            "The fingerprint identifies your Kerio Control server. Click Detect and "
            "compare it with the value your administrator gives you."))
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 1, len(rows), 1, 1)
        grid.attach(self.error, 0, len(rows) + 1, 2, 1)

        if not secretstore.available():
            self.save_pw.set_sensitive(False)
            self.save_pw.set_tooltip_text(_("No keyring (Secret Service) is available"))

        if editing:
            self.name.set_text(profile.name)
            self.server.set_text(profile.server)
            self.port.set_value(profile.port)
            self.username.set_text(profile.username)
            self.fingerprint.set_text(profile.fingerprint)
            self.save_pw.set_active(profile.save_password and secretstore.available())
            self.password.set_placeholder_text(_("unchanged"))
        else:
            self.save_pw.set_active(secretstore.available())

        self.server.connect("changed", self._on_server_changed)
        self.detect.connect("clicked", self._on_detect)
        self.connect("response", self._on_response)
        self.show_all()
        self.error.hide()

    def _on_server_changed(self, entry) -> None:
        text = entry.get_text()
        if text.count(":") == 1 and not text.startswith("["):
            host, _sep, port = text.partition(":")
            if port.isdigit():
                entry.set_text(host)
                self.port.set_value(int(port))
        if not self.name.get_text() or self.name.get_text() == getattr(self, "_auto_name", None):
            self._auto_name = entry.get_text()
            self.name.set_text(self._auto_name)

    def _show_error(self, text: str) -> None:
        self.error.set_text(text)
        self.error.show()

    def _on_detect(self, _btn) -> None:
        host = self.server.get_text().strip()
        try:
            kvc.validate_host(host)
        except kvc.ValidationError as e:
            self._show_error(_(str(e)))
            return
        self.detect.set_sensitive(False)
        self.detect.set_label(_("Detecting…"))

        def done(md5):
            self.detect.set_sensitive(True)
            self.detect.set_label(_("Detect"))
            if md5:
                self.fingerprint.set_text(md5)
                self.error.hide()
        fetch_certificate_async(self, host, self.port.get_value_as_int(),
                                self.fingerprint.get_text().strip(), done)

    def _on_response(self, _dlg, response) -> None:
        if response != Gtk.ResponseType.OK:
            return
        try:
            self.result()
        except kvc.ValidationError as e:
            self.stop_emission_by_name("response")
            self._show_error(_(str(e)))

    def result(self) -> Tuple[Profile, Optional[str]]:
        """Return (profile, new password or None). Raises ValidationError."""
        p = Profile(**vars(self.profile)) if self.profile else Profile(name="", server="")
        p.name = self.name.get_text().strip()
        p.server = self.server.get_text().strip()
        p.port = self.port.get_value_as_int()
        p.username = self.username.get_text().strip()
        p.fingerprint = kvc.normalize_fingerprint(self.fingerprint.get_text())
        p.save_password = self.save_pw.get_active()
        if self.profile and (p.server != self.profile.server):
            p.last_ips = []
        p.validate()
        pw = self.password.get_text()
        if pw:
            kvc.validate_password(pw)
            p.secret_rev = uuid.uuid4().hex
        elif not self.profile and p.save_password:
            raise kvc.ValidationError("password", "Password is required")
        return p, (pw or None)


class PasswordDialog(Gtk.Dialog):
    def __init__(self, parent, profile: Profile, reason: str = ""):
        super().__init__(title=_("Password required"), transient_for=parent, modal=True)
        self.set_default_size(400, -1)
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        ok = self.add_button(_("Connect"), Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        title = Gtk.Label(xalign=0, wrap=True)
        title.set_markup("<b>%s</b>" % GLib.markup_escape_text(
            _("Enter the password for %(user)s on %(server)s") % {
                "user": profile.username, "server": profile.address}))
        box.pack_start(title, False, False, 0)
        if reason:
            r = Gtk.Label(label=reason, xalign=0, wrap=True)
            r.get_style_context().add_class("kvp-check-fail")
            box.pack_start(r, False, False, 0)
        self.entry = password_entry()
        self.entry.set_activates_default(True)
        box.pack_start(self.entry, False, False, 0)
        self.remember = Gtk.CheckButton(label=_("Remember password in the keyring"))
        self.remember.set_active(profile.save_password and secretstore.available())
        self.remember.set_sensitive(secretstore.available())
        box.pack_start(self.remember, False, False, 0)
        self.show_all()

    def ask(self) -> Tuple[Optional[str], bool]:
        res = self.run()
        pw = self.entry.get_text() if res == Gtk.ResponseType.OK else None
        remember = self.remember.get_active()
        self.destroy()
        return (pw or None), remember
