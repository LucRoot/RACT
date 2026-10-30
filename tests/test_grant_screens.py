"""B-111 screens: the guided grant flow, the policy diff, the passphrase step, the signed result and
/permissions (ADR-0048 D13 and D3). Pure text at 80, 60 and 40 columns, plain and rich. The network
line never claims a sandbox that does not enforce (G1). Nothing is signed or read here.
"""

from __future__ import annotations

import re

import pytest

from ract.ui.grant_screens import (
    PASSPHRASE_PROMPT,
    DetectedRunner,
    PermissionsView,
    ProposedRule,
    detected_runner_lines,
    escape_controls,
    field_explanation_lines,
    passphrase_prompt_lines,
    permissions_lines,
    policy_diff_lines,
    proposed_rule_lines,
    signed_result_lines,
    sign_question_lines,
)

WIDTHS = (80, 60, 40)
MARKUP = re.compile(r"\[/?bold\]")


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(MARKUP.sub("", line) for line in lines).split())


RUNNER = DetectedRunner(
    name="pytest",
    argv=("python", "-m", "pytest"),
    evidence="pyproject.toml has [tool.pytest]",
)
RULE = ProposedRule(
    rule_id="R-1", argv=("python", "-m", "pytest"), sandbox_enforced=False
)


@pytest.mark.parametrize("width", WIDTHS)
def test_the_detected_runner_names_the_rule_and_the_evidence(width: int) -> None:
    lines = detected_runner_lines(RUNNER, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "found the test runner: pytest" in text
    assert "the rule would allow: python -m pytest" in text
    assert "seen in: pyproject.toml has [tool.pytest]" in text


def test_no_runner_says_nothing_to_grant() -> None:
    assert "nothing to grant yet" in _flat(detected_runner_lines(None, 80))


@pytest.mark.parametrize("width", WIDTHS)
def test_every_field_has_one_explanation_line_and_fits(width: int) -> None:
    lines = field_explanation_lines(RULE, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "argv: python -m pytest" in text
    assert "time limit: 15 minutes" in text
    assert "working folder: ." in text
    assert "environment passed: none beyond the defaults" in text
    assert "home: isolated" in text


def test_the_network_line_does_not_claim_an_unenforced_sandbox() -> None:
    text = _flat(field_explanation_lines(RULE, 80))
    assert "network: off: declared off; this machine does not enforce it" in text
    assert "it runs with your user's rights on this machine" in text
    enforced = ProposedRule(rule_id="R-2", argv=("python",), sandbox_enforced=True)
    text_enforced = _flat(field_explanation_lines(enforced, 80))
    assert "network: off: the command runs without the network" in text_enforced
    assert "your user's rights" not in text_enforced


def test_network_on_is_said_plainly() -> None:
    rule = ProposedRule(rule_id="R-3", argv=("python",), network=True)
    assert "network: on: the command may reach the network" in _flat(
        field_explanation_lines(rule, 80)
    )


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_proposed_rule_screen_fits_in_plain_and_rich(
    width: int, rich: bool
) -> None:
    lines = proposed_rule_lines(RULE, width, rich=rich)
    for line in lines:
        assert len(MARKUP.sub("", line)) <= width, line
    assert "proposed rule R-1" in _flat(lines)


def test_the_policy_diff_is_shown_escaped_and_folded() -> None:
    lines = policy_diff_lines(
        ["+  - argv: [python, -m, pytest]", "-  network: true\x1b[31m"], 40
    )
    for line in lines:
        assert len(line) <= 40, line
    joined = "\n".join(lines)
    assert "\x1b" not in joined and "\\x1b" in joined


def test_an_empty_diff_says_the_file_would_not_change() -> None:
    assert policy_diff_lines([], 80) == ["the policy file would not change"]


@pytest.mark.parametrize("width", WIDTHS)
def test_the_passphrase_prompt_is_typed_and_refuses_without_a_terminal(
    width: int,
) -> None:
    text = _flat(passphrase_prompt_lines(width, has_terminal=True))
    assert " ".join(PASSPHRASE_PROMPT.split()) in text
    assert "never read from an environment variable" in text
    refusal = _flat(passphrase_prompt_lines(width, has_terminal=False))
    assert "nothing was signed" in refusal


@pytest.mark.parametrize("width", WIDTHS)
def test_the_signed_result_names_the_rule_expiry_and_status(width: int) -> None:
    lines = signed_result_lines("R-1", "2027-01-30", "T3 ask", width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "signed: rule R-1 expires 2027-01-30" in text
    assert "status line now: T3 ask" in text


def test_the_sign_question_has_the_choices() -> None:
    assert "[y]es, sign once" in _flat(sign_question_lines(80))


@pytest.mark.parametrize("width", WIDTHS)
def test_permissions_shows_rules_deny_mode_expiry_and_sandbox(width: int) -> None:
    view = PermissionsView(
        rules=(RULE,),
        deny=("git push",),
        max_mode="ask",
        expires="2027-01-30",
        sandbox_enforced=False,
        notes=["a grant expiring within 7 days adds a notice"],
    )
    lines = permissions_lines(view, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "rule R-1: python -m pytest" in text
    assert "deny: git push" in text
    assert "largest mode: ask" in text
    assert "expires: 2027-01-30" in text
    assert "sandbox: best effort, not enforced on this machine" in text


def test_permissions_with_no_rule_says_so() -> None:
    assert "no rule is granted" in _flat(permissions_lines(PermissionsView(), 80))


def test_control_characters_in_names_are_escaped() -> None:
    assert escape_controls("a\x07b") == "a\\x07b"
    lines = field_explanation_lines(
        ProposedRule(rule_id="R", argv=("evil\x1b[31m",), cwd="x‮"), 40
    )
    joined = "\n".join(lines)
    assert "\x1b" not in joined and "‮" not in joined
