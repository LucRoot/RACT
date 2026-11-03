"""B-213 (G3 seam 6, P1): the six remaining `.ract/` state writers take the link guard.

The G3 re-check of seam 6 (paths across systems) dynamically confirmed two
junction escapes through a repo-planted ``.ract/`` junction -- ``ract memory
init`` wrote its SQLite files outside the workspace, and ``DiffApplier``
copied a project file's prior bytes outside the workspace -- and read four
more unguarded writers: ``memory apply-narrowings`` (``budget_overrides.yaml``),
``policy.grant.sign`` (``.ract/policy.yaml.sig``), the consolidation proposal
backups, and ``loop_controller.write_report`` (``.ract/loop_report.json``,
which ``run_reporter.export_report`` already guards -- the two writers of the
same file disagreed).

Every writer below must refuse a planted link or junction loudly, must not
write anything to the link target, and must keep the free-path behavior.

On Windows a junction needs no privilege (``mklink /J``); elsewhere a
symlink stands in.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from ract.workspace_state import StateDirRefused


def _dir_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(f"no junction here: {done.stdout.strip()} {done.stderr.strip()}")
    else:
        link.symlink_to(target, target_is_directory=True)


def _project_with_outside(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    return root, outside


def _nothing_outside(outside: Path) -> None:
    assert [p.name for p in outside.rglob("*")] == []


# ---------------------------------------------------------------- memory init


@pytest.mark.parametrize("linked", [".ract", ".ract/memory"])
def test_memory_init_refuses_a_linked_state_dir(
    tmp_path: Path, linked: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from ract.memory.cli_memory import _memory_init

    root, outside = _project_with_outside(tmp_path)
    (root / "seed.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    link = root / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    _dir_link(link, outside)

    rc = _memory_init([str(root), "--skip-semantic"])
    assert rc == 1
    assert "link or a junction" in capsys.readouterr().err
    _nothing_outside(outside)


# ------------------------------------------------- memory apply-narrowings


def test_apply_narrowings_refuses_a_linked_memory_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ract.memory.cli_memory import _memory_apply_narrowings
    from ract.memory.failure_records import FAILURE_RECORDS_PATH, FailureRecord

    root, outside = _project_with_outside(tmp_path)
    (root / ".ract").mkdir()
    # Three in-window budget_exceeded records on 'edit' -> one narrowing
    # proposal, so the command reaches the overrides write. The records sit
    # in the junction target; reads through a link are allowed, writes are not.
    records = outside / FAILURE_RECORDS_PATH
    records.parent.mkdir(parents=True)
    now = int(time.time())
    lines = []
    for i in range(3):
        rec = FailureRecord(
            function="edit",
            input_token_count=8000,
            output_token_count=0,
            failure_type="budget_exceeded",  # type: ignore[arg-type]
            resolution_level_reached="level_1_format_downgrade",  # type: ignore[arg-type]
            timestamp=now - 100 * (i + 1),
        )
        lines.append(json.dumps(asdict(rec), sort_keys=True))
    records.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _dir_link(root / ".ract" / "memory", outside)

    rc = _memory_apply_narrowings(["--repo-path", str(root)])
    assert rc == 1
    assert "link or a junction" in capsys.readouterr().err
    assert not (outside / "budget_overrides.yaml").exists()
    assert records.read_text(encoding="utf-8") != ""


# --------------------------------------------------------------- diff applier


def test_diff_applier_backup_refuses_a_linked_snapshot_dir(tmp_path: Path) -> None:
    from ract.diff_applier import DiffApplier

    root, outside = _project_with_outside(tmp_path)
    (root / ".ract").mkdir()
    (root / "src").mkdir()
    target = root / "src" / "app.py"
    original = b"line1\r\nline2\r\nline3\r\n"
    target.write_bytes(original)
    _dir_link(root / ".ract" / "diff_snapshots", outside)

    diff = (
        "--- src/app.py\n+++ src/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+CHANGED\n"
        " line3\n"
    )
    results = DiffApplier(root).apply_diff(diff)
    assert len(results) == 1
    assert results[0].applied is False
    assert "link or a junction" in (results[0].message or "")
    _nothing_outside(outside)
    # The hunk is not applied either: the refusal happens before any write.
    assert target.read_bytes() == original


# ---------------------------------------------------------------- grant sign


def _policy_text(project: Path, key_id: str) -> str:
    return (
        "version: 1\n"
        "binding:\n"
        f"  project_root: '{os.path.realpath(project)}'\n"
        "issued_at: 2026-01-01T00:00:00Z\n"
        "expires_at: 2026-12-31T00:00:00Z\n"
        f"key_id: {key_id}\n"
        "max_mode: ask\n"
        "sandbox: best_effort\n"
        "commands:\n"
        "  allow:\n"
        "    - id: tests\n"
        "      argv: [python, -m, pytest]\n"
        "      network: false\n"
        "      timeout_s: 900\n"
        "  deny:\n"
        "    - argv: [git, push]\n"
    )


def test_grant_sign_refuses_a_linked_ract(tmp_path: Path) -> None:
    from ract.policy.grant import PolicyInvalid, sign
    from ract.policy.operator_key import generate, unlock

    project, outside = _project_with_outside(tmp_path)
    passphrase = "throwaway passphrase for a test"
    cfg = tmp_path / "config"
    key = generate(passphrase, config=cfg)
    # The policy is read through the junction (reads are allowed); only the
    # signature write must be refused.
    (outside / "policy.yaml").write_text(
        _policy_text(project, key.key_id), encoding="utf-8"
    )
    _dir_link(project / ".ract", outside)

    with pytest.raises(PolicyInvalid, match="link or a junction"):
        sign(project, unlock(passphrase, config=cfg), key)
    assert not (outside / "policy.yaml.sig").exists()


# ---------------------------------------------------------------- consolidate


def test_consolidate_applier_refuses_a_linked_backup_dir(tmp_path: Path) -> None:
    from ract.consolidate import ConsolidationApplier, MergeProposal

    root, outside = _project_with_outside(tmp_path)
    (root / ".ract").mkdir()
    body = "def f():\n    return 1\n"
    (root / "a.py").write_text(body, encoding="utf-8")
    (root / "b.py").write_text(body, encoding="utf-8")
    _dir_link(root / ".ract" / "consolidate_backups", outside)

    proposal = MergeProposal(
        target="a.py", sources=("b.py",), diff="", reason="test", safe=True
    )
    result = ConsolidationApplier(root).apply(proposal, "test-0001")
    assert result.applied is False
    assert result.error is not None and "link or a junction" in result.error
    _nothing_outside(outside)
    # No shim was written over the source either.
    assert (root / "b.py").read_text(encoding="utf-8") == body


# --------------------------------------------------------------- loop report


def _plain_controller(root: Path):
    from ract.loop_controller import LoopController

    (root / "ract.yaml").write_text("project:\n  name: test\n", encoding="utf-8")
    return LoopController(root / "ract.yaml", max_iterations=1)


def test_loop_controller_write_report_refuses_a_linked_ract(tmp_path: Path) -> None:
    from ract.loop_controller import LoopResult

    root, outside = _project_with_outside(tmp_path)
    controller = _plain_controller(root)
    _dir_link(root / ".ract", outside)

    result = LoopResult(
        iterations=[], final_decision="stop", summary="done", handshake_milestones=[]
    )
    with pytest.raises(StateDirRefused, match="link or a junction"):
        controller.write_report(result)
    _nothing_outside(outside)


def test_run_reporter_export_refuses_the_same_link(tmp_path: Path) -> None:
    from ract.run_reporter import export_report

    root, outside = _project_with_outside(tmp_path)
    _dir_link(root / ".ract", outside)

    with pytest.raises(StateDirRefused, match="link or a junction"):
        export_report({"final_decision": "stop"}, root / ".ract" / "loop_report.json")
    _nothing_outside(outside)


def test_loop_report_writers_agree_on_a_plain_ract(tmp_path: Path) -> None:
    from ract.loop_controller import LoopResult
    from ract.run_reporter import export_report

    root, _ = _project_with_outside(tmp_path)
    controller = _plain_controller(root)
    result = LoopResult(
        iterations=[], final_decision="stop", summary="done", handshake_milestones=[]
    )
    path = controller.write_report(result)
    via_controller = json.loads(path.read_text(encoding="utf-8"))
    assert via_controller["final_decision"] == "stop"

    again = root / ".ract" / "loop_report_again.json"
    export_report(via_controller, again)
    assert json.loads(again.read_text(encoding="utf-8")) == via_controller
