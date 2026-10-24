"""About page: product identity, versions and support tools."""

from __future__ import annotations

import platform

from gi.repository import Gtk

from .. import APP_NAME, APP_TAGLINE, COPYRIGHT, VERSION, system
from ..i18n import _
from .widgets import InfoGrid, card


class AboutPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, border_width=32,
                      halign=Gtk.Align.CENTER)
        box.set_size_request(560, -1)
        self.add(box)

        logo = Gtk.Image.new_from_icon_name("kerio-vpn", Gtk.IconSize.DIALOG)
        logo.set_pixel_size(112)
        box.pack_start(logo, False, False, 0)
        name = Gtk.Label(label=APP_NAME)
        name.get_style_context().add_class("kvp-about-name")
        box.pack_start(name, False, False, 0)
        ver = Gtk.Label(label=_("Version %s") % VERSION)
        ver.get_style_context().add_class("kvp-badge")
        ver.set_halign(Gtk.Align.CENTER)
        box.pack_start(ver, False, False, 0)
        tag = Gtk.Label(label=_(APP_TAGLINE), wrap=True, justify=Gtk.Justification.CENTER)
        tag.get_style_context().add_class("dim-label")
        box.pack_start(tag, False, False, 0)

        self.grid = InfoGrid()
        for key, title in (("app", _("Application")), ("daemon", _("Kerio VPN client")),
                           ("os", _("Operating system")), ("kernel", _("Kernel")),
                           ("python", _("Python"))):
            self.grid.add_row(key, title)
        box.pack_start(card(self.grid, _("System information")), False, False, 0)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        diag = Gtk.Button(label=_("Diagnostics report…"))
        diag.connect("clicked", lambda _b: win.show_diagnostics())
        buttons.pack_start(diag, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        legal = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, label=_(
            "%s\nLicensed under the GNU General Public License v3.\n"
            "Kerio and Kerio Control are trademarks of their respective owners. This "
            "application is not affiliated with Kerio Technologies or GFI Software.")
            % COPYRIGHT)
        legal.get_style_context().add_class("dim-label")
        box.pack_start(legal, False, False, 0)
        self.connect("map", lambda _w: self.refresh())

    def refresh(self) -> None:
        os_name = ""
        try:
            with open("/etc/os-release") as f:
                os_name = next((l.split("=", 1)[1].strip().strip('"') for l in f
                                if l.startswith("PRETTY_NAME=")), "")
        except OSError:
            pass
        self.grid.set("app", "%s %s" % (APP_NAME, VERSION))
        self.grid.set("daemon", system.daemon_version() or _("not installed"))
        self.grid.set("os", os_name)
        self.grid.set("kernel", platform.release())
        self.grid.set("python", platform.python_version())
