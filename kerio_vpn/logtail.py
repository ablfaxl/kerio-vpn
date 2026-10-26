"""Dependency-free log follower shared by the GTK UI and CLI."""

from __future__ import annotations

import os
from typing import List, Optional

MAX_READ_PER_TICK = 8 * 1024 * 1024


class LogTail:
    def __init__(self, path: str):
        self.path = path
        self.inode: Optional[int] = None
        self.offset = 0
        self._partial = b""
        self.readable = True

    def _stat(self):
        try:
            st = os.stat(self.path)
            return st.st_ino, st.st_size
        except OSError:
            return None, 0

    def initial(self, tail_bytes: int) -> List[str]:
        inode, size = self._stat()
        self.inode = inode
        self.offset = max(0, size - tail_bytes)
        lines = self.read_new()
        if self.offset and lines and size > tail_bytes:
            lines = lines[1:]
        return lines

    def read_new(self) -> List[str]:
        inode, size = self._stat()
        if inode is None:
            self.readable = os.path.exists(os.path.dirname(self.path))
            return []
        if inode != self.inode or size < self.offset:
            self.inode, self.offset, self._partial = inode, 0, b""
        if size == self.offset:
            return []
        if size - self.offset > MAX_READ_PER_TICK:
            self.offset = size - MAX_READ_PER_TICK
            self._partial = b""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read(size - self.offset)
            self.readable = True
        except PermissionError:
            self.readable = False
            return []
        except OSError:
            return []
        self.offset += len(data)
        data = self._partial + data
        parts = data.split(b"\n")
        self._partial = parts.pop()
        return [p.decode("utf-8", errors="replace") for p in parts if p]
