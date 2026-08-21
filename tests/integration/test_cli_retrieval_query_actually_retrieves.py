"""``ract retrieval query`` returns real chunks (Lens A C3 closure).

v0.5.1 wiring module_10: the prior stub echoed the query params and
printed a "queued for v0.6" note; nothing exercised the ``retrieve()``
primitive. The regression here builds a symbol index in a tmp
workspace and asserts the CLI command's stdout carries a real
matched-chunk line, not the stub message.
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

import pytest

from ract.memory.cli_memory import retrieval_query_command


def _run_query(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = retrieval_query_command(argv)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def prepped_workspace(tmp_path: Path) -> Path:
    """Build a symbol index over one tiny Python file."""
    from ract.memory import walker
    from ract.memory.symbol_index import SymbolIndex

    src = tmp_path / "src"
    src.mkdir()
    (src / "widget.py").write_text(
        "def widget_maker():\n"
        "    '''return a widget'''\n"
        "    return 'widget'\n"
        "\n"
        "def unrelated_util():\n"
        "    return 42\n",
        encoding="utf-8",
    )

    memory_root = tmp_path / ".ract" / "memory"
    memory_root.mkdir(parents=True)
    db_path = memory_root / "symbols.db"
    idx = SymbolIndex(db_path=str(db_path))
    walker.initial_build(tmp_path, idx)
    return tmp_path


def test_retrieval_query_returns_real_chunk_on_symbol_match(
    prepped_workspace: Path,
) -> None:
    """Query for a known symbol -> stdout contains the chunk body, not stub text."""
    code, out, err = _run_query(
        [
            "widget_maker",
            "--repo-path",
            str(prepped_workspace),
            "--budget",
            "8000",
        ]
    )
    assert code == 0, err
    # Concrete signal the chunk landed: the function body or signature
    # must appear. The stub message MUST NOT appear.
    assert "widget_maker" in out
    assert (
        "queued for v0.6" not in out
        and "full retrieve() wiring" not in out
    ), "stub message leaked through -- retrieval query still not wired"


def test_retrieval_query_json_output_carries_chunks(prepped_workspace: Path) -> None:
    """JSON output includes a chunks[] array with at least one entry."""
    import json

    code, out, err = _run_query(
        [
            "widget_maker",
            "--repo-path",
            str(prepped_workspace),
            "--json",
        ]
    )
    assert code == 0, err
    payload = json.loads(out)
    assert "chunks" in payload
    assert len(payload["chunks"]) >= 1
    # At least one chunk names the queried symbol.
    assert any("widget_maker" in c.get("symbol_name", "") for c in payload["chunks"])


def test_retrieval_query_reports_missing_indexes_cleanly(tmp_path: Path) -> None:
    """Fresh workspace with no indexes: clean warn + exit 0, not traceback."""
    code, out, err = _run_query(
        [
            "widget_maker",
            "--repo-path",
            str(tmp_path),
        ]
    )
    assert code == 0
    combined = out + err
    assert "no indexes found" in combined.lower() or "ract memory init" in combined


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C3 regression)
