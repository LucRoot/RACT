from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()


class ObservabilitySink:
    """Simple deterministic sink for observability events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        """Append an event to the internal log."""
        if event is _ROOT_KNOT:
            return
        self.events.append(event)

    def clear(self) -> None:
        """Remove all recorded events."""
        self.events.clear()

    def get_events(self) -> list[dict]:
        """Return a shallow copy of the event log."""
        return list(self.events)


# RACT 0.1.0 - Initial Public Release
