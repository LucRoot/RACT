"""The named colour styles for the screens (B-179, first slice): sixteen colours, off without a terminal.

Pure: no environment read on import; the caller passes the environment and whether the output is a
terminal. ``NO_COLOR`` set to any value turns colour off, and an empty value counts as unset (the rule
``ract.tui`` already follows). Colour is never the only signal: every styled word is also in the plain
text, so a screen read without colour says the same thing. Text from a model passes through
``visible_text`` before it is styled, so nothing it writes can carry an escape sequence.
"""

from __future__ import annotations

from collections.abc import Mapping

from ract.session_events import visible_text

# Named styles, as SGR codes from the sixteen basic colours and the bold and dim attributes.
STYLES: dict[str, str] = {
    "success": "32",  # green
    "warning": "33",  # yellow
    "error": "31",  # red
    "model": "2",  # dim: text a model wrote
    "request": "1",  # bold: an approval request
    "path": "36",  # cyan
    "command": "35",  # magenta
}
RESET = "\x1b[0m"


def colour_on(env: Mapping[str, str], is_terminal: bool) -> bool:
    """True when styles should be written: a terminal, and NO_COLOR is unset or empty."""
    if not is_terminal:
        return False
    return not env.get("NO_COLOR", "").strip()


def paint(text: str, style: str, *, on: bool) -> str:
    """``text`` in the named style when colour is on; the same text otherwise. An unknown style is plain."""
    code = STYLES.get(style)
    if not on or code is None:
        return text
    return f"\x1b[{code}m{text}{RESET}"


def model_text(text: str, *, on: bool) -> str:
    """Text a model wrote: control characters shown as escapes, then dimmed when colour is on."""
    return paint(visible_text(text), "model", on=on)
