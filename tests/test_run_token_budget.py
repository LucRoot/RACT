"""B-065: a hard token budget per run.

The budget counts the usage each response reports. A request that would
start with the count at or over the budget is not sent. A response with no
usage is not counted, and the run says once that the budget is not enforced.
The exit code for a stopped run is 4.
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract import run_token_budget as token_budget
from ract.config_check import find_config_problems
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.session_turn import exit_code_for

URL = "http://127.0.0.1:9/v1"
MESSAGES = [{"role": "user", "content": "hello"}]


def _reply(prompt: int, completion: int, *, usage: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {"choices": [{"message": {"content": "ok"}}]}
    if usage:
        body["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion}
    return body


def _provider(handler: Any) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        {"url": URL, "model": "m", "api_key": "k", "max_retries": 0}
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def _counting(bodies: list[dict[str, Any]]) -> tuple[Any, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=bodies[min(len(calls), len(bodies)) - 1])

    return handler, calls


# ---------------------------------------------------------------- 1. the stop


def test_the_request_that_would_start_over_budget_is_not_sent() -> None:
    handler, calls = _counting([_reply(400, 0)] * 6)
    provider = _provider(handler)
    with token_budget.run_budget(1000) as budget:
        results = [provider.complete(MESSAGES) for _ in range(4)]
    assert all(r.is_ok() for r in results[:3])
    assert not results[3].is_ok()
    assert len(calls) == 3  # the fourth request was never sent
    assert budget is not None and budget.used == 1200
    assert results[3].error == (
        "stopped: this run used 1200 tokens; token_budget is 1000. "
        "Raise token_budget in ract.yaml, or split the task."
    )


def test_the_stop_is_exit_code_4() -> None:
    assert (
        exit_code_for("stopped: this run used 1200 tokens; token_budget is 1000.") == 4
    )


# ---------------------------------------------------------------- 2. no budget


def test_without_a_budget_nothing_changes() -> None:
    handler, calls = _counting([_reply(400, 0)] * 6)
    provider = _provider(handler)
    with token_budget.run_budget(None):
        results = [provider.complete(MESSAGES) for _ in range(4)]
    assert all(r.is_ok() for r in results)
    assert len(calls) == 4


# ---------------------------------------------------------------- 3. one large request


def test_one_request_over_the_budget_is_sent_once_then_stops(capsys: Any) -> None:
    handler, calls = _counting([_reply(500, 0)] * 3)
    provider = _provider(handler)
    with token_budget.run_budget(100):
        first = provider.complete(MESSAGES)
        second = provider.complete(MESSAGES)
    assert first.is_ok()
    assert len(calls) == 1
    assert "used 500 tokens; token_budget is 100" in (second.error or "")


# ---------------------------------------------------------------- 4. no usage


def test_a_provider_with_no_usage_is_not_enforced_and_says_so_once(capsys: Any) -> None:
    handler, calls = _counting([_reply(0, 0, usage=False)] * 5)
    provider = _provider(handler)
    with token_budget.run_budget(10):
        results = [provider.complete(MESSAGES) for _ in range(3)]
    assert all(r.is_ok() for r in results)
    assert len(calls) == 3
    out = capsys.readouterr().out
    assert out.count("reports no token counts, so it is not enforced") == 1


def test_streaming_counts_the_final_usage_and_is_stopped_before_the_next_stream() -> (
    None
):
    def stream_body(prompt: int) -> bytes:
        chunk = {"choices": [{"delta": {"content": "ok"}}]}
        final = {
            "choices": [],
            "usage": {"prompt_tokens": prompt, "completion_tokens": 0},
        }
        return (
            f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(final)}\n\ndata: [DONE]\n\n"
        ).encode()

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=stream_body(600), request=request)

    provider = _provider(handler)
    with token_budget.run_budget(500) as budget:
        list(provider.complete_stream(MESSAGES))
        second = list(provider.complete_stream(MESSAGES))
    assert len(calls) == 1
    assert budget is not None and budget.used == 600
    assert second and "stopped: this run used 600 tokens" in (second[0].error or "")


# ---------------------------------------------------------------- 5. retries


def test_a_retried_request_counts_each_reported_attempt() -> None:
    bodies = [_reply(300, 0)]
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(503, json={"error": "busy"}, request=request)
        return httpx.Response(200, json=bodies[0], request=request)

    provider = OpenAICompatibleProvider(
        {"url": URL, "model": "m", "api_key": "k", "max_retries": 2, "retry_delay": 0.0}
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    with token_budget.run_budget(10_000) as budget:
        result = provider.complete(MESSAGES)
    assert result.is_ok() and len(seen) == 2
    # The failed attempt reported no usage; the successful one counts once.
    assert budget is not None and budget.used == 300


# ---------------------------------------------------------------- 6. invalid values


@pytest.mark.parametrize("value", [0, -5, "many", 1.5, True])
def test_an_invalid_value_is_refused_and_names_the_key(value: object) -> None:
    with pytest.raises(token_budget.BudgetConfigError, match="token_budget"):
        token_budget.parse(value)


def test_absent_and_null_mean_off() -> None:
    assert token_budget.parse(None) is None
    assert find_config_problems({"token_budget": None}) == []


def test_doctor_names_an_invalid_value_in_the_config_check() -> None:
    problems = find_config_problems({"token_budget": "many"})
    assert any("token_budget must be a positive whole number" in p for p in problems)


# ---------------------------------------------------------------- the run's budget


def _budget_seen(
    monkeypatch: pytest.MonkeyPatch, config_budget: str | None, flag: Any = None
) -> Any:
    from ract import ract_runner

    seen: list[Any] = []

    def capture(config_path: Path, intent: str, **kwargs: Any) -> Any:
        seen.append(token_budget.current())
        return None

    monkeypatch.setattr(ract_runner, "_trusted_run", capture)
    body = "project:\n  name: demo\n"
    if config_budget is not None:
        body += f"token_budget: {config_budget}\n"
    config = tmp_config(body)
    kwargs = {} if flag is None else {"token_budget": flag}
    ract_runner.run_ract(config, "fix add", **kwargs)
    return seen[0]


def tmp_config(body: str) -> Path:
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="ract-budget-"))
    config = folder / "ract.yaml"
    config.write_text(body, encoding="utf-8")
    return config


def test_the_config_value_sets_the_run_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _budget_seen(monkeypatch, "700")
    assert budget is not None and budget.limit == 700


def test_the_flag_overrides_the_config_value(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = _budget_seen(monkeypatch, "700", flag=5)
    assert budget is not None and budget.limit == 5


def test_no_config_value_and_no_flag_means_no_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _budget_seen(monkeypatch, None) is None


def test_a_bad_flag_is_refused_with_the_key_named() -> None:
    from ract import ract_runner

    result = ract_runner.run_ract(
        tmp_config("project:\n  name: demo\n"), "fix add", token_budget=0
    )
    assert not result.is_ok()
    assert "token_budget" in (result.error or "")


# ---------------------------------------------------------------- the wiring


def test_the_budget_stop_is_its_own_turn_outcome_and_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract import ract_runner, session_turn
    from ract.session_events import EventStream  # noqa: PLC0415
    from ract.rooted import Rooted

    stop = "stopped: this run used 1200 tokens; token_budget is 1000. Raise token_budget in ract.yaml, or split the task."
    monkeypatch.setattr(
        ract_runner,
        "run_ract",
        lambda *a, **k: Rooted(
            value=None, assumption="x", confidence=0.0, provenance=["t"], error=stop
        ),
    )
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: demo\n", encoding="utf-8")
    events: list[Any] = []
    stream = EventStream(session="s-budget")
    stream.subscribe(events.append)
    request = session_turn.TurnRequest(
        config=config, intent="fix add", session_id=None, resume=False
    )
    code = session_turn.run_turn(stream, request, turn=1, cancel=threading.Event())
    assert code == 4
    finished = [e for e in events if e.kind == "turn.finished"]
    assert finished and finished[-1].data["outcome"] == "budget"


def test_the_headless_flag_reaches_the_turn_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract import headless, session_turn

    seen: list[Any] = []

    def capture(stream: Any, request: Any, **kwargs: Any) -> int:
        seen.append(request.token_budget)
        return 0

    monkeypatch.setattr(session_turn, "run_turn", capture)
    (tmp_path / "ract.yaml").write_text(
        "project:" + chr(10) + "  name: demo" + chr(10), encoding="utf-8"
    )
    code = headless.run_headless(
        [
            "-p",
            "fix add",
            "--config",
            str(tmp_path / "ract.yaml"),
            "--token-budget",
            "500",
        ],
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code == 0 and seen == [500]
