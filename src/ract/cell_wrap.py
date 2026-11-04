"""Word wrap by terminal columns, not characters (package I).

``textwrap`` counts characters, so a line of East Asian wide characters (two columns
each) or of emoji ran past the terminal's width. This wrap measures with
``rich.cells.cell_len``: a wide character is two columns, a combining mark is none.
A break is never placed before a zero-width character, so a mark stays with its base.
Words that do not fit are split character by character, never cut mid-column.

B-184: a space followed by a combining mark is the mark's base, so it stays
with the word before it and no line starts with the mark. ``wrap_exact`` is
for text the operator approves (code, a diff, a command, a path): every
character is kept, and a line breaks only where it would pass the width.
"""

from __future__ import annotations

from rich.cells import cell_len


def _zero_width(ch: str) -> bool:
    return cell_len(ch) == 0 and not ch.isspace()


def _clusters(text: str) -> list[str]:
    """``text`` as pieces that are never split: a character with its zero-width marks.

    A space followed by a mark is that mark's base; it joins the piece before
    it, so a break never lands between the two.
    """
    out: list[str] = []
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if out and (_zero_width(ch) or (ch.isspace() and nxt and _zero_width(nxt))):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _words(text: str) -> list[str]:
    """The words of ``text``; a space before a mark stays in the word before it."""
    words: list[str] = []
    current = ""
    for i, ch in enumerate(text):
        if not ch.isspace():
            current += ch
            continue
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if nxt and _zero_width(nxt):
            if current:
                current += ch
            elif words:
                words[-1] += ch
            else:
                current = ch
            continue
        if current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    return words


def wrap_exact(
    text: str, width: int, *, subsequent_indent: str | None = None
) -> list[str]:
    """``text`` cut into lines of at most ``width`` columns, every character kept (B-184).

    Runs of spaces and leading spaces stay; a tab is shown as ``\\t``. A line
    breaks only where it would pass the width: after its last space when that
    leaves the words whole (the space stays at the end of the line), else at
    the width, never inside a character and its marks. Continuation lines
    start with ``subsequent_indent``, by default the text's own leading spaces
    (at most half the width), so code stays aligned.
    """
    text = text.replace("\t", "\\t")
    if subsequent_indent is None:
        lead = len(text) - len(text.lstrip(" "))
        subsequent_indent = " " * lead
    if cell_len(subsequent_indent) > max(width // 2, 0):
        subsequent_indent = " " * max(width // 2, 0)
    lines: list[str] = []
    line = ""
    for piece in _clusters(text):
        base = subsequent_indent if lines else ""
        # A line holds something past its indent before it may break.
        if line != base and cell_len(line) + cell_len(piece) > width:
            cut = line.rfind(" ")
            while cut > 0 and cut + 1 < len(line) and _zero_width(line[cut + 1]):
                cut = line.rfind(" ", 0, cut)  # a space carrying a mark is not a break
            if (
                cut >= len(base)
                and line[len(base) : cut].strip()
                and not piece.isspace()
            ):
                lines.append(line[: cut + 1])
                line = subsequent_indent + line[cut + 1 :]
            else:
                lines.append(line)
                line = subsequent_indent
            if line != subsequent_indent and cell_len(line) + cell_len(piece) > width:
                lines.append(line)
                line = subsequent_indent
        line += piece
    lines.append(line)
    return lines


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
    for word in _words(text):
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
        for ch in _clusters(word):
            if filled and cell_len(line) + cell_len(ch) > width:
                lines.append(line)
                line = subsequent_indent
                filled = False
            line += ch
            filled = True
    if filled or not lines:
        lines.append(line)
    return lines
