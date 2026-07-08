# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `rootact diff` CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path


from rootact.cli import _diff_command


def test_diff_apply_no_action_prints_help(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    exit_code = _diff_command(["--config", str(config_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()


def test_diff_apply_missing_patch(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    missing = tmp_path / "missing.patch"
    exit_code = _diff_command(
        ["apply", "--patch", str(missing), "--config", str(config_path)]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "patch file not found" in captured.err


def test_diff_apply_success(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    target = tmp_path / "greet.py"
    target.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

    patch = tmp_path / "change.patch"
    patch.write_text(
        "diff --git a/greet.py b/greet.py\n"
        "--- a/greet.py\n"
        "+++ b/greet.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'hello'\n"
        "+    return 'hello world'\n",
        encoding="utf-8",
    )

    exit_code = _diff_command(
        ["apply", "--patch", str(patch), "--config", str(config_path)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "1 applied, 0 failed" in captured.out
    assert "APPLIED" in captured.out
    assert "hello world" in target.read_text(encoding="utf-8")


def test_diff_apply_dry_run_restores_file(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    target = tmp_path / "greet.py"
    original = "def greet():\n    return 'hello'\n"
    target.write_text(original, encoding="utf-8")

    patch = tmp_path / "change.patch"
    patch.write_text(
        "diff --git a/greet.py b/greet.py\n"
        "--- a/greet.py\n"
        "+++ b/greet.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'hello'\n"
        "+    return 'hello world'\n",
        encoding="utf-8",
    )

    exit_code = _diff_command(
        ["apply", "--patch", str(patch), "--dry-run", "--config", str(config_path)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert target.read_text(encoding="utf-8") == original


def test_diff_apply_failure(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    patch = tmp_path / "bad.patch"
    patch.write_text(
        "diff --git a/missing.py b/missing.py\n"
        "--- a/missing.py\n"
        "+++ b/missing.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )

    exit_code = _diff_command(
        ["apply", "--patch", str(patch), "--config", str(config_path)]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "0 applied, 1 failed" in captured.out
    assert "FAILED" in captured.out


# RACT 0.1.0 - Initial Public Release
