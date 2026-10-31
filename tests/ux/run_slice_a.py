"""Walk slice (a) in a real pseudo-terminal: the tools, review, approvals, checkpoints (B-110).

Usage (from the repository root)::

    python -m tests.ux.run_slice_a [--out docs/ux/slice-a] [--cols 80,60,40] [--only SA1]

Each journey runs this checkout's code (``python -m ract.cli`` with
``PYTHONPATH`` on its ``src``, never a ``ract`` executable from another
checkout) against the scripted fake model server, with ``agent.step_tools:
true``, in a throwaway workspace. For each width it writes ``<id>.txt``
(escape sequences removed; ConPTY's rebuilt text joins repainted lines, so
it is not the screen), ``<id>.raw.txt``, ``<id>.timeline.txt`` and
``metrics.json``. The metrics count the answers the operator typed per task
(condition 3 of decision F) and the time from the request to the "preparing
a workspace" line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux.run_baseline import (
    APP_FILES,
    CALC_FILES,
    _build,
    _configure,
    _env,
    _redact,
    _workspace,
)
from tests.ux.terminal_driver import Recording, spawn, strip_ansi

REPO = Path(__file__).resolve().parents[2]
WORKSPACE_LINE = "preparing a workspace"
FIX = {
    "path": "src/calc.py",
    "old": "    return a - b\n\n\ndef sub",
    "new": "    return a + b\n\n\ndef sub",
}


def _plan(action: str, target: str) -> dict[str, Any]:
    return {
        "reply": {
            "kind": "text",
            "content": json.dumps(
                {
                    "assumption": action,
                    "confidence": 0.9,
                    "steps": [
                        {
                            "action": action,
                            "provider_hint": "local",
                            "expected_artifact": target,
                        }
                    ],
                }
            ),
        }
    }


def _calls(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    body = [{"tool": name, "arguments": args} for name, args in calls]
    return {
        "reply": {
            "kind": "text",
            "content": json.dumps(body[0] if len(body) == 1 else body),
        }
    }


def _final(text: str) -> dict[str, Any]:
    return {"reply": {"kind": "text", "content": json.dumps({"final": text})}}


def _digest(ws: Path, rel: str) -> str:
    return hashlib.sha256((ws / rel).read_bytes()).hexdigest()


def _with_step_tools(ws: Path) -> None:
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nagent:\n  step_tools: true\n",
        encoding="utf-8",
    )


class Walk:
    """One journey: its id, title, the answers typed, notes and metrics."""

    def __init__(self, jid: str, title: str) -> None:
        self.jid = jid
        self.title = title
        self.notes: list[str] = []
        self.metrics: dict[str, Any] = {"answers": 0}


def _session(
    walk: Walk, ws: Path, cols: int, steps: list[tuple[str, Any]]
) -> Recording:
    """Run the steps; an ``answer`` step is a line typed at a question and is counted."""
    env = {**_env(), "PYTHONPATH": str(REPO / "src")}
    argv = [sys.executable, "-m", "ract.cli"]
    with spawn(argv, cwd=str(ws), env=env, cols=cols, rows=40) as session:
        seen = session.expect(r"ract> ", 60)
        walk.metrics["startup_to_prompt_s"] = round(session.now(), 3) if seen else None
        requests: list[float] = []
        for kind, arg in steps:
            if kind == "request":
                requests.append(session.send_line(arg))
            elif kind in {"line", "answer"}:
                session.send_line(arg)
                if kind == "answer":
                    walk.metrics["answers"] += 1
            elif kind == "expect":
                ok = session.expect(arg, 120)
                walk.notes.append(f"expect {arg!r}: {'seen' if ok else 'NOT SEEN'}")
            elif kind == "quiet":
                session.wait_quiet(arg, timeout=120)
        if session.alive():
            session.send_line("/exit")
        rec = session.close(timeout=15)
    for t in requests:
        line_at = next(
            (
                e.t
                for e in rec.events
                if e.kind == "out" and e.t > t and WORKSPACE_LINE in strip_ansi(e.data)
            ),
            None,
        )
        walk.metrics.setdefault("request_to_workspace_line_s", []).append(
            None if line_at is None else round(line_at - t, 3)
        )
    walk.metrics["exit_code"] = rec.exit_code
    return rec


def sa1(tmp: Path, walk: Walk, cols: int) -> Recording:
    """Fix a bug: the model edits two files; keep one hunk, restore the other file."""
    ws = _workspace(tmp, f"sa1_{cols}", git=True, files=CALC_FILES)
    scenario = Scenario.from_dict(
        {
            "name": "sa1",
            "turns": [
                _plan("Fix add() in src/calc.py so it adds", "src/calc.py"),
                _calls(("read_file", {"path": "src/calc.py"})),
                _calls(
                    (
                        "edit_file",
                        {**FIX, "expected_digest": _digest(ws, "src/calc.py")},
                    ),
                    (
                        "write_file",
                        {
                            "path": "notes/fix.md",
                            "content": "add() returned a - b.\n",
                            "create": True,
                        },
                    ),
                ),
                {**_final("add() adds now."), "repeat": True},
            ],
        }
    )
    with FakeModelServer(scenario) as server:
        _configure(ws, server.base_url, "fake-coder")
        _with_step_tools(ws)
        rec = _session(
            walk,
            ws,
            cols,
            [
                ("request", "tests/test_calc.py::test_add fails, fix it"),
                ("expect", r"answer:"),
                ("answer", "r"),  # notes/fix.md (git lists it first): not wanted
                ("expect", r"answer:"),
                ("answer", "a"),  # the fix in src/calc.py
                ("quiet", 4.0),
                ("line", "/diff"),
                ("quiet", 2.0),
                ("line", "/checkpoint"),
                ("quiet", 2.0),
            ],
        )
    walk.notes.append(
        "src/calc.py after: "
        + (ws / "src" / "calc.py").read_text(encoding="utf-8").replace("\n", "\\n")
    )
    walk.notes.append(
        f"notes/fix.md exists after: {(ws / 'notes' / 'fix.md').exists()}"
    )
    return rec


def sa2(tmp: Path, walk: Walk, cols: int) -> Recording:
    """A control file: the edit to AGENTS.md asks at tier 2; allowed for the session."""
    files = {**CALC_FILES, "AGENTS.md": "# Agents\n\nRun the tests with pytest.\n"}
    ws = _workspace(tmp, f"sa2_{cols}", git=True, files=files)
    scenario = Scenario.from_dict(
        {
            "name": "sa2",
            "turns": [
                _plan("Note in AGENTS.md how to run one test", "AGENTS.md"),
                _calls(
                    (
                        "edit_file",
                        {
                            "path": "AGENTS.md",
                            "old": "Run the tests with pytest.",
                            "new": "Run the tests with pytest; one test with pytest -k NAME.",
                            "expected_digest": _digest(ws, "AGENTS.md"),
                        },
                    )
                ),
                {**_final("AGENTS.md says how to run one test."), "repeat": True},
            ],
        }
    )
    with FakeModelServer(scenario) as server:
        _configure(ws, server.base_url, "fake-coder")
        _with_step_tools(ws)
        rec = _session(
            walk,
            ws,
            cols,
            [
                ("request", "say in AGENTS.md how to run one test"),
                ("expect", r"\[y/s/N\]"),
                ("answer", "s"),
                ("expect", r"answer:|leave it"),
                ("answer", "a"),
                ("quiet", 4.0),
            ],
        )
    walk.notes.append(
        "AGENTS.md after: "
        + (ws / "AGENTS.md").read_text(encoding="utf-8").replace("\n", "\\n")
    )
    return rec


def sa3(tmp: Path, walk: Walk, cols: int) -> Recording:
    """J7: two turns change src/calc.py; /rewind goes back to the first."""
    ws = _workspace(tmp, f"sa3_{cols}", git=True, files=CALC_FILES)
    first = CALC_FILES["src/calc.py"].replace(
        "return a - b\n\n\ndef sub", "return a + b\n\n\ndef sub"
    )
    # The second turn's digest is of the file as the first turn left it (CRLF
    # where the checkout writes CRLF).
    crlf = (ws / "src" / "calc.py").read_bytes().count(b"\r\n") > 0
    after_first = first.replace("\n", "\r\n") if crlf else first
    scenario = Scenario.from_dict(
        {
            "name": "sa3",
            "turns": [
                _plan("Fix add() in src/calc.py so it adds", "src/calc.py"),
                _calls(
                    (
                        "edit_file",
                        {**FIX, "expected_digest": _digest(ws, "src/calc.py")},
                    )
                ),
                _final("add() adds now."),
                _plan(
                    "Make sub() subtract the other way in src/calc.py", "src/calc.py"
                ),
                _calls(
                    (
                        "edit_file",
                        {
                            "path": "src/calc.py",
                            "old": "def sub(a, b):\n    return a - b",
                            "new": "def sub(a, b):\n    return b - a",
                            "expected_digest": hashlib.sha256(
                                after_first.encode("utf-8")
                            ).hexdigest(),
                        },
                    )
                ),
                {**_final("sub() is b - a now."), "repeat": True},
            ],
        }
    )
    with FakeModelServer(scenario) as server:
        _configure(ws, server.base_url, "fake-coder")
        _with_step_tools(ws)
        rec = _session(
            walk,
            ws,
            cols,
            [
                ("request", "fix add"),
                ("expect", r"answer:"),
                ("answer", "a"),
                ("quiet", 4.0),
                ("request", "make sub return b - a"),
                ("expect", r"answer:"),
                ("answer", "a"),
                ("quiet", 4.0),
                ("line", "/rewind"),
                ("expect", r"rewind to which turn"),
                ("answer", "2"),
                ("quiet", 3.0),
            ],
        )
    walk.notes.append(
        "src/calc.py after /rewind: "
        + (ws / "src" / "calc.py").read_text(encoding="utf-8").replace("\n", "\\n")
    )
    return rec


def sa4(tmp: Path, walk: Walk, cols: int) -> Recording:
    """J3 stays as it was: a question reads the project; no workspace, no question."""
    ws = _workspace(tmp, f"sa4_{cols}", git=True, files=APP_FILES)
    with FakeModelServer("j3_ask_code") as server:
        _configure(ws, server.base_url, "fake-coder")
        _with_step_tools(ws)
        rec = _session(
            walk,
            ws,
            cols,
            [("request", "/ask what does add() return?"), ("quiet", 5.0)],
        )
    return rec


JOURNEYS: dict[str, tuple[str, Callable[[Path, Walk, int], Recording]]] = {
    "SA1": ("Fix with the tools; review per hunk before it is applied", sa1),
    "SA2": ("A control file asks at tier 2; allowed for the session", sa2),
    "SA3": ("J7: two turns, then /rewind to the first", sa3),
    "SA4": ("J3: a question needs no workspace and no answer", sa4),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.ux.run_slice_a")
    parser.add_argument("--out", default=str(REPO / "docs" / "ux" / "slice-a"))
    parser.add_argument("--cols", default="80,60,40")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    selected = [s for s in args.only.split(",") if s] or list(JOURNEYS)
    for cols in [int(c) for c in args.cols.split(",")]:
        out = Path(args.out) / str(cols)
        out.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix="ract-slice-a-") as tmpdir:
            tmp = Path(tmpdir)
            for jid in selected:
                title, fn = JOURNEYS[jid]
                walk = Walk(jid, title)
                started = time.perf_counter()
                try:
                    rec: Recording | None = fn(tmp, walk, cols)
                except Exception as exc:  # noqa: BLE001 - a harness failure is a finding
                    walk.notes.append(f"HARNESS ERROR: {type(exc).__name__}: {exc}")
                    rec = None
                header = (
                    f"# {jid}: {title}\n# build: {_build()}  terminal: {cols}x40 "
                    f"pseudo-terminal  run: {time.strftime('%Y-%m-%d %H:%M')}\n"
                )
                plain = header
                if rec is not None:
                    (out / f"{jid}.raw.txt").write_text(
                        _redact(rec.raw, tmp), encoding="utf-8"
                    )
                    (out / f"{jid}.timeline.txt").write_text(
                        _redact(rec.timeline(), tmp), encoding="utf-8"
                    )
                    plain += "## interactive session\n" + rec.plain
                if walk.notes:
                    plain += (
                        "\n## harness notes\n"
                        + "\n".join(f"- {n}" for n in walk.notes)
                        + "\n"
                    )
                (out / f"{jid}.txt").write_text(_redact(plain, tmp), encoding="utf-8")
                walk.metrics["wall_s"] = round(time.perf_counter() - started, 2)
                walk.metrics["notes"] = walk.notes
                summary[jid] = walk.metrics
                print(f"{cols} {jid}: done in {walk.metrics['wall_s']} s", flush=True)
            text = _redact(json.dumps(summary, indent=2) + "\n", tmp)
        (out / "metrics.json").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
