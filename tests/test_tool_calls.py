"""Tool-call extraction ladder (``ract.tool_calls``).

One test per rung, per failure outcome, per repair rule and per loop guard,
plus end-to-end reads of fake-server scenarios.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract.tool_calls import (
    REFORMAT_REQUEST,
    LoopGuard,
    ToolCall,
    ToolSignature,
    accumulate_stream,
    contains_tool_markup,
    explain_truncation,
    extract,
    next_action,
)

TOOLS = [
    ToolSignature("read_file", frozenset({"file_path", "offset", "limit"})),
    ToolSignature("grep", frozenset({"pattern", "path"})),
    ToolSignature("write_file", frozenset({"file_path", "content"})),
    ToolSignature("write_notes", frozenset({"text"})),
]


def _resp(
    content: str = "",
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    finish: str = "stop",
    reasoning: str = "",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if reasoning:
        message["reasoning_content"] = reasoning
    out: dict[str, Any] = {
        "choices": [{"index": 0, "message": message, "finish_reason": finish}]
    }
    if usage:
        out["usage"] = usage
    return out


def _native(name: str, args: Any, call_id: str = "c1") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": args if isinstance(args, str) else json.dumps(args),
        },
    }


# ---------------------------------------------------------------- the ladder


@pytest.mark.parametrize(
    "content, rung",
    [
        (
            '<tool_call>{"name": "grep", "arguments": {"pattern": "x"}}</tool_call>',
            "tag",
        ),
        (
            'Let me look.\n<tool_call>\n{"name": "grep", "arguments": {"pattern": "x"}}\n</tool_call>',
            "tag",
        ),
        (
            '<|start|>assistant<|channel|>commentary to=functions.grep <|constrain|>json<|message|>{"pattern": "x"}<|call|>',
            "harmony",
        ),
        (
            'I will search.\n```json\n{"name": "grep", "arguments": {"pattern": "x"}}\n```',
            "fenced_json",
        ),
        ('{"tool": "grep", "arguments": {"pattern": "x"}}', "envelope"),
        ('{"name": "grep", "arguments": {"pattern": "x"}}', "bare_json"),
        ('grep(pattern="x")', "pythonic"),
    ],
)
def test_each_text_rung_yields_the_call_and_records_the_rung(
    content: str, rung: str
) -> None:
    result = extract(_resp(content), TOOLS)
    assert result.is_ok(), result.error
    ext = result.unwrap()
    assert ext.outcome == "tool_calls"
    assert ext.rung == rung
    assert [(c.name, c.arguments) for c in ext.calls] == [("grep", {"pattern": "x"})]
    assert f"rung:{rung}" in result.provenance


def test_native_rung_single_and_parallel_with_string_arguments() -> None:
    calls = [
        _native("grep", {"pattern": "x"}, "a"),
        _native("read_file", '{"file_path": "a.py"}', "b"),
    ]
    ext = extract(_resp(tool_calls=calls), TOOLS).unwrap()
    assert ext.rung == "native"
    assert [(c.name, c.arguments, c.call_id) for c in ext.calls] == [
        ("grep", {"pattern": "x"}, "a"),
        ("read_file", {"file_path": "a.py"}, "b"),
    ]


def test_native_wins_over_text_in_the_same_message() -> None:
    ext = extract(
        _resp("I will search now.", tool_calls=[_native("grep", {"pattern": "y"})]),
        TOOLS,
    ).unwrap()
    assert ext.rung == "native" and ext.calls[0].arguments == {"pattern": "y"}


def test_parallel_pythonic_list() -> None:
    ext = extract(
        _resp('[grep(pattern="a"), read_file(file_path="b.py", limit=10)]'), TOOLS
    ).unwrap()
    assert [c.name for c in ext.calls] == ["grep", "read_file"]
    assert ext.calls[1].arguments == {"file_path": "b.py", "limit": 10}


def test_final_answer_plain_and_enveloped() -> None:
    plain = extract(_resp("The loader is in config.py:12."), TOOLS).unwrap()
    envelope = extract(_resp('{"final": "Done."}'), TOOLS).unwrap()
    assert (
        plain.outcome == "final"
        and plain.final_text == "The loader is in config.py:12."
    )
    assert envelope.outcome == "final" and envelope.final_text == "Done."


# ---------------------------------------------------------------- reasoning carries no calls


def test_call_in_reasoning_field_is_not_extracted() -> None:
    ext = extract(
        _resp(
            "Here is the answer.",
            reasoning='<tool_call>{"name":"write_file","arguments":{}}</tool_call>',
        ),
        TOOLS,
    ).unwrap()
    assert ext.outcome == "final"
    assert ext.final_text == "Here is the answer."


def test_call_inside_think_block_is_not_extracted() -> None:
    content = (
        '<think>maybe write_file(file_path="x", content="y")</think>The answer is 4.'
    )
    ext = extract(_resp(content), TOOLS).unwrap()
    assert ext.outcome == "final" and ext.final_text == "The answer is 4."


def test_call_mentioned_in_prose_is_not_a_call() -> None:
    ext = extract(_resp('I would run grep(pattern="x") if I could.'), TOOLS).unwrap()
    assert ext.outcome == "final"


# ---------------------------------------------------------------- unparsed markup (R-142)


@pytest.mark.parametrize(
    "content",
    [
        "<tool_call>{not json}</tool_call>",
        '<invoke name="grep"><parameter name="pattern">x</parameter></invoke>',
        "<function_calls>\n<invoke name='x'>",
        "<tool_use></tool_use>",
        "<|channel|>commentary to=functions.grep <|message|>{broken",
        '[TOOL_CALLS] [{"name": ',
        'Sure! {"tool": "read_file", "arguments": {"path": "README.md"}',
    ],
)
def test_unparsed_markup_is_never_a_final_answer(content: str) -> None:
    result = extract(_resp(content), TOOLS)
    assert not result.is_ok()
    ext = result.value
    assert ext is not None and ext.outcome == "markup_unparsed"
    assert result.hint == "tool-parse-failed"
    assert ext.raw_text == content


def test_empty_native_tool_use_block_is_markup_unparsed() -> None:
    result = extract(
        _resp(tool_calls=[{"id": "x", "type": "function", "function": {"name": ""}}]),
        TOOLS,
    )
    assert result.value is not None and result.value.outcome == "markup_unparsed"
    assert result.hint == "tool-parse-failed"


def test_contains_tool_markup_ignores_ordinary_text() -> None:
    assert not contains_tool_markup(
        "Use the `tool_call` helper in utils.py; invoke it twice."
    )
    assert contains_tool_markup("<tool_call>")


def test_next_action_climbs_grammar_then_reformat_then_fails() -> None:
    bad = extract(_resp("<tool_call>{oops</tool_call>"), TOOLS).value
    assert bad is not None
    assert (
        next_action(
            bad, server_supports_grammar=True, grammar_tried=False, reformat_tried=False
        )
        == "grammar_retry"
    )
    assert (
        next_action(
            bad, server_supports_grammar=True, grammar_tried=True, reformat_tried=False
        )
        == "reformat_request"
    )
    assert (
        next_action(
            bad,
            server_supports_grammar=False,
            grammar_tried=False,
            reformat_tried=False,
        )
        == "reformat_request"
    )
    assert (
        next_action(
            bad, server_supports_grammar=True, grammar_tried=True, reformat_tried=True
        )
        == "fail"
    )
    final = extract(_resp("ok"), TOOLS).unwrap()
    assert (
        next_action(
            final,
            server_supports_grammar=True,
            grammar_tried=False,
            reformat_tried=False,
        )
        == "none"
    )
    assert "JSON object" in REFORMAT_REQUEST


# ---------------------------------------------------------------- truncation and empty (R-144)


def test_truncated_reasoning_only_reply_is_explained_with_token_counts() -> None:
    resp = _resp(
        "",
        finish="length",
        reasoning="thinking " * 500,
        usage={"completion_tokens": 3900, "prompt_tokens": 10},
    )
    result = extract(resp, TOOLS, max_tokens=4096)
    assert not result.is_ok()
    assert result.value is not None and result.value.outcome == "truncated"
    assert "reasoning used 3,900 of 4,096 tokens" in (result.error or "")
    assert result.hint == "output_limit"


def test_truncated_without_usage_falls_back_to_model_output_explanation() -> None:
    text = explain_truncation(_resp("half", finish="length"))
    assert "finish_reason=length" in text


def test_empty_reply_is_named() -> None:
    result = extract(_resp(""), TOOLS)
    assert result.value is not None and result.value.outcome == "empty"
    assert result.hint == "empty_output"


@pytest.mark.parametrize(
    "raw", [None, {}, {"choices": []}, {"choices": [None]}, "text"]
)
def test_malformed_responses_never_raise(raw: Any) -> None:
    result = extract(raw, TOOLS)  # type: ignore[arg-type]
    assert not result.is_ok()


# ---------------------------------------------------------------- repairs (R-143)


def test_unique_near_miss_name_and_key_are_repaired_and_visible() -> None:
    ext = extract(
        _resp('{"name": "ReadFile", "arguments": {"path": "a.py"}}'), TOOLS
    ).unwrap()
    call = ext.calls[0]
    assert call.name == "read_file"
    assert call.arguments == {"file_path": "a.py"}
    assert [str(r) for r in call.repairs] == [
        "repaired: ReadFile -> read_file",
        "repaired: path -> file_path",
    ]


def test_namespaced_name_is_repaired() -> None:
    ext = extract(
        _resp(tool_calls=[_native("functions.grep", {"pattern": "x"})]), TOOLS
    ).unwrap()
    assert ext.calls[0].name == "grep"
    assert str(ext.calls[0].repairs[0]) == "repaired: functions.grep -> grep"


def test_ambiguous_name_is_refused_with_a_hint() -> None:
    tools = TOOLS + [ToolSignature("read-file", frozenset({"file_path"}))]
    result = extract(_resp('{"name": "READFILE", "arguments": {}}'), tools)
    assert not result.is_ok()
    assert "more than one tool" in (result.error or "")
    assert result.hint and "tool names" in result.hint


def test_unknown_tool_and_unknown_key_are_refused() -> None:
    unknown = extract(_resp('{"name": "rm_rf", "arguments": {}}'), TOOLS)
    assert "no tool named 'rm_rf'" in (unknown.error or "")
    bad_key = extract(
        _resp('{"name": "grep", "arguments": {"pattern": "x", "flags": "-r"}}'), TOOLS
    )
    assert "'flags' is not an argument of grep" in (bad_key.error or "")


def test_ambiguous_key_is_refused() -> None:
    tools = [ToolSignature("copy", frozenset({"src_path", "dst_path"}))]
    result = extract(_resp('{"name": "copy", "arguments": {"path": "a"}}'), tools)
    assert "matches more than one argument" in (result.error or "")


def test_non_object_arguments_are_refused() -> None:
    result = extract(_resp(tool_calls=[_native("grep", "[1, 2]")]), TOOLS)
    assert "not a JSON object" in (result.error or "")


# ---------------------------------------------------------------- loop guards (R-119)


def test_loop_guard_stops_on_third_identical_call() -> None:
    guard = LoopGuard()
    call = ToolCall("grep", {"pattern": "x"}, "c", "native")
    assert guard.record_call(call) is None
    assert guard.record_call(ToolCall("grep", {"pattern": "y"}, "c", "native")) is None
    assert guard.record_call(call) is None
    reason = guard.record_call(call)
    assert reason and "3 times" in reason


def test_loop_guard_stops_on_second_identical_failure() -> None:
    guard = LoopGuard()
    call = ToolCall("read_file", {"file_path": "x"}, "c", "native")
    assert guard.record_failure(call, "not found") is None
    assert guard.record_failure(call, "permission denied") is None
    assert guard.record_failure(call, "not found ") is not None


# ---------------------------------------------------------------- purity


def test_module_imports_nothing_that_can_act() -> None:
    source = Path(__file__).resolve().parent.parent / "src" / "ract" / "tool_calls.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "os",
        "subprocess",
        "shutil",
        "socket",
        "httpx",
        "pathlib",
        "ract.providers",
    }
    assert not (imported & forbidden), imported & forbidden
    assert "open(" not in source.read_text(encoding="utf-8")


# ---------------------------------------------------------------- against the fake server


def _stream(server: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"model": "m", "messages": messages, "stream": True}
    chunks = []
    with httpx.stream(
        "POST", f"{server.base_url}/chat/completions", json=payload, timeout=10
    ) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: {"):
                chunks.append(json.loads(line[6:]))
    return accumulate_stream(chunks)


def test_j3_streamed_fragmented_calls_are_accumulated_and_extracted(
    fake_model_server: Any,
) -> None:
    server = fake_model_server("j3_ask_code")
    msgs = [{"role": "user", "content": "where is the config loader?"}]
    tools = [
        ToolSignature("grep", frozenset({"pattern", "path"})),
        ToolSignature("read_file", frozenset({"path", "offset", "limit"})),
    ]
    first = extract(_stream(server, msgs), tools).unwrap()
    assert first.rung == "native"
    assert first.calls[0].arguments == {"pattern": "def load_config", "path": "src"}
    second = extract(_stream(server, msgs), tools).unwrap()
    assert [c.name for c in second.calls] == ["read_file", "read_file"]
    final = extract(_stream(server, msgs), tools).unwrap()
    assert final.outcome == "final" and "config.py:12" in final.final_text


def test_j9_weak_model_malformed_then_valid_then_hidden_reasoning(
    fake_model_server: Any,
) -> None:
    server = fake_model_server("j9_weak_model")
    msgs = [{"role": "user", "content": "summarize the README"}]
    tools = [ToolSignature("read_file", frozenset({"path"}))]

    def ask() -> Any:
        resp = httpx.post(
            f"{server.base_url}/chat/completions",
            json={"model": "m", "messages": msgs},
            timeout=10,
        )
        return extract(resp.json(), tools)

    malformed = ask()
    assert malformed.value is not None and malformed.value.outcome == "markup_unparsed"
    valid = ask().unwrap()
    assert valid.rung == "envelope" and valid.calls[0].arguments == {
        "path": "README.md"
    }
    answer = ask().unwrap()
    assert answer.outcome == "final"
    assert "should not put this thinking" not in answer.final_text
    inline = ask().unwrap()
    assert inline.final_text == "Done."


def test_j10_truncation_is_explained(fake_model_server: Any) -> None:
    server = fake_model_server("j10_faults")
    for _ in range(8):  # skip the HTTP faults to reach the truncated turn
        try:
            httpx.post(
                f"{server.base_url}/chat/completions",
                json={"model": "m", "messages": [], "stream": False},
                timeout=5,
            )
        except httpx.HTTPError:
            pass
    resp = httpx.post(
        f"{server.base_url}/chat/completions",
        json={"model": "m", "messages": []},
        timeout=5,
    ).json()
    result = extract(resp, TOOLS, max_tokens=64)
    assert result.value is not None and result.value.outcome == "truncated"
    assert "output limit" in (result.error or "")
