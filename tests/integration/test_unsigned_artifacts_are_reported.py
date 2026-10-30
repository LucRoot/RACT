"""S-015: a run that writes files without a Rootknot says so.

Rootknot signing is not wired into CLI runs in this release (the executor's
v4 dependencies have no production caller). Until it is, every run that
writes a file must name the unsigned files, and `ract doctor` must say that
runs do not sign. When signing is wired, the first test here must change: a
real run followed by `ract provenance verify` should pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ux import run_baseline as rb


def _ract(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize("git", [False, True], ids=["legacy-path", "substrate-path"])
def test_run_that_writes_a_file_names_it_as_unsigned(
    tmp_path: Path, fake_model_server: Any, git: bool
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=git, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    if git:
        for args in (
            ["add", "-A"],
            [
                "-c",
                "user.name=d",
                "-c",
                "user.email=d@example.invalid",
                "commit",
                "-q",
                "-m",
                "config",
            ],
        ):
            subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)

    result = _ract(
        ws,
        "--config",
        "ract.yaml",
        "--yolo",
        "tests/test_calc.py::test_add fails, fix it",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    out = " ".join(result.stdout.split())
    assert "1 file(s) written without a Rootknot (src/calc.py)" in out
    verify = _ract(ws, "provenance", "verify", "src/calc.py")
    assert verify.returncode != 0
    verify_text = " ".join(verify.stdout.split())
    assert verify.stdout.splitlines()[0] == "unsigned"
    # AUD-013: a missing record is not proof of anything either way.
    assert "cannot be told apart from a removed one" in verify_text
    assert "not evidence of tampering" not in verify_text
    assert "invalid" not in verify_text
    # PHILOSOPHY: "attested" appears only when all three signatures land.
    import re

    assert not re.search(r"attested", result.stdout, re.IGNORECASE)


def test_doctor_states_that_runs_do_not_sign(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, "http://127.0.0.1:9/v1", "fake-coder")

    result = _ract(ws, "doctor", "--config", "ract.yaml")

    # B-083 (cold reader row 6): the doctor says it in plain words.
    assert "files ract writes are not signed yet" in " ".join(result.stdout.split())
