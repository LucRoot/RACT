"""The wording of a configuration problem: one table for the providers and the exit code (B-194).

LR:: The provider said "api_key in ract.yaml names ${VAR} ..." while the exit
table looked for "api key" with a space, so an unset key variable exited 1
(``internal``) instead of 2 (``config``). The providers, the router and the
config loader build their sentences here, and ``session_turn.exit_code_for``
reads ``PATTERNS``, so a sentence and the pattern that classifies it cannot
drift apart. A test builds every sentence and checks its exit code.
"""

from __future__ import annotations

import re


def missing_key_variable(variable: str) -> str:
    """``api_key: ${VAR}`` names a variable that is not set."""
    return (
        f"api_key in ract.yaml names ${{{variable}}}, and {variable} is not set in "
        "this environment; nothing was sent"
    )


def config_not_found(path: object) -> str:
    return f"Configuration file not found: {path}"


def config_unparsed(exc: object) -> str:
    return f"Failed to parse config: {exc}"


def slot_not_configured(name: str) -> str:
    return f"Provider slot '{name}' is not configured."


def unknown_adapter(name: object) -> str:
    return f"Unknown provider adapter: {name}"


def slot_misconfigured(name: str, exc: object) -> str:
    return f"Provider slot '{name}' is misconfigured: {exc}"


NO_PROVIDERS = "No providers are configured."

# Every sentence above, and the server's own answer to a wrong key, is a
# configuration problem: exit 2, error kind ``config``.
PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Configuration file not found", re.I),
    re.compile(r"Failed to parse config", re.I),
    re.compile(r"\bapi[_ ]key\b", re.I),
    re.compile(r"is not set in this environment", re.I),
    re.compile(r"Provider slot '[^']*' is (?:not configured|misconfigured)", re.I),
    re.compile(r"Unknown provider adapter", re.I),
    re.compile(r"No providers are configured", re.I),
    re.compile(r"HTTP 401|HTTP 403", re.I),
)


def is_config_problem(text: str) -> bool:
    """True when *text* holds a configuration problem from the table above."""
    return any(pattern.search(text) for pattern in PATTERNS)


__all__ = [
    "NO_PROVIDERS",
    "PATTERNS",
    "config_not_found",
    "config_unparsed",
    "is_config_problem",
    "missing_key_variable",
    "slot_misconfigured",
    "slot_not_configured",
    "unknown_adapter",
]
