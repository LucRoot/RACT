"""B-210: the doctor's advice and the model view wrap by terminal columns.

``textwrap`` counts characters, so a line of wide characters (two columns
each) ran past the width in ``doctor_advice.render`` and ``model_view``.
"""

from __future__ import annotations

from rich.cells import cell_len

from ract import doctor_advice


def test_doctor_advice_fits_wide_text_by_columns() -> None:
    rows = doctor_advice.render(["provider 'x': " + "日本語のテキスト" * 8], 40)
    assert len(rows) > 1
    assert all(cell_len(row) <= 40 for row in rows), rows
    assert all(row.startswith("  ") for row in rows[1:])
