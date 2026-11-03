from __future__ import annotations


"""Diff two RACT/ract.yaml configuration files."""

from pathlib import Path
from typing import Any

import yaml

from ract import redaction

_CREDENTIAL_WORDS = (
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "auth",
    "credential",
)


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Return a flat dict of dotted keys -> string values."""
    out: dict[str, str] = {}
    for key, value in d.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, full))
        else:
            out[full] = str(value)
    return out


def diff_configs(path_a: Path | str, path_b: Path | str) -> dict[str, Any]:
    """Compare two YAML config files and return added/removed/changed/unchanged."""
    a = yaml.safe_load(Path(path_a).read_text(encoding="utf-8")) or {}
    b = yaml.safe_load(Path(path_b).read_text(encoding="utf-8")) or {}
    flat_a = _flatten(a)
    flat_b = _flatten(b)

    keys_a = set(flat_a)
    keys_b = set(flat_b)

    return {
        "added": {k: flat_b[k] for k in sorted(keys_b - keys_a)},
        "removed": {k: flat_a[k] for k in sorted(keys_a - keys_b)},
        "changed": {
            k: {"before": flat_a[k], "after": flat_b[k]}
            for k in sorted(keys_a & keys_b)
            if flat_a[k] != flat_b[k]
        },
        "unchanged": sorted(k for k in keys_a & keys_b if flat_a[k] == flat_b[k]),
    }


def register_config_credentials(config: Any) -> None:
    """Register the credential-named string values of a parsed config as known.

    Mirrors ``mcp_adapter._register_credentials`` (B-202), recursing into
    nested mappings and lists. ``ract config diff`` prints flattened values,
    and a literal ``api_key`` in ract.yaml must be masked there the way
    setup's diff masks it; a value with no telltale shape is caught only by
    registration. ``${VAR}`` references are left readable, as in the wizard's
    diff.
    """
    if isinstance(config, dict):
        for name, value in config.items():
            if isinstance(value, dict | list):
                register_config_credentials(value)
            elif (
                isinstance(value, str)
                and not value.startswith("$")
                and any(word in str(name).lower() for word in _CREDENTIAL_WORDS)
            ):
                redaction.register_known(value)
                if " " in value:  # "Bearer <token>": the token alone too
                    redaction.register_known(value.split(" ", 1)[1])
    elif isinstance(config, list):
        for item in config:
            register_config_credentials(item)
