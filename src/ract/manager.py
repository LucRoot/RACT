from __future__ import annotations


"""Core Management LM interface for RACT.

The manager turns a user intent into a structured plan by calling a configured
provider with a system prompt. The plan is Rooted because its validity depends
on the assumption that the provider returned well-formed JSON.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract import egress_ledger
from ract.model_output import describe_output_problem, strip_reasoning
from ract.providers.base import ProviderAdapter
from ract.rooted import DEFAULT_CONFIDENCE_FLOOR, Rooted
from ract.temperature_router import TemperatureRouter


def _artifact_name(raw: object) -> str:
    """The planned file name, without line endings (package 5, H2).

    A trailing space is kept on purpose: it is a name Windows drops, and the path check
    refuses it with a sentence rather than writing a different file. Leading spaces are
    removed as the old strip did (a kept one wrote into a new folder whose name starts
    with a space), and a name of only spaces is no file, as before (BUILDER review).
    """
    if raw is None:
        return ""
    text = str(raw).strip(chr(13) + chr(10))
    if not text.strip():
        return ""
    return text.lstrip()


@dataclass(frozen=True)
class Step:
    """One step in a RACT plan.

    A step normally asks a provider to produce an artifact. When *tool_call* is
    set, the step is dispatched to an MCP tool instead of a language model.
    """

    action: str
    provider_hint: str
    expected_artifact: str
    tool_call: dict[str, Any] | None = None
    # B-137: the request run as one step through the step agent loop, because
    # the model answered the planning request with tool calls or prose.
    # ``opening`` is that reply, given to the loop as its first turn.
    agent: bool = False
    opening: dict[str, Any] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Plan:
    """A structured plan produced by the management LM."""

    assumption: str
    confidence: float
    steps: list[Step]
    # B-137: False when the model went straight to tools (or answered in prose
    # twice) and the request became the one step.
    planned: bool = True


def _has_tool_calls(raw: dict[str, Any] | None) -> bool:
    """True when a chat-completion reply carries native tool calls."""
    if not isinstance(raw, dict):
        return False
    choices = raw.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    return bool(message.get("tool_calls"))


# B-086: the second request after a reply with no plan steps, and the
# sentence the user sees when the second reply has none either.
NO_STEPS_HINT = "no_plan_steps"
_REPLY_ECHO_CHARS = 4000
PLAN_SHAPE_REQUEST = (
    "That reply has no plan steps. Reply with only one JSON object of this shape, "
    "and nothing else: "
    '{"assumption": "<what you assume>", "confidence": <0 to 1>, "steps": '
    '[{"action": "<what this step does>", "provider_hint": "<a provider name>", '
    '"expected_artifact": "<the file it writes, or empty for an answer>"}]}'
)
NO_PLAN_SENTENCE = (
    "The model did not return a plan, also when asked again; try a larger model "
    "or /model."
)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a model response.

    Uses json.JSONDecoder.raw_decode from each '{' position so trailing prose
    after the object does not break parsing. Falls back to a balanced-brace scan
    if the decoder cannot find a valid object.
    """
    decoder = json.JSONDecoder()
    start = 0
    while True:
        brace = text.find("{", start)
        if brace == -1:
            break
        try:
            obj, _idx = decoder.raw_decode(text, brace)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = brace + 1

    # LR:: Balanced-brace fallback for models that emit stray braces inside prose.
    depth = 0
    brace_start: int | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                brace_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and brace_start is not None:
                try:
                    return json.loads(text[brace_start : i + 1])
                except json.JSONDecodeError:
                    brace_start = None
    return None


class Manager:
    """Thin wrapper around the provider that produces structured plans."""

    def __init__(
        self,
        provider: ProviderAdapter,
        system_prompt: str,
        tools_description: str | None = None,
        temperature_router: TemperatureRouter | None = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools_description = tools_description or ""
        self.temperature_router = temperature_router or TemperatureRouter()

    def _full_system_prompt(self) -> str:
        """Return the system prompt with optional MCP tools appendix."""
        if self.tools_description:
            return f"{self.system_prompt}\n\n{self.tools_description}"
        return (
            f"{self.system_prompt}\n\n"
            "No MCP tools are configured for this project. Do not emit tool_call "
            "steps. Use normal provider steps with provider_hint values like 'local', "
            "'openai', or 'code'."
        )

    @classmethod
    def from_path(
        cls,
        provider: ProviderAdapter,
        prompt_path: Path,
        tools_description: str | None = None,
        temperature_router: TemperatureRouter | None = None,
    ) -> Rooted["Manager"]:
        """Build a Manager from a prompt file, returning Rooted failure if missing."""
        try:
            system_prompt = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Rooted(
                value=None,
                assumption=f"Manager prompt file exists: {prompt_path}",
                confidence=0.0,
                provenance=["manager.from_path"],
                error=f"Prompt file not found: {prompt_path}",
            )
        except OSError as exc:
            return Rooted(
                value=None,
                assumption=f"Manager prompt file is readable: {prompt_path}",
                confidence=0.0,
                provenance=["manager.from_path"],
                error=f"Failed to read prompt file: {exc}",
            )
        return Rooted(
            value=cls(
                provider,
                system_prompt,
                tools_description=tools_description,
                temperature_router=temperature_router,
            ),
            assumption="Manager prompt loaded successfully.",
            confidence=1.0,
            provenance=["manager.from_path"],
        )

    def plan(self, intent: str) -> Rooted[Plan]:
        """Ask the management LM to produce a Rooted plan for the intent.

        LR:: A weak model often answers the intent in prose, and the user saw
        "Plan contains no steps." (B-086, J9). A reply with no plan steps gets
        one more request that quotes the JSON shape; a second reply with none
        ends with one plain sentence. Prose never runs as a plan.
        """
        messages = [
            {"role": "system", "content": self._full_system_prompt()},
            {"role": "user", "content": f"Intent: {intent}\nEmit the JSON plan now."},
        ]
        first = self._plan_once(intent, messages)
        if not first.is_ok() and _has_tool_calls(self._last_raw):
            # B-137: the model went straight to tools; nothing of its reply is lost.
            return self._agent_plan(intent, self._last_raw)
        if first.is_ok() or first.hint != NO_STEPS_HINT:
            return first
        reply = self._last_reply[:_REPLY_ECHO_CHARS]
        retry = [
            *messages,
            {"role": "assistant", "content": reply},
            {"role": "user", "content": PLAN_SHAPE_REQUEST},
        ]
        second = self._plan_once(intent, retry)
        if not second.is_ok() and _has_tool_calls(self._last_raw):
            return self._agent_plan(intent, self._last_raw)
        if second.is_ok() or second.hint != NO_STEPS_HINT:
            return second
        # B-137: prose twice; the request becomes the one step, and its first
        # turn is the prose (an answer when the step agent loop is off).
        return self._agent_plan(intent, self._last_raw or None)

    def _agent_plan(self, intent: str, opening: dict[str, Any] | None) -> Rooted[Plan]:
        """The request as the one step, through the step agent loop (B-137)."""
        return Rooted(
            value=Plan(
                assumption=(
                    "The model went straight to tools (or answered in prose); the "
                    "request is the one step."
                ),
                # The one step is the request itself, nothing guessed; the
                # Planner passes this on, and under 0.7 it is not ok.
                confidence=1.0,
                steps=[
                    Step(
                        action=intent,
                        provider_hint="",
                        expected_artifact="",
                        agent=True,
                        opening=opening,
                    )
                ],
                planned=False,
            ),
            assumption="planned: no (the model went straight to tools)",
            # Turning the request into its one step is certain, as for an asked
            # question. Below the floor (0.7) the harness read it as "Planning
            # failed: None" (the J4 flip, B-137).
            confidence=1.0,
            provenance=["manager.plan", "agent_plan"],
        )

    def _plan_once(self, intent: str, messages: list[dict[str, str]]) -> Rooted[Plan]:
        """One planning request; the reply's text is kept in ``_last_reply`` for a retry."""
        self._last_reply = ""
        self._last_raw: dict[str, Any] = {}
        temperature = self.temperature_router.for_plan(intent)
        with egress_ledger.purpose("plan", role="manager"):
            response_rooted = self.provider.complete(
                messages, max_tokens=1024, temperature=temperature
            )
        if not response_rooted.is_ok():
            return Rooted(
                value=None,
                assumption="The management LM provider is healthy and returns valid JSON.",
                confidence=0.0,
                provenance=["manager.plan"],
                error=f"Provider call failed: {response_rooted.error}",
            )

        raw = response_rooted.unwrap()
        message = raw.get("choices", [{}])[0].get("message", {})
        content = message.get("content") or ""
        self._last_reply = content
        self._last_raw = raw
        # Inline <think> blocks can contain JSON-looking fragments; parse only
        # what the model presented as its answer.
        parsed = _extract_json(strip_reasoning(content))
        if parsed is None:
            # Prose that holds no plan: the caller asks once more (B-086). An
            # empty reply or one cut off at the limit keeps its own diagnosis.
            finish = str(raw.get("choices", [{}])[0].get("finish_reason") or "")
            prose = bool(strip_reasoning(content).strip()) and finish not in {
                "length",
                "max_tokens",
            }
            return Rooted(
                value=None,
                assumption="The management LM returns a JSON plan matching the expected schema.",
                confidence=0.0,
                provenance=["manager.plan"],
                error=(
                    "Could not parse JSON plan from model response. "
                    + describe_output_problem(raw, wanted="JSON plan")
                ),
                hint=NO_STEPS_HINT if prose else None,
            )

        steps = []
        mcp_available = bool(self.tools_description)
        for item in parsed.get("steps", []):
            tool_call = item.get("tool_call")
            if tool_call is not None and not isinstance(tool_call, dict):
                tool_call = None
            if tool_call is not None and not mcp_available:
                return Rooted(
                    value=None,
                    assumption="The plan respects the absence of configured MCP tools.",
                    confidence=0.0,
                    provenance=["manager.plan"],
                    error="Plan contains a tool_call step, but no MCP tools are configured.",
                    hint="mcp",
                )
            action = str(item.get("action", ""))
            # LR:: An empty expected_artifact is an answer step (B-042): the
            # reply is shown, nothing is written. It used to become output.txt
            # or test_results.txt, so a question wrote a file into the repo.
            expected_artifact = _artifact_name(item.get("expected_artifact"))
            steps.append(
                Step(
                    action=action,
                    provider_hint=str(item.get("provider_hint", "")),
                    expected_artifact=expected_artifact,
                    tool_call=tool_call,
                )
            )

        confidence = float(parsed.get("confidence", 1.0))
        if confidence < DEFAULT_CONFIDENCE_FLOOR:
            return Rooted(
                value=None,
                assumption=parsed.get("assumption", ""),
                confidence=confidence,
                provenance=["manager.plan"],
                error=f"Plan confidence {confidence} is below the floor.",
            )
        if not steps:
            # A plan with no steps: the caller asks once more too (B-086).
            return Rooted(
                value=None,
                assumption="The management LM returns a plan with at least one step.",
                confidence=0.0,
                provenance=["manager.plan"],
                error="Plan contains no steps.",
                hint=NO_STEPS_HINT,
            )

        return Rooted(
            value=Plan(
                assumption=parsed.get("assumption", ""),
                confidence=confidence,
                steps=steps,
            ),
            assumption=parsed.get("assumption", ""),
            confidence=confidence,
            provenance=["manager.plan"],
        )


# RACT 0.1.1 - Trust and tooling
