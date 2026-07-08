# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Core Management LM interface for RootAct.

The manager turns a user intent into a structured plan by calling a configured
provider with a system prompt. The plan is Rooted because its validity depends
on the assumption that the provider returned well-formed JSON.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.providers.base import ProviderAdapter
from rootact.rooted import DEFAULT_CONFIDENCE_FLOOR, Rooted
from rootact.temperature_router import TemperatureRouter


@dataclass(frozen=True)
class Step:
    """One step in a RootAct plan.

    A step normally asks a provider to produce an artifact. When *tool_call* is
    set, the step is dispatched to an MCP tool instead of a language model.
    """

    action: str
    provider_hint: str
    expected_artifact: str
    tool_call: dict[str, Any] | None = None


@dataclass(frozen=True)
class Plan:
    """A structured plan produced by the management LM."""

    assumption: str
    confidence: float
    steps: list[Step]


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
        """Ask the management LM to produce a Rooted plan for the intent."""
        messages = [
            {"role": "system", "content": self._full_system_prompt()},
            {"role": "user", "content": f"Intent: {intent}\nEmit the JSON plan now."},
        ]
        temperature = self.temperature_router.for_plan(intent)
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
        content = message.get("content", "")
        parsed = _extract_json(content)
        if parsed is None:
            return Rooted(
                value=None,
                assumption="The management LM returns a JSON plan matching the expected schema.",
                confidence=0.0,
                provenance=["manager.plan"],
                error="Could not parse JSON plan from model response.",
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
            expected_artifact = str(item.get("expected_artifact", ""))
            # Guard against models that emit empty expected_artifact. A plan with
            # no artifact cannot be validated or executed, so we derive a safe
            # default from the action before the Planner sees it.
            if not expected_artifact and not tool_call:
                if "test" in action.lower():
                    expected_artifact = "test_results.txt"
                else:
                    expected_artifact = "output.txt"
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


# RACT 0.1.0 - Initial Public Release
