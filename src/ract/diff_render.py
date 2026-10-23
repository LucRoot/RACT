"""Draw a change as hunks (B-014a): a pure function of two texts.

No I/O, no Rich, no color. The inputs are file contents, so they are hostile:
every output line goes through ``safe_text``, and bidi controls, which
``safe_text`` does not cover, are replaced first. Output is deterministic.
"""

from __future__ import annotations

import difflib

from ract.session_events import safe_text

_NUL_WINDOW = 8192
_NEW_FILE_PREVIEW = 20
_EXACT_DIFF_LINES = 1_000
_MAX_DIFF_LINES = 5_000
_BIDI_CONTROLS = dict.fromkeys(
    map(ord, "؜‎‏‪‫‬‭‮⁦⁧⁨⁩"),
    "?",
)


def _clean(text: str) -> str:
    return safe_text(text.translate(_BIDI_CONTROLS))


def _lines(text: str) -> list[str]:
    if not text:
        return []
    body = text[:-1] if text.endswith("\n") else text
    return body.split("\n")


def _is_binary(text: str) -> bool:
    return "\x00" in text[:_NUL_WINDOW]


def _span(start: int, end: int) -> str:
    """A zero-based half-open range shown as a one-based inclusive range."""
    return f"{start + 1}-{end}"


def _row(gutter: int, number: int, marker: str, text: str) -> str:
    return f"{number:>{gutter}} {marker} {_clean(text)}"


def _fit(line: str, width: int) -> str:
    if len(line) <= width:
        return line
    return line[: max(width - 3, 0)] + "..."


def _finish(lines: list[str], width: int, max_lines: int) -> list[str]:
    fitted = [_fit(line, width) for line in lines]
    if len(fitted) > max_lines:
        rest = len(fitted) - max_lines
        return fitted[:max_lines] + [f"... {rest} more lines"]
    return fitted


def summarize(changes: list[tuple[str, int, int]]) -> str:
    """One line for a set of (path, lines added, lines removed) changes."""
    added = sum(a for _, a, _ in changes)
    removed = sum(r for _, _, r in changes)
    if not added and not removed:
        return "no changes"
    files = len(changes)
    noun = "file" if files == 1 else "files"
    return f"{files} {noun}, +{added} -{removed}"


def _file_level(path: str, old: str | None, new: str | None) -> list[str]:
    text = new if old is None else old
    marker = "+" if old is None else "-"
    kind = "new file" if old is None else "deleted file"
    lines = _lines(text)
    gutter = len(str(max(len(lines), 1)))
    out = [f"{path}: {kind}, {len(lines)} lines"]
    out += [
        _row(gutter, number, marker, line)
        for number, line in enumerate(lines[:_NEW_FILE_PREVIEW], start=1)
    ]
    if len(lines) > _NEW_FILE_PREVIEW:
        out.append(f"... {len(lines) - _NEW_FILE_PREVIEW} more lines")
    return out


def _line_ending_change(old: str, new: str) -> str | None:
    if old.replace("\r\n", "\n") != new.replace("\r\n", "\n"):
        return None
    if old == new:
        return None
    if "\r\n" in old and "\r\n" not in new:
        return "CRLF to LF"
    if "\r\n" in new and "\r\n" not in old:
        return "LF to CRLF"
    return "mixed"


def _opcodes(old: list[str], new: list[str], autojunk: bool) -> list[tuple]:
    """difflib opcodes, after the common head and tail lines are set aside (G-130).

    Trimming first keeps a single change in a long repetitive file from being
    matched as one large replace; only the changed middle is matched.
    """
    limit = min(len(old), len(new))
    head = 0
    while head < limit and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < limit - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    middle = difflib.SequenceMatcher(
        None,
        old[head : len(old) - tail],
        new[head : len(new) - tail],
        autojunk=autojunk,
    )
    ops: list[tuple] = []
    if head:
        ops.append(("equal", 0, head, 0, head))
    for tag, i1, i2, j1, j2 in middle.get_opcodes():
        ops.append((tag, i1 + head, i2 + head, j1 + head, j2 + head))
    if tail:
        ops.append(("equal", len(old) - tail, len(old), len(new) - tail, len(new)))
    return ops


class _Plan:
    """Opcodes in the shape difflib's own grouping expects."""

    def __init__(self, ops: list[tuple]) -> None:
        self._ops = ops

    def get_opcodes(self) -> list[tuple]:
        return self._ops

    def get_grouped_opcodes(self, context: int) -> list[list[tuple]]:
        return difflib.SequenceMatcher.get_grouped_opcodes(self, context)


def render_hunks(
    path: str,
    old: str | None,
    new: str | None,
    width: int = 80,
    context: int = 3,
    max_lines: int = 200,
) -> list[str]:
    """Draw the change from ``old`` to ``new`` as hunks, one header per hunk.

    ``None`` means the file does not exist on that side. Each hunk header reads
    ``path: lines a-b -> c-d, +x -y``; body lines carry a line-number gutter and
    a ``' '``, ``-`` or ``+`` marker. Output is cut to ``width`` columns and to
    ``max_lines`` lines, and the cut says how many lines it left out.
    """
    path = _clean(path)
    if any(t is not None and _is_binary(t) for t in (old, new)):
        size = len((new if new is not None else old or "").encode("utf-8", "replace"))
        return [f"{path}: binary file, {size} bytes"]
    if old is None or new is None:
        return _finish(_file_level(path, old, new), width, max_lines)
    if old == new:
        return []
    ending = _line_ending_change(old, new)
    if ending is not None:
        return [f"{path}: line endings changed ({ending})"]

    # Compare line by line with CRLF read as LF, so a real edit in a file whose
    # endings also differ shows only the edit.
    old_lines = _lines(old.replace("\r\n", "\n"))
    new_lines = _lines(new.replace("\r\n", "\n"))
    if max(len(old_lines), len(new_lines)) > _MAX_DIFF_LINES:
        # difflib is quadratic on repetitive input (G-117). Past the cap, say only
        # what the line counts show, and do not run the matcher at all.
        grew = len(new_lines) - len(old_lines)
        counts = f"+{max(grew, 0)} -{max(-grew, 0)} by line count"
        return _finish(
            [
                f"{path}: file too large to draw a diff: "
                f"{len(old_lines)} -> {len(new_lines)} lines; {counts}"
            ],
            width,
            max_lines,
        )
    # Exact matching for short files. Past _EXACT_DIFF_LINES, difflib's junk
    # heuristic keeps repetitive lines from making the match quadratic (G-117).
    longest = max(len(old_lines), len(new_lines))
    plan = _Plan(_opcodes(old_lines, new_lines, longest > _EXACT_DIFF_LINES))
    out: list[str] = []
    for group in plan.get_grouped_opcodes(context):
        first, last = group[0], group[-1]
        added = sum(
            j2 - j1 for tag, _, _, j1, j2 in group if tag in {"insert", "replace"}
        )
        removed = sum(
            i2 - i1 for tag, i1, i2, _, _ in group if tag in {"delete", "replace"}
        )
        out.append(
            f"{path}: lines {_span(first[1], last[2])} -> "
            f"{_span(first[3], last[4])}, +{added} -{removed}"
        )
        gutter = len(str(max(last[2], last[4], 1)))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [_row(gutter, k + 1, " ", old_lines[k]) for k in range(i1, i2)]
            if tag in {"delete", "replace"}:
                out += [_row(gutter, k + 1, "-", old_lines[k]) for k in range(i1, i2)]
            if tag in {"insert", "replace"}:
                out += [_row(gutter, k + 1, "+", new_lines[k]) for k in range(j1, j2)]
    if old and not old.endswith("\n"):
        out.append(f"{path}: old text has no newline at end of file")
    if new and not new.endswith("\n"):
        out.append(f"{path}: new text has no newline at end of file")
    return _finish(out, width, max_lines)
