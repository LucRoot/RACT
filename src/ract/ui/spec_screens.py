"""The guided-spec screens (B-178, first slice): the questions, the approval, the check and the saved line.

Pure: plain data in, text out. Nothing here reads a file, asks a question or writes a spec; the harness
does that. Every line fits the width (``wrap_cells``) and control characters show as escapes
(``visible_text``). Colour is not used here: each screen reads the same with colour off (B-179).
"""

from __future__ import annotations

from ract.cell_wrap import wrap_cells
from ract.session_events import visible_text

QUESTIONS: tuple[tuple[str, str], ...] = (
    (
        "What do you want to exist when it is done? One sentence.",
        "a tool that counts the words in my notes",
    ),
    (
        "Who uses it, and what do they do with it?",
        "I use it each morning to check my drafts",
    ),
    (
        "What must it do? List the main things.",
        "count words, list the longest ten lines",
    ),
    ("What must it not do?", "change my files, send anything over the network"),
    (
        "How will we know it works? Something we can see, count or run.",
        "the command prints the word count",
    ),
    (
        "What limits do we have? Time, tools, the machines we use. You may type skip.",
        "one afternoon, Python only",
    ),
)
SECTIONS: tuple[str, ...] = (
    "Goal",
    "Users",
    "Must do",
    "Must not do",
    "How we will know",
    "Limits",
)
APPROVAL_CHOICES = "[y] keep it   [e] type a replacement   [n] draft it again"
CHECK_WORDS = ("prints", "shows", "exists", "passes", "returns", "counts")


def question_lines(index: int, question: str, example: str, width: int) -> list[str]:
    """The question screen: its number out of six, the question, and one example in plain words."""
    total = len(QUESTIONS)
    out = wrap_cells(f"question {index} of {total}", width)
    out += wrap_cells(visible_text(question), width)
    out += wrap_cells(
        f"example: {visible_text(example)}", width, subsequent_indent="  "
    )
    out += wrap_cells(
        "type your answer, or press Enter to see the example again", width
    )
    return out


def approval_lines(section: str, body: str, width: int) -> list[str]:
    """The approval screen for one section: its name, its draft, and the three choices."""
    out = wrap_cells(f"section: {visible_text(section)}", width)
    for line in visible_text(body).splitlines() or [""]:
        out += wrap_cells(line, width, subsequent_indent="  ")
    out += wrap_cells(APPROVAL_CHOICES, width)
    return out


def check_lines(
    missing: list[str], unchecked: list[tuple[str, str]], width: int
) -> list[str]:
    """The result of the harness check: nothing wrong, or each missing section and each uncheckable line."""
    if not missing and not unchecked:
        return wrap_cells(
            "every section is here, and each acceptance line can be checked", width
        )
    out: list[str] = []
    for section in missing:
        out += wrap_cells(
            f"missing section: {visible_text(section)}: the draft is written again",
            width,
        )
    for section, line in unchecked:
        out += wrap_cells(
            f'not checkable in {visible_text(section)}: "{visible_text(line)}". '
            f"Name a number, a command or a file (one of: {', '.join(CHECK_WORDS)})",
            width,
            subsequent_indent="  ",
        )
    return out


def saved_lines(path: str, digest: str, width: int) -> list[str]:
    """The line after a spec is written: the file, and the first twelve characters of its hash."""
    return wrap_cells(
        f"spec saved: {visible_text(path)} (sha256 {digest[:12]}...). A later run reads it as context.",
        width,
        subsequent_indent="  ",
    )
