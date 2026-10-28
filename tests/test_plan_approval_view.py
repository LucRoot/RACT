"""B-064b, prepared (package K): the plan approval screen, its answers and its data.

Unwired on purpose: no input read, no event emitted, no import from the event layer.
Covers the screen at 80, 60 and 40 columns (plain and rich), each answer, the bad
answers (none approves), the skipped and edited plan, and the plan hash.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from rich.cells import cell_len

from ract.ui import plan_approval_view as pav

PLAN = [
    pav.Step(1, "Fix add() in src/calc.py", "src/calc.py"),
    pav.Step(2, "Add a test in tests/test_calc.py", "tests/test_calc.py"),
    pav.Step(3, "Update README.md", "README.md"),
]


@pytest.mark.parametrize("width", [80, 60, 40])
@pytest.mark.parametrize("rich", [False, True])
def test_the_screen_fits_the_width_and_ends_with_the_question(width, rich):
    lines = pav.screen_lines(PLAN, width, rich=rich)
    plain = [line.replace("[dim]", "").replace("[/dim]", "") for line in lines]
    for line in plain:
        assert cell_len(line) <= width, (width, line)
    assert plain[0] == "Plan: 3 steps"
    joined = " ".join(plain)  # the question may fold onto two lines at 40 columns
    assert "Run it? [a]pprove" in joined and "[c]ancel" in joined


def test_a_skipped_step_shows_the_dash_mark_in_the_redrawn_list():
    lines = pav.screen_lines(pav.skip(PLAN, 3), 80)
    assert "[-] 3. Update README.md -> README.md" in lines


@pytest.mark.parametrize(
    "line, kind, n",
    [
        ("a", "approve", None),
        ("approve", "approve", None),
        ("run", "approve", None),
        ("c", "cancel", None),
        ("cancel", "cancel", None),
        ("s 3", "skip", 3),
        ("skip 2", "skip", 2),
        ("e 2", "edit", 2),
        ("EDIT 1", "edit", 1),
    ],
)
def test_each_answer_parses_to_its_meaning(line, kind, n):
    answer = pav.parse_answer(line, 3)
    assert (answer.kind, answer.n, answer.error) == (kind, n, None)


@pytest.mark.parametrize(
    "line, message",
    [
        ("", "no answer; type a, s <n>, e <n> or c"),
        ("   ", "no answer; type a, s <n>, e <n> or c"),
        ("s 9", "no step 9; the plan has 3 steps"),
        ("s x", "'x' is not a step number"),
        ("skip", "skip needs a step number"),
        ("zzz", "'zzz' is not an answer; type a, s <n>, e <n> or c"),
    ],
)
def test_a_bad_answer_is_an_error_and_never_an_approval(line, message):
    answer = pav.parse_answer(line, 3)
    assert answer.kind == "error"
    assert answer.error and message in answer.error


def test_skip_and_edit_change_only_the_named_step():
    skipped = pav.skip(PLAN, 2)
    assert [s.state for s in skipped] == ["pending", "skipped", "pending"]
    edited = pav.edit(PLAN, 1, "  Fix add() so it adds  ")
    assert edited[0].action == "Fix add() so it adds"
    assert edited[1:] == PLAN[1:]
    with pytest.raises(ValueError):
        pav.edit(PLAN, 1, "   ")


def test_the_plan_hash_ignores_confidence_and_assumption_and_changes_with_the_steps():
    base = pav.plan_hash(PLAN)
    assert pav.plan_hash(list(PLAN)) == base
    assert pav.plan_hash(pav.skip(PLAN, 1)) == base  # the state is not in the hash
    assert pav.plan_hash(pav.edit(PLAN, 1, "Something else")) != base


def test_the_module_imports_nothing_from_the_event_or_input_layers():
    source = Path(pav.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    names |= {
        a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
    }
    for forbidden in (
        "repl",
        "session_events",
        "approval_callback",
        "readline",
        "session_render",
    ):
        assert not any(name.endswith(forbidden) for name in names), names
    assert ".emit(" not in source and "input(" not in source
