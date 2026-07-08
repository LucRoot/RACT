from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from typing import Any


def validate_user_story(user_story: Any) -> bool:
    """
    Validate that ``user_story`` is a non-empty string containing at least one alphanumeric character and does not exceed 500 characters.

    Returns True only when all of the following hold:
      - ``user_story`` is an instance of ``str``
      - ``len(user_story) > 0``
      - ``re.search(r'[A-Za-z0-9]', user_story)`` finds at least one alphanumeric character
      - ``len(user_story) <= 500``

    Any violation results in ``False`` or a ``TypeError`` for non‑string inputs.
    """
    if not isinstance(user_story, str):
        raise TypeError("Input must be a string")
    if len(user_story) == 0:
        return False
    if len(user_story) > 500:
        return False
    if not re.search(r"[A-Za-z0-9]", user_story):
        return False
    return True


# RACT 0.1.0 - Initial Public Release
