"""Walk slice (b) in a real pseudo-terminal: the guided grant, the status line, a cloned policy (B-111).

Usage (from the repository root)::

    python -m tests.ux.run_slice_b [--out docs/ux/slice-b] [--cols 80,60,40] [--only SB1]

Every key is a throwaway made in a temporary user config folder for the
walk; the passphrase is a throwaway string typed into the pseudo-terminal.
The walk runs this checkout's code (``python -m ract.cli`` with
``PYTHONPATH`` on its ``src``). For each width it writes ``<id>.txt``,
``<id>.raw.txt``, ``<id>.timeline.txt`` and ``metrics.json`` (the guided
grant's time from the command to the signed result, the answers typed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tests.ux.run_baseline import (
    CALC_FILES,
    _build,
    _configure,
    _env,
    _redact,
    _workspace,
)
from tests.ux.terminal_driver import Recording, spawn, strip_ansi

REPO = Path(__file__).resolve().parents[2]
PASS = "throwaway walk passphrase"


class Walk:
    def __init__(self, jid: str, title: str) -> None:
        self.jid = jid
        self.title = title
        self.notes: list[str] = []
        self.metrics: dict[str, Any] = {"answers": 0}


def _env_for(config: Path) -> dict[str, str]:
    return {
        **_env(),
        "PYTHONPATH": str(REPO / "src"),
        "APPDATA": str(config),
        "XDG_CONFIG_HOME": str(config),
    }


def _drive(
    walk: Walk,
    argv: list[str],
    ws: Path,
    config: Path,
    cols: int,
    steps: list[tuple[str, Any]],
) -> Recording:
    with spawn(
        [sys.executable, "-m", "ract.cli", *argv],
        cwd=str(ws),
        env=_env_for(config),
        cols=cols,
        rows=40,
    ) as session:
        for kind, arg in steps:
            if kind == "expect":
                ok = session.expect(arg, 120)
                walk.notes.append(f"expect {arg!r}: {'seen' if ok else 'NOT SEEN'}")
            elif kind in {"answer", "line"}:
                session.send_line(arg)
                if kind == "answer":
                    walk.metrics["answers"] += 1
            elif kind == "quiet":
                session.wait_quiet(arg, timeout=60)
        if argv == [] and session.alive():
            session.send_line("/exit")
        rec = session.close(timeout=20)
    walk.metrics["exit_code"] = rec.exit_code
    return rec


def _grant_by(ws: Path, config: Path, *, days_ago: int = 0, days: int = 90) -> None:
    """Sign a grant for *ws* with the throwaway key in *config* (made if missing)."""
    from ract.policy.grant import sign
    from ract.policy.operator_key import NoOperatorKey, generate, load_public, unlock

    try:
        key = load_public(config / "ract")
    except NoOperatorKey:
        key = generate(PASS, config=config / "ract")
    issued = datetime.now(timezone.utc) - timedelta(days=days_ago)
    (ws / ".ract").mkdir(exist_ok=True)
    (ws / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(ws)}'\n"
        f"issued_at: {issued:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {issued + timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "max_mode: ask\n"
        "sandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n",
        encoding="utf-8",
    )
    sign(ws, unlock(PASS, config=config / "ract"), key)


def sb1(tmp: Path, walk: Walk, cols: int) -> Recording:
    """A new user: no key, no grant, to a signed pytest rule (D13, under two minutes)."""
    ws = _workspace(tmp, f"sb1_{cols}", git=True, files=CALC_FILES)
    config = tmp / f"sb1_cfg_{cols}"
    started = time.perf_counter()
    rec = _drive(
        walk,
        ["policy", "init", "--guided"],
        ws,
        config,
        cols,
        [
            ("expect", r"\[y/N\]"),
            ("answer", "y"),
            ("expect", r"New passphrase"),
            ("answer", PASS),
            ("expect", r"Again"),
            ("answer", PASS),
            ("expect", r"Tier 3: T3 ask"),
        ],
    )
    walk.metrics["to_signed_s"] = round(time.perf_counter() - started, 2)
    signed_at = next(
        (
            e.t
            for e in rec.events
            if e.kind == "out" and "Signed .ract" in strip_ansi(e.data)
        ),
        None,
    )
    walk.metrics["to_signed_in_terminal_s"] = (
        None if signed_at is None else round(signed_at, 2)
    )
    walk.notes.append(
        f"policy.yaml.sig exists: {(ws / '.ract' / 'policy.yaml.sig').is_file()}"
    )
    return rec


def sb2(tmp: Path, walk: Walk, cols: int) -> Recording:
    """The session's status line with a signed grant, and /permissions."""
    ws = _workspace(tmp, f"sb2_{cols}", git=True, files=CALC_FILES)
    _configure(ws, "http://127.0.0.1:9/v1", "fake-coder")
    config = tmp / f"sb2_cfg_{cols}"
    _grant_by(ws, config)
    return _drive(
        walk,
        [],
        ws,
        config,
        cols,
        [("expect", r"ract> "), ("line", "/permissions"), ("quiet", 2.0)],
    )


def sb3(tmp: Path, walk: Walk, cols: int) -> Recording:
    """A cloned repository's grant, signed by someone else's key, grants nothing."""
    ws = _workspace(tmp, f"sb3_{cols}", git=True, files=CALC_FILES)
    _configure(ws, "http://127.0.0.1:9/v1", "fake-coder")
    theirs = tmp / f"sb3_theirs_{cols}"
    _grant_by(ws, theirs)
    mine = tmp / f"sb3_mine_{cols}"
    from ract.policy.operator_key import generate

    generate(PASS, config=mine / "ract")
    return _drive(
        walk,
        [],
        ws,
        mine,
        cols,
        [("expect", r"ract> "), ("line", "/permissions"), ("quiet", 2.0)],
    )


def sb4(tmp: Path, walk: Walk, cols: int) -> Recording:
    """An expired grant: tier 3 off, with the date."""
    ws = _workspace(tmp, f"sb4_{cols}", git=True, files=CALC_FILES)
    _configure(ws, "http://127.0.0.1:9/v1", "fake-coder")
    config = tmp / f"sb4_cfg_{cols}"
    _grant_by(ws, config, days_ago=100, days=90)
    return _drive(walk, [], ws, config, cols, [("expect", r"ract> "), ("quiet", 1.0)])


JOURNEYS: dict[str, tuple[str, Callable[[Path, Walk, int], Recording]]] = {
    "SB1": ("A new user's first grant with ract policy init --guided", sb1),
    "SB2": ("The status line and /permissions with a signed grant", sb2),
    "SB3": ("A cloned repository's grant grants nothing", sb3),
    "SB4": ("An expired grant", sb4),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.ux.run_slice_b")
    parser.add_argument("--out", default=str(REPO / "docs" / "ux" / "slice-b"))
    parser.add_argument("--cols", default="80,60,40")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    selected = [s for s in args.only.split(",") if s] or list(JOURNEYS)
    for cols in [int(c) for c in args.cols.split(",")]:
        out = Path(args.out) / str(cols)
        out.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix="ract-slice-b-") as tmpdir:
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
                    # The timeline logs what the harness typed; the
                    # passphrase, a throwaway, is still not published.
                    (out / f"{jid}.timeline.txt").write_text(
                        _redact(rec.timeline(), tmp).replace(
                            PASS, "<typed passphrase>"
                        ),
                        encoding="utf-8",
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
