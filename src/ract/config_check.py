from __future__ import annotations


"""Shared interpretation of ``ract.yaml`` for the runner, doctor, and validator.

LR:: Three places used to answer "which provider plans the work?" three
different ways: ``doctor`` said "not set", the runner silently fell back to a
slot named ``local``, and neither said anything when the keys were indented
under ``project:``. A config that looked right on screen produced
``Provider slot 'local' is not configured``, which names a slot the user never
wrote. This module is the single answer, with messages that name the real
problem.
"""

from typing import Any

# Keys RACT reads from the top level of ract.yaml that people commonly indent
# under ``project:`` by mistake. ``project:`` itself only carries metadata
# (``project.name``).
TOP_LEVEL_ONLY_KEYS: tuple[str, ...] = (
    "manager_provider",
    "providers",
    "prompts_dir",
    "context_budget_tokens",
    "substrate_loop",
    "temperature",
    "skill",
    "retrieval",
    "legacy_whisperer",
    "coverage_gate",
    "mutation_gate",
    "mcp_servers",
)

# Provider-block spellings that look plausible but are not read.
_PROVIDER_KEY_HINTS: dict[str, str] = {
    "type": "use 'adapter:' (openai, local_http, or internal)",
    "max_output_tokens": "use 'max_tokens:'",
    "max_completion_tokens": "use 'max_tokens:'",
}


def find_config_problems(config: dict[str, Any]) -> list[str]:
    """Return plain-language descriptions of misplaced or unread keys.

    An empty list means nothing suspicious was found. This never raises on a
    malformed config; unparseable shapes are simply skipped.
    """
    problems: list[str] = []
    if not isinstance(config, dict):
        return problems

    project = config.get("project")
    if isinstance(project, dict):
        for key in TOP_LEVEL_ONLY_KEYS:
            if key in project and key not in config:
                problems.append(
                    f"'{key}' is indented under 'project:' but RACT reads it from "
                    f"the top level of ract.yaml. Move it to column 1, next to "
                    f"'project:'."
                )

    if "prompt_file" in config:
        prompts_dir = config.get("prompts_dir", "prompts")
        problems.append(
            "'prompt_file' is not a RACT setting and is ignored. The manager "
            f"prompt is read from '{prompts_dir}/manager.txt' next to ract.yaml "
            "(the bundled default is used when that file is absent)."
        )

    providers = config.get("providers")
    if isinstance(providers, dict):
        for name, settings in providers.items():
            if not isinstance(settings, dict):
                continue
            for key, advice in _PROVIDER_KEY_HINTS.items():
                if key in settings and (key != "type" or "adapter" not in settings):
                    problems.append(
                        f"provider '{name}': '{key}' is not read; {advice}."
                    )
    return problems


def resolve_manager_provider(config: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(slot_name, error)`` for the provider that plans the work.

    Resolution order:

    1. ``manager_provider`` if set (it must name a defined provider).
    2. A provider named ``local`` (the historical default, kept for configs
       that rely on it).
    3. The only provider, when exactly one is defined.

    Otherwise the error lists the defined providers and any misplaced keys, so
    the message points at the cause instead of at a slot nobody configured.
    """
    providers = config.get("providers") if isinstance(config, dict) else None
    if not isinstance(providers, dict):
        providers = {}
    defined = ", ".join(providers) if providers else "none"
    hints = [p for p in find_config_problems(config) if "indented under" in p]

    def _with_hints(message: str) -> str:
        if hints:
            return message + " " + " ".join(hints)
        return message

    name = config.get("manager_provider") if isinstance(config, dict) else None
    if name:
        if name not in providers:
            return None, _with_hints(
                f"manager_provider '{name}' is not defined under 'providers' "
                f"(defined: {defined})."
            )
        return str(name), None

    if "local" in providers:
        return "local", None
    if len(providers) == 1:
        return next(iter(providers)), None

    return None, _with_hints(
        "manager_provider is not set, so RACT cannot tell which provider plans "
        f"the work (defined: {defined}). Add a top-level line such as "
        "'manager_provider: <name>'."
    )
