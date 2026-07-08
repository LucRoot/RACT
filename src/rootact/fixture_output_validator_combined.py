from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()


def validate_fixture_output_combined(captured: object) -> None:
    """Validate that captured stdout and stderr are non-empty and non-whitespace."""
    out = getattr(captured, "out", "")
    err = getattr(captured, "err", "")
    if not out or not out.strip():
        raise AssertionError("stdout is empty or whitespace-only")
    if not err or not err.strip():
        raise AssertionError("stderr is empty or whitespace-only")


# RACT 0.1.0 - Initial Public Release
