"""Live log viewer for debug.log, error.log and the systemd journal."""

from __future__ import annotations

import os
import threading
import time
from typing import List

from gi.repository import GLib, Gtk

from .. import kvc, system
from ..i18n import _
from ..logparse import LogLine, parse_line
from ..monitor import Monitor

SOURCE_DEBUG = "debug"
SOURCE_ERROR = "error"
SOURCE_JOURNAL = "journal"


class LogsPage(Gtk.Box):
    def __init__(self, monitor: Monitor, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.monitor = monitor
        self.settings = settings
        self.source = SOURCE_DEBUG
        self.paused = False
        self._filter = ""
        self._pending: List[LogLine] = []

        bar = Gtk.Box(spacing=6, border_width=8)
        self.source_combo = Gtk.ComboBoxText()
        self.source_combo.append(SOURCE_DEBUG, _("Activity (debug.log)"))
        self.source_combo.append(SOURCE_ERROR, _("Errors (error.log)"))
        self.source_combo.append(SOURCE_JOURNAL, _("Service journal"))
        self.source_combo.set_active_id(SOURCE_DEBUG)
        self.source_combo.connect("changed", self._on_source)
        bar.pack_start(self.source_combo, False, False, 0)

        self.search = Gtk.SearchEntry(placeholder_text=_("Filter…"))
        self.search.connect("search-changed", self._on_search)
        bar.pack_start(self.search, True, True, 0)

        self.noise = Gtk.CheckButton(label=_("Hide packet noise"))
        self.noise.set_active(settings.log_hide_noise)
        self.noise.set_tooltip_text(_("Hide per-packet and polling messages"))
        self.noise.connect("toggled", self._on_noise)
        bar.pack_start(self.noise, False, False, 0)

        self.follow = Gtk.ToggleButton()
        self.follow.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic",
                                                           Gtk.IconSize.BUTTON))
        self.follow.set_tooltip_text(_("Pause live updates"))
        self.follow.connect("toggled", self._on_pause)
        bar.pack_start(self.follow, False, False, 0)

        for icon, tip, cb in (("view-refresh-symbolic", _("Reload"), self.reload),
                              ("edit-copy-symbolic", _("Copy all"), self._copy),
                              ("document-save-symbolic", _("Save to file…"), self._save),
                              ("folder-open-symbolic", _("Open log folder"), self._open_dir)):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, f=cb: f())
            bar.pack_start(b, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=8,
                                 right_margin=8, top_margin=6, bottom_margin=6)
        self.view.get_style_context().add_class("kvp-log")
        buf = self.view.get_buffer()
        buf.create_tag("ts", foreground="#888888")
        buf.create_tag("src", foreground="#7a7fd6")
        buf.create_tag("error", foreground="#db3838", weight=700)
        buf.create_tag("warning", foreground="#d98a10")
        buf.create_tag("info", foreground="#2eaf61")
        buf.create_tag("debug")
        self._end_mark = buf.create_mark("end", buf.get_end_iter(), False)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.add(self.view)
        self.pack_start(scroller, True, True, 0)

        self.status = Gtk.Label(xalign=0, margin=6)
        self.status.get_style_context().add_class("dim-label")
        self.pack_start(self.status, False, False, 0)

        monitor.connect("log-lines", self._on_lines)
        monitor.connect("error-lines", self._on_error_lines)
        self.connect("map", lambda _w: self.reload())

    # ------------------------------------------------------------ rendering
    def _matches(self, line: LogLine) -> bool:
        if self.noise.get_active() and line.noisy:
            return False
        return not self._filter or self._filter in line.raw.lower()

    def _append(self, lines: List[LogLine]) -> None:
        buf = self.view.get_buffer()
        for line in lines:
            if not self._matches(line):
                continue
            it = buf.get_end_iter()
            if line.ts:
                buf.insert_with_tags_by_name(
                    it, time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime(line.ts)), "ts")
            if line.source:
                buf.insert_with_tags_by_name(buf.get_end_iter(), "%-9s " % line.source, "src")
            buf.insert_with_tags_by_name(buf.get_end_iter(), line.message + "\n", line.level)
        overflow = buf.get_line_count() - self.settings.log_max_lines
        if overflow > 0:
            buf.delete(buf.get_start_iter(), buf.get_iter_at_line(overflow))
        if not self.paused:
            GLib.idle_add(self._scroll_end)
        self.status.set_text(_("%d lines") % max(0, buf.get_line_count() - 1))

    def _scroll_end(self) -> bool:
        buf = self.view.get_buffer()
        buf.move_mark(self._end_mark, buf.get_end_iter())
        self.view.scroll_to_mark(self._end_mark, 0, False, 0, 1)
        return False

    def _set_lines(self, lines: List[LogLine]) -> None:
        self.view.get_buffer().set_text("")
        self._append(lines[-self.settings.log_max_lines:])

    def reload(self) -> None:
        if self.source == SOURCE_DEBUG:
            lines = self.monitor.recent_lines(include_noise=not self.noise.get_active())
            if not lines and not os.access(kvc.DEBUG_LOG, os.R_OK):
                self._notice(_("The log file %s is not readable by your user.") % kvc.DEBUG_LOG)
                return
            self._set_lines(lines)
        elif self.source == SOURCE_ERROR:
            self._set_lines([parse_line(r) for r in list(self.monitor.error_lines)])
        else:
            self._notice(_("Loading journal…"))
            threading.Thread(target=self._load_journal, daemon=True).start()

    def _notice(self, text: str) -> None:
        self.view.get_buffer().set_text(text + "\n")
        self.status.set_text("")

    def _load_journal(self) -> None:
        if system.has_systemd():
            rc, out, err = system.run(["journalctl", "-u", kvc.SERVICE, "-n", "500",
                                       "--no-pager", "-o", "short-iso"], timeout=10)
        else:
            rc, out, err = 1, "", _("The systemd journal is not available.")
        lines = [LogLine(raw=r, ts=None, source="", message=r) for r in out.splitlines()]
        if rc != 0 and not lines:
            lines = [LogLine(raw=err, ts=None, source="", message=err.strip())]
        GLib.idle_add(self._set_lines, lines)

    # ------------------------------------------------------------ events
    def _on_lines(self, _m, lines: List[LogLine]) -> None:
        if self.source != SOURCE_DEBUG or not self.get_mapped():
            return
        if self.paused:
            self._pending.extend(lines)
            del self._pending[:-self.settings.log_max_lines]
            return
        self._append(lines)

    def _on_error_lines(self, _m, raw: List[str]) -> None:
        if self.source == SOURCE_ERROR and self.get_mapped() and not self.paused:
            self._append([parse_line(r) for r in raw])

    def _on_source(self, combo) -> None:
        self.source = combo.get_active_id()
        self.noise.set_sensitive(self.source == SOURCE_DEBUG)
        self.reload()

    def _on_search(self, entry) -> None:
        self._filter = entry.get_text().strip().lower()
        self.reload()

    def _on_noise(self, btn) -> None:
        self.settings.log_hide_noise = btn.get_active()
        self.settings.save()
        self.reload()

    def _on_pause(self, btn) -> None:
        self.paused = btn.get_active()
        if not self.paused and self._pending:
            pending, self._pending = self._pending, []
            self._append(pending)

    def _text(self) -> str:
        buf = self.view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _copy(self) -> None:
        from gi.repository import Gdk
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._text(), -1)

    def _save(self) -> None:
        dlg = Gtk.FileChooserNative.new(_("Save log"), self.get_toplevel(),
                                        Gtk.FileChooserAction.SAVE, _("Save"), _("Cancel"))
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name("kerio-vpn-%s-%s.log" % (self.source, time.strftime("%Y%m%d-%H%M%S")))
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            with open(dlg.get_filename(), "w", encoding="utf-8") as f:
                f.write(self._text())
        dlg.destroy()

    def _open_dir(self) -> None:
        Gtk.show_uri_on_window(self.get_toplevel(), "file://" + kvc.LOG_DIR, Gtk.get_current_event_time())
