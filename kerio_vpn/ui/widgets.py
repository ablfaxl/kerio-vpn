"""Small reusable widgets and formatting helpers."""

from __future__ import annotations

import math
import os
from collections import deque
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402

from .. import logparse  # noqa: E402
from ..i18n import _  # noqa: E402

DATA_DIR = os.environ.get("KVP_DATA_DIR") or next(
    (d for d in (os.path.join(os.path.dirname(__file__), "..", "..", "data"),
                 "/usr/share/kerio-vpn") if os.path.isdir(d)),
    "/usr/share/kerio-vpn")
ICON_DIR = os.path.abspath(os.path.join(DATA_DIR, "icons"))

STATE_STYLE = {
    logparse.NOT_INSTALLED: ("error", "kvp-disconnected"),
    logparse.STOPPED: ("idle", "kvp-disconnected"),
    logparse.STARTING: ("busy", "kvp-connecting"),
    logparse.CONNECTING: ("busy", "kvp-connecting"),
    logparse.RECONNECTING: ("warning", "kvp-error"),
    logparse.CONNECTED: ("ok", "kvp-connected"),
    logparse.DISCONNECTING: ("busy", "kvp-connecting"),
}

COLORS = {
    "ok": (0.18, 0.69, 0.38),
    "busy": (0.20, 0.52, 0.89),
    "warning": (0.93, 0.56, 0.10),
    "error": (0.86, 0.22, 0.22),
    "idle": (0.55, 0.57, 0.60),
}


def state_label(state: str) -> str:
    return {
        logparse.NOT_INSTALLED: _("Kerio VPN Client not installed"),
        logparse.STOPPED: _("Disconnected"),
        logparse.STARTING: _("Starting service…"),
        logparse.CONNECTING: _("Connecting…"),
        logparse.RECONNECTING: _("Reconnecting…"),
        logparse.CONNECTED: _("Connected"),
        logparse.DISCONNECTING: _("Disconnecting…"),
    }.get(state, state)


def error_label(code: Optional[int]) -> str:
    return {
        120: _("SSL handshake failed. The server certificate may have changed "
               "or the server does not accept VPN connections on this port."),
        142: _("The server closed the connection."),
        145: _("The connection timed out. Check the server address, port and firewall."),
        146: _("Unexpected network error. Retrying…"),
        161: _("Authentication failed. Check your username and password."),
        191: _("Cannot resolve the server name. Check the address and your DNS."),
    }.get(code or 0, _("Connection error %s") % code if code else "")


def _bytes(n: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return "%d %s" % (n, units[i])
    return ("%.0f %s" if n >= 100 or n == int(n) else "%.1f %s") % (n, units[i])


def fmt_bytes(n: float) -> str:
    return _bytes(n)


def fmt_rate(n: float) -> str:
    return _bytes(n) + "/s"


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return _("%dd %02d:%02d:%02d") % (d, h, m, s)
    return "%02d:%02d:%02d" % (h, m, s)


def load_css() -> None:
    path = os.path.join(os.path.dirname(__file__), "style.css")
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(path)
    except Exception as e:  # a broken stylesheet must not prevent startup
        print("css:", e)
        return
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class StatusOrb(Gtk.DrawingArea):
    """Coloured ring that pulses while connecting."""

    def __init__(self, size: int = 96):
        super().__init__()
        self.set_size_request(size, size)
        self.kind = "idle"
        self._phase = 0.0
        self._tick_id = 0
        self.connect("draw", self._draw)

    def set_kind(self, kind: str) -> None:
        if kind == self.kind:
            return
        self.kind = kind
        animate = kind in ("busy", "warning")
        if animate and not self._tick_id:
            self._tick_id = self.add_tick_callback(self._tick)
        elif not animate and self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        self.queue_draw()

    def _tick(self, _widget, clock) -> bool:
        self._phase = (clock.get_frame_time() / 1_000_000.0) % 2.0
        self.queue_draw()
        return True

    def _draw(self, _widget, cr) -> bool:
        w, h = self.get_allocated_width(), self.get_allocated_height()
        r = min(w, h) / 2.0 - 4
        cx, cy = w / 2.0, h / 2.0
        red, green, blue = COLORS.get(self.kind, COLORS["idle"])

        if self._tick_id:
            t = self._phase / 2.0
            cr.set_source_rgba(red, green, blue, 0.35 * (1 - t))
            cr.arc(cx, cy, r * (0.6 + 0.4 * t), 0, 2 * math.pi)
            cr.fill()

        cr.set_source_rgba(red, green, blue, 0.15)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(red, green, blue)
        cr.set_line_width(max(3.0, r / 9))
        cr.arc(cx, cy, r * 0.82, 0, 2 * math.pi)
        cr.stroke()

        # shield glyph
        s = r * 0.42
        cr.move_to(cx, cy - s)
        cr.line_to(cx + s * 0.85, cy - s * 0.68)
        cr.line_to(cx + s * 0.85, cy - s * 0.05)
        cr.curve_to(cx + s * 0.85, cy + s * 0.55, cx + s * 0.4, cy + s * 0.9, cx, cy + s * 1.08)
        cr.curve_to(cx - s * 0.4, cy + s * 0.9, cx - s * 0.85, cy + s * 0.55, cx - s * 0.85, cy - s * 0.05)
        cr.line_to(cx - s * 0.85, cy - s * 0.68)
        cr.close_path()
        cr.fill()
        if self.kind == "ok":
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(max(2.0, r / 14))
            cr.move_to(cx - s * 0.4, cy + s * 0.05)
            cr.line_to(cx - s * 0.08, cy + s * 0.4)
            cr.line_to(cx + s * 0.45, cy - s * 0.3)
            cr.stroke()
        return False


def _nice_ceiling(value: float) -> float:
    """Round a byte rate up so that quarter ticks are round numbers in KB/MB."""
    value = max(value, 1024.0)
    unit = 1.0
    while value / unit >= 1000 and unit < 1024 ** 3:
        unit *= 1024
    for step in (1, 2, 4, 8, 10, 20, 40, 80, 100, 200, 400, 800, 1000):
        if step * unit >= value:
            return step * unit
    return 1024 * unit


class TrafficChart(Gtk.DrawingArea):
    """Download/upload history with a labelled axis and a legend."""

    SECONDS = 120

    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 190)
        self.rx = deque([0.0] * self.SECONDS, maxlen=self.SECONDS)
        self.tx = deque([0.0] * self.SECONDS, maxlen=self.SECONDS)
        self.connect("draw", self._draw)

    def push(self, rx: float, tx: float) -> None:
        self.rx.append(rx)
        self.tx.append(tx)
        self.queue_draw()

    def clear(self) -> None:
        self.rx.extend([0.0] * self.SECONDS)
        self.tx.extend([0.0] * self.SECONDS)
        self.queue_draw()

    def _text(self, cr, text, x, y, size=8.5, alpha=0.6, align_right=False, color=None):
        layout = PangoCairo.create_layout(cr)
        desc = self.get_style_context().get_font(Gtk.StateFlags.NORMAL).copy()
        desc.set_size(int(size * Pango.SCALE))
        layout.set_font_description(desc)
        layout.set_text(text, -1)
        w, h = layout.get_pixel_size()
        if color:
            cr.set_source_rgba(color[0], color[1], color[2], 1.0)
        else:
            fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
        cr.move_to(x - w if align_right else x, y - h / 2.0)
        PangoCairo.show_layout(cr, layout)
        return w

    def _draw(self, widget, cr) -> bool:
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        fg = widget.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        left, right, top, bottom = 64, 8, 26, 20
        pw, ph = width - left - right, height - top - bottom
        if pw <= 10 or ph <= 10:
            return False

        # the scale follows the peak of the visible window, so it rarely jumps
        scale = _nice_ceiling(max(max(self.rx), max(self.tx)))

        for i in range(5):
            y = top + ph * i / 4.0
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08 if i < 4 else 0.2)
            cr.rectangle(left, round(y), pw, 1)
            cr.fill()
            self._text(cr, _bytes(scale * (4 - i) / 4.0) + "/s", left - 8, y, align_right=True)
        self._text(cr, _("2 min ago"), left, height - bottom / 2.0 + 2, alpha=0.45)
        self._text(cr, _("now"), width - right, height - bottom / 2.0 + 2, alpha=0.45,
                   align_right=True)

        n = len(self.rx)
        step = pw / float(n - 1)
        for series, color in ((self.rx, COLORS["ok"]), (self.tx, COLORS["busy"])):
            pts = [(left + i * step, top + ph - ph * min(v / scale, 1.0))
                   for i, v in enumerate(series)]
            cr.move_to(*pts[0])
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                mx = (x0 + x1) / 2.0
                cr.curve_to(mx, y0, mx, y1, x1, y1)
            path = cr.copy_path()
            cr.line_to(left + pw, top + ph)
            cr.line_to(left, top + ph)
            cr.close_path()
            cr.set_source_rgba(color[0], color[1], color[2], 0.14)
            cr.fill()
            cr.append_path(path)
            cr.set_source_rgb(*color)
            cr.set_line_width(2.0)
            cr.stroke()

        x = width - right
        for label, color in ((_("Upload"), COLORS["busy"]), (_("Download"), COLORS["ok"])):
            w = self._text(cr, label, x, 10, size=9, alpha=0.8, align_right=True)
            x -= w + 6
            cr.set_source_rgb(*color)
            cr.arc(x - 4, 10, 4, 0, 2 * math.pi)
            cr.fill()
            x -= 22
        return False


class StatTile(Gtk.Box):
    """Small card with a caption and a large value."""

    def __init__(self, caption: str, icon: str, css: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.get_style_context().add_class("kvp-tile")
        top = Gtk.Box(spacing=6)
        img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        img.get_style_context().add_class("dim-label")
        top.pack_start(img, False, False, 0)
        cap = Gtk.Label(label=caption, xalign=0)
        cap.get_style_context().add_class("kvp-tile-caption")
        top.pack_start(cap, False, False, 0)
        self.value = Gtk.Label(label="—", xalign=0)
        self.value.get_style_context().add_class("kvp-tile-value")
        if css:
            self.value.get_style_context().add_class(css)
        self.pack_start(top, False, False, 0)
        self.pack_start(self.value, False, False, 0)

    def set(self, text: str) -> None:
        self.value.set_text(text or "—")


class InfoGrid(Gtk.Grid):
    """Label/value rows with selectable values."""

    def __init__(self):
        super().__init__(column_spacing=18, row_spacing=6)
        self._rows = {}

    def add_row(self, key: str, title: str) -> Gtk.Label:
        row = len(self._rows)
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("dim-label")
        v = Gtk.Label(label="—", xalign=0, selectable=True)
        v.set_ellipsize(Pango.EllipsizeMode.END)
        self.attach(t, 0, row, 1, 1)
        self.attach(v, 1, row, 1, 1)
        self._rows[key] = (t, v)
        return v

    def set(self, key: str, value: str) -> None:
        self._rows[key][1].set_text(value or "—")

    def show_row(self, key: str, visible: bool) -> None:
        for w in self._rows[key]:
            w.set_visible(visible)
            w.set_no_show_all(not visible)


def card(child: Gtk.Widget, title: Optional[str] = None,
         extra: Optional[Gtk.Widget] = None) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.get_style_context().add_class("kvp-card")
    if title or extra:
        head = Gtk.Box(spacing=8)
        lbl = Gtk.Label(label=title or "", xalign=0)
        lbl.get_style_context().add_class("kvp-card-title")
        head.pack_start(lbl, True, True, 0)
        if extra:
            head.pack_end(extra, False, False, 0)
        box.pack_start(head, False, False, 0)
    box.pack_start(child, True, True, 0)
    return box


def page_header(title: str, subtitle: str = "") -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    t = Gtk.Label(label=title, xalign=0)
    t.get_style_context().add_class("kvp-page-title")
    box.pack_start(t, False, False, 0)
    if subtitle:
        s = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        s.get_style_context().add_class("dim-label")
        box.pack_start(s, False, False, 0)
    return box


def icon_button(icon: str, tooltip: str, callback=None) -> Gtk.Button:
    btn = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    btn.set_tooltip_text(tooltip)
    btn.set_valign(Gtk.Align.CENTER)
    if callback:
        btn.connect("clicked", lambda _b: callback())
    return btn


def message(parent: Optional[Gtk.Window], title: str, detail: str = "",
            kind: Gtk.MessageType = Gtk.MessageType.ERROR) -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                            buttons=Gtk.ButtonsType.CLOSE, text=title)
    if detail:
        dlg.format_secondary_text(detail)
    dlg.run()
    dlg.destroy()


def confirm(parent: Optional[Gtk.Window], title: str, detail: str, ok_label: str,
            destructive: bool = False) -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=Gtk.MessageType.QUESTION, text=title)
    dlg.format_secondary_text(detail)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(ok_label, Gtk.ResponseType.OK)
    ok.get_style_context().add_class("destructive-action" if destructive else "suggested-action")
    dlg.set_default_response(Gtk.ResponseType.CANCEL)
    res = dlg.run()
    dlg.destroy()
    return res == Gtk.ResponseType.OK
