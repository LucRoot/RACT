from __future__ import annotations


"""Helpers for reading chat-completion responses from reasoning models.

LR:: Reasoning models (DeepSeek-R, Qwen thinking variants, and similar) spend an
unpredictable number of tokens thinking before they answer. Servers report that
thinking either in a separate ``reasoning_content`` field or inline in
``content`` between ``<think>`` tags. When the thinking exhausts the output
limit, the visible answer is empty or cut off. RACT used to report that as
"Could not parse JSON plan" and, worse, wrote the empty answer over the target
file. These helpers name the real cause so the person can act on it.
"""

import re
from typing import Any

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# A response cut off while still thinking has an opening tag and no closing tag.
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove inline ``<think>...</think>`` blocks from model output."""
    if not text:
        return ""
    without_blocks = _THINK_BLOCK.sub("", text)
    return _UNCLOSED_THINK.sub("", without_blocks)


def _first_choice(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    choices = raw.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def finish_reason(raw: dict[str, Any] | None) -> str:
    return str(_first_choice(raw).get("finish_reason") or "")


def reasoning_length(raw: dict[str, Any] | None) -> int:
    message = _first_choice(raw).get("message") or {}
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    return len(str(reasoning))


def describe_output_problem(raw: dict[str, Any] | None, *, wanted: str) -> str:
    """Explain why a response did not contain a usable *wanted* (plan, artifact).

    Returns one or two plain sentences naming the most likely cause and the
    setting to change. Never raises on a malformed response.
    """
    choice = _first_choice(raw)
    message = choice.get("message") or {}
    content = str(message.get("content") or "")
    visible = strip_reasoning(content).strip()
    reason = finish_reason(raw)
    thought = reasoning_length(raw) + (len(content) - len(visible))

    if reason == "length":
        spent = (
            f" It had already produced {thought} characters of reasoning."
            if thought
            else ""
        )
        return (
            f"The model hit its output limit (finish_reason=length) before "
            f"finishing the {wanted}.{spent} Remove or raise 'max_tokens' on "
            "this provider in ract.yaml, and check the server's own limit "
            "(llama-server: --n-predict) and context size."
        )
    if not visible and thought:
        return (
            f"The model returned {thought} characters of reasoning and no "
            f"answer, so there was no {wanted} to use. Raise or remove "
            "'max_tokens' on this provider, or use a non-reasoning model for "
            "this role."
        )
    if not visible:
        return f"The model returned an empty response instead of a {wanted}."
    snippet = visible[:200].replace("\n", " ")
    ellipsis = "..." if len(visible) > 200 else ""
    return (
        f"The response did not contain a usable {wanted}. It began: {snippet}{ellipsis}"
    )
