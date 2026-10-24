"""User-visible strings. The application is English only; `_` marks UI text."""

from __future__ import annotations


def _(message: str) -> str:
    return message


def ngettext(singular: str, plural: str, n: int) -> str:
    return singular if n == 1 else plural
