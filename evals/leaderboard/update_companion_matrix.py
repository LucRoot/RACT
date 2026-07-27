"""COMPANION_MATRIX regenerator — ALM module_04.

Reads the most recent conformance report per provider under
``evals/conformance/results/`` and regenerates
``evals/conformance/COMPANION_MATRIX.md`` — a table mapping every
registered provider to the set of providers eligible as its companion.

Eligibility per ALM §3.7:

- Different training family from the primary.
- Current anti-lazy conformance score ≥ 0.7.
- Current schema conformance score ≥ 0.9.

The script is idempotent (Lateral Chain branch E, module_07): running
it without new inputs leaves the output file byte-identical, so a
no-op nightly run produces no commit.

Providers whose report is missing the ``anti_lazy`` category (produced
before ALM was released) are excluded from both roles — the matrix
does not silently admit an unmeasured provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ANTI_LAZY_MIN: float = 0.7
DEFAULT_SCHEMA_MIN: float = 0.9


# Training-family classification. Providers not in the map are treated
# as their own singleton family. The map is intentionally coarse — it
# only needs to distinguish families that share a common training
# regime enough to share blind spots.
_TRAINING_FAMILY: dict[str, str] = {
    "openai": "openai",
    "gpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "google": "google",
    "gemini": "google",
    "flash": "google",
    "mistral": "mistral",
    "magistral": "mistral",
    "nvidia": "nvidia",
    "nemotron": "nvidia",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "minimax": "minimax",
    "openrouter": "openrouter",
    "fake": "fake",
}


def _family_for(provider_name: str) -> str:
    """Return the training family for ``provider_name``.

    Case-insensitive substring match against the ``_TRAINING_FAMILY``
    keys; falls back to the provider name itself when nothing matches.
    """
    low = provider_name.lower()
    for token, family in _TRAINING_FAMILY.items():
        if token in low:
            return family
    return low


@dataclass(frozen=True)
class ProviderRow:
    """One row in the matrix — the provider plus its scores."""

    name: str
    family: str
    anti_lazy_score: float
    schema_score: float

    def eligible_as_companion(
        self,
        *,
        anti_lazy_min: float = DEFAULT_ANTI_LAZY_MIN,
        schema_min: float = DEFAULT_SCHEMA_MIN,
    ) -> bool:
        """True iff the row's scores meet the companion floor."""
        return (
            self.anti_lazy_score >= anti_lazy_min
            and self.schema_score >= schema_min
        )


def _latest_report_per_provider(results_root: Path) -> dict[str, Path]:
    """Return the newest ``<provider>-<date>.json`` per provider."""
    if not results_root.is_dir():
        return {}
    latest: dict[str, Path] = {}
    for path in sorted(results_root.glob("*.json")):
        # Report file names are ``<provider>-<yyyy-mm-dd>.json`` per
        # ``ract.providers.conformance.write_report``. Split on the
        # last dash-date pattern.
        name = path.stem
        parts = name.rsplit("-", 3)
        if len(parts) < 4:
            continue
        provider = parts[0]
        # Lexicographic sort works because dates are ISO-8601.
        prev = latest.get(provider)
        if prev is None or path.name > prev.name:
            latest[provider] = path
    return latest


def _load_provider_row(path: Path) -> ProviderRow | None:
    """Parse one conformance report into a ``ProviderRow`` (or None)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    provider = data.get("provider")
    if not isinstance(provider, str):
        return None
    categories = data.get("categories")
    if not isinstance(categories, dict):
        return None
    al = categories.get("anti_lazy")
    sc = categories.get("schema_compliance")
    if not isinstance(al, dict) or not isinstance(sc, dict):
        return None
    return ProviderRow(
        name=provider,
        family=_family_for(provider),
        anti_lazy_score=float(al.get("score", 0.0)),
        schema_score=float(sc.get("score", 0.0)),
    )


def _render_matrix(
    rows: list[ProviderRow],
    *,
    anti_lazy_min: float = DEFAULT_ANTI_LAZY_MIN,
    schema_min: float = DEFAULT_SCHEMA_MIN,
) -> str:
    """Return the Markdown body for ``COMPANION_MATRIX.md``.

    Rows are sorted by provider name (ASCII ascending) for determinism
    across regens (idempotence).
    """
    sorted_rows = sorted(rows, key=lambda r: r.name)
    header = (
        "# Companion Matrix\n\n"
        "**ALM module_04 (G7).** Every registered provider mapped to "
        "the set of providers eligible as its companion. Eligibility "
        f"(ALM §3.7): different training family, anti-lazy conformance "
        f"score >= {anti_lazy_min:.2f}, schema conformance score >= "
        f"{schema_min:.2f}. Regenerated idempotently by "
        "``evals/leaderboard/update_companion_matrix.py``.\n\n"
        "## Scored providers\n\n"
        "| Provider | Family | Anti-lazy | Schema | Eligible-companion count |\n"
        "|---|---|---|---|---|\n"
    )
    lines: list[str] = [header]
    if not sorted_rows:
        lines.append(
            "| _(none)_ | _(no scored providers)_ | - | - | 0 |\n"
        )
    else:
        for row in sorted_rows:
            companion_count = sum(
                1
                for other in sorted_rows
                if other.name != row.name
                and other.family != row.family
                and other.eligible_as_companion(
                    anti_lazy_min=anti_lazy_min, schema_min=schema_min
                )
            )
            lines.append(
                f"| {row.name} | {row.family} | "
                f"{row.anti_lazy_score:.3f} | {row.schema_score:.3f} | "
                f"{companion_count} |\n"
            )
    # Pairs table.
    lines.append("\n## Eligible pairs\n\n")
    lines.append("| Primary | Eligible companions |\n")
    lines.append("|---|---|\n")
    if not sorted_rows:
        lines.append("| _(none)_ | _(no scored providers)_ |\n")
    else:
        for row in sorted_rows:
            eligibles = [
                other.name
                for other in sorted_rows
                if other.name != row.name
                and other.family != row.family
                and other.eligible_as_companion(
                    anti_lazy_min=anti_lazy_min, schema_min=schema_min
                )
            ]
            cell = ", ".join(sorted(eligibles)) if eligibles else "_(none)_"
            lines.append(f"| {row.name} | {cell} |\n")
    lines.append(
        "\n## Notes\n\n"
        "- Providers with a missing ``anti_lazy`` or "
        "``schema_compliance`` category are excluded from both roles.\n"
        "- Training family is a coarse substring match against known "
        "identifiers (openai, anthropic, google, gemini, mistral, "
        "nvidia, nemotron, deepseek, qwen, minimax); unknown "
        "providers are treated as their own singleton family.\n"
        "- Same-family pairings are refused even when scores clear "
        "the floor — shared training regimes share blind spots (ALM "
        "§3.7 rejected alternative: same-provider companion).\n"
        "- The `single_provider_advisory` deployment mode (lateral "
        "chain branch D) opts a run into advisory-only companion "
        "findings without changing this matrix.\n"
        "\nRACT 0.4.0\n"
    )
    return "".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` iff it would change. Returns True on write.

    Idempotence guard: a no-op run must not modify the file's mtime
    (Lateral Chain branch E). Compares byte-for-byte before opening
    the file for write.
    """
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == content:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def regenerate_companion_matrix(
    *,
    results_root: Path,
    output_path: Path,
    anti_lazy_min: float = DEFAULT_ANTI_LAZY_MIN,
    schema_min: float = DEFAULT_SCHEMA_MIN,
) -> tuple[bool, list[ProviderRow]]:
    """Regenerate the matrix; return ``(changed, rows)``."""
    reports = _latest_report_per_provider(results_root)
    rows: list[ProviderRow] = []
    for path in reports.values():
        row = _load_provider_row(path)
        if row is None:
            continue
        rows.append(row)
    body = _render_matrix(
        rows, anti_lazy_min=anti_lazy_min, schema_min=schema_min
    )
    changed = _write_if_changed(output_path, body)
    return changed, rows


def main(argv: list[str] | None = None) -> int:
    """CLI entry — reads from `evals/conformance/results/`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("evals/conformance/results"),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("evals/conformance/COMPANION_MATRIX.md"),
    )
    parser.add_argument(
        "--anti-lazy-min",
        type=float,
        default=DEFAULT_ANTI_LAZY_MIN,
    )
    parser.add_argument(
        "--schema-min",
        type=float,
        default=DEFAULT_SCHEMA_MIN,
    )
    args = parser.parse_args(argv)
    changed, rows = regenerate_companion_matrix(
        results_root=args.results_root,
        output_path=args.output_path,
        anti_lazy_min=args.anti_lazy_min,
        schema_min=args.schema_min,
    )
    print(
        f"companion matrix: {len(rows)} scored provider(s); "
        f"{'wrote' if changed else 'no change'} {args.output_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())


# RACT 0.4.0
