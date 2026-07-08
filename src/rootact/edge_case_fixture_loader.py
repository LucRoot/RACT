from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from typing import Dict, Callable, Optional

from rootact.manager import Plan, Step

_fixture_pattern = re.compile(r"^test_[a-z][a-z0-9_]*$")


def load_and_validate_fixtures(
    fixture_dict: Dict[str, Callable[[], None]],
    capsys,
    expected_error: Optional[str] = None,
) -> Dict[str, str]:
    """
    Load each fixture in *fixture_dict*, execute it, capture both stdout and stderr
    via ``capsys.readouterr()``, and validate the output.

    Each fixture must produce non-empty output on stdout or stderr. If
    *expected_error* is supplied, the combined output must contain that substring.
    On validation failure an :class:`AssertionError` is raised naming the fixture.
    """
    validated_outputs: Dict[str, str] = {}
    for name, func in fixture_dict.items():
        func()
        captured = capsys.readouterr()
        combined_output = captured.out + captured.err
        if not combined_output.strip():
            raise AssertionError(
                f"Fixture '{name}' did not produce output on stdout or stderr"
            )
        if expected_error is not None and expected_error not in combined_output:
            raise AssertionError(
                f"Fixture '{name}' output does not contain expected error substring: {expected_error!r}"
            )
        validated_outputs[name] = combined_output
    return validated_outputs


_plan = Plan(
    assumption="RootAct must load and validate fixtures while respecting stdlib_only and capture semantics",
    confidence=0.95,
    steps=[
        Step(
            action="load_and_validate_fixtures",
            provider_hint="internal",
            expected_artifact="None",
        )
    ],
)
