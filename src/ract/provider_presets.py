from __future__ import annotations


"""Provider presets for RACT.

New users should not have to write adapter URLs and env-var names from scratch.
These presets seed ract.yaml with sensible defaults for cheap frontier
providers and local models.

LR:: Each preset is named after a real provider but expressed in RACT's
model-agnostic adapter vocabulary. This keeps the user portable: swapping
providers is a one-line config change, not a code change.
"""

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "local": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 4096,
    },
    "openai": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "openai",
        "providers": {
            "openai": {
                "adapter": "openai",
                "url": "https://api.openai.com/v1",
                "api_key": "${OPENAI_API_KEY}",
                "model": "gpt-4o-mini",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 8192,
    },
    "anthropic": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "anthropic",
        "providers": {
            "anthropic": {
                "adapter": "openai",
                "url": "https://api.anthropic.com/v1",
                "api_key": "${ANTHROPIC_API_KEY}",
                "model": "claude-3-5-sonnet-20241022",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 8192,
    },
    "zai": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "zai",
        "providers": {
            "zai": {
                "adapter": "openai",
                "url": "https://api.z.ai/v1",
                "api_key": "${ZAI_API_KEY}",
                "model": "zai-model",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 8192,
    },
    "moonshot": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "moonshot",
        "providers": {
            "moonshot": {
                "adapter": "openai",
                "url": "https://api.moonshot.cn/v1",
                "api_key": "${MOONSHOT_API_KEY}",
                "model": "moonshot-v1-8k",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 8192,
    },
    "openrouter": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "openrouter",
        "providers": {
            "openrouter": {
                "adapter": "openai",
                "url": "https://openrouter.ai/api/v1",
                "api_key": "${OPENROUTER_API_KEY}",
                "model": "openrouter/auto",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 8192,
    },
}


def list_presets() -> list[str]:
    """Return available preset names."""
    return sorted(PRESETS.keys())


def get_preset(name: str) -> dict[str, Any]:
    """Return a deep copy of the named preset."""
    if name not in PRESETS:
        raise KeyError(
            f"Unknown provider preset: {name}. Choose from {list_presets()}."
        )
    import copy

    return copy.deepcopy(PRESETS[name])


# RACT 0.1.1 - Trust and tooling
