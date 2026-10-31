"""B-145: one conformance harness for every screen at 80, 60 and 40 columns (plain and rich).

A registry of fixtures: each entry renders a screen from plain data. The harness checks, for every
entry and every width: no line is wider than the width (markup not counted); no raw escape sequence
or bidirectional control character; no em-dash (the wording rule); and the plain rendering has no
markup, so NO_COLOR and plain mode are the same text. A new screen is added here by adding one
registry entry, not by writing a new test.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from ract.ui import command_screens as cmd
from ract.ui import tier_status_view as tier
from ract.ui import workspace_screens as ws
from ract.ui.plan_approval_view import screen_lines as plan_screen_lines

WIDTHS = (80, 60, 40)
MARKUP = re.compile(r"\[/?bold\]")
RAW_CONTROL = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
DASH = "\u2014"

# name -> render(width, rich) -> list of lines
Renderer = Callable[[int, bool], list[str]]


def _diff(width: int, rich: bool) -> list[str]:
    hunk = ws.Hunk(
        id=ws.hunk_id("src/calc.py", 1),
        old_start=1,
        old_count=2,
        new_start=1,
        new_count=2,
        lines=("-    return a - b", "+    return a + b"),
    )
    return ws.diff_proposed_lines(
        [ws.FileProposal(path="src/calc.py", hunks=(hunk,))], width, rich=rich
    )


def _apply(width: int, rich: bool) -> list[str]:
    return ws.apply_result_lines(
        ws.ApplyResult(
            applied_hunks=2, applied_files=1, skipped=("src/other.py",), session="s-1"
        ),
        width,
    )


def _checkpoints(width: int, rich: bool) -> list[str]:
    return ws.checkpoint_lines(
        [ws.Checkpoint(number=1, when="10:00", turn="t-1", files=1)], width
    )


def _prompt(width: int, rich: bool) -> list[str]:
    request = cmd.CommandRequest(
        argv=("python", "-m", "pytest"),
        executable="C:/Python312/python.exe",
        cwd=".",
        network=False,
        sandbox_enforced=False,
        env_names=("PATH",),
        reason="run the tests",
    )
    return cmd.approval_prompt_lines(request, width, rich=rich)


def _results(width: int, rich: bool) -> list[str]:
    summary = cmd.RunSummary(
        passed=3,
        failed=1,
        skipped=0,
        duration_s=1.2,
        exit_code=1,
        failing=(
            cmd.FailingTest(
                name="tests/test_calc.py::test_add", message="assert 1 == 2"
            ),
        ),
    )
    return cmd.result_lines(summary, width, rich=rich)


def _verdict(width: int, rich: bool) -> list[str]:
    return cmd.verdict_lines("passed, with 1 command run", 1, width, rich=rich)


def _status(width: int, rich: bool) -> list[str]:
    text = tier.status_line(tier.TierState(mode="unrestricted"), None, rich=rich)
    return [text]


def _plan(width: int, rich: bool) -> list[str]:
    return list(plan_screen_lines(_plan_steps(), width, rich=rich))


def _plan_steps() -> list:
    from ract.ui.plan_approval_view import Step

    return [
        Step(
            n=1,
            action="Fix add() in src/calc.py",
            target="src/calc.py",
            state="pending",
        )
    ]


REGISTRY: dict[str, Renderer] = {
    "diff_proposed": _diff,
    "apply_result": _apply,
    "checkpoint_list": _checkpoints,
    "approval_prompt": _prompt,
    "test_result": _results,
    "verdict": _verdict,
    "status_line": _status,
    "plan_checklist": _plan,
}


@pytest.mark.parametrize("name", sorted(REGISTRY))
@pytest.mark.parametrize("width", WIDTHS)
def test_each_screen_fits_the_width_plain_and_rich(name: str, width: int) -> None:
    render = REGISTRY[name]
    for rich in (False, True):
        for line in render(width, rich):
            visible = MARKUP.sub("", line)
            assert len(visible) <= width, (
                f"{name} at {width} (rich={rich}): {visible!r}"
            )


@pytest.mark.parametrize("name", sorted(REGISTRY))
@pytest.mark.parametrize("width", WIDTHS)
def test_no_raw_control_or_dash_and_no_markup_in_plain(name: str, width: int) -> None:
    render = REGISTRY[name]
    plain = render(width, False)
    joined = "\n".join(plain)
    assert not RAW_CONTROL.search(joined), name
    assert DASH not in joined, name
    assert not MARKUP.search(joined), f"{name}: markup in the plain text"


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_the_rich_text_has_the_same_words_as_the_plain_text(name: str) -> None:
    render = REGISTRY[name]
    for width in WIDTHS:
        plain = " ".join(" ".join(render(width, False)).split())
        rich = " ".join(
            " ".join(MARKUP.sub("", line) for line in render(width, True)).split()
        )
        assert plain == rich, f"{name} at {width}"
