"""S-015: what a run says about signing the files it writes.

S-015b wired signing into CLI runs, and this file changed as it said it
would: a real run followed by `ract provenance verify` passes, and `ract
doctor` says that runs sign. A file left unsigned is still named, and a
missing record is still "unsigned" (AUD-013).
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
def test_run_that_writes_a_file_signs_it(
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
    assert "without a Rootknot" not in out
    verify = _ract(ws, "provenance", "verify", "src/calc.py")
    assert verify.returncode == 0, verify.stdout + verify.stderr
    verify_text = " ".join(verify.stdout.split())
    assert "unsigned" not in verify_text and "invalid" not in verify_text
    # AUD-013: a file no run wrote still has no record, and says so.
    (ws / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    other = _ract(ws, "provenance", "verify", "src/extra.py")
    assert other.returncode != 0
    assert other.stdout.splitlines()[0] == "unsigned"
    assert "cannot be told apart from a removed one" in " ".join(other.stdout.split())
    # PHILOSOPHY: "attested" appears only when all three signatures land.
    import re

    assert not re.search(r"attested", result.stdout, re.IGNORECASE)


def test_doctor_states_that_runs_sign(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, "http://127.0.0.1:9/v1", "fake-coder")

    result = _ract(ws, "doctor", "--config", "ract.yaml")

    # B-083 (cold reader row 6): the doctor says it in plain words.
    assert "each file a run writes is signed" in " ".join(result.stdout.split())
