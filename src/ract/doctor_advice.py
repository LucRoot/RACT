"""Advice lines for ``ract doctor`` (B-059).

Pure functions: the caller gathers the facts (memory, the probe results and
whether each key variable is set and paired with its host), and this module
returns plain lines. A key value never reaches this module. Only the presence
of the variable and the host pairing are passed in.

The memory numbers are estimates: parameters in billions times 0.6 GB, plus
2 GB, for 4-bit weights. The size is read from the model id only.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any

from ract.providers.capability_probe import ProviderProbe

GB_PER_BILLION_PARAMETERS = 0.6
OVERHEAD_GB = 2.0
_SIZE_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[bB](?![A-Za-z])")


@dataclass(frozen=True)
class Memory:
    """Total and free memory in GB. None means the reading is not available."""

    total_gb: float | None
    free_gb: float | None


@dataclass(frozen=True)
class KeyFacts:
    """The state of one ``${VAR}`` key: presence and the host pairing only."""

    provider: str
    variable: str
    is_set: bool
    host: str
    paired: bool


def model_size_billions(model: object) -> float | None:
    """The size from a model id such as ``qwen-7b-instruct``, or None."""
    if not isinstance(model, str):
        return None
    match = _SIZE_RE.search(model)
    return float(match.group(1)) if match else None


def _budget(config: dict[str, Any]) -> int | None:
    value = config.get("context_budget_tokens")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def advise(
    config: dict[str, Any],
    memory: Memory | None,
    probes: list[ProviderProbe],
    keys: list[KeyFacts],
) -> list[str]:
    """Plain advice lines, at most one per problem. Empty when nothing is wrong."""
    lines: list[str] = []
    providers = config.get("providers") if isinstance(config, dict) else None
    providers = providers if isinstance(providers, dict) else {}

    if (
        memory is not None
        and memory.total_gb is not None
        and memory.free_gb is not None
    ):
        for settings in providers.values():
            model = settings.get("model") if isinstance(settings, dict) else None
            size = model_size_billions(model)
            if size is None:
                continue
            need = size * GB_PER_BILLION_PARAMETERS + OVERHEAD_GB
            if need > memory.free_gb:
                lines.append(
                    f"model '{model}' is about {size:g} billion parameters; at 4-bit "
                    f"that needs roughly {need:.0f} GB; this machine has "
                    f"{memory.total_gb:.0f} GB total and {memory.free_gb:.0f} GB free "
                    "right now. These are estimates. Load a smaller model, or free "
                    "memory before loading it"
                )

    budget = _budget(config)
    for probe in probes:
        for finding in probe.findings:
            if finding.label == "context window" and finding.number is not None:
                if budget is not None and budget > finding.number:
                    suggested = (finding.number // 1000) * 1000 or finding.number
                    lines.append(
                        f"ract.yaml asks for {budget:,} tokens of context; the server "
                        f"reports {finding.number:,}. Set context_budget_tokens to "
                        f"{suggested:,} or less"
                    )

    for probe in probes:
        for finding in probe.findings:
            if finding.label == "tool calling" and finding.status == "not supported":
                lines.append(
                    f"provider '{probe.name}' answers but cannot call tools. RACT will "
                    "use its text fallback, which works for small steps."
                )
                break

    by_name = {probe.name: probe for probe in probes}
    for key in keys:
        if not key.is_set:
            lines.append(
                f"provider '{key.provider}': set the environment variable "
                f"{key.variable}. Its value is never shown."
            )
        elif not key.paired:
            lines.append(
                f"provider '{key.provider}': the key in {key.variable} is not paired "
                f"with {key.host}, so RACT does not send it there. Pair them in "
                "RACT_KEY_HOSTS (VAR=host) or point url at the host the key belongs to."
            )
        else:
            probe = by_name.get(key.provider)
            chat = (
                next((f for f in probe.findings if f.label == "chat"), None)
                if probe
                else None
            )
            if chat is None:
                lines.append(
                    f"provider '{key.provider}': the key and host pair. Run ract doctor "
                    "--check-providers to test the connection."
                )
            elif chat.status == "works":
                lines.append(
                    f"provider '{key.provider}': the key and host pair, and one tiny "
                    "request worked."
                )
            else:
                lines.append(
                    f"provider '{key.provider}': the key and host pair, but the tiny "
                    f"request failed: {chat.detail}"
                )
    return lines


def render(lines: list[str], width: int) -> list[str]:
    """Wrap each advice line to *width* columns, keeping every word."""
    rows: list[str] = []
    for line in lines:
        rows += textwrap.wrap(
            line,
            width=width,
            subsequent_indent="  ",
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
    return rows
