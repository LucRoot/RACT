"""The ``/spec`` walk: an idea in, an approved ``SPEC.md`` out (B-178, first slice).

The design page (``docs/design/B-178_spec_guide.md``) is the spec. Six
questions, one at a time; each answer is kept as written; the person
approves section by section (``y`` keep, ``e`` type a replacement, ``n``
ask the question again); nothing touches ``SPEC.md`` until every section
is approved; the draft lives in ``.ract/spec_draft.json`` so an abandoned
walk resumes; ``.ract/spec_hash.txt`` holds the SHA-256 of the approved
file. An acceptance line must be checkable: it names a number, a command
or file in backticks, or one of the words an operator can see, run or
count. This slice drafts each section from the person's own words; the
model-drafted redraft needs a model call and is the stated next piece.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ract.atomic_write import write_atomic
from ract.ui.spec_screens import (
    QUESTIONS,
    SECTIONS,
    approval_lines,
    check_lines,
    question_lines,
    saved_lines,
)

SPEC_NAME = "SPEC.md"
DRAFT_NAME = "spec_draft.json"
HASH_NAME = "spec_hash.txt"
KEYS = ("goal", "users", "must_do", "must_not_do", "how_known", "limits")
CHECKABLE_WORDS = ("prints", "shows", "exists", "passes", "returns", "counts")


@dataclass
class SpecDraft:
    answers: dict[str, str] = field(default_factory=dict)
    approved: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"answers": self.answers, "approved": self.approved}


def _draft_path(project: Path) -> Path:
    return project / ".ract" / DRAFT_NAME


def _load_draft(project: Path) -> SpecDraft:
    path = _draft_path(project)
    if not path.is_file():
        return SpecDraft()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SpecDraft(
            answers=dict(data.get("answers") or {}),
            approved=dict(data.get("approved") or {}),
        )
    except (OSError, ValueError):
        return SpecDraft()


def _save_draft(project: Path, draft: SpecDraft) -> None:
    from ract.workspace_state import check_state_path

    folder = project / ".ract"
    target = _draft_path(project)
    check_state_path(target)
    folder.mkdir(parents=True, exist_ok=True)
    write_atomic(
        target, json.dumps(draft.to_dict(), indent=2).encode("utf-8")
    )


def _is_checkable(line: str) -> bool:
    if any(ch.isdigit() for ch in line):
        return True
    if any(word in line.lower() for word in CHECKABLE_WORDS):
        return True
    return "`" in line or '"' in line


def _write_spec(project: Path, draft: SpecDraft) -> Path:
    lines: list[str] = ["# SPEC", ""]
    for key, section in zip(KEYS, SECTIONS):
        lines.append(f"## {section}")
        lines.append("")
        lines.append(draft.approved[key])
        lines.append("")
    spec = project / SPEC_NAME
    # B-238 class: the state files go through the state-path guard and a
    # fresh temporary file, so a link planted at a name is replaced, not
    # written through.
    from ract.workspace_state import check_state_path

    data = "\n".join(lines).encode("utf-8")
    write_atomic(spec, data)
    digest = hashlib.sha256(data).hexdigest()
    ract_dir = project / ".ract"
    hash_path = ract_dir / HASH_NAME
    check_state_path(hash_path)
    ract_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(hash_path, f"{digest}\n".encode("utf-8"))
    _draft_path(project).unlink(missing_ok=True)
    return spec


def walk(
    project: Path,
    *,
    ask: Callable[[str], str],
    width: int,
    say: Callable[[str], None] = print,
) -> bool:
    """Run the guided walk. True when the spec was approved and written.

    False when the walk was abandoned (end of input): the draft is kept and
    the next ``/spec`` offers to continue it. Question 6 (limits) may be
    skipped with one blank answer; the others re-ask once with the example,
    and a second blank abandons the walk.
    """
    project = Path(project)
    draft = _load_draft(project)
    for index, (key, (question, example)) in enumerate(zip(KEYS, QUESTIONS)):
        if key in draft.approved:
            continue
        re_asks = 0
        while True:
            body = draft.answers.get(key)
            if body is None:
                say("")
                for line in question_lines(index, question, example, width):
                    say(line)
                body = ask(question)
                if not body.strip():
                    if key == "limits":
                        body = "(no limits named)"
                    elif re_asks == 0:
                        re_asks += 1
                        again = f"{question} (for example: {example})"
                        body = ask(again)
                        if not body.strip():
                            _save_draft(project, draft)
                            return False
                    else:
                        _save_draft(project, draft)
                        return False
            say("")
            for line in approval_lines(SECTIONS[index], body, width):
                say(line)
            reply = ask(
                "[y] keep it, [e] type a replacement, [n] ask again: "
            ).strip().lower()
            if not reply:
                # End of input at the approval: the walk is abandoned, and
                # nothing is approved by a missing answer.
                _save_draft(project, draft)
                return False
            if reply == "e":
                body = ask("Type the replacement: ")
                continue
            if reply == "n":
                # Ask the same section's question again.
                draft.answers.pop(key, None)
                _save_draft(project, draft)
                continue
            if reply in {"y", "yes"}:
                draft.approved[key] = body
                draft.answers[key] = body
                _save_draft(project, draft)
                break
            say("Answer y, e or n.")
    missing = [
        line
        for line in draft.approved.get("how_known", "").splitlines()
        if line.strip() and not _is_checkable(line)
    ]
    if missing:
        say("")
        unchecked = [(line, "names no number, command or file") for line in missing]
        for line in check_lines([], unchecked, width):
            say(line)
        draft.approved.pop("how_known", None)
        draft.answers.pop("how_known", None)
        _save_draft(project, draft)
        say("Answer 'How we will know' again: name a number, a command or a file.")
        return walk(project, ask=ask, width=width, say=say)
    spec = _write_spec(project, draft)
    digest = (project / ".ract" / HASH_NAME).read_text(encoding="utf-8").strip()
    say("")
    for line in saved_lines(spec.name, digest, width):
        say(line)
    return True
