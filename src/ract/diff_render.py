"""Draw a change as hunks (B-014a): a pure function of two texts.

No I/O, no Rich, no color. The inputs are file contents, so they are hostile:
every output line goes through ``safe_text``, which also shows direction
marks as escapes. Output is deterministic.
"""

from __future__ import annotations

import difflib

from rich.cells import cell_len

from ract.session_events import safe_text

_NUL_WINDOW = 8192
_NEW_FILE_PREVIEW = 20
_EXACT_DIFF_LINES = 1_000
# Package Q: the matcher is quadratic in this range (2.5 s at 5000 lines, 0.09 s at 1000),
# so past 2000 lines the diff is a count of lines, not hunks.
_MAX_DIFF_LINES = 2_000


def _clean(text: str) -> str:
    return safe_text(text)


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
    """The line cut to ``width`` terminal columns, with "..." at the cut (package O)."""
    if cell_len(line) <= width:
        return line
    budget = max(width - 3, 0)
    out = ""
    used = 0
    for ch in line:
        step = cell_len(ch)
        if used + step > budget:
            break
        out += ch
        used += step
    return out + "..."


def _finish(lines: list[str], width: int, max_lines: int) -> list[str]:
    fitted = [_fit(line, width) for line in lines]
    if len(fitted) > max_lines:
        rest = len(fitted) - max_lines
        return fitted[:max_lines] + [f"... {_noun(rest, 'more line')}"]
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
    out = [f"{path}: {kind}, {_noun(len(lines), 'line')}"]
    out += [
        _row(gutter, number, marker, line)
        for number, line in enumerate(lines[:_NEW_FILE_PREVIEW], start=1)
    ]
    if len(lines) > _NEW_FILE_PREVIEW:
        out.append(f"... {_noun(len(lines) - _NEW_FILE_PREVIEW, 'more line')}")
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


def _diff(
    path: str,
    old: str | None,
    new: str | None,
    width: int = 80,
    context: int = 3,
    max_lines: int = 200,
) -> tuple[list[str], int, int]:
    """Lines for one file's change, and the lines added and removed.

    The counts come from the hunks themselves, never from matching the rendered
    text, so text inside a file cannot change them (G-152).
    """
    path = _clean(path)
    if any(t is not None and _is_binary(t) for t in (old, new)):
        size = len((new if new is not None else old or "").encode("utf-8", "replace"))
        return [_fit(f"{path}: binary file, {size} bytes", width)], 0, 0
    if old is None or new is None:
        lines = _finish(_file_level(path, old, new), width, max_lines)
        if old is None:
            return lines, len(_lines(new or "")), 0
        return lines, 0, len(_lines(old))
    if old == new:
        return [], 0, 0
    ending = _line_ending_change(old, new)
    if ending is not None:
        return [_fit(f"{path}: line endings changed ({ending})", width)], 0, 0

    # Compare line by line with CRLF read as LF, so a real edit in a file whose
    # endings also differ shows only the edit.
    old_lines = _lines(old.replace("\r\n", "\n"))
    new_lines = _lines(new.replace("\r\n", "\n"))
    if max(len(old_lines), len(new_lines)) > _MAX_DIFF_LINES:
        # difflib is quadratic on repetitive input (G-117). Past the cap, say only
        # what the line counts show, and do not run the matcher at all.
        grew = len(new_lines) - len(old_lines)
        counts = f"+{max(grew, 0)} -{max(-grew, 0)} by line count"
        lines = _finish(
            [
                f"{path}: file too large to draw a diff: "
                f"{len(old_lines)} -> {len(new_lines)} lines; {counts}"
            ],
            width,
            max_lines,
        )
        return lines, max(grew, 0), max(-grew, 0)
    out: list[str] = []
    total_added = total_removed = 0
    for group in group_hunks(old_lines, new_lines, context) or []:
        added, removed = hunk_counts(group)
        total_added += added
        total_removed += removed
        out += _hunk_rows(path, old_lines, new_lines, group)
    if old and not old.endswith("\n"):
        out.append(f"{path}: old text has no newline at end of file")
    if new and not new.endswith("\n"):
        out.append(f"{path}: new text has no newline at end of file")
    return _finish(out, width, max_lines), total_added, total_removed


def group_hunks(
    old_lines: list[str], new_lines: list[str], context: int = 3
) -> list[list[tuple]] | None:
    """The change as difflib opcode groups, one group per hunk as it is drawn.

    None past the size cap (the matcher is quadratic there): the caller treats
    the file as one change. B-014c asks about these same groups, so the hunks
    a user accepts are the hunks the summary draws.
    """
    if max(len(old_lines), len(new_lines)) > _MAX_DIFF_LINES:
        return None
    # Exact matching for short files. Past _EXACT_DIFF_LINES, difflib's junk
    # heuristic keeps repetitive lines from making the match quadratic (G-117).
    longest = max(len(old_lines), len(new_lines))
    plan = _Plan(_opcodes(old_lines, new_lines, longest > _EXACT_DIFF_LINES))
    return [group for group in plan.get_grouped_opcodes(context)]


def hunk_counts(group: list[tuple]) -> tuple[int, int]:
    """Lines added and removed in one hunk."""
    added = sum(j2 - j1 for tag, _, _, j1, j2 in group if tag in {"insert", "replace"})
    removed = sum(
        i2 - i1 for tag, i1, i2, _, _ in group if tag in {"delete", "replace"}
    )
    return added, removed


def _hunk_rows(
    path: str, old_lines: list[str], new_lines: list[str], group: list[tuple]
) -> list[str]:
    first, last = group[0], group[-1]
    added, removed = hunk_counts(group)
    out = [
        f"{path}: lines {_span(first[1], last[2])} -> "
        f"{_span(first[3], last[4])}, +{added} -{removed}"
    ]
    gutter = len(str(max(last[2], last[4], 1)))
    for tag, i1, i2, j1, j2 in group:
        if tag == "equal":
            out += [_row(gutter, k + 1, " ", old_lines[k]) for k in range(i1, i2)]
        if tag in {"delete", "replace"}:
            out += [_row(gutter, k + 1, "-", old_lines[k]) for k in range(i1, i2)]
        if tag in {"insert", "replace"}:
            out += [_row(gutter, k + 1, "+", new_lines[k]) for k in range(j1, j2)]
    return out


def draw_hunk(
    path: str,
    old_lines: list[str],
    new_lines: list[str],
    group: list[tuple],
    width: int = 80,
    max_lines: int = 200,
) -> list[str]:
    """One hunk of ``group_hunks``, drawn as ``render_hunks`` draws it (B-014c)."""
    return _finish(
        _hunk_rows(_clean(path), old_lines, new_lines, group), width, max_lines
    )


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
    return _diff(path, old, new, width, context, max_lines)[0]


def _noun(count: int, word: str) -> str:
    """``1 line``, ``2 lines``; ``word`` is the singular form."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def draw_turn_diff(
    changes: list[tuple[str, str | None, str | None]],
    *,
    width: int = 80,
    max_lines: int = 60,
) -> list[str]:
    """The diff block of a turn summary: one hunk list per changed file.

    ``changes`` are ``(path, before, after)`` in the order the turn changed them;
    ``None`` on a side means the file did not exist there. The block holds at
    most ``max_lines`` lines of hunks. When it cuts, it says how many lines and
    files it left out. The last line is the total, summed from each file's hunks.
    """
    rendered: list[tuple[list[str], int, int]] = []
    for path, before, after in changes:
        lines, added, removed = _diff(path, before, after, width=width, max_lines=10**9)
        if lines:
            rendered.append((lines, added, removed))
    if not rendered:
        return []
    total_added = sum(added for _, added, _ in rendered)
    total_removed = sum(removed for _, _, removed in rendered)
    body: list[str] = []
    for index, (lines, _, _) in enumerate(rendered):
        if len(body) + len(lines) <= max_lines:
            body += lines
            continue
        left_after = len(rendered) - index - 1
        room = max_lines - len(body) - 1 - (1 if left_after else 0)
        if room > 0:
            body += lines[:room]
            body.append(f"... {_noun(len(lines) - room, 'more line')}")
        if left_after:
            left = len(rendered) - index - (1 if room > 0 else 0)
            body.append(f"... and {_noun(left, 'more file')}")
        break
    files = len(rendered)
    noun = "file" if files == 1 else "files"
    return [*body, f"{files} {noun}, +{total_added} -{total_removed}"]
