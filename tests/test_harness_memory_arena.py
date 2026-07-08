from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from rootact.harness import Harness
from rootact.memory_arena import MemoryArena
from rootact.rooted import Rooted


def _write_config(tmp_path: Path) -> Path:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "manager.txt").write_text("You are the manager.", encoding="utf-8")
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
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_harness_prepends_memory_arena_to_intent(tmp_path):
    config_path = _write_config(tmp_path)
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
    fake_step_response = {"choices": [{"message": {"content": "def test_x(): pass"}}]}
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    arena = MemoryArena()
    arena.record("constraint", "always import annotations first", importance=2)

    report_rooted = harness.run("write tests for the harness", memory_arena=arena)
    assert report_rooted.is_ok()

    plan_call = harness.manager.provider.complete.call_args_list[0]
    messages = plan_call.kwargs.get(
        "messages", plan_call.args[0] if plan_call.args else []
    )
    user_content = messages[-1]["content"]
    assert "Memory:" in user_content
    assert "always import annotations first" in user_content


def test_harness_records_outcomes_in_arena(tmp_path):
    config_path = _write_config(tmp_path)
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
    fake_step_response = {"choices": [{"message": {"content": "def test_x(): pass"}}]}
    harness.manager.provider.complete = MagicMock(
        side_effect=[
            Rooted(value=fake_plan_response, assumption="ok", confidence=1.0),
            Rooted(value=fake_step_response, assumption="ok", confidence=1.0),
        ]
    )

    arena = MemoryArena()
    harness.run("write tests", memory_arena=arena)

    replay = arena.replay()
    assert "plan" in replay
    assert "outcome" in replay
    assert "write tests -> tests/test_x.py" in replay
