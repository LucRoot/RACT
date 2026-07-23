# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import yaml

from ract.executor import ExecutionReport, StepResult
from ract.harness import Harness
from ract.manager import Plan, Step
from ract.ract_runner import run_ract
from ract.rooted import Rooted

_ROOT_KNOT = object()


def _write_config(tmp_path: Path) -> Path:
    config = {
        "project": {"name": "test-project"},
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "test-model",
            }
        },
    }
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "manager.txt").write_text(
        "You are a helpful coding assistant.", encoding="utf-8"
    )
    return config_path


def test_run_ract_missing_config() -> None:
    result = run_ract(Path("/nonexistent/ract.yaml"), "intent")
    assert not result.is_ok()
    assert "not found" in (result.error or "").lower()


def test_run_ract_invalid_config(tmp_path: Path) -> None:
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("invalid: [", encoding="utf-8")

    result = run_ract(config_path, "intent")

    assert not result.is_ok()
    assert "preflight" in (result.error or "").lower()


def test_run_ract_dry_run_success(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    plan = Plan(assumption="test plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(config_path, "intent", dry_run=True)

    assert result.is_ok()
    assert isinstance(result.unwrap(), Plan)
    mock_harness.planner.plan.assert_called_once_with("intent")


def test_run_ract_execution_success(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="x")],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.run.return_value = Rooted(
        value=report, assumption="executed", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            return_value=Rooted(value=report, assumption="enriched", confidence=0.9),
        ) as mock_enrich:
            result = run_ract(config_path, "intent")

    assert result.is_ok()
    assert result.unwrap() is report
    mock_enrich.assert_called_once_with(
        mock_harness,
        "intent",
        mode="default",
        pre_execute_callback=ANY,
        approval_callback=ANY,
        memory_arena=ANY,
        stream=ANY,
        stream_callback=ANY,
    )


def test_run_ract_harness_init_failure(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(
            value=None, error="bad adapter", assumption="loaded", confidence=0.0
        ),
    ):
        result = run_ract(config_path, "intent")

    assert not result.is_ok()
    assert "bad adapter" in (result.error or "")


def test_run_ract_unsupported_mode(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "intent", mode="invalid")
    assert not result.is_ok()
    assert "unsupported" in (result.error or "").lower()
    assert "default" in (result.error or "")
    assert "documentation" in (result.error or "")
    assert "git" in (result.error or "")


def test_run_ract_documentation_mode_rewrites_intent(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    plan = Plan(assumption="test plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(
            config_path, "update docs", dry_run=True, mode="documentation"
        )

    assert result.is_ok()
    called_intent = mock_harness.planner.plan.call_args[0][0]
    assert "DOCUMENTATION MODE" in called_intent
    assert "update docs" in called_intent


def test_run_ract_saves_session_after_dry_run(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    plan = Plan(assumption="test plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(config_path, "intent", dry_run=True, session_id="s1")

    assert result.is_ok()
    session_file = tmp_path / ".ract" / "sessions" / "s1.json"
    assert session_file.exists()


def test_run_ract_resume_without_session_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "intent", resume=True)
    assert not result.is_ok()
    assert "requires --session" in (result.error or "")


def test_run_ract_resume_loads_prior_session(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.ract_runner import _session_store_for

    store = _session_store_for(config_path)
    plan = Plan(assumption="prior", confidence=0.9, steps=[Step("a", "b", "c")])
    from ract.session_store import SessionState
    from dataclasses import asdict

    store.save(
        "s1",
        asdict(
            SessionState(
                intent="original intent",
                plan=plan,
                outcomes=["step a -> c"],
                artifacts={},
            )
        ),
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(
            config_path, "ignored", dry_run=True, session_id="s1", resume=True
        )

    assert result.is_ok()
    called_intent = mock_harness.planner.plan.call_args[0][0]
    assert "Resuming session 's1'" in called_intent
    assert "original intent" in called_intent
    assert "step a -> c" in called_intent


def test_run_ract_overwrite_without_force_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.ract_runner import _session_store_for
    from ract.session_store import SessionState
    from dataclasses import asdict

    store = _session_store_for(config_path)
    store.save(
        "s1",
        asdict(
            SessionState(
                intent="old", plan=Plan("old", 0.5, []), outcomes=[], artifacts={}
            )
        ),
    )

    result = run_ract(config_path, "new intent", session_id="s1")
    assert not result.is_ok()
    assert "already exists" in (result.error or "").lower()
    assert "--force" in (result.error or "") or "--resume" in (result.error or "")


def test_run_ract_overwrite_with_force_succeeds(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.ract_runner import _session_store_for
    from ract.session_store import SessionState
    from dataclasses import asdict

    store = _session_store_for(config_path)
    store.save(
        "s1",
        asdict(
            SessionState(
                intent="old", plan=Plan("old", 0.5, []), outcomes=[], artifacts={}
            )
        ),
    )

    plan = Plan(assumption="new plan", confidence=0.9, steps=[Step("a", "b", "c")])
    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(
            config_path, "new intent", dry_run=True, session_id="s1", force=True
        )

    assert result.is_ok()


def test_run_ract_resume_corrupted_session_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.ract_runner import _session_store_for

    store = _session_store_for(config_path)
    session_file = store.base_dir / "s1.json"
    session_file.write_text("not valid json", encoding="utf-8")

    result = run_ract(config_path, "intent", session_id="s1", resume=True)
    assert not result.is_ok()
    assert "corrupted" in (result.error or "").lower()


def test_run_ract_rollback_without_session_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "intent", rollback=True)
    assert not result.is_ok()
    assert "requires --session" in (result.error or "")


def test_run_ract_rollback_restores_snapshot(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.session_rollback import SessionRollback

    rollback = SessionRollback(tmp_path)
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    rollback.capture("s1", [target])
    target.write_text("changed", encoding="utf-8")

    result = run_ract(config_path, "ignored", session_id="s1", rollback=True)
    assert result.is_ok()
    assert target.read_text(encoding="utf-8") == "original"


def test_run_ract_rollback_missing_snapshot_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "ignored", session_id="s1", rollback=True)
    assert not result.is_ok()
    assert "no snapshot" in (result.error or "").lower()


def test_run_ract_missing_project_doc_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "intent", project_doc=tmp_path / "missing.json")
    assert not result.is_ok()
    assert "project document" in (result.error or "").lower()


def test_run_ract_project_doc_prefixes_intent(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    doc_path = tmp_path / "doc.json"
    doc_path.write_text(
        '{"goal": "Build a CLI", "plan": [], "notes": ["use argparse"]}',
        encoding="utf-8",
    )
    plan = Plan(assumption="plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(config_path, "add flag", dry_run=True, project_doc=doc_path)

    assert result.is_ok()
    called_intent = mock_harness.planner.plan.call_args[0][0]
    assert "Project goal: Build a CLI" in called_intent
    assert "Project notes: use argparse" in called_intent
    assert "add flag" in called_intent


def test_run_ract_project_doc_updates_plan(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    doc_path = tmp_path / "doc.json"
    doc_path.write_text('{"goal": "Build a CLI", "plan": []}', encoding="utf-8")
    plan = Plan(assumption="plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(config_path, "add flag", dry_run=True, project_doc=doc_path)

    assert result.is_ok()
    updated = json.loads(doc_path.read_text(encoding="utf-8"))
    assert len(updated["plan"]) == 1
    assert updated["plan"][0]["action"] == "a"


def test_run_ract_yolo_and_auto_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path)
    result = run_ract(config_path, "intent", yolo=True, auto=True)
    assert not result.is_ok()
    assert "mutually exclusive" in (result.error or "").lower()


def test_run_ract_yolo_passes_approval_callback(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="x")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.run.return_value = Rooted(
        value=report, assumption="executed", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            return_value=Rooted(value=report, assumption="enriched", confidence=0.9),
        ) as mock_enrich:
            result = run_ract(config_path, "intent", yolo=True)

    assert result.is_ok()
    callback = mock_enrich.call_args.kwargs.get("approval_callback")
    assert callback is not None
    assert callback(Step("any", "code", "x")) is True


def test_run_ract_auto_passes_console_callback(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="x")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.run.return_value = Rooted(
        value=report, assumption="executed", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            return_value=Rooted(value=report, assumption="enriched", confidence=0.9),
        ) as mock_enrich:
            result = run_ract(config_path, "intent", auto=True)

    assert result.is_ok()
    callback = mock_enrich.call_args.kwargs.get("approval_callback")
    assert callback is not None
    assert callback.__name__ == "console_approval_callback"


def test_run_ract_saves_memory_arena_for_session(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="x")],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.run.return_value = Rooted(
        value=report, assumption="executed", confidence=0.9
    )

    def _fake_enrich(_harness, _intent, *, memory_arena=None, **kwargs):
        # Simulate the real enricher recording into the arena.
        if memory_arena is not None:
            memory_arena.record(
                "plan",
                "assumption=test plan; confidence=0.9; steps=1",
                importance=2,
            )
            memory_arena.record(
                "outcome",
                f"{step.action} -> {step.expected_artifact}",
                importance=1,
            )
        return Rooted(value=report, assumption="enriched", confidence=0.9)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            side_effect=_fake_enrich,
        ) as mock_enrich:
            result = run_ract(config_path, "intent", session_id="mem_session")

    assert result.is_ok()
    memory_file = tmp_path / ".ract" / "memory" / "mem_session.json"
    assert memory_file.exists()
    data = json.loads(memory_file.read_text(encoding="utf-8"))
    categories = {item["category"] for item in data}
    assert "plan" in categories
    assert "outcome" in categories
    # Memory arena should have been passed to the enricher.
    assert mock_enrich.call_args.kwargs.get("memory_arena") is not None


def test_run_ract_reload_executes_twice(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="x")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)
    mock_harness.run.return_value = Rooted(
        value=report, assumption="executed", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            return_value=Rooted(value=report, assumption="enriched", confidence=0.9),
        ) as mock_enrich:
            result = run_ract(config_path, "intent", reload=True)

    assert result.is_ok()
    assert mock_enrich.call_count == 2


def test_run_ract_reload_second_run_fails(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="x")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            side_effect=[
                Rooted(value=report, assumption="enriched", confidence=0.9),
                Rooted(
                    value=None,
                    error="second run failed",
                    assumption="failed",
                    confidence=0.0,
                ),
            ],
        ) as mock_enrich:
            result = run_ract(config_path, "intent", reload=True)

    assert not result.is_ok()
    assert "second run failed" in (result.error or "")
    assert mock_enrich.call_count == 2


def test_run_ract_stream_callback_passed(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="x")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)

    def _fake_callback(
        _harness, _intent, *, stream=False, stream_callback=None, **kwargs
    ):
        if stream_callback is not None:
            stream_callback("delta")
        return Rooted(value=report, assumption="enriched", confidence=0.9)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            side_effect=_fake_callback,
        ) as mock_enrich:
            deltas: list[str] = []
            result = run_ract(
                config_path, "intent", stream=True, stream_callback=deltas.append
            )

    assert result.is_ok()
    assert "delta" in deltas
    assert mock_enrich.call_args.kwargs.get("stream") is True


def test_run_ract_rollback_with_missing_file(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.session_rollback import SessionRollback

    rollback = SessionRollback(tmp_path)
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    rollback.capture("s1", [target])
    target.write_text("changed", encoding="utf-8")

    # Manually inject a missing file entry into the snapshot.
    snapshot_path = rollback.snapshot_dir / "s1.json"
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    data["files"]["src/missing.py"] = "content"
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")
    # Create a directory where the file would be restored.
    (tmp_path / "src" / "missing.py").mkdir(parents=True, exist_ok=True)

    result = run_ract(config_path, "ignored", session_id="s1", rollback=True)
    assert result.is_ok()
    assert target.read_text(encoding="utf-8") == "original"
    report = result.unwrap()
    assert isinstance(report, ExecutionReport)


def test_run_ract_default_mode_when_none(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    plan = Plan(assumption="plan", confidence=0.9, steps=[Step("a", "b", "c")])

    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(config_path, "intent", dry_run=True, mode=None)

    assert result.is_ok()
    called_intent = mock_harness.planner.plan.call_args[0][0]
    assert "DOCUMENTATION MODE" not in called_intent


def test_run_ract_resume_includes_prior_artifacts(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    from ract.ract_runner import _session_store_for
    from ract.session_store import SessionState
    from dataclasses import asdict

    store = _session_store_for(config_path)
    store.save(
        "s1",
        asdict(
            SessionState(
                intent="original intent",
                plan=Plan("prior", 0.9, [Step("a", "b", "c")]),
                outcomes=[],
                artifacts={"src/foo.py": {"checksum": "abc"}},
            )
        ),
    )

    plan = Plan(assumption="plan", confidence=0.9, steps=[Step("a", "b", "c")])
    mock_harness = MagicMock(spec=Harness)
    mock_harness.planner = MagicMock()
    mock_harness.planner.plan.return_value = Rooted(
        value=plan, assumption="planned", confidence=0.9
    )

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        result = run_ract(
            config_path, "ignored", dry_run=True, session_id="s1", resume=True
        )

    assert result.is_ok()
    called_intent = mock_harness.planner.plan.call_args[0][0]
    assert "src/foo.py" in called_intent


def test_run_ract_captures_rollback_snapshot(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")

    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="x")],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)

    captured_plan: Plan | None = None

    def _fake_enrich(_harness, _intent, *, pre_execute_callback=None, **kwargs):
        nonlocal captured_plan
        plan = Plan(assumption="plan", confidence=0.9, steps=[step])
        captured_plan = plan
        if pre_execute_callback is not None:
            pre_execute_callback(plan)
        return Rooted(value=report, assumption="enriched", confidence=0.9)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            side_effect=_fake_enrich,
        ):
            result = run_ract(config_path, "intent", session_id="s1")

    assert result.is_ok()
    assert captured_plan is not None
    snapshot_path = tmp_path / ".ract" / "snapshots" / "s1.json"
    assert snapshot_path.is_file()


def test_run_ract_project_doc_updates_after_execution(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    doc_path = tmp_path / "doc.json"
    doc_path.write_text('{"goal": "Build a CLI", "plan": []}', encoding="utf-8")
    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="x")],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )

    mock_harness = MagicMock(spec=Harness)

    with patch(
        "ract.ract_runner.Harness.from_config_path",
        return_value=Rooted(value=mock_harness, assumption="loaded", confidence=1.0),
    ):
        with patch(
            "ract.ract_runner.enrich_harness_run",
            return_value=Rooted(value=report, assumption="enriched", confidence=0.9),
        ):
            result = run_ract(config_path, "add flag", project_doc=doc_path)

    assert result.is_ok()
    updated = json.loads(doc_path.read_text(encoding="utf-8"))
    assert len(updated["plan"]) == 1
    assert updated["plan"][0]["action"] == "write"


# RACT 0.1.1 - Trust and tooling
