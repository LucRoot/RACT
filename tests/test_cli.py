# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RootAct CLI."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import patch

import rootact
from rootact.cli import main
from rootact.executor import ExecutionReport, StepResult
from rootact.loop_controller import LoopResult
from rootact.manager import Plan, Step
from rootact.rooted import Rooted


def test_cli_version_flag(capsys):
    code = main(["--version"])
    assert code == 0
    out = capsys.readouterr().out
    assert rootact.__version__ in out
    assert "RACT" in out


def test_cli_dry_run_success(capsys):
    plan = Plan(
        assumption="test assumption",
        confidence=0.95,
        steps=[
            Step(
                action="write tests",
                provider_hint="chat",
                expected_artifact="tests/test_x.py",
            )
        ],
    )
    with patch(
        "rootact.cli.run_rootact",
        return_value=Rooted(
            value=plan,
            assumption="ok",
            confidence=0.95,
            provenance=["rootact_runner.run_rootact"],
        ),
    ):
        code = main(["write tests", "--config", "rootact.yaml", "--dry-run"])

    assert code == 0
    out = capsys.readouterr().out
    assert "write tests" in out
    assert "test assumption" in out
    assert "tests/test_x.py" in out
    assert "quality score" in out.lower()


def test_cli_run_success(capsys):
    step = Step(
        action="write tests", provider_hint="chat", expected_artifact="tests/test_x.py"
    )
    report = ExecutionReport(
        intent="write tests",
        step_results=[StepResult(step=step, raw_response={}, content="done")],
        assumptions=["test assumption"],
        provenance={},
        artifacts={},
        plan=Plan(assumption="test assumption", confidence=0.95, steps=[step]),
    )
    with patch(
        "rootact.cli.run_rootact",
        return_value=Rooted(
            value=report,
            assumption="ok",
            confidence=0.95,
            provenance=["rootact_runner.run_rootact"],
        ),
    ):
        code = main(["write tests", "--config", "rootact.yaml"])

    assert code == 0
    out = capsys.readouterr().out
    assert "write tests" in out
    assert "test assumption" in out
    assert "done" in out
    assert "quality score" in out.lower()
    assert "0.475" in out


def test_cli_failure(capsys):
    with patch(
        "rootact.cli.run_rootact",
        return_value=Rooted(
            value=None,
            assumption="config missing",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error="Configuration file not found: missing.yaml",
        ),
    ):
        code = main(["write tests", "--config", "missing.yaml"])

    assert code == 1
    err = capsys.readouterr().err
    assert "failed" in err
    assert "not found" in err.lower()


def test_cli_default_config_is_cwd_file():
    """The CLI should default to a rootact.yaml in the current directory."""
    with patch("rootact.cli.run_rootact") as mock_run:
        mock_run.return_value = Rooted(
            value=Plan(assumption="a", confidence=1.0, steps=[]),
            assumption="ok",
            confidence=1.0,
        )
        main(["hello"])
        mock_run.assert_called_once_with(
            Path("rootact.yaml"),
            "hello",
            dry_run=False,
            mode="default",
            session_id=None,
            resume=False,
            force=False,
            rollback=False,
            project_doc=None,
            yolo=False,
            auto=False,
            reload=False,
            stream=False,
            stream_callback=None,
            allow_load_bearing_override=False,
            allow_novelty_overrun=False,
        )


def test_cli_documentation_mode_passes_mode(capsys):
    plan = Plan(assumption="a", confidence=1.0, steps=[])
    with patch("rootact.cli.run_rootact") as mock_run:
        mock_run.return_value = Rooted(value=plan, assumption="ok", confidence=1.0)
        code = main(["update docs", "--mode", "documentation", "--dry-run"])
    assert code == 0
    mock_run.assert_called_once_with(
        Path("rootact.yaml"),
        "update docs",
        dry_run=True,
        mode="documentation",
        session_id=None,
        resume=False,
        force=False,
        rollback=False,
        project_doc=None,
        yolo=False,
        auto=False,
        reload=False,
        stream=False,
        stream_callback=None,
        allow_load_bearing_override=False,
        allow_novelty_overrun=False,
    )
    out = capsys.readouterr().out
    assert "mode: documentation" in out


def test_cli_self_test_runs_pytest(capsys):
    from rootact.self_test_benchmark_mode import PytestRunResult

    result = PytestRunResult(
        command=["python", "-m", "pytest", "-q"],
        returncode=0,
        passed=3,
        failed=0,
        output="ok",
    )
    with patch(
        "rootact.cli.SelfTestBenchmarkMode.run_tests",
        return_value=result,
    ) as mock_self_test:
        code = main(["--self-test"])
    assert code == 0
    mock_self_test.assert_called_once()
    out = capsys.readouterr().out
    assert "self-test" in out.lower()


def test_cli_review_diff_reviews_file(tmp_path, capsys):
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(
        "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old\n+print('debug')\n",
        encoding="utf-8",
    )
    code = main(["--review-diff", str(diff_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "reviewing diff" in out.lower()
    assert "debug print" in out.lower() or "print" in out.lower()


def test_cli_review_diff_missing_file(tmp_path, capsys):
    code = main(["--review-diff", str(tmp_path / "missing.diff")])
    assert code == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_cli_stream_flag_passes_stream_to_runner(capsys):
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(step=Step("a", "b", "c"), raw_response={}, content="streamed")
        ],
        assumptions=["a"],
        provenance={},
        artifacts={},
    )
    with patch("rootact.cli.run_rootact") as mock_run:
        mock_run.return_value = Rooted(value=report, assumption="ok", confidence=0.9)
        code = main(["write tests", "--stream"])

    assert code == 0
    assert mock_run.call_args.kwargs.get("stream") is True
    assert mock_run.call_args.kwargs.get("stream_callback") is not None
    out = capsys.readouterr().out
    assert "streaming mode" in out.lower()


def test_cli_init_provider_writes_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["--init-provider", "local"])
    assert code == 0
    config_path = tmp_path / "rootact.yaml"
    assert config_path.is_file()
    text = config_path.read_text(encoding="utf-8")
    assert "manager_provider: local" in text
    assert "adapter: local_http" in text
    assert (tmp_path / "prompts" / "manager.txt").is_file()
    assert "RootAct Core Manager" in (tmp_path / "prompts" / "manager.txt").read_text(
        encoding="utf-8"
    )


def test_cli_init_provider_refuses_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rootact.yaml").write_text("existing: true\n", encoding="utf-8")
    code = main(["--init-provider", "local"])
    assert code == 1
    err = capsys.readouterr().err
    assert "already exists" in err.lower()


def test_cli_skills_list(capsys):
    code = main(["skills", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "python-package" in out
    assert "test-generation" in out


def test_cli_skills_install(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["skills", "install", "python-package"])
    assert code == 0
    assert (tmp_path / "skills" / "python-package.json").is_file()


def test_cli_skills_install_unknown():
    code = main(["skills", "install", "nonexistent"])
    assert code == 1


def test_cli_report_last_shows_loop_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        '{"final_decision": "done", "summary": "ok", "handshake_milestones": [], "iterations": []}',
        encoding="utf-8",
    )
    code = main(["report", "--last", "--config", str(tmp_path / "rootact.yaml")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Final decision: done" in out


def test_cli_handshakes_list(capsys):
    code = main(["handshakes", "list"])
    assert code == 0


def test_cli_handshakes_approve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = __import__(
        "rootact.handshake_registry", fromlist=["HandshakeRegistry"]
    ).HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "push")
    code = main(["handshakes", "approve", "m1"])
    assert code == 0
    assert registry.entries()[0].status == "approved"


def test_cli_loop_mode_runs_until_done(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    fake_result = LoopResult(
        iterations=[],
        final_decision="done",
        summary="All milestones completed.",
        handshake_milestones=[],
    )
    with patch(
        "rootact.cli.LoopController.run",
        return_value=fake_result,
    ):
        code = main(["build a thing", "--config", str(config_path), "--loop"])

    assert code == 0
    out = capsys.readouterr().out
    assert "loop mode" in out.lower()
    assert "done" in out.lower()
    assert "loop report" in out.lower()


def test_cli_loop_mode_returns_failure_on_regression(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    fake_result = LoopResult(
        iterations=[],
        final_decision="regression",
        summary="Tests failed.",
        handshake_milestones=[],
    )
    with patch(
        "rootact.cli.LoopController.run",
        return_value=fake_result,
    ):
        code = main(["build a thing", "--config", str(config_path), "--loop"])

    assert code == 1
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "regression" in combined


def test_cli_about(capsys):
    code = main(["--about"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dr. Lucas Root" in out
    assert "Root Knot" in out


def test_cli_yolo_and_auto_mutually_exclusive(capsys):
    code = main(["do thing", "--yolo", "--auto"])
    assert code == 1
    err = capsys.readouterr().err
    assert "mutually exclusive" in err.lower()


def test_cli_report_session_shows_session_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    store = __import__("rootact.session_store", fromlist=["SessionStore"]).SessionStore(
        tmp_path / ".rootact" / "sessions"
    )
    store.save("demo", {"intent": "test", "plan": {}, "artifacts": {}, "outcomes": []})
    code = main(
        ["report", "--session", "demo", "--config", str(tmp_path / "rootact.yaml")]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "demo" in out.lower()


def test_cli_handshakes_reject_and_defer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = __import__(
        "rootact.handshake_registry", fromlist=["HandshakeRegistry"]
    ).HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "push")

    assert main(["handshakes", "reject", "m1"]) == 0
    assert registry.entries()[0].status == "rejected"

    assert main(["handshakes", "defer", "m1"]) == 0
    assert registry.entries()[0].status == "deferred"


def test_cli_refactor_dry_run(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "core.py").write_text("def process():\n    pass\n", encoding="utf-8")

    code = main(
        [
            "refactor",
            "--old",
            "process",
            "--new",
            "handle",
            "--dry-run",
            "--config",
            str(config_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    # Path separators differ across platforms; accept either form.
    assert "src/core.py" in out or "src\\core.py" in out
    assert "handle" in out
    assert "Dry run" in out
    # Ensure files were not modified.
    assert "def process():" in (src / "core.py").read_text(encoding="utf-8")


# RACT 0.1.0 - Initial Public Release
