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
                "model": "local-model",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 4096,
    },
    "ollama": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "ollama",
        "providers": {
            "ollama": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "local-model",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 4096,
    },
    "llamacpp": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "llamacpp",
        "providers": {
            "llamacpp": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:8080/v1",
                "model": "<set the model name your server lists>",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 4096,
    },
    "lmstudio": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "lmstudio",
        "providers": {
            "lmstudio": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:1234/v1",
                "model": "<set the model name your server lists>",
            }
        },
        "prompts_dir": "prompts",
        "context_budget_tokens": 4096,
    },
    "vllm": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "vllm",
        "providers": {
            "vllm": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:8000/v1",
                "model": "<set the model name your server serves>",
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
    "glm": {
        "project": {"name": "my-ract-project"},
        "manager_provider": "glm",
        "providers": {
            "glm": {
                "adapter": "openai",
                "url": "https://integrate.api.nvidia.com/v1",
                "api_key": "${NVIDIA_API_KEY}",
                "model": "z-ai/glm-5.3",
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
    """Return a deep copy of the named preset.

    ``RACT_PRESET_BASE_URL`` (``preset=url[,preset=url]``) replaces the named
    preset's address in the copy, for tests and walks against a fake server
    (B-160d). It changes only what is written to ``ract.yaml``: the hosts a
    key may reach are read from ``PRESETS`` itself (``key_hosts``), so the
    override never pairs a key with a new host; only ``RACT_KEY_HOSTS`` does.
    """
    if name not in PRESETS:
        raise KeyError(
            f"Unknown provider preset: {name}. Choose from {list_presets()}."
        )
    import copy

    preset = copy.deepcopy(PRESETS[name])
    url = preset_url_override(name)
    spec = (preset.get("providers") or {}).get(name)
    if url is not None and isinstance(spec, dict):
        spec["url"] = url
    return preset


class PresetOverrideError(ValueError):
    """``RACT_PRESET_BASE_URL`` is set but not ``preset=url[,preset=url]`` (G-265)."""


def preset_url_overrides() -> dict[str, str]:
    """Every preset address ``RACT_PRESET_BASE_URL`` sets; empty when it is unset.

    LR:: It fails tight, as RACT_NO_NETWORK does: a value that is not
    ``preset=url[,preset=url]`` with an http or https address, that names an
    unknown preset, or that carries credentials raises. Ignoring it sent a
    walk aimed at a fake server to the real provider's address (G-265). The
    value is not echoed, since an address can hold a secret.
    """
    import os
    from urllib.parse import urlsplit

    raw = os.environ.get("RACT_PRESET_BASE_URL", "")
    if not raw.strip():
        return {}
    form = (
        "RACT_PRESET_BASE_URL must be preset=url[,preset=url] with an http or https "
        f"address and a known preset ({', '.join(list_presets())}); "
    )
    found: dict[str, str] = {}
    for pair in raw.split(","):
        name, sep, url = pair.strip().partition("=")
        name, url = name.strip(), url.strip()
        if not sep or not name or not url:
            raise PresetOverrideError(form + "a pair is not preset=url")
        if name not in PRESETS:
            raise PresetOverrideError(form + "it names a preset that does not exist")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise PresetOverrideError(form + "an address is not http(s)://host")
        if parts.username is not None or parts.password is not None:
            raise PresetOverrideError(form + "an address holds a user name or password")
        found[name] = url.rstrip("/")
    return found


def preset_url_override(name: str) -> str | None:
    """The address ``RACT_PRESET_BASE_URL`` gives preset *name*, or None (raises if malformed)."""
    return preset_url_overrides().get(name)


# RACT 0.1.1 - Trust and tooling
