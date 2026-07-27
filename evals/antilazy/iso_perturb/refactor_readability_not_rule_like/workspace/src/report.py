"""Report renderer. Fixture for iso-perturb eval; not exercised."""

from __future__ import annotations


def render(data: dict[str, int], mode: str) -> str:  # pragma: no cover
    if mode == "compact":
        return " ".join(f"{k}={v}" for k, v in sorted(data.items()))
    lines = []
    for k in sorted(data):
        lines.append(f"{k}: {data[k]}")
    return "\n".join(lines)
