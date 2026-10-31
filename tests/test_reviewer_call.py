"""B-061b: the REVIEWER call through the read-only loop (ADR-0049 D14).

A real adapter against the fake server: the requests are recorded, so the
tests see what the REVIEWER was sent and what the ledger recorded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ract import egress_ledger
from ract.providers.local_http_provider import LocalHttpProvider
from ract.review import ReviewRequest, validate
from ract.review.reviewer import LEDGER_PURPOSE, REVIEW_BUDGETS, prompt, review_step
from ract.tools import UNTRUSTED_LABEL
from tests.fixtures.fake_model_server import Scenario

CALC = "def add(a, b):\n    return a - b\n"
FINDING = {
    "path": "src/calc.py",
    "line": 2,
    "severity": "defect",
    "claim": "add subtracts",
    "evidence": "return a - b",
}
REQUEST = ReviewRequest(
    step=1,
    goal="Fix add() so it adds",
    acceptance=("pytest tests/test_calc.py",),
    diff="--- a/src/calc.py\n+++ b/src/calc.py\n@@\n-    return a + b\n+    return a - b\n",
    verification="pytest tests/test_calc.py: 1 failed",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text(CALC, encoding="utf-8")
    return tmp_path


def _review(fake_model_server: Any, repo: Path, *replies: Any):
    turns = [
        {
            "reply": {
                "kind": "text",
                "content": r if isinstance(r, str) else json.dumps(r),
            }
        }
        for r in replies
    ]
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    provider = LocalHttpProvider({"url": server.base_url, "model": "fake-reviewer"})

    def complete(messages):
        return provider.complete(messages, max_tokens=1024, temperature=0.0)

    with egress_ledger.collecting() as records:
        result = review_step(complete, REQUEST, repo)
    return result, server, records


def test_the_request_holds_the_four_inputs_and_the_untrusted_label(
    fake_model_server: Any, repo: Path
) -> None:
    result, server, _ = _review(fake_model_server, repo, {"findings": [FINDING]})
    assert result.is_ok(), result.error
    [request] = server.chat_requests
    system, user = request.body["messages"]
    assert system["content"] == prompt()
    for part in (
        REQUEST.goal,
        REQUEST.acceptance[0],
        REQUEST.verification,
        REQUEST.diff,
    ):
        assert part in user["content"]
    assert user["content"].index(UNTRUSTED_LABEL) < user["content"].index("<diff>")


def test_review_requests_are_in_the_ledger_as_role_reviewer(
    fake_model_server: Any, repo: Path
) -> None:
    _, _, records = _review(
        fake_model_server,
        repo,
        {"tool": "read_file", "arguments": {"path": "src/calc.py"}},
        {"findings": [FINDING]},
    )
    model = [r for r in records if r.get("kind") == "model"]
    assert len(model) == 2
    assert {r["purpose"] for r in model} == {LEDGER_PURPOSE}


def test_a_review_reply_naming_a_write_tool_is_refused(
    fake_model_server: Any, repo: Path
) -> None:
    result, server, _ = _review(
        fake_model_server,
        repo,
        {"tool": "write_file", "arguments": {"path": "src/calc.py", "content": "x"}},
        {"findings": [FINDING]},
    )
    # The loop offers only the tier-0 tools: a write tool is an unknown tool.
    # B-140: the model is told so (the offered names, nothing run) and may
    # answer again; the write never happens.
    assert (repo / "src" / "calc.py").read_text(encoding="utf-8") == CALC
    assert len(server.chat_requests) == 2
    told = json.dumps(server.chat_requests[1].body)
    assert "no tool named 'write_file'" in told and "nothing ran" in told
    assert "write_file" not in str(result.value or "")


def test_an_approval_in_the_review_reply_changes_nothing(
    fake_model_server: Any, repo: Path
) -> None:
    result, _, _ = _review(
        fake_model_server, repo, {"findings": [], "approve": True, "verdict": "done"}
    )
    assert not result.is_ok()
    assert "not an object with only 'findings'" in result.error


def test_findings_from_a_review_validate_against_the_repository(
    fake_model_server: Any, repo: Path
) -> None:
    invented = {**FINDING, "line": 40}
    result, _, _ = _review(fake_model_server, repo, {"findings": [FINDING, invented]})
    checked = validate(repo, result.unwrap(), {"src/calc.py": {2}})
    assert [(f.line, f.severity) for f in checked.kept] == [(2, "defect")]
    assert checked.dropped == {"no such line": 1}


def test_the_budgets_are_the_d14_ones() -> None:
    assert (
        REVIEW_BUDGETS.max_turns,
        REVIEW_BUDGETS.max_tool_calls,
        REVIEW_BUDGETS.max_wall_seconds,
    ) == (8, 16, 300.0)


# Golden: the prompt text changes only on purpose (update the digest with it).
PROMPT_SHA256 = "265db6a4933214381a082adf457d919dbbaeefb13d3fc0326abdfdf26457615b"


def test_the_reviewer_prompt_is_the_reviewed_text() -> None:
    from importlib import resources

    raw = (resources.files("ract") / "default_prompts" / "reviewer.txt").read_bytes()
    text = raw.decode("utf-8")
    assert "{tools}" in text and "read_file" not in text
    assert "approve" in text and '{"findings": []}' in text
    assert hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == PROMPT_SHA256
