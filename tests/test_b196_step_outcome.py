"""B-196: a step is refused exactly when the turn would exit 3; a provider failure is failed.

``unfinished_step_outcome`` and the substrate path called a step refused when
its error held the word "refused", so a provider that was down ("connection
refused") gave a refused step under a failed turn that exited 6.
"""

from __future__ import annotations

import pytest

from ract.executor.steps import step_outcome, unfinished_step_outcome
from ract.session_turn import exit_code_for


@pytest.mark.parametrize(
    ("error", "outcome", "code"),
    [
        ("Request failed: nothing is answering at http://127.0.0.1:9/v1 (connection refused).", "failed", 6),
        ("ConnectError: [WinError 10061] No connection could be made because the target machine actively refused it", "failed", 6),
        ("refused: the path is outside the project", "refused", 3),
        ("not written: path refused (.git/config)", "refused", 3),
        ("Preflight validation failed for step 1", "refused", 3),
        ("the step's tests failed", "failed", 1),
        ("api_key in ract.yaml names ${X}, and X is not set in this environment; nothing was sent", "failed", 2),
    ],
)
def test_the_step_outcome_follows_the_turn_exit_code(error: str, outcome: str, code: int) -> None:
    assert exit_code_for(error) == code
    assert step_outcome(error) == outcome
    assert unfinished_step_outcome(error, cancelled=False) == outcome


def test_an_interrupted_step_is_skipped() -> None:
    assert unfinished_step_outcome("refused: anything", cancelled=True) == "skipped"
