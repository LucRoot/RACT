"""Audit round 2 (seam 6 P2): ``_work_with_step_tools`` resolves its target.

The step-tools path joined ``step.expected_artifact`` onto the step worktree
raw and then did ``read_bytes`` / ``write_bytes(before)`` / ``unlink()`` on
it: ``..`` segments reached the operator's ``.git/`` internals and an
absolute segment won the join outright. The eventual artifact write was
gated; this block was not. The target now goes through
``resolve_workspace_path`` before any filesystem touch, and a refused path
ends the step as the module's normal Rooted step failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class _Adapter:
    name = "fake"


def _failing_work(complete, instruction, project_dir, **kwargs):  # type: ignore[no-untyped-def]
    from ract.rooted import Rooted

    return Rooted(
        value=None,
        assumption="a",
        confidence=0.0,
        provenance=["test"],
        error="provider down",
        hint="provider",
    )


def _executor(worktree: Path):  # type: ignore[no-untyped-def]
    from ract.executor.steps import Executor
    from ract.providers.router import ProviderRouter

    return Executor(router=ProviderRouter({}), project_dir=worktree)


def test_a_parent_segment_artifact_is_refused_before_any_touch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.manager import Step

    worktree = tmp_path / "wt"
    worktree.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("operator data\n", encoding="utf-8")
    reads: list[Path] = []
    real_read_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda p: reads.append(Path(p)) or real_read_bytes(p),
    )
    monkeypatch.setattr("ract.tools.loop.work_with_tools", _failing_work)

    step = Step(action="read it", provider_hint="", expected_artifact="../victim.txt")
    result = _executor(worktree)._work_with_step_tools(
        [_Adapter()], step, "do it", 1, 0.0
    )

    assert not result.is_ok()
    assert "refused" in (result.error or "")
    assert "Nothing was applied" in (result.error or "")
    assert victim not in reads  # the read happened before the fix
    assert victim.read_text(encoding="utf-8") == "operator data\n"


def test_an_absolute_artifact_outside_the_worktree_is_refused_before_any_touch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.manager import Step

    worktree = tmp_path / "wt"
    worktree.mkdir()
    victim = tmp_path / "abs_victim.txt"
    monkeypatch.setattr("ract.tools.loop.work_with_tools", _failing_work)

    step = Step(
        action="plant it",
        provider_hint="",
        expected_artifact=str(victim),
    )
    result = _executor(worktree)._work_with_step_tools(
        [_Adapter()], step, "do it", 1, 0.0
    )

    assert not result.is_ok()
    assert "refused" in (result.error or "")
    assert not victim.exists()


def test_a_plain_relative_artifact_still_reaches_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard must not change what plans may do: an ordinary in-worktree
    # target resolves exactly as the raw join did.
    from ract.manager import Step

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "src").mkdir()
    monkeypatch.setattr("ract.tools.loop.work_with_tools", _failing_work)

    step = Step(action="edit", provider_hint="", expected_artifact="src/app.py")
    result = _executor(worktree)._work_with_step_tools(
        [_Adapter()], step, "do it", 1, 0.0
    )

    # provider failure, not a path refusal: the resolver accepted the target
    assert not result.is_ok()
    assert "refused" not in (result.error or "")
    assert "provider down" in (result.error or "")
