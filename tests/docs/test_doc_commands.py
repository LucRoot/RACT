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


def test_the_committed_table_matches_a_fresh_run(tmp_path):
    # B-080: the test never writes the table. A stale table fails with the command that fixes it.
    from tests.docs.doc_commands import generate_table
    from tests.fixtures.fake_model_server import FakeModelServer
    from tests.ux.run_baseline import _configure

    with FakeModelServer("j1_first_run") as server:
        workdir = tmp_path / "project"
        workdir.mkdir()
        fresh = generate_table(
            ROOT,
            workdir,
            prepare=lambda folder: _configure(folder, server.base_url, "fake-coder"),
        )
    committed = (ROOT / "docs" / "DOC_COMMANDS.md").read_text(encoding="utf-8")
    assert fresh == committed.replace(chr(13) + chr(10), chr(10)), (
        "docs/DOC_COMMANDS.md is stale: run python tests/docs/doc_commands.py --write"
    )


def test_a_planted_ract_variable_and_a_key_do_not_reach_the_child(
    tmp_path, monkeypatch
):
    from tests.docs import doc_commands
    from tests.docs.doc_commands import Block, run_allowed

    seen: dict = {}

    class _Done:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs["env"]
        return _Done()

    monkeypatch.setenv("RACT_DEMO_BASE_URL", "http://127.0.0.1:9/planted")
    monkeypatch.setenv("PLANTED_API_KEY", "not-a-real-key")
    monkeypatch.setenv("PLANTED_TOKEN", "not-a-real-token")
    monkeypatch.setattr(doc_commands.subprocess, "run", fake_run)
    result = run_allowed(Block("doc.md", 1, "ract --version"), tmp_path)
    assert result.status == "ran"
    env = seen["env"]
    assert "RACT_DEMO_BASE_URL" not in env
    assert "PLANTED_API_KEY" not in env
    assert "PLANTED_TOKEN" not in env
