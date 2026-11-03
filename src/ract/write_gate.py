"""The last check before a step's reply replaces an existing file (S-026).

LR:: The executor writes a step's reply to its target file. A model that
answers in prose when the plan named a file replaced that file with prose:
the v0.5.2 manager prompt even taught "for reads use the target file path",
so a question about a file could overwrite it. The planner side is fixed
(answer steps, B-042); this module is the safety net behind it for models
that still name a file. It refuses a replacement that is plainly not the
file:

- a step whose action reads like a question never replaces an existing file;
- before the parse check, a Python reply's think blocks and one outer code
  fence are stripped, and the body between the fences is what is written;
- a file RACT can parse that parsed before must still parse after;
- a new Python file must parse (B-095: a new file was written with a
  syntax error and the run reported done);
- any other file of more than 50 lines is not cut to under a tenth of its
  size unless the action says it deletes or truncates.
"""

from __future__ import annotations

import ast
import configparser
import dataclasses
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import yaml

from ract.workspace_path import resolve_workspace_path

if TYPE_CHECKING:
    from ract.manager import Plan

# First words of a step action that asks for information, not a change.
# A safety net behind the manager prompt, not a classifier: keep it short.
QUESTION_VERBS = frozenset(
    {
        "read",
        "show",
        "explain",
        "list",
        "find",
        "review",
        "check",
        "summarize",
        "summarise",
        "describe",
    }
)

# Words that make an action a change even when it starts with a question
# verb: "check the loader and fix the typo" writes (D-019).
WRITE_VERBS = frozenset(
    {
        "fix",
        "change",
        "update",
        "edit",
        "rewrite",
        "replace",
        "modify",
        "implement",
        "add",
        "remove",
        "refactor",
        "create",
    }
)

# Words in an action that make a large reduction intended.
_SHRINK_WORDS = ("delete", "remove", "truncate", "clear", "empty", "shorten")

_SIZE_RULE_MIN_LINES = 50
_SIZE_RULE_FRACTION = 0.1

# A model's reasoning wrapped in <think>...</think>, inline in the reply
# (the same block strip_reasoning removes earlier in the executor; the gate
# removes it too so a direct call still judges the visible answer).
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ReplacementRefused(Exception):
    """A step's reply would have replaced an existing file and was refused."""

    def __init__(
        self, path: str, reason: str, rule: str, *, created: bool = False
    ) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason
        # "question", "parse" or "size": which check refused the write.
        self.rule = rule
        # True when the refused write would have created the file.
        self.created = created


def reads_like_a_question(action: str) -> bool:
    """True when the action starts with a QUESTION_VERB and names no WRITE_VERB."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", action)]
    return bool(words) and words[0] in QUESTION_VERBS and not WRITE_VERBS & set(words)


def answer_instead(plan: Plan, project_dir: Path | None) -> tuple[Plan, list[str]]:
    """Turn question-like steps that name an existing file into answer steps.

    LR:: A step such as "read src/calc.py" naming src/calc.py asks for
    information; writing its reply over the file is never what was meant
    (G-048). Refusing the write after the model answered cost the call and
    hid the answer (G-051). Deciding before the step runs gives the model
    the answer prompt, shows the reply as the answer and touches no file.
    Returns the plan and one note per converted step.
    """
    if project_dir is None:
        return plan, []
    steps = []
    notes: list[str] = []
    for n, step in enumerate(plan.steps, start=1):
        target = (
            resolve_workspace_path(
                project_dir, step.expected_artifact, purpose="write"
            ).value
            if step.expected_artifact and step.tool_call is None
            else None
        )
        if (
            target is not None
            and target.is_file()
            and reads_like_a_question(step.action)
        ):
            notes.append(
                f"step {n} asks for information, so its reply is shown as the answer; "
                f"the plan named {step.expected_artifact}, which is not written"
            )
            step = dataclasses.replace(step, expected_artifact="")
        steps.append(step)
    if not notes:
        return plan, []
    return dataclasses.replace(plan, steps=steps), notes


def _parses(kind: str, text: str) -> bool:
    try:
        if kind == "python":
            ast.parse(text)
        elif kind == "json":
            json.loads(text)
        elif kind == "yaml":
            yaml.safe_load(text)
        elif kind == "toml":
            tomllib.loads(text)
        elif kind == "ini":
            configparser.ConfigParser().read_string(text)
    except (SyntaxError, ValueError, yaml.YAMLError, configparser.Error):
        return False
    return True


_KINDS = {
    ".py": "python",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
}


BOM = "\ufeff"


def with_bom_of(old: bytes | None, new: str) -> str:
    """*new* with the leading byte order mark *old* had, and only that (B-092, D-100).

    LR:: A full rewrite dropped a file's BOM, because the model's reply has
    none. The rule: a file that started with a BOM keeps exactly one; a file
    without one, or a new file (*old* None), gets none, even when the reply
    carries one. Nothing else about the encoding changes.
    """
    body = new.lstrip(BOM)
    if old is not None and old.startswith(b"\xef\xbb\xbf"):
        return BOM + body
    return body


def python_error(text: str) -> SyntaxError | None:
    """The SyntaxError of *text* as Python, or None when it parses."""
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return exc
    except ValueError as exc:  # a NUL byte in the source
        return SyntaxError(str(exc))
    return None


def _where(exc: SyntaxError) -> str:
    return f"line {exc.lineno}: {exc.msg}" if exc.lineno else str(exc.msg)


def check_new_file(path: str, new: str) -> None:
    """Raise ReplacementRefused when a new Python file at *path* does not parse.

    LR:: A replacement was parse-checked (S-026) and a new file was not, so a
    model's broken file was written and the run said done (S2 D2). Only
    Python is checked here; other new files are written as before.
    """
    if _KINDS.get(PurePosixPath(path.replace("\\", "/")).suffix.lower()) != "python":
        return
    error = python_error(new)
    if error is not None:
        raise ReplacementRefused(
            path,
            f"the reply is not valid python ({_where(error)})",
            "parse",
            created=True,
        )


def _strip_outer_fence(text: str) -> str | None:
    """The body between one outer code fence pair, or None when there is no
    single fenced block (S2 floor leg).

    LR:: The 3B replay's reply carried the file between one ```python fence
    with prose before and after it, and the parse check refused the whole
    reply. The ruling: the outer fence runs from the FIRST opening fence to
    the LAST closing fence; the prose around it is dropped and every fence
    line inside the body stays as content. A fence not at the start of its
    line is prose. No fence, a lone fence, or more than one separate fenced
    block (a second fence line that carries a language) strips nothing, so
    the unchanged refusal stands.
    """
    lines = text.split("\n")
    fence_at = [i for i, line in enumerate(lines) if line.startswith("```")]
    if len(fence_at) < 2:
        return None
    openings = sum(1 for i in fence_at if lines[i][3:].strip(" `\t\r"))
    if openings > 1:
        return None  # more than one separate fenced block
    first, last = fence_at[0], fence_at[-1]
    # Character offsets of the body's span: after the opening fence line,
    # up to the closing fence line. Bytes between the fences are kept as
    # they are, including the newline that ends the last body line.
    offset = 0
    line_start = []
    for line in lines:
        line_start.append(offset)
        offset += len(line) + 1
    body_from = line_start[first] + len(lines[first]) + 1
    body_to = line_start[last]
    if body_from >= body_to:
        return None  # an empty body is never a file
    return text[body_from:body_to]


def _strip_formatting(kind: str, text: str) -> tuple[str, int] | None:
    """A Python reply's think blocks and one outer code fence, with the count.

    LR:: Only a target RACT parses as Python gets this treatment; for any
    other file type a fence is content and None is returned. Think blocks
    go first, then the fence logic runs on the remainder. Returns the
    stripped text and how many characters were removed, or None when there
    is nothing to strip or the fences do not form one outer block.
    """
    if kind != "python":
        return None
    result = _THINK_BLOCK.sub("", text)
    fenced = _strip_outer_fence(result)
    if fenced is not None:
        result = fenced
    if result == text:
        return None
    return result, len(text) - len(result)


def formatting_notice(removed_chars: int) -> str:
    """The one plain line the change screen and the turn summary say.

    The strip happens before the parse check and the write, so the diff and
    the file hold the stripped bytes; the line says so.
    """
    unit = "character" if removed_chars == 1 else "characters"
    return (
        f"RACT removed {removed_chars} {unit} of formatting from the reply; "
        "the diff shows the stripped bytes."
    )


def check_replacement(
    path: str, old: bytes, new: str, action: str
) -> tuple[str, int]:
    """Check *new* against *old* and return the text to write and the count.

    The returned text is *new* with the formatting strip applied when the
    target parses as Python; it is what gets written and shown. The count
    is how many characters the strip removed (0 when nothing was stripped).
    """
    if reads_like_a_question(action):
        raise ReplacementRefused(
            path,
            f'the step "{action}" asks for information, so its reply is an '
            "answer, not a new version of the file",
            "question",
        )
    try:
        # A leading BOM is not content (B-092); ast.parse refuses U+FEFF.
        old_text = old.decode("utf-8").lstrip(BOM)
    except UnicodeDecodeError:
        return new, 0  # not a text file RACT can judge; the backup still keeps it
    kind = _KINDS.get(PurePosixPath(path.replace("\\", "/")).suffix.lower())
    removed = 0
    if kind is not None:
        stripped = _strip_formatting(kind, new)
        if stripped is not None:
            new, removed = stripped
        if _parses(kind, old_text) and not _parses(kind, new):
            error = python_error(new) if kind == "python" else None
            where = f" ({_where(error)})" if error is not None else ""
            raise ReplacementRefused(
                path,
                f"the reply is not a valid {kind} file, and the current one is{where}",
                "parse",
            )
        return new, removed
    lowered = action.lower()
    if (
        old_text.count("\n") > _SIZE_RULE_MIN_LINES
        and len(new) < _SIZE_RULE_FRACTION * len(old_text)
        and not any(word in lowered for word in _SHRINK_WORDS)
    ):
        raise ReplacementRefused(
            path,
            f"the reply is {len(new)} characters and the current file is "
            f"{len(old_text)}; the step does not say it deletes or truncates",
            "size",
        )
    return new, removed


__all__ = [
    "QUESTION_VERBS",
    "WRITE_VERBS",
    "answer_instead",
    "ReplacementRefused",
    "BOM",
    "check_new_file",
    "check_replacement",
    "formatting_notice",
    "python_error",
    "with_bom_of",
    "reads_like_a_question",
]
