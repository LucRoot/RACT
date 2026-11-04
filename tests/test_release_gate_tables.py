"""B-051: the release gate reads the severity-1 rows of docs/ux/*/defects.md.

The gate script is loaded from its file, because scripts/ is not a package.
Every table check names the row it fails on.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release_gate.py"


def _gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


HEADER = (
    "| Id | Journey | Sev | What happens | Evidence | Card | Status |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _table(*rows: str) -> str:
    return "# Defects\n\n" + HEADER + "".join(row + "\n" for row in rows)


def _row(
    id_: str = "UX-01",
    sev: str = "S1",
    status: str = "fixed (S-011)",
    *,
    cells: int | None = None,
) -> str:
    fields = [id_, "J4", sev, "what happens", "file", "card", status]
    if cells is not None:
        fields = fields[:cells]
    return "| " + " | ".join(fields) + " |"


def _write(root: Path, folder: str, text: str) -> Path:
    path = root / "docs" / "ux" / folder / "defects.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 1. well formed


def test_a_well_formed_table_passes() -> None:
    gate = _gate()
    rows = gate.parse_defects(_table(_row(), _row("UX-02", "S2", "open")))
    assert gate.validate(rows) == []
    assert [r.id for r in rows] == ["UX-01", "UX-02"]


# ---------------------------------------------------------------- 2. bad rows


def test_a_row_without_a_status_cell_fails_with_its_id() -> None:
    gate = _gate()
    rows = gate.parse_defects(_table(_row("UX-07", cells=6)))
    errors = gate.validate(rows)
    assert errors and "UX-07" in errors[0]


@pytest.mark.parametrize("status", ["done", "closed", "wip", "fixed"])
def test_a_status_word_outside_the_list_fails_with_its_id(status: str) -> None:
    gate = _gate()
    errors = gate.validate(gate.parse_defects(_table(_row("UX-08", status=status))))
    assert errors and "UX-08" in errors[0]


def test_fixed_with_nothing_in_the_parentheses_fails_with_its_id() -> None:
    gate = _gate()
    errors = gate.validate(gate.parse_defects(_table(_row("UX-09", status="fixed ()"))))
    assert errors and "UX-09" in errors[0]


def test_a_table_without_a_status_column_is_named() -> None:
    gate = _gate()
    text = (
        "| Id | Journey | Sev | What happens | Evidence | Card |\n"
        "|---|---|---|---|---|---|\n"
        "| UX-10 | J3 | S1 | x | y | z |\n"
    )
    errors = gate.validate(gate.parse_defects(text))
    assert errors and "UX-10" in errors[0] and "Status" in errors[0]


def test_the_allowed_status_words_pass() -> None:
    gate = _gate()
    statuses = [
        "open",
        "fixed (S-011)",
        "blocked (B-010, gated)",
        "not testable today (B-011)",
        "accepted (OPERATOR)",
    ]
    rows = gate.parse_defects(
        _table(*(_row(f"UX-2{i}", "S2", s) for i, s in enumerate(statuses)))
    )
    assert gate.validate(rows) == []


# ---------------------------------------------------------------- 3. the gate


def test_one_open_s1_row_exits_1_and_names_it(tmp_path: Path) -> None:
    _write(tmp_path, "fixture", _table(_row("UX-30", "S1", "open")))
    code, out = _run_gate(tmp_path)
    assert code == 1
    assert "UX-30" in out


def test_only_fixed_and_accepted_rows_exit_0(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "fixture",
        _table(
            _row("UX-31", "S1", "fixed (B-043)"),
            _row("UX-32", "S1", "accepted (OPERATOR)"),
        ),
    )
    code, _ = _run_gate(tmp_path)
    assert code == 0


def test_open_s2_and_s3_rows_exit_0(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "fixture",
        _table(_row("UX-33", "S2", "open"), _row("UX-34", "S3", "open")),
    )
    code, _ = _run_gate(tmp_path)
    assert code == 0


def test_a_blocked_s1_row_holds_the_gate(tmp_path: Path) -> None:
    _write(tmp_path, "fixture", _table(_row("UX-35", "S1", "blocked (B-010, gated)")))
    code, out = _run_gate(tmp_path)
    assert code == 1 and "UX-35" in out


# ---------------------------------------------------------------- 4. no S1 rows


def test_a_folder_with_no_s1_rows_passes(tmp_path: Path) -> None:
    _write(tmp_path, "fixture", _table(_row("UX-36", "S3", "open")))
    code, _ = _run_gate(tmp_path)
    assert code == 0


# ---------------------------------------------------------------- 5. files only


def test_the_script_reads_files_only_and_takes_root_from_the_argument(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    _write(root, "fixture", _table(_row("UX-37", "S1", "open")))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 1
    assert "UX-37" in proc.stdout


# ---------------------------------------------------------------- the real tree


def test_every_defects_table_in_the_repository_is_well_formed() -> None:
    gate = _gate()
    errors: list[str] = []
    for path in sorted((REPO / "docs" / "ux").glob("*/defects.md")):
        errors += gate.validate(gate.parse_defects(path.read_text(encoding="utf-8")))
    assert errors == []


def _run_gate(root: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return proc.returncode, proc.stdout


@pytest.mark.parametrize("sev", ["s1", "S 1", "P1", ""])
def test_a_severity_outside_s1_s2_s3_is_a_table_error_naming_the_row(sev: str) -> None:
    gate = _gate()
    errors = gate.validate(gate.parse_defects(_table(_row("UX-40", sev, "open"))))
    assert errors and "UX-40" in errors[0]


def test_a_gate_with_a_bad_severity_exits_1_even_with_no_open_s1(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "fixture", _table(_row("UX-41", "s1", "fixed (B-043)")))
    code, out = _run_gate(tmp_path)
    assert code == 1 and "UX-41" in out


def test_the_real_tree_is_held_by_the_two_gated_journey_rows() -> None:
    # G-098: UX-07 (J3) and UX-08 (J4) were severity 1, blocked by the tool
    # layer. The interactive session shipped the fix (read tools and checked
    # citations; change screens, /diff, /undo, granted test runs), re-verified
    # on the release tip by the expectations audit and the live user test, and
    # the rows were closed for the v0.6.0 cut (release(v0.6.0)-prep). The pin
    # now holds the closed state: the gate exits 0 and no S1 row is open.
    code, out = _run_gate(REPO)
    assert code == 0, out
    assert "OPEN S1" not in out
