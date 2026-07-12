#!/usr/bin/env python3
"""Generate a synthetic asciinema v2 recording of a short RACT demo session.

This does not need a real PTY (which asciinema cannot create on Windows). It runs
the actual commands against a throw-away demo project and writes a valid
`demo.cast` file that can be played with `asciinema play` on macOS/Linux or
uploaded to asciinema.org.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Git Bash is the only bash we can reliably spawn from native Windows Python.
BASH_EXE = Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH_EXE.exists():
    BASH_EXE = Path("C:/Program Files/Git/bin/bash.exe")
WIDTH = 100
HEIGHT = 30

DEMO_FILES = {
    "rootact.yaml": """\
project:
  name: DemoApp
manager_provider: local
providers:
  local:
    adapter: local_http
    base_url: http://127.0.0.1:8011/v1
    model: nemotron
""",
    "src/myapp/util.py": """\
def normalize(data):
    \"\"\"Normalize input data.\"\"\"
    return [x.lower().strip() for x in data if x]


def tokenize(text):
    return text.split()
""",
    "src/myapp/helpers.py": """\
def normalize_values(values):
    \"\"\"Normalize input values.\"\"\"
    return [v.lower().strip() for v in values if v]


def split_tokens(txt):
    return txt.split()
""",
}

COMMANDS = [
    ("rootact --welcome", None),
    ("cd demo-app", None),
    ("rootact doctor", None),
    ("rootact auction list", None),
    ("rootact consolidate scan", None),
]


def prepare_demo_project(base: Path) -> None:
    for rel_path, content in DEMO_FILES.items():
        path = base / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_command(base: Path, command: str) -> tuple[str, int]:
    """Run a shell command and return (stdout+stderr, exit_code)."""
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    if command.startswith("cd "):
        return "", 0
    proc = subprocess.run(
        [str(BASH_EXE), "-c", command],
        cwd=base,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return (proc.stdout or "") + (proc.stderr or ""), proc.returncode


def emit_cast(out_path: Path, events: list[list]) -> None:
    header = {
        "version": 2,
        "width": WIDTH,
        "height": HEIGHT,
        "timestamp": int(time.time()),
        "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    }
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for event in events:
            fh.write(json.dumps(event) + "\n")


def main() -> int:
    out_path = PROJECT_ROOT / "assets" / "demo.cast"
    if len(sys.argv) > 1:
        out_path = Path(sys.argv[1])

    base = Path(tempfile.mkdtemp(prefix="ract-demo-cast-"))
    try:
        prepare_demo_project(base)

        events: list[list] = []
        t = 0.0
        char_delay = 0.04
        line_delay = 0.2
        output_delay = 0.05

        def add_output(text: str, dt: float = output_delay) -> None:
            nonlocal t
            events.append([round(t, 6), "o", text])
            t += dt

        def add_input(text: str) -> None:
            nonlocal t
            for ch in text:
                events.append([round(t, 6), "o", ch])
                t += char_delay

        # Clear screen and show a welcome banner
        add_output("\033[2J\033[H", dt=0.0)
        add_output("RACT demo: init a project, check health, find duplication\r\n\r\n", dt=line_delay)

        cwd_name = "~"
        for command, _ in COMMANDS:
            # prompt
            prompt = f"\r\n\033[1;32m{cwd_name}\033[0m$ "
            add_output(prompt, dt=0.0)

            if command.startswith("cd "):
                cwd_name = command[3:].strip()
                add_input(command)
                add_output("\r\n", dt=line_delay)
                continue

            add_input(command)
            add_output("\r\n", dt=line_delay)

            output, rc = run_command(base, command)
            if rc != 0:
                output = f"(exit {rc})\r\n{output}"
            add_output(output.rstrip("\n") + "\r\n", dt=output_delay)

        add_output("\r\nDone. Run `rootact handshakes` to approve the merge.\r\n", dt=line_delay)

        emit_cast(out_path, events)
        print(f"Wrote {out_path} ({len(events)} events)")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
# RACT 0.1.1 - Trust and Tooling
