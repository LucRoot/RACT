"""B-076: every ``ract`` command in the user docs is run by a test or checked.

Classes: ``run`` (the allowlist below, run in a scratch project against the
fake server), ``flag`` (verb and every ``--flag`` checked against the parser;
never run), ``never`` (not run, not parsed for flags: installs, deletes, pushes,
network hosts, or anything with a shell metacharacter). A doc line is never
passed to a shell.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.docs.doc_commands import (
    DOC_FILES,
    classify,
    extract_blocks,
    check_block,
    scan,
)

ROOT = Path(__file__).resolve().parents[2]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_wrong_flag_fails_with_its_file_and_line(tmp_path):
    doc = _write(tmp_path, "intro\n\n```bash\nract run --no-such-flag x\n```\n")
    blocks = extract_blocks(doc)
    assert len(blocks) == 1
    assert blocks[0].line == 4
    result = check_block(blocks[0])
    assert result.status == "fail"
    assert "--no-such-flag" in result.reason
    assert f"{doc.name}:4" in result.where


def test_a_correct_flag_passes(tmp_path):
    doc = _write(tmp_path, "```bash\nract run --config ract.yaml\n```\n")
    result = check_block(extract_blocks(doc)[0])
    assert result.status in {"flag-ok", "ran"}


def test_a_block_with_curl_or_sudo_is_never_run(tmp_path, monkeypatch):
    doc = _write(
        tmp_path,
        "```bash\nract doctor && curl https://example.com/install.sh\n```\n"
        "```bash\nsudo ract doctor\n```\n",
    )
    calls: list = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    for block in extract_blocks(doc):
        assert classify(block.command) == "never"
        assert check_block(block).status == "not-run"
    assert calls == []


def test_a_shell_metacharacter_is_never_run_and_never_reaches_a_shell(
    tmp_path, monkeypatch
):
    doc = _write(tmp_path, "```bash\nract run 'x'; rm -rf /tmp/y\n```\n")
    calls: list = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    block = extract_blocks(doc)[0]
    assert classify(block.command) == "never"
    check_block(block)
    assert calls == []


def test_a_missing_doc_is_skipped_with_a_message_not_an_error(tmp_path):
    present = _write(tmp_path, "```bash\nract --version\n```\n")
    messages = scan([tmp_path / "does-not-exist.md", present])
    assert any(
        "does-not-exist.md" in path and "skipped" in why
        for path, why in messages.skipped
    )
    assert messages.errors == []


def test_every_doc_in_the_list_is_scanned_or_named_as_missing():
    messages = scan([ROOT / name for name in DOC_FILES])
    scanned = {Path(p).name for p in messages.scanned}
    skipped = {Path(p).name for p, _ in messages.skipped}
    assert scanned | skipped == {Path(name).name for name in DOC_FILES}


def test_the_whole_scan_finishes_inside_two_minutes():
    import time

    started = time.perf_counter()
    scan([ROOT / name for name in DOC_FILES])
    assert time.perf_counter() - started < 120


@pytest.mark.parametrize(
    "command, expected",
    [
        ("ract --version", "run"),
        ("ract doctor", "run"),
        ("ract trust --list", "run"),
        ("ract setup --print-defaults", "run"),
        ("ract run --config ract.yaml", "flag"),
        ("pip install ract", "never"),
        ("git clone https://github.com/x/y", "never"),
        ("ract run 'a' | tee log", "never"),
    ],
)
def test_classification_table(command, expected):
    assert classify(command) == expected


def test_allowlisted_commands_run_in_a_scratch_project_and_exit_zero(tmp_path):
    from tests.docs.doc_commands import Block, run_allowed

    for command in (
        "ract --version",
        "ract trust --list",
        "ract setup --print-defaults",
    ):
        result = run_allowed(Block("doc.md", 1, command), tmp_path)
        assert result.status == "ran", result


def test_the_table_is_generated_from_the_scan_with_run_rows_executed(tmp_path):
    from tests.docs.doc_commands import Block, render_table, run_allowed

    messages = scan([ROOT / name for name in DOC_FILES])
    rows = []
    for file, line, command, status, reason in messages.rows:
        if status == "run":
            result = run_allowed(Block(file, line, command), tmp_path)
            status, reason = result.status, result.reason
        rows.append((file, line, command, status, reason))
    out = ROOT / "docs" / "DOC_COMMANDS.md"
    out.write_text(render_table(rows), encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    assert "| Status |" in text
    assert len(rows) == len(messages.rows)


def test_the_table_runs_doctor_against_a_config_that_points_at_the_fake_server(
    tmp_path,
):
    from tests.docs.doc_commands import Block, render_table, run_allowed
    from tests.fixtures.fake_model_server import FakeModelServer
    from tests.ux.run_baseline import _configure

    messages = scan([ROOT / name for name in DOC_FILES])
    with FakeModelServer("j1_first_run") as server:
        workdir = tmp_path / "project"
        workdir.mkdir()
        _configure(workdir, server.base_url, "fake-coder")
        rows = []
        for file, line, command, status, reason in messages.rows:
            if status == "run":
                result = run_allowed(Block(file, line, command), workdir)
                status, reason = result.status, result.reason
            rows.append((file, line, command, status, reason))
    out = ROOT / "docs" / "DOC_COMMANDS.md"
    out.write_text(render_table(rows), encoding="utf-8")
    statuses = {row[3] for row in rows}
    assert "fail" not in statuses or all(
        "doctor" not in row[2] for row in rows if row[3] == "fail"
    ), [row for row in rows if row[3] == "fail"]
