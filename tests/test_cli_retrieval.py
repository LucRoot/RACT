"""Tests for the `ract retrieval` CLI command."""

from __future__ import annotations


from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from ract.cli import _retrieval_command


def test_retrieval_search_no_config(tmp_path: Path, capsys):
    missing = tmp_path / "ract.yaml"
    exit_code = _retrieval_command(["search", "foo", "--config", str(missing)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "config not found" in captured.err


def test_retrieval_search_with_results(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )

    mock_result = MagicMock()
    mock_result.source = "src/foo.py"
    mock_result.score = 0.95
    mock_result.content = "def foo(): pass"

    mock_adapter = MagicMock()
    mock_rooted = MagicMock()
    mock_rooted.error = None
    mock_rooted.value = [mock_result]
    mock_adapter.search.return_value = mock_rooted

    with patch("ract.cli._build_retrieval_adapter", return_value=mock_adapter):
        exit_code = _retrieval_command(["search", "foo", "--config", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "src/foo.py" in captured.out
    assert "0.9500" in captured.out
    assert "def foo(): pass" in captured.out


def test_retrieval_search_empty_results(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )

    mock_adapter = MagicMock()
    mock_rooted = MagicMock()
    mock_rooted.error = None
    mock_rooted.value = []
    mock_adapter.search.return_value = mock_rooted

    with patch("ract.cli._build_retrieval_adapter", return_value=mock_adapter):
        exit_code = _retrieval_command(["search", "bar", "--config", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No results for query" in captured.out


def test_retrieval_search_top_k_passed(tmp_path: Path):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )

    mock_adapter = MagicMock()
    mock_rooted = MagicMock()
    mock_rooted.error = None
    mock_rooted.value = []
    mock_adapter.search.return_value = mock_rooted

    with patch("ract.cli._build_retrieval_adapter", return_value=mock_adapter):
        _retrieval_command(
            ["search", "baz", "--top-k", "3", "--config", str(config_path)]
        )

    mock_adapter.search.assert_called_once_with("baz", top_k=3)


def test_retrieval_search_error(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )

    mock_adapter = MagicMock()
    mock_rooted = MagicMock()
    mock_rooted.error = "network failure"
    mock_adapter.search.return_value = mock_rooted

    with patch("ract.cli._build_retrieval_adapter", return_value=mock_adapter):
        exit_code = _retrieval_command(["search", "qux", "--config", str(config_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "network failure" in captured.err


def test_retrieval_no_action_prints_help(tmp_path: Path, capsys):
    # v0.5.1 spec-completeness wiring module_10 (Lens A M7 closure):
    # bare ``ract retrieval`` / ``memory`` / ``plan`` return exit 0 after
    # printing help — exit 1 was blocking CI capability-probing scripts
    # that grep --help output. Align the test to the shipped behaviour.
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )
    exit_code = _retrieval_command(["--config", str(config_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()


# RACT 0.1.1 - Trust and tooling
