from __future__ import annotations


from pathlib import Path
from unittest.mock import MagicMock

import yaml

from ract.harness import Harness
from ract.rooted import Rooted


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
    config_path = tmp_path / "ract.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_harness_streaming_collects_and_calls_callback(tmp_path):
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

    class _StreamingAdapter:
        @property
        def name(self) -> str:
            return "streaming_mock"

        def capabilities(self) -> set[str]:
            return {"chat", "streaming"}

        def complete_stream(self, messages, **kwargs):
            for token in ["abc", "def"]:
                yield Rooted(
                    value={"choices": [{"delta": {"content": token}}]},
                    assumption="chunk",
                    confidence=1.0,
                )

    harness.manager.provider.complete = MagicMock(
        return_value=Rooted(value=fake_plan_response, assumption="ok", confidence=1.0)
    )
    harness.executor.router._adapters["local"] = _StreamingAdapter()

    received: list[str] = []
    report_rooted = harness.run(
        "write tests for the harness", stream=True, stream_callback=received.append
    )
    assert report_rooted.is_ok()
    content = report_rooted.unwrap().step_results[0].content
    assert "abcdef" in content
    assert received == ["abc", "def"]


# RACT 0.1.1 - Trust and tooling
