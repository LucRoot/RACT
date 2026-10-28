"""B-017b: parser amendment 2 (audit findings AUD-005, AUD-006, AUD-008, AUD-016).

Each case is the audit's own probe. AUD-005: two model arguments collapsed onto one
and the last silently won. AUD-006: several reply shapes raised out of ``extract`` and
``accumulate_stream``, whose docstring says they never raise. AUD-008: unclosed markers
made the parser quadratic (80 s for 100 KB). AUD-016: the Harmony role-header form was
not read.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from ract.tool_calls import ToolSignature, accumulate_stream, extract

from tests.test_tool_calls import TOOLS, _native, _resp

WRITE = [ToolSignature("write_file", frozenset({"path", "content"}))]
GREP = [ToolSignature("grep", frozenset({"pattern", "ignore_case"}))]


def _envelope(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return _resp(json.dumps({"tool": tool, "arguments": args}))


# ------------------------------------------------------------------ AUD-005


@pytest.mark.parametrize(
    "args",
    [
        {"target_path": "a.txt", "backup_path": "b.txt", "content": "x"},
        {"file_path": "README.md", "dir_path": "secrets/", "content": "x"},
    ],
)
def test_two_keys_that_repair_to_one_argument_are_refused(args: dict) -> None:
    result = extract(_envelope("write_file", args), WRITE)
    assert result.unwrap().outcome == "invalid_arguments"
    assert "would repair to 'path'" in (result.error or "")


def test_a_key_that_repairs_onto_an_argument_given_by_name_is_refused() -> None:
    result = extract(
        _envelope(
            "write_file", {"path": "a.txt", "file_path": "b.txt", "content": "x"}
        ),
        WRITE,
    )
    assert result.unwrap().outcome == "invalid_arguments"


@pytest.mark.parametrize("key", ["_", "e", "ic"])
def test_a_key_shorter_than_three_characters_is_not_repaired(key: str) -> None:
    result = extract(_envelope("grep", {"pattern": "x", key: True}), GREP)
    assert result.unwrap().outcome == "invalid_arguments"


def test_a_unique_long_near_miss_is_still_repaired() -> None:
    result = extract(
        _envelope("write_file", {"file_path": "a.txt", "content": "x"}), WRITE
    )
    call = result.unwrap().calls[0]
    assert call.arguments == {"path": "a.txt", "content": "x"}


# ------------------------------------------------------------------ AUD-006


def _never_raises(response: Any) -> Any:
    try:
        return extract(response, TOOLS)
    except Exception as exc:  # the test reports what escaped
        pytest.fail(f"extract raised {type(exc).__name__}: {exc}")


def test_arguments_with_a_5000_digit_integer_are_a_named_failure() -> None:
    raw = '{"file_path": ' + "1" * 5000 + "}"
    result = _never_raises(_resp(tool_calls=[_native("read_file", raw)]))
    assert result.unwrap().outcome != "tool_calls"


@pytest.mark.parametrize("function", ["read_file", None, 42, ["read_file"]])
def test_a_native_function_that_is_not_an_object_is_a_named_failure(
    function: Any,
) -> None:
    result = _never_raises(
        _resp(tool_calls=[{"id": "c1", "type": "function", "function": function}])
    )
    assert result.unwrap().outcome == "markup_unparsed"


def test_list_valued_content_is_joined_not_printed_as_a_python_list() -> None:
    content = [
        {"type": "text", "text": "The answer "},
        {"type": "text", "text": "is 4."},
    ]
    result = _never_raises({"choices": [{"message": {"content": content}}]})
    extraction = result.unwrap()
    assert extraction.outcome == "final"
    assert extraction.final_text == "The answer is 4."


@pytest.mark.parametrize(
    "chunks",
    [
        pytest.param(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": None, "function": {"name": "grep"}}
                                ]
                            }
                        }
                    ]
                }
            ],
            id="index-null",
        ),
        pytest.param(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "grep",
                                            "arguments": {"pattern": "x"},
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
            id="arguments-object",
        ),
        pytest.param([{"choices": [None]}], id="choice-null"),
        pytest.param([{"choices": [{"delta": "text"}]}], id="delta-string"),
        pytest.param(
            [{"choices": [{"delta": {"tool_calls": ["x", None]}}]}],
            id="call-not-object",
        ),
        pytest.param(
            [
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "function": "grep"}]}}
                    ]
                }
            ],
            id="function-string",
        ),
        pytest.param([None, "chunk"], id="chunk-not-object"),
        pytest.param(
            [{"choices": [{"delta": {"content": ["a", "b"]}}]}], id="content-list"
        ),
    ],
)
def test_accumulate_stream_never_raises(chunks: list[Any]) -> None:
    try:
        response = accumulate_stream(chunks)
    except Exception as exc:
        pytest.fail(f"accumulate_stream raised {type(exc).__name__}: {exc}")
    _never_raises(response)


def test_streamed_arguments_sent_as_an_object_survive() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {
                                    "name": "grep",
                                    "arguments": {"pattern": "x"},
                                },
                            }
                        ]
                    }
                }
            ]
        }
    ]
    result = extract(accumulate_stream(chunks), TOOLS)
    assert result.unwrap().calls[0].arguments == {"pattern": "x"}


# ------------------------------------------------------------------ AUD-008


@pytest.mark.parametrize(
    "unit", ["<tool_call> ", "to=functions.a ", "<|start|>assistant to=functions.a "]
)
def test_100_kb_of_unclosed_markers_is_parsed_in_linear_time(unit: str) -> None:
    content = unit * (100_000 // len(unit))
    started = time.perf_counter()
    result = extract(_resp(content), TOOLS)
    elapsed = time.perf_counter() - started
    assert result.unwrap().outcome != "tool_calls"
    # 80 s before (AUD-008); a linear scan of 100 KB takes milliseconds.
    assert elapsed < 2.0, f"{elapsed:.1f} s for 100 KB of {unit!r}"


def test_a_closed_tag_after_many_unclosed_ones_is_still_read() -> None:
    content = "<tool_call> " * 500 + (
        '<tool_call>{"name": "grep", "arguments": {"pattern": "x"}}</tool_call>'
    )
    result = extract(_resp(content), TOOLS)
    assert result.unwrap().outcome in {"tool_calls", "markup_unparsed"}


# ------------------------------------------------------------------ AUD-016


def test_the_harmony_role_header_form_is_read() -> None:
    content = (
        "<|start|>assistant to=functions.read_file<|channel|>commentary json"
        '<|message|>{"file_path": "a.py"}<|call|>'
    )
    extraction = extract(_resp(content), TOOLS).unwrap()
    assert extraction.outcome == "tool_calls"
    assert extraction.rung == "harmony"
    assert extraction.calls[0].name == "read_file"
    assert extraction.calls[0].arguments == {"file_path": "a.py"}


def test_the_harmony_channel_form_still_reads() -> None:
    content = (
        "<|start|>assistant<|channel|>commentary to=functions.grep <|constrain|>json"
        '<|message|>{"pattern": "x"}<|call|>'
    )
    extraction = extract(_resp(content), TOOLS).unwrap()
    assert extraction.rung == "harmony"
    assert extraction.calls[0].arguments == {"pattern": "x"}
