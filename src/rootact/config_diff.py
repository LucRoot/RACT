# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Diff two RACT/rootact.yaml configuration files."""

from pathlib import Path
from typing import Any

import yaml


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
