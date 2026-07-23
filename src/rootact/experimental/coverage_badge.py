# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Generate a simple SVG coverage badge."""

from pathlib import Path


def _color_for_coverage(coverage_pct: float) -> str:
    if coverage_pct >= 80:
        return "#4c1"
    if coverage_pct >= 50:
        return "#dfb317"
    return "#e05d44"


def generate_svg(coverage_pct: float, output_path: Path | str) -> Path:
    """Write a Shields-style SVG badge for the given coverage percentage."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    color = _color_for_coverage(coverage_pct)
    label = "coverage"
    message = f"{coverage_pct:.0f}%"
    label_width = 70
    message_width = 50
    total_width = label_width + message_width
    label_x = label_width / 2
    message_x = label_width + message_width / 2
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" '
        f'role="img" aria-label="{label}: {message}">\n'
        f'  <title>{label}: {message}</title>\n'
        f'  <g shape-rendering="crispEdges">\n'
        f'    <rect width="{label_width}" height="20" fill="#555"/>\n'
        f'    <rect x="{label_width}" width="{message_width}" height="20" fill="{color}"/>\n'
        f'  </g>\n'
        f'  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">\n'
        f'    <text x="{label_x}" y="14">{label}</text>\n'
        f'    <text x="{message_x}" y="14">{message}</text>\n'
        f'  </g>\n'
        f'</svg>\n'
    )
    output_path.write_text(svg, encoding="utf-8")
    return output_path


# RACT 0.1.2 - Trust and tooling
