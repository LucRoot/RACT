# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass


@dataclass
class EdgeCaseTest:
    """A single generated edge-case test."""

    description: str
    inputs: dict[str, object]
    expected_error: str | None = None
    expected_output: object | None = None


class AutomatedTestCaseGenerator:
    """Generate edge-case tests from a user story.

    The generator is intentionally deterministic: it parses the story for
    common risk signals (empty input, huge values, missing fields) and emits
    focused ``EdgeCaseTest`` records that a downstream fixture builder can turn
    into pytest cases.
    """

    def generate(self, story: str) -> list[EdgeCaseTest]:
        """Return edge-case tests derived from ``story``."""
        story = story.strip()
        if not story:
            return []

        tests: list[EdgeCaseTest] = []
        lowered = story.lower()

        # Empty / missing inputs.
        if "input" in lowered or "value" in lowered or "field" in lowered:
            tests.append(
                EdgeCaseTest(
                    description="empty input",
                    inputs={},
                    expected_error="ValueError",
                )
            )
            tests.append(
                EdgeCaseTest(
                    description="missing required field",
                    inputs={"required": None},
                    expected_error="ValueError",
                )
            )

        # Boundary size.
        if "size" in lowered or "length" in lowered or "count" in lowered:
            tests.append(
                EdgeCaseTest(
                    description="maximum allowed size",
                    inputs={"size": 100},
                    expected_output="ok",
                )
            )
            tests.append(
                EdgeCaseTest(
                    description="size exceeding limit",
                    inputs={"size": 101},
                    expected_error="ValueError",
                )
            )

        # Numeric boundaries.
        if "number" in lowered or "amount" in lowered or "balance" in lowered:
            tests.append(
                EdgeCaseTest(
                    description="zero value",
                    inputs={"value": 0},
                    expected_output="ok",
                )
            )
            tests.append(
                EdgeCaseTest(
                    description="negative value",
                    inputs={"value": -1},
                    expected_error="ValueError",
                )
            )

        # If no signals matched, emit a generic invalid-input case.
        if not tests:
            tests.append(
                EdgeCaseTest(
                    description="unexpected input type",
                    inputs={"value": object()},
                    expected_error="TypeError",
                )
            )

        return tests


# RACT 0.1.0 - Initial Public Release
