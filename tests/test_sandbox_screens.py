"""B-125 screens: the sandbox line in its three postures, the doctor section, and the approval
line (ADR-0048 D7). Pure text at 80, 60 and 40 columns. The wording never claims confinement
on a posture that does not enforce it.
"""

from __future__ import annotations

import pytest

from ract.ui.sandbox_screens import (
    BEST_EFFORT,
    ENFORCED,
    NONE,
    SandboxPosture,
    approval_sandbox_line,
    doctor_sandbox_lines,
    escape_controls,
    permissions_sandbox_line,
    sandbox_line,
)

WIDTHS = (80, 60, 40)


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


@pytest.mark.parametrize(
    ("posture", "text"),
    [
        (
            SandboxPosture("linux-bwrap", ENFORCED),
            "sandbox: enforced on this machine (linux-bwrap)",
        ),
        (
            SandboxPosture("windows-job", BEST_EFFORT),
            "sandbox: best effort, not enforced on this machine (windows-job)",
        ),
        (
            SandboxPosture("none", NONE),
            "sandbox: none; commands run with your user's rights",
        ),
    ],
)
def test_the_sandbox_line_has_the_honest_wording_for_each_posture(
    posture: SandboxPosture, text: str
) -> None:
    assert sandbox_line(posture) == text


@pytest.mark.parametrize("width", WIDTHS)
def test_the_doctor_section_fits_and_states_the_limits(width: int) -> None:
    posture = SandboxPosture(
        "linux-bwrap", ENFORCED, limits="wall 900 s, 1 MiB per stream"
    )
    lines = doctor_sandbox_lines(posture, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "sandbox" in text and "enforced on this machine" in text
    assert "limits applied: wall 900 s, 1 MiB per stream" in text


def test_best_effort_says_a_grant_must_name_it() -> None:
    text = _flat(doctor_sandbox_lines(SandboxPosture("windows-job", BEST_EFFORT), 80))
    assert "not enforced on this machine" in text
    assert "a grant must say sandbox: best_effort" in text


def test_none_says_no_tier_three_grant_is_possible() -> None:
    text = _flat(doctor_sandbox_lines(SandboxPosture("none", NONE), 80))
    assert "commands cannot be granted tier 3 on this machine" in text


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("posture", [ENFORCED, BEST_EFFORT, NONE])
def test_the_permissions_and_approval_lines_fit_at_each_width(
    width: int, posture: str
) -> None:
    p = SandboxPosture("b", posture)
    for lines in (permissions_sandbox_line(p, width), approval_sandbox_line(p, width)):
        for line in lines:
            assert len(line) <= width, line


def test_the_approval_line_never_says_confined_for_best_effort() -> None:
    text = _flat(approval_sandbox_line(SandboxPosture("w", BEST_EFFORT), 80))
    assert "NOT confined on this machine" in text
    assert "confined to the project folder" not in text


def test_the_approval_line_says_enforced_only_when_enforced() -> None:
    assert "confined to the project folder" in _flat(
        approval_sandbox_line(SandboxPosture("l", ENFORCED), 80)
    )


def test_backend_names_are_escaped() -> None:
    assert "\x1b" not in sandbox_line(SandboxPosture("evil\x1b[31m", ENFORCED))
    assert escape_controls("a\x07b") == "a\\x07b"
