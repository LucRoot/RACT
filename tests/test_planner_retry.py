"""B-086: a planner reply with no steps gets one retry, then one plain sentence (J9).

A weak model answers the intent in prose; the user saw "Plan contains no steps."
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from ract import egress_ledger, run_token_budget
from ract.manager import NO_PLAN_SENTENCE, PLAN_SHAPE_REQUEST, Manager
from ract.providers.local_http_provider import LocalHttpProvider
from ract.rooted import Rooted
from tests.fixtures.fake_model_server import Scenario

PLAN = {
    "assumption": "add() is wrong",
    "confidence": 0.8,
    "steps": [
        {
            "action": "Fix add()",
            "provider_hint": "local",
            "expected_artifact": "src/calc.py",
        }
    ],
}
PROSE = "Sure! add() subtracts; change the minus to a plus."


def _reply(text: str) -> Rooted[dict[str, Any]]:
    return Rooted(
        value={"choices": [{"message": {"content": text}}]},
        assumption="ok",
        confidence=1.0,
    )


def _manager(*texts: str) -> tuple[Manager, MagicMock]:
    provider = MagicMock()
    provider.complete.side_effect = [_reply(t) for t in texts]
    return Manager(provider, "You are the manager."), provider


def test_prose_then_json_on_the_retry() -> None:
    manager, provider = _manager(PROSE, json.dumps(PLAN))
    result = manager.plan("fix add")
    assert result.is_ok(), result.error
    assert [s.action for s in result.unwrap().steps] == ["Fix add()"]
    assert provider.complete.call_count == 2
    retry = provider.complete.call_args_list[1].args[0]
    assert retry[-2] == {"role": "assistant", "content": PROSE}
    assert retry[-1] == {"role": "user", "content": PLAN_SHAPE_REQUEST}


def test_prose_twice_ends_with_one_plain_sentence() -> None:
    manager, provider = _manager(PROSE, PROSE)
    result = manager.plan("fix add")
    assert not result.is_ok()
    assert result.error == NO_PLAN_SENTENCE
    assert provider.complete.call_count == 2


def test_a_plan_with_no_steps_is_asked_again() -> None:
    empty = json.dumps({"assumption": "x", "confidence": 0.9, "steps": []})
    manager, provider = _manager(empty, json.dumps(PLAN))
    assert manager.plan("fix add").is_ok()
    assert provider.complete.call_count == 2


def test_a_reply_with_escape_sequences_never_reaches_the_user() -> None:
    hostile = "\x1b[2J\x1b]0;pwned\x07 no plan here"
    manager, _ = _manager(hostile, hostile)
    result = manager.plan("fix add")
    assert result.error == NO_PLAN_SENTENCE
    assert "\x1b" not in result.error and "\x07" not in result.error


def test_the_retry_is_one_request_counted_in_the_budget(fake_model_server: Any) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": PROSE}},
                    {"reply": {"kind": "text", "content": json.dumps(PLAN)}},
                ]
            }
        )
    )
    manager = Manager(
        LocalHttpProvider({"url": server.base_url, "model": "m"}), "You plan."
    )
    with (
        run_token_budget.run_budget(1_000_000) as budget,
        egress_ledger.collecting() as records,
    ):
        assert manager.plan("fix add").is_ok()
    assert len(server.chat_requests) == 2
    plan_records = [r for r in records if r.get("purpose") == "plan"]
    assert len(plan_records) == 2
    assert budget is not None and budget.used == sum(
        (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0) for r in plan_records
    )
