"""Run the UX journeys against the current build and save transcripts.

Usage (from the repository root)::

    python -m tests.ux.run_baseline [--out docs/ux/baseline] [--only J3,J4]

Every interactive journey runs ``ract`` in a real pseudo-terminal at 80
columns (see ``terminal_driver``) against the scripted fake model server, in
a throwaway workspace outside the repository. For each journey it writes:

- ``Jn.raw.txt``: every byte the terminal received, escape sequences kept;
- ``Jn.txt``: the same with escape sequences removed;
- ``Jn.timeline.txt``: inputs and output chunks with times;

plus ``metrics.json`` with time to first visible output after each input and
the longest silent gap. Judging the transcripts (defects, severities) is a
human step recorded in ``defects.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux.terminal_driver import Recording, spawn, strip_ansi

REPO = Path(__file__).resolve().parents[2]
RACT = Path(sys.executable).with_name("ract.exe" if os.name == "nt" else "ract")


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env.pop("NO_COLOR", None)
    return env


def _workspace(
    tmp: Path, name: str, *, git: bool, files: dict[str, str] | None = None
) -> Path:
    ws = tmp / name
    ws.mkdir()
    for rel, body in (files or {}).items():
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    if git:
        identity = ["-c", "user.name=demo", "-c", "user.email=demo@example.invalid"]
        for args in (
            ["init", "-q"],
            [*identity, "add", "-A"],
            [*identity, "commit", "-q", "-m", "init", "--allow-empty"],
        ):
            subprocess.run(["git", *args], cwd=ws, capture_output=True, check=True)
    return ws


def _configure(ws: Path, base_url: str, model: str) -> None:
    (ws / "ract.yaml").write_text(
        "project:\n  name: demo\n\n"
        "manager_provider: local\n\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        f"    url: {base_url}\n"
        f"    model: {model}\n\n"
        "prompts_dir: prompts\n",
        encoding="utf-8",
    )
    (ws / "prompts").mkdir(exist_ok=True)
    shutil.copy(REPO / "prompts" / "manager.txt", ws / "prompts" / "manager.txt")


CALC_FILES = {
    "src/calc.py": "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from src.calc import add, sub\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n",
    "src/__init__.py": "",
    "README.md": "# calc\n\nA tiny calculator library.\n",
}
APP_FILES = {
    "src/app/config.py": "import os\n\n\ndef load_config(path='app.yaml'):\n    return {'path': os.path.expandvars(path)}\n",
    "src/app/main.py": "from app.config import load_config\n\nCONFIG = load_config()\n",
    "README.md": "# app\n",
}


class Journey:
    def __init__(self, jid: str, title: str) -> None:
        self.jid = jid
        self.title = title
        self.notes: list[str] = []
        self.metrics: dict[str, Any] = {}
        self.extra_text = ""

    def note(self, text: str) -> None:
        self.notes.append(text)


def _interactive(
    journey: Journey,
    ws: Path,
    steps: list[tuple[str, Any]],
    *,
    startup_pattern: str = r"(ract|plan)> ",
    extra_env: dict[str, str] | None = None,
) -> Recording:
    env = {**_env(), **(extra_env or {})}
    # S6-8: RACT_UX_COLS sets the terminal width (80 by default; the sprint 6 journeys also run at 60).
    cols = int(os.environ.get("RACT_UX_COLS", "80"))
    session = spawn([str(RACT)], cwd=str(ws), env=env, cols=cols, rows=40)
    sends: list[tuple[str, float]] = []
    seen = session.expect(startup_pattern, 30)
    journey.metrics["startup_to_prompt_s"] = round(session.now(), 3) if seen else None
    for kind, arg in steps:
        if kind == "line":
            sends.append((arg, session.send_line(arg)))
        elif kind == "ctrl_c":
            t = session.ctrl_c()
            sends.append(("^C", t))
            back = session.expect(startup_pattern, 10)
            journey.metrics["ctrl_c_to_prompt_s"] = (
                round(session.now() - t, 3) if back else None
            )
        elif kind == "quiet":
            session.wait_quiet(arg, timeout=120)
        elif kind == "sleep":
            time.sleep(arg)
        elif kind == "expect":
            ok = session.expect(arg, 120)
            journey.note(f"expect {arg!r}: {'seen' if ok else 'NOT SEEN within 120 s'}")
    if session.alive():
        session.send_line("/exit")
    rec = session.close(timeout=10)
    per_input = []
    for label, t in sends:
        # The next input of any kind, from the recording: the closing /exit
        # is sent outside ``sends``, and taking the next send from that list
        # counted the harness's wait before /exit as silence (G-19: J3 said
        # 5 s for a 1 s turn).
        next_send = next(
            (e.t for e in rec.events if e.kind == "in" and e.t > t), float("inf")
        )
        # Measure silence only while the program was still answering: up to
        # its last visible output before the next input, so the harness's own
        # wait after the answer does not count as a silent gap.
        outputs = [
            e.t
            for e in rec.events
            if e.kind == "out" and t < e.t < next_send and strip_ansi(e.data).strip()
        ]
        end = max(outputs) if outputs else t
        per_input.append(
            {
                "input": label,
                "first_visible_output_s": None
                if (v := rec.first_output_after(t)) is None
                else round(v, 3),
                "longest_silence_s": round(rec.longest_silence(start=t, end=end), 3),
            }
        )
    journey.metrics["inputs"] = per_input
    journey.metrics["exit_code"] = rec.exit_code
    return rec


def _noninteractive(
    argv: list[str], ws: Path, stdin: str | None = None
) -> tuple[int, str, float]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(RACT), *argv],
        cwd=ws,
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        timeout=120,
    )
    elapsed = time.perf_counter() - t0
    out = f"$ ract {' '.join(argv)}{' < stdin' if stdin else ''}\n{proc.stdout}{proc.stderr}[exit {proc.returncode}, {elapsed:.2f}s]\n"
    return proc.returncode, out, elapsed


# ---------------------------------------------------------------- journeys


def j1(tmp: Path, j: Journey) -> Recording:
    ws = _workspace(tmp, "j1", git=False)
    code, text, _ = _noninteractive([], ws)
    j.extra_text += "## bare `ract` without a terminal\n" + text
    code, text, _ = _noninteractive(["explain what this folder contains"], ws)
    j.extra_text += (
        '\n## `ract "explain ..."` without a terminal and without config\n' + text
    )
    return _interactive(
        j,
        ws,
        [
            ("line", "explain what this folder contains"),
            ("quiet", 3.0),
            ("line", "/help"),
            ("quiet", 1.5),
        ],
    )


def j1b(tmp: Path, j: Journey) -> Recording:
    ws = _workspace(tmp, "j1b", git=False)
    _, text, _ = _noninteractive(["--init-provider", "local"], ws)
    j.extra_text += "## following the hint: `ract --init-provider local`\n" + text
    _, text, _ = _noninteractive(["doctor"], ws)
    j.extra_text += "\n## then `ract doctor`\n" + text
    return _interactive(
        j, ws, [("line", "explain what this folder contains"), ("quiet", 25.0)]
    )


def j2(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("j1_first_run") as server:
        ws = _workspace(tmp, "j2", git=True, files=APP_FILES)
        _configure(ws, server.base_url, "fake-coder")
        return _interactive(
            j,
            ws,
            [
                ("line", "/settings"),
                ("quiet", 1.5),
                ("line", "/providers"),
                ("quiet", 2.0),
                ("line", "/session"),
                ("quiet", 1.0),
            ],
        )


def j3(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("baseline_j3_today") as server:
        ws = _workspace(tmp, "j3", git=True, files=APP_FILES)
        _configure(ws, server.base_url, "fake-coder")
        rec = _interactive(
            j,
            ws,
            [("line", "where is the config loader and who calls it?"), ("quiet", 5.0)],
        )
        j.metrics["model_requests"] = len(server.chat_requests)
        status = subprocess.run(
            ["git", "status", "--short"], cwd=ws, capture_output=True, text=True
        ).stdout
        j.note(f"git status after the turn: {status.strip() or '(clean)'}")
        return rec


def j4(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("baseline_j4_today") as server:
        ws = _workspace(tmp, "j4", git=True, files=CALC_FILES)
        _configure(ws, server.base_url, "fake-coder")
        rec = _interactive(
            j,
            ws,
            [
                ("line", "tests/test_calc.py::test_add fails, fix it"),
                ("quiet", 6.0),
                ("line", "/report --last"),
                ("quiet", 2.0),
            ],
        )
        j.metrics["model_requests"] = len(server.chat_requests)
        diff = subprocess.run(
            ["git", "diff", "--stat"], cwd=ws, capture_output=True, text=True
        ).stdout
        j.note(f"git diff --stat after the turn: {diff.strip() or '(no change)'}")
        j.note(
            "src/calc.py after: "
            + (ws / "src" / "calc.py").read_text(encoding="utf-8").replace("\n", "\\n")
        )
        return rec


def j6(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("baseline_j6_today") as server:
        ws = _workspace(tmp, "j6", git=True, files=APP_FILES)
        _configure(ws, server.base_url, "fake-slow")
        rec = _interactive(
            j,
            ws,
            [
                ("line", "explain this project"),
                ("sleep", 3.0),
                ("ctrl_c", None),
                ("quiet", 1.0),
                ("line", "/settings"),
                ("quiet", 1.0),
            ],
        )
        j.metrics["model_requests"] = len(server.chat_requests)
        return rec


def j7(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("baseline_j3_today") as server:
        ws = _workspace(tmp, "j7", git=True, files=APP_FILES)
        _configure(ws, server.base_url, "fake-coder")
        _interactive(
            Journey("J7a", "first session"),
            ws,
            [("line", "where is the config loader and who calls it?"), ("quiet", 5.0)],
        )
        return _interactive(
            j,
            ws,
            [
                ("line", "/session"),
                ("quiet", 1.0),
                ("line", "/resume"),
                ("quiet", 1.0),
                ("line", "/sessions"),
                ("quiet", 1.0),
            ],
        )


def j8(tmp: Path, j: Journey) -> Recording | None:
    with FakeModelServer("baseline_j3_today") as server:
        ws = _workspace(tmp, "j8", git=True, files=APP_FILES)
        _configure(ws, server.base_url, "fake-coder")
        for argv, stdin in [
            (["-p", "where is the config loader?"], None),
            (["where is the config loader?", "--json"], None),
            ([], "where is the config loader?\n"),
        ]:
            code, text, _ = _noninteractive(argv, ws, stdin)
            j.extra_text += text + "\n"
            j.metrics.setdefault("exit_codes", []).append(
                {"argv": argv, "stdin": bool(stdin), "exit": code}
            )
    return None


def j9(tmp: Path, j: Journey) -> Recording:
    with FakeModelServer("baseline_j9_today") as server:
        ws = _workspace(tmp, "j9", git=True, files=CALC_FILES)
        _configure(ws, server.base_url, "fake-weak")
        rec = _interactive(
            j,
            ws,
            [
                ("line", "summarize the README"),
                ("quiet", 5.0),
                ("line", "summarize the README"),
                ("quiet", 5.0),
            ],
        )
        j.metrics["model_requests"] = len(server.chat_requests)
        reasoning_echoed = any(
            "I should not show this" in json.dumps(r.body) for r in server.chat_requests
        )
        j.note(f"hidden reasoning sent back to the model: {reasoning_echoed}")
        j.note(
            f"hidden reasoning shown on screen: {'I should not show this' in rec.plain or 'hidden plan thoughts' in rec.plain}"
        )
        return rec


def j10(tmp: Path, j: Journey) -> Recording:
    ws = _workspace(tmp, "j10", git=True, files=APP_FILES)
    _configure(ws, "http://127.0.0.1:9/v1", "nothing-listening")
    return _interactive(j, ws, [("line", "summarize the README"), ("quiet", 8.0)])


# ------------------------------------------------- first-run setup (B-015)

_SETUP_OFFER = r"Set one up now\?"


def _setup_scenario() -> Any:
    from tests.fixtures.fake_model_server import Scenario

    plan = json.dumps(
        {
            "assumption": "the folder is empty apart from RACT's own files",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Explain what this folder contains",
                    "provider_hint": "local",
                    "expected_artifact": "",
                }
            ],
        }
    )
    return Scenario.from_dict(
        {
            "model": "fake-coder",
            "turns": [
                {"reply": {"kind": "text", "content": "ready"}},
                {"reply": {"kind": "text", "content": plan}},
                {
                    "reply": {
                        "kind": "text",
                        "content": "The folder holds ract.yaml and prompts/, nothing else yet.",
                    },
                    "repeat": True,
                },
            ],
        }
    )


def s1(tmp: Path, j: Journey) -> Recording:
    """Empty directory, a server found through RACT_BASE_URL, then a question."""
    with FakeModelServer(_setup_scenario()) as server:
        ws = _workspace(tmp, "s1", git=False)
        rec = _interactive(
            j,
            ws,
            [
                ("line", ""),  # set one up now? yes
                ("expect", r"Use the server at"),
                ("line", ""),  # use it? yes
                ("expect", r"Run git init here now"),
                ("line", "y"),
                ("expect", r"ract> "),
                ("line", "what does this folder contain?"),
                ("expect", r"Done: "),
                ("quiet", 1.0),
            ],
            startup_pattern=_SETUP_OFFER,
            extra_env={"RACT_BASE_URL": server.base_url},
        )
        j.note(f"ract.yaml written: {(ws / 'ract.yaml').is_file()}")
        j.note(f"git repository: {(ws / '.git').is_dir()}")
        return rec


def s2(tmp: Path, j: Journey) -> Recording:
    """No server anywhere: local guidance, then write the config and skip."""
    ws = _workspace(tmp, "s2", git=True)
    rec = _interactive(
        j,
        ws,
        [
            ("line", ""),
            ("expect", r"local model or a cloud provider"),
            ("line", "l"),
            ("expect", r"How many GB"),
            ("line", ""),
            ("expect", r"type skip"),
            ("line", "skip"),
            ("expect", r"(ract> |Opening the session)"),
            ("quiet", 2.0),
        ],
        startup_pattern=_SETUP_OFFER,
        extra_env={"RACT_BASE_URL": "http://127.0.0.1:9/v1"},
    )
    j.note(f"ract.yaml written: {(ws / 'ract.yaml').is_file()}")
    return rec


def s3(tmp: Path, j: Journey) -> Recording:
    """A server that answers /models but lists no model."""
    import http.server
    import threading

    class NoModels(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"object": "list", "data": []}'
            self.send_response(
                200 if self.path.rstrip("/").endswith("/models") else 404
            )
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NoModels)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        ws = _workspace(tmp, "s3", git=True)
        return _interactive(
            j,
            ws,
            [
                ("line", ""),
                ("expect", r"lists no model yet"),
                ("expect", r"local model or a cloud provider"),
                ("line", "l"),
                ("expect", r"How many GB"),
                ("line", ""),
                ("expect", r"type skip"),
                ("line", "skip"),
                ("expect", r"(ract> |Opening the session)"),
                ("quiet", 2.0),
            ],
            startup_pattern=_SETUP_OFFER,
            extra_env={"RACT_BASE_URL": f"http://127.0.0.1:{httpd.server_port}/v1"},
        )
    finally:
        httpd.shutdown()


def s4(tmp: Path, j: Journey) -> Recording:
    """Ctrl-C at the first setup question leaves no file."""
    with FakeModelServer(_setup_scenario()) as server:
        ws = _workspace(tmp, "s4", git=True)
        rec = _interactive(
            j,
            ws,
            [
                ("line", ""),
                ("expect", r"Use the server at"),
                # A person reads the question first. A Ctrl-C within a few
                # milliseconds of the prompt, before input() starts reading,
                # is held by Windows until Enter (CPython; logged L-084).
                ("sleep", 0.3),
                ("ctrl_c", None),
                ("quiet", 2.0),
            ],
            startup_pattern=_SETUP_OFFER,
            extra_env={"RACT_BASE_URL": server.base_url},
        )
        left = sorted(p.name for p in ws.iterdir() if p.name != ".git")
        j.note(f"files left after Ctrl-C: {left or 'none'}")
        return rec


JOURNEYS: dict[str, tuple[str, Callable[[Path, Journey], Recording | None]]] = {
    "J1": ("First run in an empty directory, no config", j1),
    "J1b": ("First run following the printed hint", j1b),
    "J2": ("Daily start in a configured repo", j2),
    "J3": ("Ask about the code (read-only)", j3),
    "J4": ("Fix the failing test", j4),
    "J6": ("Interrupt during a slow turn", j6),
    "J7": ("Resume an earlier session", j7),
    "J8": ("Headless use", j8),
    "J9": ("Weak or reasoning model", j9),
    "J10": ("Provider is down", j10),
    "S1": ("Setup: empty directory, server found, first question", s1),
    "S2": ("Setup: no server found, local guidance, skip", s2),
    "S3": ("Setup: server found that lists no model", s3),
    "S4": ("Setup: Ctrl-C at a question", s4),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.ux.run_baseline")
    parser.add_argument("--out", default=str(REPO / "docs" / "ux" / "baseline"))
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    selected = [s for s in args.only.split(",") if s] or list(JOURNEYS)
    summary: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="ract-ux-") as tmpdir:
        tmp = Path(tmpdir)
        for jid in selected:
            title, fn = JOURNEYS[jid]
            journey = Journey(jid, title)
            started = time.perf_counter()
            try:
                rec = fn(tmp, journey)
            except Exception as exc:  # noqa: BLE001 - a harness failure is itself a finding
                journey.note(f"HARNESS ERROR: {type(exc).__name__}: {exc}")
                rec = None
            header = f"# {jid}: {title}\n# build: {_build()}  terminal: 80x40 pseudo-terminal  run: {time.strftime('%Y-%m-%d %H:%M')}\n"
            plain = header + (journey.extra_text + "\n" if journey.extra_text else "")
            if rec is not None:
                (out / f"{jid}.raw.txt").write_text(
                    _redact(rec.raw, tmp), encoding="utf-8"
                )
                (out / f"{jid}.timeline.txt").write_text(
                    _redact(rec.timeline(), tmp), encoding="utf-8"
                )
                plain += "## interactive session\n" + rec.plain
            if journey.notes:
                plain += (
                    "\n## harness notes\n"
                    + "\n".join(f"- {n}" for n in journey.notes)
                    + "\n"
                )
            (out / f"{jid}.txt").write_text(_redact(plain, tmp), encoding="utf-8")
            journey.metrics["wall_s"] = round(time.perf_counter() - started, 2)
            journey.metrics["notes"] = journey.notes
            summary[jid] = journey.metrics
            print(f"{jid}: done in {journey.metrics['wall_s']} s", flush=True)
        metrics_text = _redact(json.dumps(summary, indent=2) + "\n", tmp)
    (out / "metrics.json").write_text(metrics_text, encoding="utf-8")
    return 0


def _redact(text: str, tmp: Path) -> str:
    """Replace machine paths so transcripts carry no workstation details."""
    home = str(Path.home())
    for raw, label in (
        (str(tmp), "<tmp>"),
        (str(REPO), "<repo>"),
        # The ract executable can live in another checkout's venv.
        (str(RACT.parents[2]), "<repo>"),
        (home, "~"),
    ):
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            text = text.replace(variant, label)
    return text


def _build() -> str:
    """The last commit's subject, for the transcript header.

    LR:: Transcripts are tracked files, and tracked files cite subjects, tags
    or card ids, never a commit hash: a history rewrite changes every hash
    and leaves the citation pointing at nothing (BOARD G-025, S-023).
    """
    head = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return f'"{head}"' + (" +src-changes" if dirty else "")


if __name__ == "__main__":
    raise SystemExit(main())
