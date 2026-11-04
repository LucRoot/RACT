"""B-231: the WSL mutation runner reads the distribution list right and passes its variables.

``wsl -l`` writes UTF-16LE with a header line; read as text, the header became
the distribution passed to ``wsl -d``. ``WSLENV`` was never set, so
``RACT_MUTATION_TARGETS`` and ``RACT_TEST_RUNNER`` reached WSL empty, and a
network or extended-length path was mangled. Recorded output; nothing runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ract import mutation_runner
from ract.mutation_runner import _to_wsl_path, wsl_distributions


def _wsl(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("utf-16-le")


@pytest.mark.parametrize(
    ("out", "names"),
    [
        (
            _wsl(
                "Windows Subsystem for Linux Distributions:\nUbuntu-24.04 (Default)\n"
            ),
            ["Ubuntu-24.04"],
        ),
        (
            _wsl(
                "Windows Subsystem for Linux Distributions:\nUbuntu (Default)\nDebian\n"
            ),
            ["Ubuntu", "Debian"],
        ),
        (_wsl("Ubuntu\ndocker-desktop\n"), ["Ubuntu", "docker-desktop"]),
        (_wsl("* Ubuntu\n"), ["Ubuntu"]),
        (_wsl("\n\n"), []),
        (b"", []),
    ],
)
def test_the_distribution_list_is_decoded(out: bytes, names: list[str]) -> None:
    assert wsl_distributions(out) == names


def test_paths_with_a_prefix_or_a_share() -> None:
    assert _to_wsl_path(Path("\\\\?\\C:\\proj\\run.sh")) == "/mnt/c/proj/run.sh"
    assert _to_wsl_path(Path("C:\\proj\\run.sh")) == "/mnt/c/proj/run.sh"
    with pytest.raises(ValueError, match="network path"):
        _to_wsl_path(Path("\\\\server\\share\\run.sh"))


@pytest.mark.skipif(
    sys.platform != "win32", reason="the WSL runner is the Windows path"
)
def test_no_distribution_is_a_sentence_and_no_run(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "run.sh"
    script.write_text("echo\n", encoding="utf-8")
    monkeypatch.delenv("RACT_WSL_DISTRO", raising=False)
    monkeypatch.setattr(mutation_runner, "_detect_wsl_distro", lambda: None)

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("nothing may run")

    monkeypatch.setattr(subprocess, "run", forbidden)
    result = mutation_runner.run_mutation_tests(tmp_path, script_path=script)
    assert not result.is_ok() and "no running Linux distribution" in (
        result.error or ""
    )


@pytest.mark.skipif(sys.platform != "win32", reason="WSLENV is read by wsl.exe")
def test_the_variables_are_named_in_wslenv(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / "run.sh"
    script.write_text("echo\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def capture(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(cmd=cmd, env=kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("WSLENV", "EXISTING/p")
    monkeypatch.setattr(subprocess, "run", capture)
    mutation_runner.run_mutation_tests(
        tmp_path,
        script_path=script,
        wsl_distro="Ubuntu",
        targets=["src/a.py"],
        test_runner="pytest -x",
    )
    assert seen["cmd"][:3] == ["wsl", "-d", "Ubuntu"]
    assert seen["env"]["WSLENV"].split(":") == [
        "EXISTING/p",
        "RACT_MUTATION_TARGETS",
        "RACT_TEST_RUNNER",
    ]
