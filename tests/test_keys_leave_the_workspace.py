"""B-111 (ADR-0048 R3): keys live outside every workspace; the old places stay readable once.

The test run's user state and config folders are temporary (conftest); every
key here is a throwaway.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from ract.core.intent_recompile import _load_operator_key
from ract.key_paths import migrate, recompile_key_path, repo_key_dir
from ract.security.alm_verifier_key import AlmVerifierKey
from ract.security.keys import SandboxKey

RUN = bytes(range(16))


@pytest.mark.parametrize(
    ("cls", "kind"), [(SandboxKey, "sandbox"), (AlmVerifierKey, "alm")]
)
def test_run_keys_are_written_outside_the_project(
    tmp_path: Path, cls, kind: str
) -> None:
    key = cls.generate(RUN, workspace_root=tmp_path)
    assert not (tmp_path / ".ract" / kind).exists()
    live = repo_key_dir(tmp_path, kind) / f"{RUN.hex()}.key"
    assert live.is_file()
    archived = key.archive()
    assert archived == repo_key_dir(tmp_path, kind) / "archive" / f"{RUN.hex()}.key"
    again = cls.load_archived(RUN, tmp_path)
    assert again is not None and again.public == key.public


@pytest.mark.parametrize(
    ("cls", "kind"), [(SandboxKey, "sandbox"), (AlmVerifierKey, "alm")]
)
def test_an_archived_key_in_the_old_place_is_read_with_a_warning(
    tmp_path: Path, cls, kind: str, capsys
) -> None:
    key = cls.generate(RUN, workspace_root=tmp_path)
    archived = key.archive()
    old = tmp_path / ".ract" / kind / "archive" / archived.name
    old.parent.mkdir(parents=True)
    os.replace(archived, old)
    again = cls.load_archived(RUN, tmp_path)
    assert again is not None and again.public == key.public
    assert "inside the project" in capsys.readouterr().err


def test_the_recompile_key_is_read_from_the_user_config_first(
    tmp_path: Path, capsys
) -> None:
    new = recompile_key_path()
    new.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32).encode()
    new.write_bytes(value)
    try:
        old = tmp_path / ".ract"
        old.mkdir()
        (old / "operator.key").write_bytes(secrets.token_hex(32).encode())
        assert _load_operator_key(old) == value
        assert capsys.readouterr().err == ""  # the new place: no warning
    finally:
        new.unlink()


def test_the_old_recompile_key_still_works_once_with_a_warning(
    tmp_path: Path, capsys
) -> None:
    old = tmp_path / ".ract"
    old.mkdir()
    value = secrets.token_hex(32).encode()
    (old / "operator.key").write_bytes(value)
    assert _load_operator_key(old) == value
    assert "migrate-keys" in capsys.readouterr().err


def test_migrate_moves_every_key_out_and_overwrites_nothing(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / ".ract" / "sandbox" / "archive").mkdir(parents=True)
    (project / ".ract" / "alm").mkdir(parents=True)
    (project / ".ract" / "operator.key").write_bytes(b"r" * 64)
    (project / ".ract" / "sandbox" / "archive" / "a.key").write_bytes(b"s")
    (project / ".ract" / "alm" / "b.key").write_bytes(b"a")
    blocked = repo_key_dir(project, "alm") / "b.key"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_bytes(b"another key")
    try:
        lines = migrate(project)
    finally:
        moved_recompile = recompile_key_path()
    assert any(line.startswith("moved") and "operator.key" in line for line in lines)
    assert (repo_key_dir(project, "sandbox") / "archive" / "a.key").read_bytes() == b"s"
    assert not (project / ".ract" / "operator.key").exists()
    assert moved_recompile.read_bytes() == b"r" * 64
    # The ALM key's target held another key: left alone and named.
    assert (project / ".ract" / "alm" / "b.key").read_bytes() == b"a"
    assert blocked.read_bytes() == b"another key"
    assert any(line.startswith("left") and "b.key" in line for line in lines)
    moved_recompile.unlink()


def test_the_cli_says_when_there_is_nothing_to_move(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from ract.policy.cli import policy_command

    monkeypatch.chdir(tmp_path)
    assert policy_command(["migrate-keys"]) == 0
    assert "nothing to move" in capsys.readouterr().out
