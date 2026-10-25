#!/usr/bin/env python3
"""Render the GitHub social preview image (1280x640) from the dark dashboard screenshot.

Usage: python3 tools/social_preview.py docs/screenshots/dashboard-dark.png docs/social-preview.png
"""

import math
import os
import sys

import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gdk", "3.0")
import cairo  # noqa: E402
from gi.repository import Gdk, GdkPixbuf, Pango, PangoCairo  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1280, 640


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def text(cr, markup, x, y, size, weight="normal", alpha=1.0, width=None):
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription("Sans %s %d" % (weight, size))
    layout.set_font_description(desc)
    if width:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD)
    layout.set_markup(markup, -1)
    cr.set_source_rgba(1, 1, 1, alpha)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)
    return layout.get_pixel_size()[1]


def main(shot, out):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surface)

    grad = cairo.LinearGradient(0, 0, W, H)
    grad.add_color_stop_rgb(0, 0.06, 0.09, 0.16)
    grad.add_color_stop_rgb(1, 0.08, 0.22, 0.42)
    cr.set_source(grad)
    cr.paint()
    glow = cairo.RadialGradient(1050, 120, 10, 1050, 120, 560)
    glow.add_color_stop_rgba(0, 0.23, 0.56, 0.94, 0.35)
    glow.add_color_stop_rgba(1, 0.23, 0.56, 0.94, 0.0)
    cr.set_source(glow)
    cr.paint()

    # screenshot card on the right, slightly cropped
    img = GdkPixbuf.Pixbuf.new_from_file(shot)
    scale = 640.0 / img.get_width()
    sw, sh = 640, int(img.get_height() * scale)
    x0, y0 = 600, 70
    cr.save()
    cr.set_source_rgba(0, 0, 0, 0.45)
    rounded(cr, x0 + 10, y0 + 16, sw, sh, 14)
    cr.fill()
    rounded(cr, x0, y0, sw, sh, 14)
    cr.clip()
    cr.translate(x0, y0)
    cr.scale(scale, scale)
    Gdk.cairo_set_source_pixbuf(cr, img, 0, 0)
    cr.paint()
    cr.restore()

    logo = GdkPixbuf.Pixbuf.new_from_file_at_size(
        os.path.join(ROOT, "data", "icons", "kerio-vpn.svg"), 96, 96)
    Gdk.cairo_set_source_pixbuf(cr, logo, 64, 78)
    cr.paint()

    y = 196
    y += text(cr, "Kerio VPN", 64, y, 46, "Bold") + 6
    y += text(cr, "Kerio Control VPN Client GUI for Linux", 64, y, 19, alpha=0.85,
              width=500) + 26
    for item in ("One-click connect &amp; profiles", "Split tunneling &amp; kill switch",
                 "Live traffic, routes &amp; logs", "Ubuntu · Debian · Linux Mint"):
        cr.set_source_rgb(0.18, 0.69, 0.38)
        cr.arc(72, y + 13, 5, 0, 2 * math.pi)
        cr.fill()
        y += text(cr, item, 90, y, 16, alpha=0.92) + 10
    text(cr, "Free &amp; open source  ·  GPL-3.0", 64, H - 70, 13, alpha=0.6)

    surface.write_to_png(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots/dashboard-dark.png",
         sys.argv[2] if len(sys.argv) > 2 else "docs/social-preview.png")
