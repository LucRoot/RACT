"""B-178 wiring: the ``/spec`` walk from an idea to an approved ``SPEC.md``.

The design page (``docs/design/B-178_spec_guide.md``) is the spec: six
questions one at a time, each answer kept as written, approval per section
(``y`` keep, ``e`` type a replacement, ``n`` ask again), nothing written to
``SPEC.md`` until every section is approved, the draft kept in
``.ract/spec_draft.json`` for an abandoned walk, and ``.ract/spec_hash.txt``
holding the SHA-256 of the approved file. This slice drafts each section
from the person's own words; the model-drafted redraft needs a model call
and is the stated next piece.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ract.spec_guide import (
    DRAFT_NAME,
    HASH_NAME,
    SPEC_NAME,
    walk,
)

Y = "y"


def _scripted(answers: list[str]):
    """An ask callable that answers in order and records the prompts."""
    seen: list[str] = []
    queue = list(answers)

    def ask(prompt: str) -> str:
        seen.append(prompt)
        return queue.pop(0) if queue else ""

    return ask, seen


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    return root


def test_the_walk_asks_six_questions_and_writes_the_spec(tmp_path: Path) -> None:
    root = _project(tmp_path)
    answers = [
        "A tally app", Y,
        "Runners log miles", Y,
        "log and total runs", Y,
        "no cloud sync", Y,
        "the command prints the total", Y,
        "one weekend", Y,
    ]
    ask, _seen = _scripted(answers)
    assert walk(root, ask=ask, width=80) is True
    spec = (root / SPEC_NAME).read_text(encoding="utf-8")
    for section in ("Goal", "Users", "Must do", "Must not do",
                    "How we will know", "Limits"):
        assert section in spec
    assert "A tally app" in spec
    digest = (root / ".ract" / HASH_NAME).read_text(encoding="utf-8").strip()
    assert digest == hashlib.sha256((root / SPEC_NAME).read_bytes()).hexdigest()
    assert not (root / ".ract" / DRAFT_NAME).exists()


def test_a_blank_answer_is_asked_again_with_the_example(tmp_path: Path) -> None:
    root = _project(tmp_path)
    answers = [
        "", "A tally app", Y,
        "Runners log miles", Y,
        "log and total runs", Y,
        "no cloud sync", Y,
        "the command prints the total", Y,
        "one weekend", Y,
    ]
    ask, seen = _scripted(answers)
    assert walk(root, ask=ask, width=80) is True
    # The re-ask names the example (the prompt carries the question again).
    assert any("for example" in prompt.lower() for prompt in seen)


def test_question_six_may_be_skipped(tmp_path: Path) -> None:
    root = _project(tmp_path)
    answers = [
        "A tally app", Y,
        "Runners", Y,
        "log runs", Y,
        "no sync", Y,
        "the command prints the total", Y,
        "", Y,
    ]
    ask, _seen = _scripted(answers)
    assert walk(root, ask=ask, width=80) is True
    spec = (root / SPEC_NAME).read_text(encoding="utf-8")
    assert "Limits" in spec


def test_an_uncheckable_acceptance_line_is_named(tmp_path: Path) -> None:
    root = _project(tmp_path)
    # "it is fast" is not checkable: the walk names it and asks again.
    answers = [
        "A tally app", Y,
        "Runners", Y,
        "log runs", Y,
        "no sync", Y,
        "it is fast", Y,
        "one weekend", Y,
        "the command prints the total in under 2 seconds", Y,
    ]
    ask, _seen = _scripted(answers)
    assert walk(root, ask=ask, width=80) is True
    spec = (root / SPEC_NAME).read_text(encoding="utf-8")
    assert "under 2 seconds" in spec


def test_a_rejected_section_is_asked_again(tmp_path: Path) -> None:
    root = _project(tmp_path)
    answers = [
        "A tally app", Y,
        "wrong", "n",
        "Runners log miles", Y,
        "log and total runs", Y,
        "no cloud sync", Y,
        "the command prints the total", Y,
        "one weekend", Y,
    ]
    ask, _seen = _scripted(answers)
    assert walk(root, ask=ask, width=80) is True
    spec = (root / SPEC_NAME).read_text(encoding="utf-8")
    assert "Runners log miles" in spec
    assert "wrong" not in spec


def test_an_abandoned_walk_keeps_its_draft_and_resumes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ask, _seen = _scripted(["A tally app", Y, "Runners"])
    # The scripted queue runs dry at an approval: the walk is abandoned.
    assert walk(root, ask=ask, width=80) is False
    draft = json.loads((root / ".ract" / DRAFT_NAME).read_text(encoding="utf-8"))
    assert draft["approved"]["goal"] == "A tally app"
    assert not (root / SPEC_NAME).exists()
    # The next /spec continues: the approved sections stand, the rest are asked.
    answers = [
        "Runners log miles", Y,
        "log and total runs", Y,
        "no cloud sync", Y,
        "the command prints the total", Y,
        "one weekend", Y,
    ]
    ask2, seen2 = _scripted(answers)
    assert walk(root, ask=ask2, width=80) is True
    assert not any("What do you want to exist" in prompt for prompt in seen2)
    assert (root / SPEC_NAME).is_file()


def test_nothing_is_written_until_every_section_is_approved(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ask, _seen = _scripted(["A tally app", Y, "Runners"])
    walk(root, ask=ask, width=80)
    assert not (root / SPEC_NAME).exists()
    assert not (root / ".ract" / HASH_NAME).exists()
