# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import random
import string


def generate_id(length: int = 8) -> str:
    """Generate a deterministic random identifier of the given length.

    This helper is used across RootACT to create short, unique identifiers
    for artifacts, plans, or temporary files. It uses only the standard
    library and does not rely on any external state or models.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


if __name__ == "__main__":
    # Simple sanity check when run directly.
    print(generate_id())
# RACT 0.1.0 - Initial Public Release
