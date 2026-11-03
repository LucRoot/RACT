"""B-042: the manager prompt's answer-step rules are what real models see.

The v0.5.2 prompt said expected_artifact "must not be empty" and "for reads
use the target file path", which made a read overwrite the file it read
(G-048). These sentences are pinned so a later edit cannot quietly drop
them. Both copies are checked: the bundled default and the repository's own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = [
    ROOT / "src" / "ract" / "default_prompts" / "manager.txt",
    ROOT / "prompts" / "manager.txt",
]

PINNED = [
    'expected_artifact: the one file this step writes, or "" for an answer step',
    "Name a file only when the step must create or change that file.",
    'is an answer step: set expected_artifact to "". Nothing is written; the reply '
    "is the answer shown to the user.",
    "Never name a file you only want to read: the step would overwrite it with its reply.",
    "with a signed grant, RACT runs the granted test command and asks the "
    "user before every run",
    "RACT runs nothing that is not granted.",
    "With no grant, do not plan a step that runs tests or commands or writes "
    "their results",
    "When the intent is only a question, the plan is a single answer step.",
]

FORBIDDEN = [
    "must not be empty",
    "test_results.txt",
    "for reads use the target file",
    "cannot run tests or commands in this release",
]


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.parent.name)
def test_answer_step_rules_are_in_the_prompt(path: Path) -> None:
    text = " ".join(path.read_text(encoding="utf-8").split())

    for sentence in PINNED:
        assert sentence in text, sentence
    for phrase in FORBIDDEN:
        assert phrase not in text, phrase


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.parent.name)
def test_every_example_step_that_names_a_file_changes_it(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    examples = [
        json.loads(block)
        for block in re.findall(r"^\{\n.*?^\}$", text, flags=re.S | re.M)
    ]

    assert len(examples) == 2
    steps = [step for example in examples for step in example["steps"]]
    assert any(step["expected_artifact"] == "" for step in steps)
    for step in steps:
        if step["expected_artifact"]:
            assert step["action"].split()[0].lower() not in {"read", "explain", "show"}
