"""S-017: the corrected sentences say what docs/CLAIMS_AUDIT_2.md records."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TABLE = (ROOT / "docs" / "CLAIMS_AUDIT_2.md").read_text(encoding="utf-8")

ROWS = [
    (
        "README.md",
        "upload to a signed archive",
        # B-133: a colon after the verb in README's index.
        "`ract receipt-export`: Print the signed receipts in a directory as JSON.",
    ),
    (
        "docs/QUICKSTART.md",
        "signed skill templates",
        "RACT ships skill templates for common tasks (they are not signed):",
    ),
    (
        "docs/PHILOSOPHY.md",
        "derived from a signed capability manifest",
        "no backend enforces it",
    ),
]


@pytest.mark.parametrize("doc, false_claim, now", ROWS, ids=[r[0] for r in ROWS])
def test_a_false_claim_is_gone_and_the_table_names_the_text_now(
    doc, false_claim, now
) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert false_claim not in text
    assert now in " ".join(text.split())
    assert false_claim in TABLE  # the table records what was claimed


def test_every_row_says_true_or_false() -> None:
    rows = [
        line
        for line in TABLE.splitlines()
        if line.startswith("| ") and "---" not in line
    ]
    verdicts = [line.split("|")[2].strip() for line in rows[1:]]
    assert verdicts and set(verdicts) <= {"true", "false"}
