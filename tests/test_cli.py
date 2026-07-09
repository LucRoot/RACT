# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RootAct CLI."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import patch

import json

import pytest
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


def test_cli_welcome_flag(capsys):
    code = main(["--welcome"])
    assert code == 0
    out = capsys.readouterr().out
    assert "RACT" in out


def test_cli_coverage_delta_missing_files(capsys):
    code = main(["coverage", "delta"])
    assert code == 1
    err = capsys.readouterr().err
    assert "requires --before and --after" in err.lower()


def test_cli_coverage_delta_unreadable_before(tmp_path, capsys):
    before = tmp_path / "before.json"
    before.write_text("not json", encoding="utf-8")
    after = tmp_path / "after.json"
    after.write_text("{}", encoding="utf-8")
    code = main(["coverage", "delta", "--before", str(before), "--after", str(after)])
    assert code == 1
    err = capsys.readouterr().err
    assert "failed to read before snapshot" in err.lower()


def test_cli_whisper_missing_config(capsys):
    code = main(["whisper", "--intent", "test", "--config", "missing.yaml"])
    assert code == 1
    err = capsys.readouterr().err
    assert "config not found" in err.lower()


def test_cli_whisper_bad_yaml(tmp_path, capsys):
    config = tmp_path / "rootact.yaml"
    config.write_text("not: valid: yaml:::", encoding="utf-8")
    code = main(["whisper", "--intent", "test", "--config", str(config)])
    assert code == 1
    err = capsys.readouterr().err
    assert "failed to parse config" in err.lower()


def test_cli_fence_missing_config(capsys):
    code = main(
        ["fence", "inspect", "--file", "src/foo.py", "--config", "missing.yaml"]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "config not found" in err.lower()


def test_cli_fence_bad_yaml(tmp_path, capsys):
    config = tmp_path / "rootact.yaml"
    config.write_text("not: valid: yaml:::", encoding="utf-8")
    code = main(["fence", "inspect", "--file", "src/foo.py", "--config", str(config)])
    assert code == 1
    err = capsys.readouterr().err
    assert "failed to parse config" in err.lower()


def test_cli_mcp_list_missing_config(capsys):
    code = main(["mcp", "list", "--config", "missing.yaml"])
    assert code == 1
    err = capsys.readouterr().err
    assert "config not found" in err.lower()


def test_cli_mcp_invoke_invalid_json(capsys):
    code = main(["mcp", "invoke", "--tool", "srv/tool", "--input", "not-json"])
    assert code == 1
    err = capsys.readouterr().err
    assert "invalid" in err.lower() or "json" in err.lower()


def test_cli_retrieval_search_no_query(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieval", "search"])
    assert exc_info.value.code == 2


# RACT 0.1.1 - Trust and tooling


def test_cli_doctor_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "manager.txt").write_text("manager prompt\n", encoding="utf-8")
    config_path.write_text(
        "project:\n  name: test\nmanager_provider: local\nproviders:\n  local:\n    adapter: local_http\n    url: http://127.0.0.1:11434/v1/chat/completions\n    model: local-model\n",
        encoding="utf-8",
    )
    code = main(["doctor", "--config", str(config_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Doctor:" in out


def test_cli_load_bearing_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["load-bearing", "list", "--config", str(config_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "No load-bearing annotations found" in out


def test_cli_load_bearing_finds_annotation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "core.py").write_text(
        "# load-bearing: legacy contract\ndef process():\n    pass\n",
        encoding="utf-8",
    )
    code = main(["load-bearing", "list", "--config", str(config_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "legacy contract" in out
    assert "process" in out or "1-3" in out


def test_cli_auction_missing_config(capsys):
    code = main(["auction", "list", "--config", "missing.yaml"])
    assert code == 1
    err = capsys.readouterr().err
    assert "config not found" in err.lower()


def test_cli_auction_json_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["auction", "list", "--json", "--config", str(config_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert '"project"' in out
    assert '"items"' in out


def test_cli_handshakes_missing_id(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["handshakes", "approve"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "milestone_id" in err.lower()


def test_cli_marketplace_top_level_dispatch(tmp_path, monkeypatch, capsys):
    """`rootact marketplace list` must dispatch to the marketplace subcommand."""
    monkeypatch.chdir(tmp_path)
    code = main(["marketplace", "list"])
    assert code == 0, capsys.readouterr().err


def test_cli_marketplace_skills_alias(tmp_path, monkeypatch, capsys):
    """`rootact skills marketplace list` continues to work."""
    monkeypatch.chdir(tmp_path)
    code = main(["skills", "marketplace", "list"])
    assert code == 0, capsys.readouterr().err


def test_cli_marketplace_install_positional_name(tmp_path, monkeypatch, capsys):
    """`rootact skills marketplace install <name>` installs the skill."""
    monkeypatch.chdir(tmp_path)
    catalog = tmp_path / "catalog.json"
    skill = tmp_path / "hello-world.json"
    skill.write_text(json.dumps({"name": "hello-world", "tools": []}), encoding="utf-8")
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "hello-world",
                        "description": "test",
                        "author": "test",
                        "url": str(skill),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code = main(
        ["skills", "marketplace", "install", "hello-world", "--catalog", str(catalog)]
    )
    assert code == 0, capsys.readouterr().err
    assert (tmp_path / "skills" / "hello-world.json").is_file()


def test_cli_marketplace_install_requires_name(tmp_path, monkeypatch, capsys):
    """`rootact skills marketplace install` without a name exits with a clean error."""
    monkeypatch.chdir(tmp_path)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"skills": []}), encoding="utf-8")
    code = main(["skills", "marketplace", "install", "--catalog", str(catalog)])
    assert code == 1
    assert "requires a skill name" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--version"],
        ["--about"],
        ["--welcome"],
        ["skills", "list"],
        ["marketplace", "list"],
        ["handshakes", "list"],
        ["mcp", "list", "--config", "missing.yaml"],
        ["coverage", "delta"],
        ["auction", "list", "--config", "missing.yaml"],
        ["fence", "inspect", "--file", "src/foo.py", "--config", "missing.yaml"],
    ],
)
def test_cli_documented_verbs_dispatch_cleanly(argv, capsys):
    """Each documented verb must reach its handler without an argparse traceback."""
    try:
        main(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "unrecognized arguments" not in combined
    assert "argument error" not in combined
    assert "traceback" not in combined


def test_cli_diff_apply_dry_run(tmp_path, monkeypatch, capsys):
    """`rootact diff apply --patch` previews changes in dry-run mode."""
    monkeypatch.chdir(tmp_path)
    rootact_yaml = tmp_path / "rootact.yaml"
    rootact_yaml.write_text("project:\n  name: test\n", encoding="utf-8")
    target = tmp_path / "src" / "foo.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line one\nline two\n", encoding="utf-8")
    patch = tmp_path / "change.diff"
    patch.write_text(
        "--- src/foo.txt\n+++ src/foo.txt\n@@ -1,2 +1,2 @@\n line one\n-line two\n+line two changed\n",
        encoding="utf-8",
    )
    code = main(["diff", "apply", "--patch", str(patch), "--dry-run"])
    assert code == 0, capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "line one\nline two\n"


def test_cli_report_last_with_loop_report(tmp_path, monkeypatch, capsys):
    """`rootact report --last` renders a saved loop report."""
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"final_decision": "done", "summary": "ok"}), encoding="utf-8"
    )
    code = main(["report", "--last"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "RACT Loop Report" in out
    assert "done" in out


def test_cli_report_session(tmp_path, monkeypatch, capsys):
    """`rootact report --session` renders a saved session."""
    monkeypatch.chdir(tmp_path)
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "demo.json").write_text(
        json.dumps(
            {"intent": "demo intent", "plan": {"assumption": "ok", "confidence": 0.9}}
        ),
        encoding="utf-8",
    )
    code = main(["report", "--session", "demo"])
    assert code == 0, capsys.readouterr().err
    assert "demo intent" in capsys.readouterr().out


def test_cli_mcp_list_no_servers(tmp_path, monkeypatch, capsys):
    """`rootact mcp list` exits cleanly when no MCP servers are configured."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["mcp", "list", "--config", str(config)])
    assert code == 0, capsys.readouterr().err
    combined = (capsys.readouterr().out + capsys.readouterr().err).lower()
    assert "no mcp tools" in combined or "configured" in combined


def test_cli_mcp_invoke_requires_tool(tmp_path, monkeypatch, capsys):
    """`rootact mcp invoke` without --tool returns a clear error."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["mcp", "invoke", "--config", str(config)])
    assert code == 1
    assert "requires --tool" in capsys.readouterr().err


# RACT 0.1.1 - Trust and tooling


def test_cli_explain_plan(tmp_path, monkeypatch, capsys):
    """`rootact explain --plan` narrates a saved plan without calling a provider."""
    monkeypatch.chdir(tmp_path)
    from rootact.manager import Plan, Step
    from rootact.plan_serializers import save_plan

    plan = Plan(
        assumption="add greeting",
        confidence=0.9,
        steps=[
            Step(
                action="create hello.py",
                provider_hint="local",
                expected_artifact="hello.py",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    save_plan(plan, plan_path)
    code = main(["explain", "--plan", str(plan_path)])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "add greeting" in out
    assert "create hello.py" in out
    assert "hello.py" in out


def test_cli_explain_requires_intent_or_plan(capsys):
    """`rootact explain` without --intent or --plan prints help and exits."""
    code = main(["explain"])
    assert code == 1
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "intent" in combined or "plan" in combined


# RACT 0.1.1 - Trust and tooling


def _write_healthy_config(path: Path) -> None:
    """Write a minimal RACT config that passes `doctor` without network calls."""
    path.write_text(
        "project:\n"
        "  name: audit-test\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    base_url: http://127.0.0.1:8011/v1\n"
        "    model: local\n",
        encoding="utf-8",
    )


def test_cli_audit_passes_on_healthy_project(tmp_path, monkeypatch, capsys):
    """`rootact audit` passes when doctor and auction are clean."""
    monkeypatch.chdir(tmp_path)
    _write_healthy_config(tmp_path / "rootact.yaml")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    code = main(["audit", "--config", str(tmp_path / "rootact.yaml")])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    out = captured.out
    assert "RACT Audit" in out
    assert "PASS" in out


def test_cli_audit_json_output(tmp_path, monkeypatch, capsys):
    """`rootact audit --json` emits a JSON report."""
    monkeypatch.chdir(tmp_path)
    _write_healthy_config(tmp_path / "rootact.yaml")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    code = main(["audit", "--config", str(tmp_path / "rootact.yaml"), "--json"])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    out = captured.out
    data = json.loads(out)
    assert data["passed"] == data["total"]
    assert any(f["tool"] == "doctor" for f in data["findings"])


# RACT 0.1.1 - Trust and tooling


def test_cli_handshakes_list_with_items(tmp_path, monkeypatch, capsys):
    """`rootact handshakes list` renders a table when items exist."""
    monkeypatch.chdir(tmp_path)
    registry = __import__(
        "rootact.handshake_registry", fromlist=["HandshakeRegistry"]
    ).HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "push")
    code = main(["handshakes", "list"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "Operator Handshakes" in out
    assert "m1" in out


def test_cli_handshakes_missing_milestone_error(tmp_path, monkeypatch, capsys):
    """`rootact handshakes approve <missing>` prints a clear error."""
    monkeypatch.chdir(tmp_path)
    code = main(["handshakes", "approve", "missing"])
    assert code == 1
    assert "missing" in capsys.readouterr().err.lower()


def test_cli_explain_intent_dry_run(capsys):
    """`rootact explain --intent` narrates the dry-run plan."""
    plan = Plan(
        assumption="add greeting",
        confidence=0.9,
        steps=[
            Step(
                action="create hello.py",
                provider_hint="local",
                expected_artifact="hello.py",
            )
        ],
    )
    with patch(
        "rootact.cli.run_rootact",
        return_value=Rooted(value=plan, assumption="ok", confidence=0.9),
    ):
        code = main(["explain", "--intent", "create hello.py"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "RACT Plan Explanation" in out
    assert "add greeting" in out
    assert "create hello.py" in out
    assert "hello.py" in out


def test_cli_explain_intent_planning_failure(capsys):
    """`rootact explain --intent` surfaces a planning failure."""
    with patch(
        "rootact.cli.run_rootact",
        return_value=Rooted(
            value=None,
            assumption="fail",
            confidence=0.0,
            error="provider unreachable",
        ),
    ):
        code = main(["explain", "--intent", "create hello.py"])
    assert code == 1
    assert "planning failed" in capsys.readouterr().err.lower()


def test_cli_retrieval_search_with_results(tmp_path, monkeypatch, capsys):
    """`rootact retrieval search` falls back to keyword search and renders results."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "greeting.py").write_text(
        "def hello():\n    return 'greeting world'\n", encoding="utf-8"
    )
    code = main(["retrieval", "search", "greeting", "--config", str(config)])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "Retrieval results" in out
    assert "greeting.py" in out


def test_cli_report_last_json_output(tmp_path, monkeypatch, capsys):
    """`rootact report --last --format json` emits JSON."""
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"final_decision": "done", "summary": "ok"}), encoding="utf-8"
    )
    code = main(["report", "--last", "--format", "json"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["final_decision"] == "done"


def test_cli_report_last_writes_output_file(tmp_path, monkeypatch, capsys):
    """`rootact report --last --output` writes the report to disk."""
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"final_decision": "done", "summary": "ok"}), encoding="utf-8"
    )
    output = tmp_path / "report.txt"
    code = main(["report", "--last", "--output", str(output)])
    assert code == 0, capsys.readouterr().err
    assert output.is_file()
    assert "done" in output.read_text(encoding="utf-8")


def test_cli_mcp_bad_yaml(tmp_path, monkeypatch, capsys):
    """`rootact mcp list` surfaces a YAML parse error."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("not: valid: yaml:::", encoding="utf-8")
    code = main(["mcp", "list", "--config", str(config)])
    assert code == 1
    assert "failed to parse config" in capsys.readouterr().err.lower()


def test_cli_mcp_invoke_tool_error(tmp_path, monkeypatch, capsys):
    """`rootact mcp invoke` surfaces a tool call error."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    registry = __import__(
        "rootact.mcp_adapter", fromlist=["McpToolRegistry"]
    ).McpToolRegistry()
    with patch.object(registry, "call_tool", return_value=Rooted(error="boom")):
        with patch(
            "rootact.mcp_adapter.McpToolRegistry.from_config", return_value=registry
        ):
            code = main(
                ["mcp", "invoke", "--tool", "srv/tool", "--config", str(config)]
            )
    assert code == 1
    assert "boom" in capsys.readouterr().err.lower()


def test_cli_mcp_invoke_non_text_content(tmp_path, monkeypatch, capsys):
    """`rootact mcp invoke` renders non-text content as JSON."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    ToolResult = __import__(
        "rootact.mcp_adapter", fromlist=["McpToolResult"]
    ).McpToolResult
    registry = __import__(
        "rootact.mcp_adapter", fromlist=["McpToolRegistry"]
    ).McpToolRegistry()
    result = ToolResult(
        tool="srv/tool",
        content=[{"type": "image", "url": "http://example.com/x.png"}],
        is_error=False,
    )
    with patch.object(registry, "call_tool", return_value=Rooted(value=result)):
        with patch(
            "rootact.mcp_adapter.McpToolRegistry.from_config", return_value=registry
        ):
            code = main(
                ["mcp", "invoke", "--tool", "srv/tool", "--config", str(config)]
            )
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "x.png" in out


def test_cli_mcp_invoke_tool_reports_error(tmp_path, monkeypatch, capsys):
    """`rootact mcp invoke` surfaces a tool-level error flag."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    ToolResult = __import__(
        "rootact.mcp_adapter", fromlist=["McpToolResult"]
    ).McpToolResult
    registry = __import__(
        "rootact.mcp_adapter", fromlist=["McpToolRegistry"]
    ).McpToolRegistry()
    result = ToolResult(tool="srv/tool", content=[{"text": "bad"}], is_error=True)
    with patch.object(registry, "call_tool", return_value=Rooted(value=result)):
        with patch(
            "rootact.mcp_adapter.McpToolRegistry.from_config", return_value=registry
        ):
            code = main(
                ["mcp", "invoke", "--tool", "srv/tool", "--config", str(config)]
            )
    assert code == 0  # CLI returns 0; stderr indicates tool error
    err = capsys.readouterr().err
    assert "tool reported an error" in err.lower()


def test_cli_report_no_args_prints_help(capsys):
    """`rootact report` with no flags prints help and exits 1."""
    code = main(["report"])
    assert code == 1
    assert "usage:" in capsys.readouterr().out.lower()


def test_cli_diff_no_action_prints_help(capsys):
    """`rootact diff` with no action prints help and exits 1."""
    code = main(["diff"])
    assert code == 1
    assert "usage:" in capsys.readouterr().out.lower()


def test_cli_diff_apply_requires_patch(tmp_path, monkeypatch, capsys):
    """`rootact diff apply` without --patch returns a clear error."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["diff", "apply", "--config", str(config)])
    assert code == 1
    assert "--patch is required" in capsys.readouterr().err.lower()


def test_cli_init_scaffolds_project(tmp_path, monkeypatch, capsys):
    """`rootact init --template --provider` writes a project scaffold."""
    monkeypatch.chdir(tmp_path)
    code = main(["init", "--template", "python-package", "--provider", "local"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "initialized" in out.lower()
    assert (tmp_path / "rootact.yaml").is_file()


def test_cli_novelty_scan_empty_project(tmp_path, monkeypatch, capsys):
    """`rootact novelty scan` exits cleanly on a project with no Python files."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["novelty", "scan", "--config", str(config)])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "novelty scan" in out.lower()


def test_cli_fence_bad_lines_format(tmp_path, monkeypatch, capsys):
    """`rootact fence inspect --lines` rejects malformed ranges."""
    monkeypatch.chdir(tmp_path)
    _write_healthy_config(tmp_path / "rootact.yaml")
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# placeholder\n", encoding="utf-8")
    code = main(
        [
            "fence",
            "inspect",
            "--file",
            str(target),
            "--lines",
            "not-a-range",
            "--config",
            str(tmp_path / "rootact.yaml"),
        ]
    )
    assert code == 1
    assert "start-end" in capsys.readouterr().err.lower()


def _write_mutation_badge(path: Path, score: float) -> None:
    """Write a mutation badge JSON with the given score percent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"message": f"{score:.2f}%"}), encoding="utf-8")


def test_cli_audit_deep_runs_consolidate_and_mutation_drift(
    tmp_path, monkeypatch, capsys
):
    """`rootact audit --deep` includes consolidate and mutation-drift findings."""
    monkeypatch.chdir(tmp_path)
    _write_healthy_config(tmp_path / "rootact.yaml")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    _write_mutation_badge(tmp_path / "docs" / "mutation-badge.json", 90.0)
    code = main(["audit", "--config", str(tmp_path / "rootact.yaml"), "--deep"])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    out_lower = captured.out.lower()
    assert "consolidate" in out_lower
    assert "mutation" in out_lower


def test_cli_audit_deep_flags_merge_proposals(tmp_path, monkeypatch, capsys):
    """`rootact audit --deep` fails when consolidate finds merge proposals."""
    monkeypatch.chdir(tmp_path)
    _write_healthy_config(tmp_path / "rootact.yaml")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    _write_mutation_badge(tmp_path / "docs" / "mutation-badge.json", 90.0)
    ConsolidationResult = __import__(
        "rootact.consolidate", fromlist=["ConsolidationResult"]
    ).ConsolidationResult
    MergeProposal = __import__(
        "rootact.consolidate", fromlist=["MergeProposal"]
    ).MergeProposal
    fake_result = ConsolidationResult(
        proposals=[
            MergeProposal(
                target="src/a.py",
                sources=("src/b.py",),
                diff="--- a.py\n+++ a.py",
                reason="duplicate",
            )
        ]
    )
    with patch("rootact.cli.ConsolidationScanner.scan", return_value=fake_result):
        code = main(["audit", "--config", str(tmp_path / "rootact.yaml"), "--deep"])
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "merge proposal" in captured.out.lower()


def test_cli_audit_deep_mutation_drift_below_floor(tmp_path, monkeypatch, capsys):
    """`rootact audit --deep` fails when mutation score is below the floor."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text(
        "project:\n"
        "  name: audit-test\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    base_url: http://127.0.0.1:8011/v1\n"
        "    model: local\n"
        "mutation_gate:\n"
        "  min_score: 50.0\n",
        encoding="utf-8",
    )
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "manager.txt").write_text("manager", encoding="utf-8")
    _write_mutation_badge(tmp_path / "docs" / "mutation-badge.json", 47.81)
    code = main(["audit", "--config", str(config), "--deep"])
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "below" in captured.out.lower()


def test_cli_coverage_status_no_baseline(tmp_path, monkeypatch, capsys):
    """`rootact coverage status` reports when no baseline exists."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    code = main(["coverage", "status", "--config", str(config)])
    assert code == 1
    captured = capsys.readouterr()
    assert "no coverage baseline" in (captured.out + captured.err).lower()
