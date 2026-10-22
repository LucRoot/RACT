"""B-057: the reasoning effort setting (session value, off by default).

The request body is checked on the provider's own payload builder. The fake
model server cannot show the mapped path, because the mapping only applies to
the OpenAI endpoint; that is why these checks are unit tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import cli
from ract.providers import reasoning
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.doctor import RactDoctor
from ract.executor.steps import Executor
from ract.repl import ReplSession
from ract.rooted import Rooted
from tests.test_repl import _Console

OPENAI_URL = "https://api.openai.com/v1"
LOCAL_URL = "http://127.0.0.1:9/v1"
MESSAGES = [{"role": "user", "content": "hello"}]


@pytest.fixture(autouse=True)
def _fresh_setting() -> None:
    reasoning.reset_session_effort()
    yield
    reasoning.reset_session_effort()


def _body(url: str) -> dict:
    provider = OpenAICompatibleProvider(
        {"url": url, "model": "m", "api_key": "sentinel-b057"}
    )
    return provider._build_payload(
        MESSAGES, model=None, max_tokens=8, temperature=0, stream=False
    )


def test_the_setting_is_off_by_default_and_no_request_carries_it() -> None:
    assert reasoning.session_effort() == "off"
    assert "reasoning_effort" not in _body(OPENAI_URL)


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_a_mapped_provider_gets_the_exact_parameter(level: str) -> None:
    reasoning.set_session_effort(level)
    assert _body(OPENAI_URL)["reasoning_effort"] == level


def test_a_provider_without_a_mapping_is_unchanged_and_noted_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _body(LOCAL_URL)
    reasoning.set_session_effort("low")
    first = _body(LOCAL_URL)
    second = _body(LOCAL_URL)
    assert first == second == baseline
    err = capsys.readouterr().err
    assert err.count("reasoning_effort is ignored by openai_compatible") == 1


def test_a_bad_value_is_refused_with_the_list_and_nothing_changes() -> None:
    reasoning.set_session_effort("low")
    with pytest.raises(ValueError, match="off, low, medium, high"):
        reasoning.set_session_effort("extreme")
    assert reasoning.session_effort() == "low"


def _session_for(config: Path) -> tuple[ReplSession, _Console]:
    console = _Console()
    session = ReplSession(
        config,
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, console


def _session() -> tuple[ReplSession, _Console]:
    console = _Console()
    session = ReplSession(
        Path("ract.yaml"),
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, console


def test_set_reasoning_then_settings_shows_it() -> None:
    session, console = _session()
    session.handle("/set reasoning low")
    assert reasoning.session_effort() == "low"
    session.handle("/settings")
    assert "reasoning effort | low" in console.text


def test_set_reasoning_refuses_a_bad_value_and_lists_the_valid_ones() -> None:
    session, console = _session()
    session.handle("/set reasoning low")
    session.handle("/set reasoning bogus")
    assert reasoning.session_effort() == "low"
    assert "off, low, medium, high" in console.text


def test_a_new_session_starts_from_off_again() -> None:
    session, _ = _session()
    session.handle("/set reasoning high")
    assert reasoning.session_effort() == "high"
    _session()  # a new session resets the setting to its default
    assert reasoning.session_effort() == "off"


# ---------------------------------------------------------------- B-057b: config key


def _write_config(path: Path, effort: str) -> Path:
    lines = [
        "project:",
        "  name: demo",
        "manager_provider: local",
        "providers:",
        "  local:",
        "    adapter: local_http",
        "    url: http://127.0.0.1:9/v1",
        "    model: m",
        f"    reasoning_effort: {effort}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_config_value_is_the_session_starting_value(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "ract.yaml", "high")
    assert reasoning.configured_default(config) == "high"
    session, _ = _session_for(config)
    assert reasoning.session_effort() == "high"


def test_a_missing_or_bad_config_value_starts_at_off(tmp_path: Path) -> None:
    assert reasoning.configured_default(tmp_path / "absent.yaml") == "off"
    config = _write_config(tmp_path / "ract.yaml", "extreme")
    assert reasoning.configured_default(config) == "off"


def test_the_provider_refuses_a_value_outside_the_four() -> None:
    with pytest.raises(ValueError, match="off, low, medium, high"):
        OpenAICompatibleProvider(
            {"url": LOCAL_URL, "model": "m", "reasoning_effort": "extreme"}
        )


def test_doctor_names_the_bad_value_and_the_valid_list(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "ract.yaml", "extreme")
    results = RactDoctor(config).diagnose()
    providers = next(r for r in results if r.name == "providers")
    assert providers.passed is False
    assert "reasoning_effort" in providers.message
    assert "off, low, medium, high" in providers.message


def test_reasoning_text_is_not_the_answer_and_is_not_sent_back() -> None:
    class _Stream:
        def complete_stream(self, messages, **kwargs):
            yield Rooted(
                value={"choices": [{"delta": {"reasoning_content": "PRIVATE THOUGHT"}}]}
            )
            yield Rooted(value={"choices": [{"delta": {"content": "the answer"}}]})

    shown: list[str] = []
    result = Executor._stream_completion(
        object.__new__(Executor), _Stream(), [], shown.append
    )
    message = result.unwrap()["choices"][0]["message"]
    assert message["content"] == "the answer"
    assert "PRIVATE THOUGHT" not in message["content"]
    assert "".join(shown) == "the answer"
