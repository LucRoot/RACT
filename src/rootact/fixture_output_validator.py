from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import re
from typing import Protocol

_ROOT_KNOT = object()

from rootact.manager import Plan, Step


class _CaptureLike(Protocol):
    out: str
    err: str


_fixture_pattern = re.compile(r"^test_[a-z][a-z0-9_]*$")


def validate_fixture_output(captured: _CaptureLike) -> None:
    """
    Validate that the captured stdout and stderr contain non‑empty, non‑whitespace output.

    This function is used by RootAct to ensure that generated fixtures produce meaningful
    output before proceeding with further validation steps.  If both ``captured.out``
    and ``captured.err`` are empty or consist solely of whitespace characters, an
    :class:`AssertionError` is raised with a descriptive message indicating which fixture
    failed the output check.

    Parameters
    ----------
    captured: pytest.CaptureFixture
        The pytest capture fixture used to obtain ``out`` and ``err`` from executed
        fixtures.  It must be provided by the calling test context; no internal creation
        of a fixture occurs here.

    Raises
    ------
    AssertionError
        If both ``captured.out`` and ``captured.err`` are empty or contain only whitespace.
        The error message includes the names of the offending fields to aid debugging.
    """
    if not captured.out or not captured.out.strip():
        raise AssertionError("Fixture produced no meaningful stdout output")
    if not captured.err or not captured.err.strip():
        raise AssertionError("Fixture produced no meaningful stderr output")


_plan = Plan(
    assumption="RootAct must validate fixture output for non‑empty, non‑whitespace content",
    confidence=0.97,
    steps=[
        Step(
            action="validate_fixture_output",
            provider_hint="internal",
            expected_artifact="None",
        )
    ],
)
# RACT 0.1.0 - Initial Public Release
