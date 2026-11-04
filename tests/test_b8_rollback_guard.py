"""B-8roll (audit round 2, seam 6, P1): rollback provenance for config files.

A snapshot file under ``.ract/snapshots/`` can be shipped by a cloned
repository. Restoring it must not give a repo-supplied snapshot write access
to config-bearing names (``ract.yaml``, secret-shaped names such as ``.env``,
``.github/workflows/*``). RACT's own snapshots legitimately contain
``ract.yaml``, so the guard is provenance-based: a snapshot whose session id
is known to the operator-side session store (``.ract/sessions/<id>.json``) is
operator-owned and restores normally; any other snapshot file is treated as
repo-supplied and its config-bearing entries are refused, named, and skipped
while the remaining entries still restore.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.session_rollback import SessionRollback
from ract.session_store import SessionStore


def _ship_snapshot(project: Path, session_id: str, files: dict[str, str]) -> None:
    """Write a snapshot file directly, simulating one a cloned repo ships."""
    snap_dir = project / ".ract" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / f"{session_id}.json").write_text(
        json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "files": files}),
        encoding="utf-8",
    )


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".github" / "workflows").mkdir(parents=True)
    (ws / "ract.yaml").write_text("provider: good\n", encoding="utf-8")
    (ws / ".env").write_text("API_KEY=original\n", encoding="utf-8")
    (ws / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    return ws


def test_shipped_snapshot_cannot_restore_config_files(tmp_path: Path) -> None:
    """The finding's repro: a shipped ``default`` snapshot is refused the
    config-bearing entries; the files on disk keep their content and every
    refused entry is named in ``missing``."""
    ws = _workspace(tmp_path)
    _ship_snapshot(
        ws,
        "default",
        {
            "ract.yaml": "provider: attacker-controlled\n",
            ".env": "API_KEY=attacker\n",
            ".github/workflows/ci.yml": "on: push\njobs: [pwn]\n",
        },
    )

    restored, missing = SessionRollback(ws).restore("default")

    assert (ws / "ract.yaml").read_text(encoding="utf-8") == "provider: good\n"
    assert (ws / ".env").read_text(encoding="utf-8") == "API_KEY=original\n"
    assert (ws / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    ) == "name: ci\n"
    assert restored == []
    assert set(missing) == {"ract.yaml", ".env", ".github/workflows/ci.yml"}


def test_operator_snapshot_restores_ract_yaml(tmp_path: Path) -> None:
    """RACT's own snapshot of a session the store knows still restores
    ``ract.yaml``: the feature's purpose is not broken."""
    ws = _workspace(tmp_path)
    rollback = SessionRollback(ws)
    rollback.capture("default", [ws / "ract.yaml"])
    (ws / "ract.yaml").write_text("provider: changed\n", encoding="utf-8")
    SessionStore(ws / ".ract" / "sessions").save("default", {"intent": "demo"})

    restored, missing = rollback.restore("default")

    assert (ws / "ract.yaml").read_text(encoding="utf-8") == "provider: good\n"
    assert restored == ["ract.yaml"]
    assert missing == []


def test_shipped_snapshot_restores_non_config_entries(tmp_path: Path) -> None:
    """A repo-supplied snapshot still restores ordinary project files."""
    ws = _workspace(tmp_path)
    (ws / "src").mkdir()
    app = ws / "src" / "app.py"
    app.write_text("print('original')\n", encoding="utf-8")
    _ship_snapshot(ws, "default", {"src/app.py": "print('shipped')\n"})

    restored, missing = SessionRollback(ws).restore("default")

    assert app.read_text(encoding="utf-8") == "print('shipped')\n"
    assert restored == ["src/app.py"]
    assert missing == []


def test_run_ract_rollback_refuses_shipped_config(tmp_path: Path) -> None:
    """End to end through the runner call path: ``--rollback --session
    default`` on a workspace that ships the snapshot leaves ``ract.yaml``
    alone and still reports a successful rollback command."""
    from ract.ract_runner import run_ract

    ws = _workspace(tmp_path)
    _ship_snapshot(ws, "default", {"ract.yaml": "provider: attacker-controlled\n"})

    result = run_ract(ws / "ract.yaml", "rollback", session_id="default", rollback=True)

    assert result.error is None
    assert (ws / "ract.yaml").read_text(encoding="utf-8") == "provider: good\n"
