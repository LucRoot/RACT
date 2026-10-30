"""Walk slice (c) in a real pseudo-terminal: J4 with run_tests under a grant (B-112).

Usage (from the repository root)::

    python -m tests.ux.run_slice_c [--out docs/ux/slice-c] [--cols 80,60,40]

Nothing executes a command: ``RACT_FAKE_RUNNER`` points the run at a
scripted runner (every result says ``runner: fake`` and never verifies a
turn). The grant is signed with a throwaway key in a temporary user config
folder. The walk runs this checkout's code (``python -m ract.cli``,
``PYTHONPATH`` on its ``src``) against the fake model server. It writes, per
width, ``<id>.txt``, ``<id>.raw.txt``, ``<id>.timeline.txt`` and
``metrics.json`` with the answers typed per task (condition 3).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux.run_baseline import (
    CALC_FILES,
    _build,
    _configure,
    _env,
    _redact,
    _workspace,
)
from tests.ux.run_slice_b import PASS, _grant_by
from tests.ux.terminal_driver import Recording, spawn

REPO = Path(__file__).resolve().parents[2]
INTENT = "tests/test_calc.py::test_add fails, fix it"


class Walk:
    def __init__(self, jid: str, title: str) -> None:
        self.jid = jid
        self.title = title
        self.notes: list[str] = []
        self.metrics: dict[str, Any] = {"answers": 0}


def _session(
    walk: Walk, ws: Path, config: Path, script: Path, cols: int, steps
) -> Recording:
    # The prompt shows the resolved program: on a PATH of a placeholder
    # ``python`` (it is never run) and git's own folder, so the capture names
    # no program of this machine's other tools.
    import os
    import shutil
    import stat

    bin_dir = config / "walk-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    placeholder = bin_dir / ("python.exe" if os.name == "nt" else "python")
    placeholder.write_text("", encoding="utf-8")
    placeholder.chmod(placeholder.stat().st_mode | stat.S_IEXEC)
    git = shutil.which("git")
    path = os.pathsep.join([str(bin_dir)] + ([str(Path(git).parent)] if git else []))
    env = {
        **_env(),
        "PATH": path,
        "PYTHONPATH": str(REPO / "src"),
        "APPDATA": str(config),
        "XDG_CONFIG_HOME": str(config),
        "RACT_FAKE_RUNNER": str(script),
    }
    with spawn(
        [sys.executable, "-m", "ract.cli"], cwd=str(ws), env=env, cols=cols, rows=40
    ) as s:
        s.expect(r"ract> ", 60)
        for kind, arg in steps:
            if kind == "expect":
                ok = s.expect(arg, 120)
                walk.notes.append(f"expect {arg!r}: {'seen' if ok else 'NOT SEEN'}")
            elif kind in {"answer", "line"}:
                s.send_line(arg)
                if kind == "answer":
                    walk.metrics["answers"] += 1
            elif kind == "quiet":
                s.wait_quiet(arg, timeout=120)
        if s.alive():
            s.send_line("/exit")
        rec = s.close(timeout=20)
    walk.metrics["exit_code"] = rec.exit_code
    return rec


def _setup(
    tmp: Path, name: str, server: FakeModelServer, granted: bool
) -> tuple[Path, Path, Path]:
    ws = _workspace(tmp, name, git=True, files=CALC_FILES)
    _configure(ws, server.base_url, "fake-coder")
    config = tmp / f"{name}_cfg"
    if granted:
        _grant_by(ws, config)
    else:
        from ract.policy.operator_key import generate

        generate(PASS, config=config / "ract")
    script = tmp / f"{name}_runner.json"
    script.write_text(
        json.dumps([{"exit_code": 0, "stdout": "1 passed in 0.01s"}]), encoding="utf-8"
    )
    return ws, config, script


def sc1(tmp: Path, walk: Walk, cols: int) -> Recording:
    """J4: the fix is approved, then the named test runs on a yes."""
    with FakeModelServer("baseline_j4_today") as server:
        ws, config, script = _setup(tmp, f"sc1_{cols}", server, granted=True)
        return _session(
            walk,
            ws,
            config,
            script,
            cols,
            [
                ("line", INTENT),
                ("expect", r"\[y/N\]"),
                ("answer", "y"),  # the step
                ("expect", r"Run it once"),
                ("answer", "y"),  # the command
                ("quiet", 4.0),
            ],
        )


def sc2(tmp: Path, walk: Walk, cols: int) -> Recording:
    """J4 declined: the test does not run, and the summary says so."""
    with FakeModelServer("baseline_j4_today") as server:
        ws, config, script = _setup(tmp, f"sc2_{cols}", server, granted=True)
        return _session(
            walk,
            ws,
            config,
            script,
            cols,
            [
                ("line", INTENT),
                ("expect", r"\[y/N\]"),
                ("answer", "y"),
                ("expect", r"Run it once"),
                ("answer", "n"),
                ("quiet", 4.0),
            ],
        )


def sc3(tmp: Path, walk: Walk, cols: int) -> Recording:
    """No grant: nothing is asked and the summary names the way to a grant."""
    with FakeModelServer("baseline_j4_today") as server:
        ws, config, script = _setup(tmp, f"sc3_{cols}", server, granted=False)
        return _session(
            walk,
            ws,
            config,
            script,
            cols,
            [
                ("line", INTENT),
                ("expect", r"\[y/N\]"),
                ("answer", "y"),
                ("quiet", 5.0),
            ],
        )


JOURNEYS: dict[str, tuple[str, Callable[[Path, Walk, int], Recording]]] = {
    "SC1": ("J4 with a grant: fix, then the named test runs on a yes", sc1),
    "SC2": ("J4 with a grant: the command declined", sc2),
    "SC3": ("J4 with no grant", sc3),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.ux.run_slice_c")
    parser.add_argument("--out", default=str(REPO / "docs" / "ux" / "slice-c"))
    parser.add_argument("--cols", default="80,60,40")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    selected = [s for s in args.only.split(",") if s] or list(JOURNEYS)
    for cols in [int(c) for c in args.cols.split(",")]:
        out = Path(args.out) / str(cols)
        out.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix="ract-slice-c-") as tmpdir:
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
                plain = (
                    f"# {jid}: {title}\n# build: {_build()}  terminal: {cols}x40 "
                    f"pseudo-terminal  run: {time.strftime('%Y-%m-%d %H:%M')}\n"
                )
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
