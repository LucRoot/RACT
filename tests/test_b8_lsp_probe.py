"""B-8lsp (audit round 2 P1): the LSP probe refuses a planted probe file.

``probe_lsp`` writes its synthetic fixture at a fixed name inside the
repository root and unlinks it afterwards. A cloned repository can ship
that name as a symlink or a hard link to a file outside the workspace;
the probe then truncates the victim to the fixture content and unlinks
the plant. Same class as B-212/B-213. The probe must refuse to write
when anything already exists at the probe name and must only ever
unlink a file it created in the same run.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest

import ract.memory.lsp as lsp


class _StubServer:
    def open_file(self, rel: str):
        @contextlib.contextmanager
        def _cm():
            yield None

        return _cm()

    def request_references(self, rel: str, line: int, column: int) -> list:
        return []


class _StubClient:
    def __init__(self, root: Path, language: str, timeout_seconds: int = 15):
        self._server = _StubServer()

    def close(self) -> None:
        pass


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reach the real write path without multilspy or a language server."""
    monkeypatch.setattr(lsp, "LspClient", _StubClient)


def test_probe_refuses_a_planted_probe_file(tmp_path: Path, stub_client) -> None:
    root = tmp_path / "project"
    root.mkdir()
    planted = root / "___ract_lsp_probe___.py"
    planted.write_bytes(b"keep me\n")

    result = lsp.probe_lsp("python", root)

    assert planted.read_bytes() == b"keep me\n"
    assert result.available is False
    assert "already exists" in (result.error_message or "")


def test_probe_does_not_write_through_a_planted_hard_link(
    tmp_path: Path, stub_client
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"keep me\n")
    planted = root / "___ract_lsp_probe___.py"
    try:
        os.link(victim, planted)
    except OSError as exc:
        pytest.skip(f"no hard link here: {exc}")

    result = lsp.probe_lsp("python", root)

    assert victim.read_bytes() == b"keep me\n"
    assert result.available is False


def test_probe_writes_and_cleans_up_when_the_name_is_free(
    tmp_path: Path, stub_client
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    result = lsp.probe_lsp("python", root)

    assert result.available is True
    assert list(root.iterdir()) == []
