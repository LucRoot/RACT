"""The last check before a step's reply replaces an existing file (S-026).

LR:: The executor writes a step's reply to its target file. A model that
answers in prose when the plan named a file replaced that file with prose:
the v0.5.2 manager prompt even taught "for reads use the target file path",
so a question about a file could overwrite it. The planner side is fixed
(answer steps, B-042); this module is the safety net behind it for models
that still name a file. It refuses a replacement that is plainly not the
file:

- a step whose action reads like a question never replaces an existing file;
- a file RACT can parse that parsed before must still parse after;
- any other file of more than 50 lines is not cut to under a tenth of its
  size unless the action says it deletes or truncates.
"""

from __future__ import annotations

import ast
import configparser
import json
import tomllib
from pathlib import PurePosixPath

import yaml

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

# Words in an action that make a large reduction intended.
_SHRINK_WORDS = ("delete", "remove", "truncate", "clear", "empty", "shorten")

_SIZE_RULE_MIN_LINES = 50
_SIZE_RULE_FRACTION = 0.1


class ReplacementRefused(Exception):
    """A step's reply would have replaced an existing file and was refused."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def reads_like_a_question(action: str) -> bool:
    """True when the action's first word asks for information (QUESTION_VERBS)."""
    words = action.strip().split(maxsplit=1)
    return bool(words) and words[0].lower().strip(".,:;!?") in QUESTION_VERBS


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


def check_replacement(path: str, old: bytes, new: str, action: str) -> None:
    """Raise ReplacementRefused when *new* should not replace *old* at *path*."""
    if reads_like_a_question(action):
        raise ReplacementRefused(
            path,
            f'the step "{action}" asks for information, so its reply is an '
            "answer, not a new version of the file",
        )
    try:
        old_text = old.decode("utf-8")
    except UnicodeDecodeError:
        return  # not a text file RACT can judge; the backup still keeps it
    kind = _KINDS.get(PurePosixPath(path.replace("\\", "/")).suffix.lower())
    if kind is not None:
        if _parses(kind, old_text) and not _parses(kind, new):
            raise ReplacementRefused(
                path, f"the reply is not a valid {kind} file, and the current one is"
            )
        return
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
        )


__all__ = [
    "QUESTION_VERBS",
    "ReplacementRefused",
    "check_replacement",
    "reads_like_a_question",
]
