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
from ract.repl import ReplSession
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
