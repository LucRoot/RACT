from __future__ import annotations


"""Terminal UI helpers for RACT.

LR:: RACT is a terminal-first tool, so the terminal experience is part of the
product. This module wraps Rich so every command feels branded, readable, and
intentionally not boring. Colors are auto-detected; set NO_COLOR=1 to disable.
"""

import os
import sys
from typing import Any

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table


_PLAIN = False


def set_plain(on: bool = True) -> None:
    """Turn plain mode on for this process (``--plain``, B-041b)."""
    global _PLAIN
    _PLAIN = on


def plain_mode() -> bool:
    """True for ``--plain`` or ``TERM=dumb``: labels, no color, no boxes."""
    return _PLAIN or os.environ.get("TERM", "") == "dumb"


def _reconfigure_utf8() -> None:
    """Force stdout/stderr to UTF-8 so branded Unicode renders everywhere.

    LR:: Windows legacy consoles default to cp1252 and choke on box-drawing
    characters. Reconfiguring to UTF-8 with replacement keeps output flowing
    even if the terminal cannot display every glyph.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def stdin_is_terminal() -> bool:
    """True when stdin is a terminal a person can answer at.

    LR:: On Windows ``isatty()`` is also True for the NUL device, so a run
    started with stdin from NUL (a script, a test, ``< NUL``) looked like a
    terminal and asked a question nobody could answer (B-101). There a
    console handle is the test: ``GetConsoleMode`` succeeds only for one.
    """
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError, AttributeError):
        return False
    mode = wintypes.DWORD()
    return bool(
        ctypes.windll.kernel32.GetConsoleMode(
            wintypes.HANDLE(handle), ctypes.byref(mode)
        )
    )


def terminal_width() -> int:
    """The columns a line should fit: the terminal, between 40 and 80 (B-041c)."""
    import shutil

    return max(40, min(80, shutil.get_terminal_size((80, 24)).columns))


class RactConsole:
    """Branded console for RACT CLI output."""

    BRAND_GOLD = "#D4AF37"
    BRAND_BLUE = "#1E90FF"
    BRAND_RED = "#FF4C4C"
    BRAND_GREEN = "#32CD32"
    BRAND_AMBER = "#FFBF00"
    USER_INPUT = "#00CED1"  # cyan — anything the user typed/entered
    DIRECT_OUTPUT = "#DA70D6"  # orchid — direct system-to-user communication

    def __init__(self) -> None:
        _reconfigure_utf8()
        # Respect NO_COLOR (an empty value counts as unset); otherwise let Rich
        # detect terminal capabilities.
        self._color = not os.environ.get("NO_COLOR", "").strip() and not plain_mode()
        self._build()

    def _build(self) -> None:
        kwargs: dict[str, Any] = {
            "color_system": "auto" if self._color else None,
            # Wrap at word boundaries to the terminal width. soft_wrap=True let
            # long lines break in the middle of a word (B-041c).
            "soft_wrap": False,
            "highlight": False,
            "legacy_windows": False,
        }
        self._console = Console(**kwargs)
        self._stderr_console = Console(stderr=True, **kwargs)

    @property
    def color_enabled(self) -> bool:
        return self._color

    def disable_color(self) -> None:
        """Turn color off for the rest of the process (``--no-color``, B-041a)."""
        self._color = False
        self._build()

    @property
    def console(self) -> Console:
        return self._console

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._console.print(*args, **kwargs)

    # B-185: every message is text, never markup. "[line 3]" in a message was
    # read as a style and deleted, and "[/bold]" raised MarkupError.

    def info(self, message: str) -> None:
        self._console.print(f"[bold {self.BRAND_BLUE}][ract][/] {escape(message)}")

    def success(self, message: str) -> None:
        self._console.print(
            f"[bold {self.BRAND_GREEN}]✓[/] [bold {self.BRAND_BLUE}][ract][/] {escape(message)}"
        )

    def warning(self, message: str) -> None:
        self._console.print(
            f"[bold {self.BRAND_AMBER}]⚠[/] [bold {self.BRAND_BLUE}][ract][/] {escape(message)}"
        )

    def error(self, message: str) -> None:
        self._stderr_console.print(
            f"[bold {self.BRAND_RED}]✗[/] [bold {self.BRAND_BLUE}][ract][/] {escape(message)}"
        )

    def user_input(self, label: str, value: str) -> None:
        """Highlight text that originated from the user."""
        self._console.print(
            f"[bold {self.BRAND_BLUE}][ract][/] {escape(label)}: "
            f"[italic {self.USER_INPUT}]{escape(value)}[/]"
        )

    def direct(self, message: str) -> None:
        """Direct system-to-user communication in a unique color."""
        self._console.print(f"[bold {self.DIRECT_OUTPUT}]▸ {escape(message)}[/]")

    def panel(self, title: str, content: str, style: str = "") -> None:
        style = style or f"bold {self.BRAND_GOLD}"
        self._console.print(
            Panel(
                content,
                title=f"[bold]{title}[/]",
                border_style=style,
                title_align="left",
                box=self._box() or box.ROUNDED,
            )
        )

    def rule(self, title: str = "") -> None:
        self._console.print(
            Rule(title=title, style=self.BRAND_GOLD, characters=self._rule_chars())
        )

    def clear_screen(self) -> None:
        """Clear the terminal. With color off, a blank line instead (B-041a)."""
        if self._color:
            self._console.print("\033[2J\033[H", end="")
        else:
            self._console.print()

    def _box(self) -> box.Box | None:
        """Plain ``+ - |`` borders when color is off, Rich's default otherwise."""
        return None if self._color else box.ASCII

    def _rule_chars(self) -> str:
        return "─" if self._color else "-"

    def table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        table = Table(
            title=title,
            title_style=f"bold {self.BRAND_GOLD}",
            box=self._box() or box.HEAVY_HEAD,
        )
        for col in columns:
            table.add_column(col, overflow="fold")
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        # Rich falls back to 80 columns on a dumb terminal; the table fits the real width (package A).
        self._console.print(table, width=terminal_width())

    def _logo(self, version: str) -> str:
        """Return the colorized ASCII Root-Knot logo."""
        g = f"bold {self.BRAND_GOLD}"
        return (
            f"[{g}]        ╭──────────────────────────────────╮[/]\n"
            f"[{g}]        │[/]  [bold {self.BRAND_GOLD}]R[/][bold {self.BRAND_BLUE}]A[/][bold {self.BRAND_GREEN}]C[/][bold {self.BRAND_AMBER}]T[/]"
            f"  · Agentic Coding Tool      [{g}]│[/]\n"
            f"[{g}]        ╰──────────────────┬───────────────╯[/]\n"
            f"[{g}]                           │[/]\n"
            f"[{g}]        ╭──────────────────┴───────────────╮[/]\n"
            f"[{g}]        │[/]         [bold {self.BRAND_GOLD}]✦  Claim & Verify  ✦[/]         [{g}]│[/]\n"
            f"[{g}]        ╰──────────────────────────────────╯[/]\n"
            f"[{g}]        [/][italic]Every plan Rooted. Every assumption explicit.[/]"
        )

    def welcome(self, version: str) -> None:
        """Print the RACT welcome letter."""
        if plain_mode():
            # No logo and no panel: plain lines a screen reader reads in order.
            self._console.print(f"RACT {version}, by Dr. Lucas Root, Ph.D.")
            self._console.print("License: PolyForm Noncommercial License 1.0.0")
            self._console.print("Type an intent, or /help for commands.")
            return
        body = (
            f"[bold {self.BRAND_BLUE}]Version:[/] {version}\n"
            f"[bold {self.BRAND_BLUE}]Author:[/] Dr. Lucas Root, Ph.D.\n"
            f"[bold {self.BRAND_BLUE}]License:[/] PolyForm Noncommercial License 1.0.0\n"
            "\n"
            "RACT keeps the human in the loop while a small management LM routes work "
            "to the right provider. Every plan is Rooted to the assumption that justifies it, "
            "and every generated change is validated by tests before it compounds.\n"
            "\n"
            "[italic]Quick commands:[/]\n"
            "  [bold]ract setup[/]                      · check this machine and write ract.yaml\n"
            "  [bold]ract run 'your intent' --loop[/]   · run a quality-anchored build loop\n"
            "  [bold]ract report --last[/]              · see what changed and why\n"
            "  [bold]ract whisper --intent '...'[/]     · get a codebase dialect brief\n"
            "  [bold]ract auction list[/]               · review dead-code candidates\n"
            "  [bold]ract fence inspect --file f.py[/]  · ask why legacy code exists\n"
            "\n"
            "[italic]Set NO_COLOR=1 to disable styling.[/]"
        )

        self._console.print(self._logo(version))
        self._console.print()
        self.panel("Welcome to RACT", body)


# Global branded console instance.
console = RactConsole()
# RACT 0.1.1 - Trust and tooling
