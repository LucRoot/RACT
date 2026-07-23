"""Tests for the RACT manager and plan parsing."""

from __future__ import annotations


from unittest.mock import MagicMock, patch

from ract.manager import Manager, Plan, _extract_json
from ract.rooted import Rooted
from ract.temperature_router import TemperatureRouter


def test_extract_json_plain_object():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_trailing_prose():
    text = 'Here is the plan:\n{"steps": [], "confidence": 0.9}\nHope this helps!'
    parsed = _extract_json(text)
    assert parsed == {"steps": [], "confidence": 0.9}


def test_extract_json_with_leading_prose():
    text = 'Sure thing! {"steps": [{"action": "x"}], "assumption": "ok"} trailing'
    parsed = _extract_json(text)
    assert parsed is not None
    assert parsed["assumption"] == "ok"


def test_extract_json_no_object():
    assert _extract_json("no json here") is None


def test_extract_json_malformed_braces():
    text = "Some text { without balance } and { more"
    assert _extract_json(text) is None


def test_plan_returns_rooted_plan():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "write tests", "provider_hint": "chat", "expected_artifact": "tests/test_x.py"}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("write tests")
    assert plan_rooted.is_ok()
    plan = plan_rooted.unwrap()
    assert isinstance(plan, Plan)
    assert plan.confidence == 0.95
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "write tests"


def test_plan_uses_temperature_router_for_intent():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.9, "steps": []}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    router = TemperatureRouter(plan_temp=0.35, brainstorm_temp=0.75)
    manager = Manager(provider, "You are the manager.", temperature_router=router)
    plan_rooted = manager.plan("brainstorm new features")
    assert plan_rooted.is_ok()
    assert provider.complete.call_args.kwargs["temperature"] == 0.75


def test_plan_fails_when_provider_fails():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value=None,
        assumption="provider healthy",
        confidence=0.0,
        provenance=["provider.complete"],
        error="timeout",
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("write tests")
    assert not plan_rooted.is_ok()
    assert "timeout" in (plan_rooted.error or "")


def test_plan_fails_when_json_missing():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={"choices": [{"message": {"content": "I will not emit JSON."}}]},
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("write tests")
    assert not plan_rooted.is_ok()
    assert "JSON" in (plan_rooted.error or "")


def test_manager_from_path_returns_rooted_error_for_missing_file(tmp_path):
    missing = tmp_path / "missing.txt"
    provider = MagicMock()
    result = Manager.from_path(provider, missing)
    assert not result.is_ok()
    assert "not found" in (result.error or "").lower()


def test_plan_parses_tool_call_step():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "read config", "provider_hint": "mcp", '
                            '"expected_artifact": "", "tool_call": '
                            '{"name": "fs/read", "arguments": {"path": "config.yaml"}}}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(
        provider,
        "You are the manager.",
        tools_description="Tools: fs/read",
    )
    plan_rooted = manager.plan("inspect project")
    assert plan_rooted.is_ok()
    plan = plan_rooted.unwrap()
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool_call == {"name": "fs/read", "arguments": {"path": "config.yaml"}}


def test_manager_includes_tools_description_in_system_prompt():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": '{"assumption": "ok", "confidence": 0.95, "steps": []}'
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(
        provider, "You are the manager.", tools_description="Tools: fs/read"
    )
    manager.plan("do something")
    call_args = provider.complete.call_args[0][0]
    system_message = call_args[0]
    assert "You are the manager." in system_message["content"]
    assert "Tools: fs/read" in system_message["content"]


def test_manager_system_prompt_notes_when_no_tools_configured():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": '{"assumption": "ok", "confidence": 0.95, "steps": []}'
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    manager.plan("do something")
    call_args = provider.complete.call_args[0][0]
    system_message = call_args[0]
    assert "No MCP tools are configured" in system_message["content"]


def test_manager_from_path_returns_rooted_error_for_os_error(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("prompt", encoding="utf-8")
    provider = MagicMock()

    with patch("pathlib.Path.read_text", side_effect=OSError("denied")):
        result = Manager.from_path(provider, prompt)

    assert not result.is_ok()
    assert "denied" in (result.error or "")


def test_plan_rejects_tool_call_when_no_tools_configured():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "read", "provider_hint": "mcp", '
                            '"expected_artifact": "", "tool_call": {"name": "x"}}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("do something")
    assert not plan_rooted.is_ok()
    assert "tool_call" in (plan_rooted.error or "")


def test_plan_ignores_non_dict_tool_call():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "write code", "provider_hint": "chat", '
                            '"expected_artifact": "src/foo.py", "tool_call": "bad"}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("do something")
    assert plan_rooted.is_ok()
    assert plan_rooted.unwrap().steps[0].tool_call is None


def test_plan_fills_default_expected_artifact_for_test_action():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "run tests", "provider_hint": "chat"}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("do something")
    assert plan_rooted.is_ok()
    assert plan_rooted.unwrap().steps[0].expected_artifact == "test_results.txt"


def test_plan_fills_default_expected_artifact_for_non_test_action():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.95, '
                            '"steps": [{"action": "write code", "provider_hint": "chat"}]}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("do something")
    assert plan_rooted.is_ok()
    assert plan_rooted.unwrap().steps[0].expected_artifact == "output.txt"


def test_plan_rejects_low_confidence():
    provider = MagicMock()
    provider.complete.return_value = Rooted(
        value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"assumption": "ok", "confidence": 0.05, "steps": []}'
                        )
                    }
                }
            ]
        },
        assumption="ok",
        confidence=1.0,
    )
    manager = Manager(provider, "You are the manager.")
    plan_rooted = manager.plan("do something")
    assert not plan_rooted.is_ok()
    assert "confidence" in (plan_rooted.error or "").lower()


def test_extract_json_balanced_brace_fallback():
    text = 'prose {"a": 1} more prose {"b": 2}'
    assert _extract_json(text) == {"a": 1}


# RACT 0.1.1 - Trust and tooling
