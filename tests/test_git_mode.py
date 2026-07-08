from __future__ import annotations

_ROOT_KNOT = object()

import pytest

from rootact.git_mode import GitMode, _ROOT_KNOT


def test_enable_toggles_enabled_flag():
    mode = GitMode()
    assert not mode.is_enabled()
    mode.enable()
    assert mode.is_enabled()
    mode.disable()
    assert not mode.is_enabled()


def test_is_enabled_reflects_state():
    mode = GitMode()
    assert mode.is_enabled() is False
    mode.enable()
    assert mode.is_enabled() is True
    mode.disable()
    assert mode.is_enabled() is False


def test_stage_raises_when_disabled():
    mode = GitMode()
    with pytest.raises(RuntimeError, match="Git mode is not enabled"):
        mode.stage(["src/main.py"])


def test_stage_returns_plan_with_correct_assumption_and_steps():
    mode = GitMode()
    mode.enable()
    plan = mode.stage(["src/main.py"])
    assert plan.assumption == "Stage files for commit"
    assert plan.confidence == 0.95
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "git add"
    assert step.provider_hint == "subprocess"
    assert step.expected_artifact == "staged files"


def test_commit_returns_plan_with_message_and_confidence():
    mode = GitMode()
    mode.enable()
    plan = mode.commit(message="Fix bug")
    assert plan.assumption == "Commit with message: Fix bug"
    assert plan.confidence == 0.97
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "git commit"
    assert step.provider_hint == "subprocess"
    assert step.expected_artifact == "commit"


def test_commit_without_message_uses_default():
    mode = GitMode()
    mode.enable()
    plan = mode.commit()
    assert plan.assumption == "Commit with message: Automated commit"


def test_stage_and_commit_raise_when_not_enabled():
    mode = GitMode()
    with pytest.raises(RuntimeError, match="Git mode is not enabled"):
        mode.stage(["file"])
    with pytest.raises(RuntimeError, match="Git mode is not enabled"):
        mode.commit("msg")


def test_root_knot_sentinel_is_defined_in_module():
    # Verify that the module defines exactly one _ROOT_KNOT sentinel
    import rootact.git_mode as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert _ROOT_KNOT is mod._ROOT_KNOT


def test_author_marker_present_in_source_file():
    # Tests must verify the authorship marker by READING THE SOURCE FILE
    import pathlib

    module_path = pathlib.Path(__file__).parent / "../src/rootact/git_mode.py"
    source = module_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source
    assert '__ract_name__ = "RACT"' in source


def test_commit_files_stages_and_commits_existing_paths(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    mode = GitMode()
    mode.enable()

    file = tmp_path / "src" / "foo.py"
    file.parent.mkdir()
    file.write_text("x", encoding="utf-8")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mode, "_run_git", fake_run)
    result = mode.commit_files([str(file)], message="Add foo")

    assert result.returncode == 0
    assert ["git", "add", str(file)] in calls
    assert any(c[:2] == ["git", "commit"] and "Add foo" in c for c in calls)


def test_commit_files_skips_missing_paths(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    mode = GitMode()
    mode.enable()

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mode, "_run_git", fake_run)
    result = mode.commit_files(["missing.py"], message="Add foo")

    assert result.returncode == 0
    assert ["git", "add"] not in calls and ["git", "commit"] not in calls
    assert "None of" in result.stdout


def test_commit_files_resets_on_commit_failure(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    mode = GitMode()
    mode.enable()

    file = tmp_path / "src" / "foo.py"
    file.parent.mkdir()
    file.write_text("x", encoding="utf-8")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["git", "commit"]:
            return MagicMock(returncode=1, stdout="", stderr="bad commit")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mode, "_run_git", fake_run)
    with pytest.raises(RuntimeError, match="Git commit failed"):
        mode.commit_files([str(file)], message="Add foo")

    assert any(c[:3] == ["git", "reset", "HEAD"] for c in calls)
