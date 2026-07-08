# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.manager import Plan, Step


class Intent:
    """A parsed intent representing a user goal."""

    def __init__(self, description: str, confidence: float, plan: Plan) -> None:
        self.description = description
        self.confidence = confidence
        self.plan = plan


class IntentParser:
    """Simple intent parser that converts text into a Plan of Steps."""

    def parse(self, text: str) -> Intent:
        """Convert a natural language description into an Intent with a Plan.

        The implementation is deterministic and uses only the Step and Plan
        dataclasses from rootact.manager. It extracts a single action, infers a
        provider hint, and sets a placeholder expected artifact.
        """
        text = text.strip().lower()
        if "list" in text or "find" in text or "show" in text:
            action = "list"
        elif "create" in text or "add" in text:
            action = "create"
        elif "delete" in text or "remove" in text:
            action = "delete"
        else:
            action = "noop"

        provider_hint = "default"
        expected_artifact = "output"

        step = Step(
            action=action,
            provider_hint=provider_hint,
            expected_artifact=expected_artifact,
        )
        plan = Plan(assumption=text, confidence=0.9, steps=[step])
        return Intent(description=text, confidence=0.9, plan=plan)


if __name__ == "__main__":
    parser = IntentParser()
    intent = parser.parse("List recent blog posts")
    print(intent.plan.steps[0].action)
