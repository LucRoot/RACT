"""Reasoning-model handling: diagnose truncated answers, never write empty files."""

from __future__ import annotations

from typing import Any

from ract.executor import Executor
from ract.manager import Manager, Plan, Step
from ract.model_output import (
    describe_output_problem,
    finish_reason,
    reasoning_length,
    strip_reasoning,
)
from ract.rooted import Rooted


def _response(
    content: str = "",
    *,
    reasoning: str = "",
    finish: str = "stop",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message, "finish_reason": finish}]}


class _Adapter:
    name = "scripted"

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.calls = 0

    def capabilities(self) -> set[str]:
        return {"chat"}

    def input_cost_per_1k(self) -> None:
        return None

    def output_cost_per_1k(self) -> None:
        return None

    def complete(self, messages, *, model=None, max_tokens=512, temperature=0.3):
        self.calls += 1
        return Rooted(
            value=self.raw,
            assumption="scripted",
            confidence=1.0,
            provenance=["test"],
        )


class _Router:
    def __init__(self, adapter: _Adapter) -> None:
        self.adapter = adapter

    def select_for_hint(self, hint: str) -> Rooted[Any]:
        return Rooted(
            value=self.adapter, assumption="x", confidence=1.0, provenance=["t"]
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted[Any]]:
        return []


# --- model_output -------------------------------------------------------------


def test_strip_reasoning_removes_closed_block():
    assert strip_reasoning('<think>maybe {"a": 1}</think>{"b": 2}') == '{"b": 2}'


def test_strip_reasoning_removes_unclosed_block():
    assert strip_reasoning("<think>still thinking about {") == ""


def test_strip_reasoning_leaves_plain_text_alone():
    assert strip_reasoning("def f():\n    pass\n") == "def f():\n    pass\n"


def test_strip_reasoning_handles_empty_and_none():
    assert strip_reasoning("") == ""
    assert strip_reasoning(None) == ""  # type: ignore[arg-type]


def test_finish_reason_and_reasoning_length():
    raw = _response("", reasoning="x" * 40, finish="length")
    assert finish_reason(raw) == "length"
    assert reasoning_length(raw) == 40


def test_truncation_is_named_with_the_setting_to_change():
    text = describe_output_problem(
        _response("", reasoning="x" * 2036, finish="length"), wanted="JSON plan"
    )
    assert "finish_reason=length" in text
    assert "2036" in text
    assert "max_tokens" in text


def test_reasoning_only_response_is_named():
    text = describe_output_problem(
        _response("", reasoning="thinking " * 50), wanted="artifact"
    )
    assert "reasoning and no answer" in text


def test_empty_response_without_reasoning_is_named():
    text = describe_output_problem(_response(""), wanted="artifact")
    assert "empty response" in text


def test_unparseable_text_is_quoted():
    text = describe_output_problem(
        _response("Sure! Here is the plan: first, we..."), wanted="JSON plan"
    )
    assert "Sure! Here is the plan" in text


def test_describe_never_raises_on_garbage():
    assert describe_output_problem(None, wanted="x")
    assert describe_output_problem({"choices": "nope"}, wanted="x")  # type: ignore[arg-type]


# --- manager ------------------------------------------------------------------

_PLAN_JSON = (
    '{"assumption": "a", "confidence": 0.9, "steps": ['
    '{"action": "edit f.py", "provider_hint": "local", "expected_artifact": "f.py"}]}'
)


def test_manager_error_explains_a_truncated_plan():
    adapter = _Adapter(_response("", reasoning="r" * 500, finish="length"))
    result = Manager(adapter, "prompt").plan("do it")
    assert not result.is_ok()
    assert result.error.startswith("Could not parse JSON plan from model response.")
    assert "finish_reason=length" in result.error


def test_manager_ignores_json_inside_inline_think_block():
    content = f'<think>draft: {{"steps": []}}</think>{_PLAN_JSON}'
    result = Manager(_Adapter(_response(content)), "prompt").plan("do it")
    assert result.is_ok()
    assert result.unwrap().steps[0].action == "edit f.py"


def test_manager_still_parses_a_normal_plan():
    result = Manager(_Adapter(_response(_PLAN_JSON)), "prompt").plan("do it")
    assert result.is_ok()


def test_manager_handles_null_content():
    raw = {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
    result = Manager(_Adapter(raw), "prompt").plan("do it")
    assert not result.is_ok()
    assert "empty response" in result.error


# --- executor: empty output must not clobber the target -----------------------


def _plan() -> Plan:
    return Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="edit hello.py", provider_hint="x", expected_artifact="hello.py"
            )
        ],
    )


def test_empty_answer_does_not_overwrite_existing_file(tmp_path):
    """Regression: the user's hello.py was truncated to zero bytes by an empty step."""
    target = tmp_path / "hello.py"
    original = "def greet(name):\n    return name\n"
    target.write_text(original, encoding="utf-8")
    adapter = _Adapter(_response("", reasoning="r" * 300, finish="length"))
    executor = Executor(_Router(adapter), project_dir=tmp_path)

    result = executor.execute(intent="i", plan=_plan())

    assert not result.is_ok()
    assert "nothing was written" in result.error
    assert "finish_reason=length" in result.error
    assert result.hint == "empty_output"
    assert target.read_text(encoding="utf-8") == original


def test_whitespace_only_answer_is_rejected(tmp_path):
    adapter = _Adapter(_response("  \n\n "))
    result = Executor(_Router(adapter), project_dir=tmp_path).execute(
        intent="i", plan=_plan()
    )
    assert not result.is_ok()
    assert not (tmp_path / "hello.py").exists()


def test_think_only_answer_is_rejected(tmp_path):
    adapter = _Adapter(_response("<think>I should write a docstring</think>"))
    result = Executor(_Router(adapter), project_dir=tmp_path).execute(
        intent="i", plan=_plan()
    )
    assert not result.is_ok()
    assert not (tmp_path / "hello.py").exists()


def test_inline_think_block_is_not_written_into_the_file(tmp_path):
    adapter = _Adapter(_response("<think>plan</think>def greet():\n    pass\n"))
    result = Executor(_Router(adapter), project_dir=tmp_path).execute(
        intent="i", plan=_plan()
    )
    assert result.is_ok()
    written = (tmp_path / "hello.py").read_text(encoding="utf-8")
    assert "<think>" not in written
    assert "def greet()" in written


# --- executor: the step sees the file it replaces -----------------------------


class _RecordingAdapter(_Adapter):
    def complete(self, messages, **kwargs):
        self.last_user = messages[-1]["content"]
        return super().complete(messages, **kwargs)


def _run_step(tmp_path, *, artifact="hello.py", context=""):
    adapter = _RecordingAdapter(_response("def greet():\n    pass\n"))
    executor = Executor(_Router(adapter), project_dir=tmp_path)
    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="add a docstring", provider_hint="x", expected_artifact=artifact
            )
        ],
    )
    executor.execute(intent="i", plan=plan, context=context)
    return adapter.last_user


def test_existing_target_file_is_shown_to_the_step(tmp_path):
    (tmp_path / "hello.py").write_text(
        "def greet(name):\n    return name\n", encoding="utf-8"
    )
    prompt = _run_step(tmp_path)
    assert "--- hello.py ---" in prompt
    assert "def greet(name):" in prompt
    assert "replaces it" in prompt and "complete updated file" in prompt


def test_target_file_is_not_repeated_when_context_already_has_it(tmp_path):
    (tmp_path / "hello.py").write_text(
        "def greet(name):\n    return name\n", encoding="utf-8"
    )
    context = "--- hello.py ---\ndef greet(name):\n    return name\n"
    prompt = _run_step(tmp_path, context=context)
    assert prompt.count("def greet(name):") == 1
    assert "replaces it" in prompt


def test_new_file_gets_no_replacement_notice(tmp_path):
    prompt = _run_step(tmp_path, artifact="new_module.py")
    assert "replaces it" not in prompt and "Current contents" not in prompt


def test_target_outside_the_project_is_never_read(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    prompt = _run_step(project, artifact="../outside.txt")
    assert "SECRET" not in prompt


def test_oversized_target_is_left_to_context_curation(tmp_path):
    (tmp_path / "big.py").write_text("x = 1\n" * 40000, encoding="utf-8")
    prompt = _run_step(tmp_path, artifact="big.py")
    assert "Current contents" not in prompt
    assert "replaces it" in prompt
