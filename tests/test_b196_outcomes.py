"""B-196 (parts c and e): one outcome word for exit 3; a trusted headless run lists what it loads.

The turn path said ``failed`` for a refusal that exits 3 while the loop path
said ``refused``; ``extensions.loaded`` was always empty in headless, even for
a trusted repository whose extensions run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.test_headless import _plan, _plant_hook, _ract, _repo, _scenario


def test_a_refused_step_is_outcome_refused_with_exit_3(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server(_scenario(_plan("settings.env.txt"), "x\n"))
    ws = _repo(tmp_path, server.base_url)
    (ws / "settings.env.txt").write_text("API_TOKEN=" + "tok_9f8e7d6c5b4a3210\n", encoding="utf-8")
    result = _ract(ws, "-p", "--accept-edits", "tidy settings", "--output-format", "json")
    data = json.loads(result.stdout)
    assert (result.returncode, data["exit_code"], data["outcome"]) == (3, 3, "refused")


def test_a_trusted_run_lists_the_hook_it_loads(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    _plant_hook(ws, tmp_path / "hook.ran")
    result = _ract(
        ws, "-p", "--accept-edits", "--trust-project", "fix add", "--output-format", "stream-json"
    )
    started = json.loads(result.stdout.splitlines()[0])
    assert {"kind": "hook", "name": "pre_audit"} in started["data"]["extensions"]["loaded"]
    assert started["data"]["extensions"]["skipped"] == []
