"""S-035: the one reader of files a repository can ship (``ract.untrusted_file``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.untrusted_file import UntrustedFileRefused, read_untrusted


def test_a_missing_file_gives_none(tmp_path: Path) -> None:
    assert read_untrusted(tmp_path / "absent.json") is None


def test_a_file_comes_back_whole(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"{}\r\n\xff")
    assert read_untrusted(tmp_path / "a.json", root=tmp_path) == b"{}\r\n\xff"


def test_a_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.json").mkdir()
    with pytest.raises(UntrustedFileRefused, match="not a file"):
        read_untrusted(tmp_path / "a.json")


def test_a_file_over_the_limit_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"x" * 101)
    with pytest.raises(UntrustedFileRefused, match="larger than 100"):
        read_untrusted(tmp_path / "a.json", max_bytes=100)
    (tmp_path / "b.json").write_bytes(b"x" * 100)
    assert read_untrusted(tmp_path / "b.json", max_bytes=100) == b"x" * 100


def test_a_link_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"secret")
    link = tmp_path / "project" / "a.json"
    link.parent.mkdir()
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symbolic links need a privilege this machine does not grant")
    with pytest.raises(UntrustedFileRefused, match="link"):
        read_untrusted(link, root=tmp_path / "project")


def _junction(link: Path, target: Path) -> None:
    """A directory junction: on Windows it needs no privilege."""
    if os.name != "nt":
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            pytest.skip("cannot create a directory link here")
        return
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J failed: {result.stderr.strip()}")


def test_a_folder_that_leaves_the_project_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.json").write_bytes(b"secret")
    project = tmp_path / "project"
    project.mkdir()
    _junction(project / ".ract", outside)

    with pytest.raises(UntrustedFileRefused, match="leaves the project"):
        read_untrusted(project / ".ract" / "a.json", root=project)
