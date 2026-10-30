"""B-083b: run `ract -p --output-format json` once per error kind and print the JSON.

Run from the repository root: `python docs/ux/b083b/run_kinds.py`. Uses the
fake model server; temporary paths are replaced with <tmp>. Ctrl-C (`cancelled`)
needs a signal and is shown by tests/test_headless_error_object.py instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.fixtures.fake_model_server import FakeModelServer, Scenario  # noqa: E402
from tests.test_session_turn import _repo  # noqa: E402


def _dir(tmp: Path, name: str) -> Path:
    path = tmp / name
    path.mkdir()
    return path


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}


def _run(ws: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "ract.cli", "-p", *args, "--output-format", "json"],
        cwd=ws,
        env=env or _env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
    )
    return proc.stdout


def _stall(ws: Path) -> str:
    env = {**_env(), "RACT_STDIN_IDLE_TIMEOUT": "2"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "ract.cli", "-p", "fix add", "--output-format", "json"],
        cwd=ws,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 60
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if proc.poll() is None:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    if proc.stdin is not None:
        proc.stdin.close()
    return out


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ract-b083b-") as tmp_name:
        tmp = Path(tmp_name)
        rows: list[tuple[str, str]] = []
        empty = tmp / "empty"
        empty.mkdir()
        rows.append(("usage (no prompt)", _run(empty)))
        rows.append(("config (no ract.yaml)", _run(empty, "x")))
        down = _repo(_dir(tmp, "down"), "http://127.0.0.1:9/v1")
        config = down / "ract.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "    model: fake-coder\n", "    model: fake-coder\n    max_retries: 0\n"
            ),
            encoding="utf-8",
        )
        rows.append(("provider", _run(down, "--accept-edits", "fix add")))
        with FakeModelServer("baseline_j4_today") as server:
            ws = _repo(_dir(tmp, "refused"), server.base_url)
            rows.append(("refused (default mode, nobody to ask)", _run(ws, "fix add")))
        with FakeModelServer("baseline_j4_today") as server:
            ws = _repo(_dir(tmp, "budget"), server.base_url)
            rows.append(
                (
                    "budget",
                    _run(ws, "--accept-edits", "fix add", "--token-budget", "10"),
                )
            )
        with FakeModelServer("baseline_j4_today") as server:
            ws = _repo(_dir(tmp, "stall"), server.base_url)
            rows.append(("stdin_stall", _stall(ws)))
        not_a_plan = Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": "this is not a plan"}},
                    {"reply": {"kind": "text", "content": "still not a plan"}},
                ]
            }
        )
        with FakeModelServer(not_a_plan) as server:
            ws = _repo(_dir(tmp, "internal"), server.base_url)
            rows.append(("internal", _run(ws, "--accept-edits", "fix add")))
        with FakeModelServer("baseline_j4_today") as server:
            ws = _repo(_dir(tmp, "done"), server.base_url)
            rows.append(("success", _run(ws, "--accept-edits", "fix add")))
        for label, out in rows:
            obj = json.loads(out)
            shown = {"exit_code": obj["exit_code"], "error": obj["error"]}
            text = json.dumps(shown, ensure_ascii=False).replace(tmp_name, "<tmp>")
            print(f"{label}:\n{text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
