# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Terminal UI helpers for RACT.

LR:: RACT is a terminal-first tool, so the terminal experience is part of the
product. This module wraps Rich so every command feels branded, readable, and
intentionally not boring. Colors are auto-detected; set NO_COLOR=1 to disable.
"""

import os
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table


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
        # Respect NO_COLOR; otherwise let Rich detect terminal capabilities.
        no_color = os.environ.get("NO_COLOR", "").strip()
        kwargs: dict[str, Any] = {
            "color_system": None if no_color else "auto",
            "soft_wrap": True,
            "highlight": False,
            "legacy_windows": False,
        }
        self._console = Console(**kwargs)
        self._stderr_console = Console(stderr=True, **kwargs)

    @property
    def console(self) -> Console:
        return self._console

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._console.print(*args, **kwargs)

    def info(self, message: str) -> None:
        self._console.print(f"[bold {self.BRAND_BLUE}][rootact][/] {message}")

    def success(self, message: str) -> None:
        self._console.print(
            f"[bold {self.BRAND_GREEN}]✓[/] [bold {self.BRAND_BLUE}][rootact][/] {message}"
        )

    def warning(self, message: str) -> None:
        self._console.print(
            f"[bold {self.BRAND_AMBER}]⚠[/] [bold {self.BRAND_BLUE}][rootact][/] {message}"
        )

    def error(self, message: str) -> None:
        self._stderr_console.print(
            f"[bold {self.BRAND_RED}]✗[/] [bold {self.BRAND_BLUE}][rootact][/] {message}"
        )

    def user_input(self, label: str, value: str) -> None:
        """Highlight text that originated from the user."""
        self._console.print(
            f"[bold {self.BRAND_BLUE}][rootact][/] {label}: "
            f"[italic {self.USER_INPUT}]{value}[/]"
        )

    def direct(self, message: str) -> None:
        """Direct system-to-user communication in a unique color."""
        self._console.print(f"[bold {self.DIRECT_OUTPUT}]▸ {message}[/]")

    def panel(self, title: str, content: str, style: str = "") -> None:
        style = style or f"bold {self.BRAND_GOLD}"
        self._console.print(
            Panel(
                content,
                title=f"[bold]{title}[/]",
                border_style=style,
                title_align="left",
            )
        )

    def rule(self, title: str = "") -> None:
        self._console.print(Rule(title=title, style=self.BRAND_GOLD))

    def table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        table = Table(title=title, title_style=f"bold {self.BRAND_GOLD}")
        for col in columns:
            table.add_column(col, overflow="fold")
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self._console.print(table)

    def _logo(self, version: str) -> str:
        """Return the colorized ASCII Root-Knot logo."""
        g = f"bold {self.BRAND_GOLD}"
        return (
            f"[{g}]        ╭──────────────────────────────────╮[/]\n"
            f"[{g}]        │[/]  [bold {self.BRAND_GOLD}]R[/][bold {self.BRAND_BLUE}]o[/][bold {self.BRAND_GREEN}]o[/][bold {self.BRAND_AMBER}]t[/]"
            f" [bold {self.BRAND_GOLD}]K[/][bold {self.BRAND_BLUE}]n[/][bold {self.BRAND_GREEN}]o[/][bold {self.BRAND_AMBER}]t[/]"
            f"  · Agentic Coding Tool      [{g}]│[/]\n"
            f"[{g}]        ╰──────────────────┬───────────────╯[/]\n"
            f"[{g}]                           │[/]\n"
            f"[{g}]        ╭──────────────────┴───────────────╮[/]\n"
            f"[{g}]        │[/]         [bold {self.BRAND_GOLD}]✦  The Root Knot  ✦[/]          [{g}]│[/]\n"
            f"[{g}]        ╰──────────────────────────────────╯[/]\n"
            f"[{g}]        [/][italic]Every plan Rooted. Every file carries the Knot.[/]"
        )

    def welcome(self, version: str) -> None:
        """Print the RACT welcome letter."""
        body = (
            f"[bold {self.BRAND_BLUE}]Version:[/] {version}\n"
            f"[bold {self.BRAND_BLUE}]Author:[/] Dr. Lucas Root, Ph.D.\n"
            f"[bold {self.BRAND_BLUE}]License:[/] PolyForm Noncommercial License 1.0.0\n"
            "\n"
            "RACT keeps the human in the loop while a small management LM routes work "
            "to the right provider. Every plan is Rooted to the assumption that justifies it, "
            "and every generated file carries the Root Knot so unsigned work cannot compound.\n"
            "\n"
            "[italic]Quick commands:[/]\n"
            "  [bold]rootact --init-provider local[/]     · scaffold a project for a local model\n"
            "  [bold]rootact 'your intent' --loop[/]       · run a Root-Knot-anchored build loop\n"
            "  [bold]rootact report --last[/]              · see what changed and why\n"
            "  [bold]rootact whisper --intent '...'[/]     · get a codebase dialect brief\n"
            "  [bold]rootact auction list[/]               · review dead-code candidates\n"
            "  [bold]rootact fence inspect --file f.py[/]  · ask why legacy code exists\n"
            "\n"
            "[italic]Set NO_COLOR=1 to disable styling.[/]"
        )

        self._console.print(self._logo(version))
        self._console.print()
        self.panel("Welcome to RACT", body)


# Global branded console instance.
console = RactConsole()
# RACT 0.1.1 - Trust and tooling
