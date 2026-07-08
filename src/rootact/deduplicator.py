from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DeduplicationResult:
    unique_items: List[str]
    original_count: int
    deduplicated_count: int


def deduplicate_strings(items: List[str]) -> DeduplicationResult:
    """Return a deterministic deduplication report for a list of strings.

    This helper is pure and side‑effect free, making it safe for use in
    tests and CI pipelines. It reports how many items were present originally
    and how many remain after duplicate removal.
    """
    seen = set()
    unique_items = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return DeduplicationResult(
        unique_items=unique_items,
        original_count=len(items),
        deduplicated_count=len(unique_items),
    )


if __name__ == "__main__":
    # Simple manual sanity check
    sample = ["a", "b", "a", "c"]
    result = deduplicate_strings(sample)
    print(result)
# RACT 0.1.0 - Initial Public Release
