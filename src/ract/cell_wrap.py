"""Word wrap by terminal columns, not characters (package I).

``textwrap`` counts characters, so a line of East Asian wide characters (two columns
each) or of emoji ran past the terminal's width. This wrap measures with
``rich.cells.cell_len``: a wide character is two columns, a combining mark is none.
A break is never placed before a zero-width character, so a mark stays with its base.
Words that do not fit are split character by character, never cut mid-column.
"""

from __future__ import annotations

from rich.cells import cell_len


def wrap_cells(
    text: str,
    width: int,
    *,
    initial_indent: str = "",
    subsequent_indent: str = "",
) -> list[str]:
    """``text`` as lines of at most ``width`` terminal columns, words kept whole where they fit.

    An indent wider than half the width is dropped to half the width, so the text
    always has room to wrap.
    """
    limit = max(width // 2, 0)
    if cell_len(initial_indent) > limit:
        initial_indent = " " * limit
    if cell_len(subsequent_indent) > limit:
        subsequent_indent = " " * limit
    lines: list[str] = []
    line = initial_indent
    filled = False
    for word in text.split():
        if filled:
            candidate = line + " " + word
            if cell_len(candidate) <= width:
                line = candidate
                continue
            lines.append(line)
            line = subsequent_indent
            filled = False
        if cell_len(line + word) <= width:
            line += word
            filled = True
            continue
        for ch in word:
            if filled and cell_len(line) + cell_len(ch) > width:
                lines.append(line)
                line = subsequent_indent
                filled = False
            line += ch
            filled = True
    if filled or not lines:
        lines.append(line)
    return lines
