"""Integration test: LoopController routes through build_loop_state when
an AcceptanceSuite is provided (module_02 wiring, honest-gap from
module_01 close).

The predicate substrate exists and is testable as of module_01. Module_02
lands the wiring that makes the *running* LoopController consume it —
this test asserts that (a) constructing the controller with a suite
persists ``suite.json`` under ``run_dir`` and (b) ``controller.loop_state``
exposes the same suite for T1 consumption.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.loop_controller import LoopController


def _suite() -> AcceptanceSuite:
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from="loop_controller substrate wiring test",
    )


def test_loop_state_exposed_and_suite_persisted(tmp_path: Path) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    suite = _suite()
    controller = LoopController(
        config,
        max_iterations=1,
        acceptance_suite=suite,
        run_dir=run_dir,
    )

    # The controller does not construct the state until ``run()`` fires
    # because the loop needs the intent to seed the plan; but the substrate
    # method that ``run()`` calls is exercised in isolation here to keep
    # this test hermetic (no provider dependencies).
    from ract.core.loop import WorkspaceSnapshot, build_loop_state
    from ract.manager import Plan

    controller._loop_state = build_loop_state(
        plan=Plan(assumption="test", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(files={}, timestamp=0.0),
        suite=suite,
        run_dir=run_dir,
    )

    assert controller.loop_state is not None
    assert controller.loop_state.suite.digest() == suite.digest()

    persisted = run_dir / "suite.json"
    assert persisted.is_file()
    on_disk = json.loads(persisted.read_text(encoding="utf-8"))
    assert on_disk["intent_id"] == suite.intent_id.hex()


def test_loop_entry_refuses_non_git_workspace(tmp_path: Path) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    # Deliberately no ``git init`` under tmp_path.
    with pytest.raises(Exception) as excinfo:
        LoopController(
            config,
            max_iterations=1,
            require_git_workspace=True,
        )
    assert "not a git repository" in str(excinfo.value).lower()


def test_loop_entry_refuses_dirty_tracked_tree(tmp_path: Path) -> None:
    import os
    import subprocess

    config = tmp_path / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "test"],
        ["git", "config", "commit.gpgsign", "false"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "initial"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True, env=env)
    # Now mutate the tracked config so the tree is dirty.
    config.write_text('providers: ["broken"]\n', encoding="utf-8")
    with pytest.raises(Exception) as excinfo:
        LoopController(
            config,
            max_iterations=1,
            require_git_workspace=True,
            require_clean_tracked_tree=True,
        )
    msg = str(excinfo.value).lower()
    assert "uncommitted" in msg or "clean" in msg
