"""Tests for the RACT harness."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ract.harness import (
    Harness,
    _build_retrieval_adapter,
    _context_relevance,
    _curate_context,
    _load_config,
)
from ract.rooted import Rooted
from ract.skills_registry import SkillRegistry
from ract.coverage_delta import CoverageSnapshot


@pytest.fixture
def tmp_project(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "manager.txt").write_text("You are the manager.", encoding="utf-8")
    return tmp_path


def test_harness_runs_intent_end_to_end(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }

    config_path = tmp_project / "ract.yaml"
    config_path.write_text(
        "\n".join(f"{k}: {v}" for k, v in config.items()) if False else "",
        encoding="utf-8",
    )
    # LR:: Write a real YAML config so from_config_path can load it.
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    # Mock the manager provider to return a plan.
    fake_plan_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "test assumption", "confidence": 0.95, '
                        '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                    )
                }
            }
        ]
    }
    fake_step_response = {"choices": [{"message": {"content": "def test_x(): pass"}}]}

    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    report_rooted = harness.run("write tests for the harness")
    assert report_rooted.is_ok()
    report = report_rooted.unwrap()
    assert report.intent == "write tests for the harness"
    assert len(report.step_results) == 1
    assert "def test_x(): pass" in report.step_results[0].content


def test_harness_includes_curated_context(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 200,
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    # Create a source file the intent explicitly names.
    src_dir = tmp_project / "src" / "ract"
    src_dir.mkdir(parents=True)
    (src_dir / "widget.py").write_text("def widget(): pass\n", encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "test assumption", "confidence": 0.95, '
                        '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_widget.py"}]}'
                    )
                }
            }
        ]
    }
    fake_step_response = {
        "choices": [{"message": {"content": "def test_widget():\n    return 42\n"}}]
    }
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    report_rooted = harness.run("write tests for the widget module")
    assert report_rooted.is_ok()

    # The manager should have received an augmented intent containing the
    # curated context block.
    plan_call = harness.manager.provider.complete.call_args_list[0]
    messages = plan_call.kwargs.get(
        "messages", plan_call.args[0] if plan_call.args else []
    )
    user_content = messages[-1]["content"]
    assert "widget.py" in user_content
    assert "def widget(): pass" in user_content


def test_harness_rejects_plan_missing_assumption(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    bad_plan = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "", "confidence": 0.95, '
                        '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                    )
                }
            }
        ]
    }
    harness.manager.provider.complete = MagicMock(
        return_value=Rooted(value=bad_plan, assumption="ok", confidence=1.0)
    )

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    assert "Plan validation failed" in (report_rooted.error or "")


def test_harness_rejects_plan_with_empty_steps(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    bad_plan = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "valid", "confidence": 0.95, "steps": []}'
                    )
                }
            }
        ]
    }
    harness.manager.provider.complete = MagicMock(
        return_value=Rooted(value=bad_plan, assumption="ok", confidence=1.0)
    )

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    # The planner already guards empty step lists; the harness surfaces it as a
    # planning failure before plan_validator is reached.
    assert "Plan contains no steps" in (report_rooted.error or "")


def test_harness_rejects_plan_with_dependency_cycle(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    cyclic_plan = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "valid", "confidence": 0.95, "steps": ['
                        '{"action": "use B", "provider_hint": "chat", "expected_artifact": "A"},'
                        '{"action": "use A", "provider_hint": "chat", "expected_artifact": "B"}'
                        "]}"
                    )
                }
            }
        ]
    }
    harness.manager.provider.complete = MagicMock(
        return_value=Rooted(value=cyclic_plan, assumption="ok", confidence=1.0)
    )

    report_rooted = harness.run("write code")
    assert not report_rooted.is_ok()
    assert "dependency cycle" in (report_rooted.error or "").lower()


def test_harness_uses_configured_skill(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "skill": "test_skill",
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    SkillRegistry(tmp_project / ".ract").register(
        "test_skill", "Focus on $intent for project $project_name."
    )

    captured_intents = []

    def capture_complete(messages, **kwargs):
        captured_intents.append(messages[-1]["content"])
        return Rooted(
            value={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"assumption": "test assumption", "confidence": 0.95, '
                                '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                            )
                        }
                    }
                ]
            },
            assumption="ok",
            confidence=1.0,
        )

    harness.manager.provider.complete = MagicMock(side_effect=capture_complete)
    harness.executor.router._adapters["chat"] = harness.manager.provider

    report_rooted = harness.run("write tests")
    assert report_rooted.is_ok()
    # The planning call should include the rendered skill prompt.
    assert any("Focus on write tests" in content for content in captured_intents)


def test_harness_git_mode_commits_artifacts(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "git_mode": True,
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "test", "confidence": 0.95, '
                        '"steps": [{"action": "write file", "provider_hint": "chat", "expected_artifact": "src/foo.py"}]}'
                    )
                }
            }
        ]
    }
    fake_step_response = {"choices": [{"message": {"content": "x"}}]}
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    committed = []

    def fake_commit(paths, message):
        committed.extend(paths)

        class _R:
            returncode = 0
            stdout = ""

        return _R()

    harness.git_mode.commit_files = fake_commit

    report_rooted = harness.run("write foo", mode="git")
    assert report_rooted.is_ok()
    assert any(Path(p).name == "foo.py" for p in committed)


from ract.retrieval_adapter import KeywordRetrievalAdapter, WebSearchAdapter


def test_build_retrieval_adapter_keyword(tmp_project):
    config = {"retrieval": {"adapter": "keyword", "top_k": 3}}
    adapter = _build_retrieval_adapter(config, tmp_project)
    assert isinstance(adapter, KeywordRetrievalAdapter)


def test_build_retrieval_adapter_web(tmp_project):
    config = {"retrieval": {"adapter": "web", "api_key": "secret"}}
    adapter = _build_retrieval_adapter(config, tmp_project)
    assert isinstance(adapter, WebSearchAdapter)


def test_build_retrieval_adapter_missing_section(tmp_project):
    adapter = _build_retrieval_adapter({}, tmp_project)
    assert adapter is None


def test_harness_includes_retrieval_block(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "retrieval": {"adapter": "keyword", "top_k": 5},
    }
    config_path = tmp_project / "ract.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    src_dir = tmp_project / "src" / "ract"
    src_dir.mkdir(parents=True)
    (src_dir / "retrieval_target.py").write_text(
        "def find_me(): pass\n", encoding="utf-8"
    )

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "test assumption", "confidence": 0.95, '
                        '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                    )
                }
            }
        ]
    }
    fake_step_response = {
        "choices": [{"message": {"content": "def test_x():\n    return 42\n"}}]
    }
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    report_rooted = harness.run("find the retrieval_target module")
    assert report_rooted.is_ok()

    plan_call = harness.manager.provider.complete.call_args_list[0]
    messages = plan_call.kwargs.get(
        "messages", plan_call.args[0] if plan_call.args else []
    )
    user_content = messages[-1]["content"]
    assert "Retrieved snippets:" in user_content
    assert "retrieval_target.py" in user_content


def test_harness_from_config_uses_bundled_prompt_when_project_prompt_missing(tmp_path):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        "project:\n  name: test\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:8011/v1\n"
        "    model: test-model\n",
        encoding="utf-8",
    )
    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()
    assert "RACT Core Manager" in harness.manager.system_prompt


def test_load_config_missing_file(tmp_path):
    missing = tmp_path / "missing.yaml"
    result = _load_config(missing)
    assert not result.is_ok()
    assert "not found" in result.error


def test_load_config_parse_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("{not valid yaml: [", encoding="utf-8")
    result = _load_config(bad)
    assert not result.is_ok()
    assert "Failed to parse config" in result.error


def test_build_retrieval_adapter_unknown_type(tmp_project):
    config = {"retrieval": {"adapter": "unknown"}}
    assert _build_retrieval_adapter(config, tmp_project) is None


def test_context_relevance_tests_path():
    tests_path = Path("tests/test_foo.py")
    score = _context_relevance(tests_path, "test the widget")
    assert score > 0.0


def test_curate_context_skips_unsupported_suffix(tmp_path):
    (tmp_path / "readme.bin").write_bytes(b"data")
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_skips_ignored_dirs(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text("[core]\n", encoding="utf-8")
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_skips_oversized_file(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("x" * 200_000, encoding="utf-8")
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_handles_unreadable_file(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\xff\xfe")
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_empty_project(tmp_path):
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_budget_too_small_for_overhead(tmp_path):
    (tmp_path / "tiny.py").write_text("x = 1\n", encoding="utf-8")
    long_intent = " ".join(["intent"] * 200)
    assert _curate_context(tmp_path, long_intent, 10) == ""


def test_harness_from_config_load_failure(tmp_path):
    missing = tmp_path / "ract.yaml"
    result = Harness.from_config_path(missing)
    assert not result.is_ok()
    assert "Configuration file not found" in result.error


def test_harness_from_config_bad_manager_provider(tmp_path):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        "manager_provider: missing\nproviders: {}\n", encoding="utf-8"
    )
    result = Harness.from_config_path(config_path)
    assert not result.is_ok()
    assert "missing" in result.error


def test_harness_from_config_manager_prompt_read_failure(tmp_path, monkeypatch):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:8011/v1\n"
        "    model: test-model\n",
        encoding="utf-8",
    )

    def failing_from_path(*_args, **_kwargs):
        return Rooted(
            value=None,
            assumption="prompt readable",
            confidence=0.0,
            provenance=["test"],
            error="prompt read failed",
        )

    monkeypatch.setattr("ract.manager.Manager.from_path", failing_from_path)
    result = Harness.from_config_path(config_path)
    assert not result.is_ok()
    assert "prompt read failed" in result.error


def test_curate_context_skips_ignored_dirs_with_allowed_suffix(tmp_path):
    # Files with allowed suffixes inside ignored directories must be skipped.
    ignored = tmp_path / ".venv"
    ignored.mkdir(parents=True)
    (ignored / "script.py").write_text("x = 1\n", encoding="utf-8")
    assert _curate_context(tmp_path, "intent", 500) == ""


def test_curate_context_returns_empty_when_no_files_fit(tmp_path):
    # Budget is large enough for the overhead but too small for the only file.
    (tmp_path / "huge.py").write_text(" ".join(["word"] * 50), encoding="utf-8")
    assert _curate_context(tmp_path, "x", 4) == ""


def test_harness_from_config_empty_mcp_registry_keeps_tools_desc_empty(tmp_project):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    import yaml

    config_path = tmp_project / "ract.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()
    assert harness.manager.tools_description == ""
    assert "No MCP tools are configured" in harness.manager._full_system_prompt()


def test_harness_from_config_populates_tools_desc_with_mcp_tools(
    tmp_project, monkeypatch
):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    import yaml

    config_path = tmp_project / "ract.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    fake_registry = MagicMock()
    fake_registry.list_all_tools.return_value = Rooted(
        value=[{"name": "fs/read", "description": "read a file"}],
        assumption="tools listed",
        confidence=1.0,
        provenance=["test"],
    )

    def fake_from_config(_config):
        return fake_registry

    monkeypatch.setattr("ract.harness.McpToolRegistry.from_config", fake_from_config)

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()
    assert "fs/read" in harness.manager.tools_description
    assert "Available MCP tools" in harness.manager._full_system_prompt()


def _build_harness(tmp_project, config_extra=None):
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }
    if config_extra:
        config.update(config_extra)
    import yaml

    config_path = tmp_project / "ract.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    return harness_rooted.unwrap()


def _fake_plan_and_step(harness):
    fake_plan_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"assumption": "test assumption", "confidence": 0.95, '
                        '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                    )
                }
            }
        ]
    }
    fake_step_response = {"choices": [{"message": {"content": "def test_x(): pass"}}]}
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )


def test_coverage_gate_records_delta_in_report(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project, {"coverage_gate": {"enabled": True, "hard_fail": False}}
    )
    _fake_plan_and_step(harness)

    class FakeDelta:
        verdict = "stagnant"
        detail = "coverage stagnant"
        floor_breached = False
        percent_delta = 0.0
        per_file_breaches: list[str] = []
        before = CoverageSnapshot(
            percent_covered=50.0, covered_lines=50, missing_lines=50, total_lines=100
        )
        after = CoverageSnapshot(
            percent_covered=50.0, covered_lines=50, missing_lines=50, total_lines=100
        )

    monkeypatch.setattr(
        "ract.harness.coverage_gate",
        lambda *_args, **_kwargs: Rooted(
            value=FakeDelta(),
            assumption="coverage gate ok",
            confidence=1.0,
            provenance=["fake_gate"],
        ),
    )

    report_rooted = harness.run("write tests")
    assert report_rooted.is_ok(), report_rooted.error
    report = report_rooted.unwrap()
    assert "coverage_delta" in report.artifacts
    assert report.artifacts["coverage_delta"]["verdict"] == "stagnant"


def test_coverage_gate_hard_fail_returns_error(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project, {"coverage_gate": {"enabled": True, "hard_fail": True}}
    )
    _fake_plan_and_step(harness)

    class FakeDelta:
        verdict = "regress"
        detail = "coverage regressed"
        floor_breached = False
        percent_delta = -5.0
        per_file_breaches: list[str] = []
        before = CoverageSnapshot(
            percent_covered=55.0, covered_lines=55, missing_lines=45, total_lines=100
        )
        after = CoverageSnapshot(
            percent_covered=50.0, covered_lines=50, missing_lines=50, total_lines=100
        )

    monkeypatch.setattr(
        "ract.harness.coverage_gate",
        lambda *_args, **_kwargs: Rooted(
            value=FakeDelta(),
            assumption="coverage gate ok",
            confidence=1.0,
            provenance=["fake_gate"],
        ),
    )

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    assert "Coverage gate" in (report_rooted.error or "")


def test_mutation_gate_records_score_in_report(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project, {"mutation_gate": {"enabled": True, "hard_fail": False}}
    )
    _fake_plan_and_step(harness)

    class FakeMutationReport:
        mutation_score = 42.0
        killed = 21
        survived = 29
        timeout = 0
        error = None
        total = 50

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=FakeMutationReport(),
            assumption="mutation gate ok",
            confidence=1.0,
            provenance=["fake_runner"],
        ),
    )

    report_rooted = harness.run("write tests")
    assert report_rooted.is_ok(), report_rooted.error
    report = report_rooted.unwrap()
    assert "mutation_score" in report.artifacts
    assert report.artifacts["mutation_score"]["score"] == 42.0


def test_mutation_gate_hard_fail_when_below_floor(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project,
        {
            "mutation_gate": {
                "enabled": True,
                "hard_fail": True,
                "min_score": 50.0,
            }
        },
    )
    _fake_plan_and_step(harness)

    class FakeMutationReport:
        mutation_score = 42.0
        killed = 21
        survived = 29
        timeout = 0
        error = None
        total = 50

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=FakeMutationReport(),
            assumption="mutation gate ok",
            confidence=1.0,
            provenance=["fake_runner"],
        ),
    )

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    assert "Mutation gate" in (report_rooted.error or "")


def test_per_file_mutation_gate_records_scores(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project,
        {
            "mutation_gate": {
                "enabled": True,
                "hard_fail": True,
                "per_file": {"src/ract/widget.py": 30.0},
            }
        },
    )
    _fake_plan_and_step(harness)
    src_dir = tmp_project / "src" / "ract"
    src_dir.mkdir(parents=True)
    (src_dir / "widget.py").write_text("def widget(): pass\n", encoding="utf-8")

    class FakeMutationReport:
        mutation_score = 42.0
        killed = 21
        survived = 29
        timeout = 0
        error = 0
        total = 50

    calls: list[tuple[str, str | None]] = []

    def fake_run(
        project_dir,
        *,
        script_path=None,
        timeout=None,
        wsl_distro=None,
        targets=None,
        test_runner=None,
    ):
        calls.append((targets[0] if targets else None, test_runner))
        return Rooted(
            value=FakeMutationReport(),
            assumption="mutation gate ok",
            confidence=1.0,
            provenance=["fake_runner"],
        )

    monkeypatch.setattr("ract.harness.run_mutation_tests", fake_run)

    report_rooted = harness.run("write tests")
    assert report_rooted.is_ok(), report_rooted.error
    report = report_rooted.unwrap()
    assert "mutation_score_per_file" in report.artifacts
    per_file = report.artifacts["mutation_score_per_file"]
    assert "src/ract/widget.py" in per_file
    assert per_file["src/ract/widget.py"]["score"] == 42.0
    assert per_file["src/ract/widget.py"]["min_score"] == 30.0
    assert calls == [
        ("src/ract/widget.py", "python3 -m pytest tests/test_widget.py -q")
    ]


def test_per_file_mutation_gate_hard_fail_when_below_floor(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project,
        {
            "mutation_gate": {
                "enabled": True,
                "hard_fail": True,
                "per_file": {"src/ract/widget.py": 50.0},
            }
        },
    )
    _fake_plan_and_step(harness)
    src_dir = tmp_project / "src" / "ract"
    src_dir.mkdir(parents=True)
    (src_dir / "widget.py").write_text("def widget(): pass\n", encoding="utf-8")

    class FakeMutationReport:
        mutation_score = 42.0
        killed = 21
        survived = 29
        timeout = 0
        error = 0
        total = 50

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=FakeMutationReport(),
            assumption="mutation gate ok",
            confidence=1.0,
            provenance=["fake_runner"],
        ),
    )

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    assert "src/ract/widget.py" in (report_rooted.error or "")
    assert "42.00%" in (report_rooted.error or "")


def test_per_file_mutation_gate_missing_target_hard_fails(tmp_project, monkeypatch):
    harness = _build_harness(
        tmp_project,
        {
            "mutation_gate": {
                "enabled": True,
                "hard_fail": True,
                "per_file": {"src/ract/missing.py": 30.0},
            }
        },
    )
    _fake_plan_and_step(harness)

    report_rooted = harness.run("write tests")
    assert not report_rooted.is_ok()
    assert "src/ract/missing.py" in (report_rooted.error or "")


# RACT 0.1.1 - Trust and tooling
