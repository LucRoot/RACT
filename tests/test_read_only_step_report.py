"""H4 (package 4): a step is not reported done before its file is applied.

A read-only file refuses the apply (substrate_adapter, "left these paths as they are"). Before
this change the step had already printed "[step 1] done" (steps.py _step_done, reported when
the model's content existed). The step must end refused, and the output must not say done.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux.run_baseline import _configure
from tests.ux import run_baseline as rb

RACT = rb.RACT
ORIGINAL = "def add(a, b):\n    return a + b\n"
NEW = "print('hello from RACT')\n"


def _scenario(target: str) -> Scenario:
    plan = {
        "assumption": "write the file",
        "confidence": 0.9,
        "steps": [{"n": 1, "action": "write the file", "expected_artifact": target}],
    }
    data = {
        "name": "h4_read_only",
        "model": "fake-coder",
        "tools_supported": False,
        "turns": [
            {
                "match": {"last_message": "(?i)probe"},
                "reply": {"kind": "text", "content": "ok"},
            },
            {"reply": {"kind": "text", "content": json.dumps(plan)}},
            {"reply": {"kind": "text", "content": NEW}, "repeat": True},
        ],
    }
    return Scenario.from_dict(data, name="h4_read_only")


@pytest.mark.skipif(
    os.name != "nt", reason="the read-only attribute is the Windows refusal"
)
def test_a_read_only_file_step_is_not_reported_done(tmp_path):
    with FakeModelServer(_scenario("src/calc.py")) as server:
        ws = tmp_path / "proj"
        (ws / "src").mkdir(parents=True)
        target = ws / "src" / "calc.py"
        target.write_text(ORIGINAL, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True, capture_output=True)
        _configure(ws, server.base_url, "fake-coder")
        subprocess.run(["git", "add", "-A"], cwd=ws, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "-m",
                "base",
            ],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        os.chmod(target, stat.S_IREAD)
        try:
            proc = subprocess.run(
                [
                    str(RACT),
                    "-p",
                    "write the file",
                    "--accept-edits",
                    "--config",
                    "ract.yaml",
                ],
                cwd=ws,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                stdin=subprocess.DEVNULL,
            )
        finally:
            os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
    text = proc.stdout + proc.stderr
    assert "[step 1] done" not in text, text
    assert proc.returncode != 0, text
    assert target.read_text(encoding="utf-8") == ORIGINAL
