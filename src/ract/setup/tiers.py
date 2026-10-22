"""Which local model fits the memory the user gives it (B-015).

LR:: A user with a local stack did not know which model fit their machine.
The guidance lives in ``model_tiers.yaml`` so it can change without a code
release; this module only reads it and picks. Unknown memory picks the
smallest entry and says why, instead of guessing high.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

# Share of available memory offered by default for the model.
DEFAULT_SHARE = 0.6


@dataclass(frozen=True)
class Tier:
    id: str
    display: str
    weights_gb: float
    needs_gb: float
    note: str
    ollama: str | None
    llama_cpp_hf: str | None


@dataclass(frozen=True)
class Recommendation:
    tier: Tier
    reason: str
    reviewed: str


def load() -> tuple[str, list[Tier]]:
    """The reviewed date and the tiers, smallest first."""
    text = (resources.files("ract.setup") / "model_tiers.yaml").read_text(
        encoding="utf-8"
    )
    data: dict[str, Any] = yaml.safe_load(text)
    tiers = [Tier(**entry) for entry in data["tiers"]]
    return str(data["reviewed"]), sorted(tiers, key=lambda t: t.needs_gb)


def default_dedicated_gb(available_gb: float | None) -> float | None:
    return None if available_gb is None else round(available_gb * DEFAULT_SHARE, 1)


def recommend(dedicated_gb: float | None) -> Recommendation:
    """The largest tier that fits ``dedicated_gb``; the smallest when unknown."""
    reviewed, tiers = load()
    if dedicated_gb is None:
        return Recommendation(
            tiers[0],
            "the memory size could not be read, so the smallest model is suggested",
            reviewed,
        )
    fitting = [t for t in tiers if t.needs_gb <= dedicated_gb]
    if not fitting:
        return Recommendation(
            tiers[0],
            f"{dedicated_gb:g} GB is less than the smallest model needs "
            f"({tiers[0].needs_gb:g} GB); it may run slowly or not at all, "
            "and a cloud provider may suit this machine better",
            reviewed,
        )
    best = fitting[-1]
    return Recommendation(
        best,
        f"it needs about {best.needs_gb:g} GB of the {dedicated_gb:g} GB you dedicate",
        reviewed,
    )


def install_steps(tier: Tier) -> list[str]:
    """How to get the model running. Setup prints these; it never downloads."""
    lines = []
    if tier.ollama:
        lines.append(
            f"Ollama:     ollama pull {tier.ollama}   (then Ollama serves it on port 11434)"
        )
    if tier.llama_cpp_hf:
        lines.append(f"llama.cpp:  llama-server -hf {tier.llama_cpp_hf} --port 8080")
    else:
        lines.append(f"llama.cpp:  search Hugging Face for a GGUF of {tier.display}")
    lines.append(
        f"LM Studio:  search for {tier.display} in the app, load it, start the server"
    )
    return lines


__all__ = [
    "DEFAULT_SHARE",
    "Recommendation",
    "Tier",
    "default_dedicated_gb",
    "install_steps",
    "load",
    "recommend",
]
