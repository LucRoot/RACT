"""Roles as data (ADR-0049 D1, D2): load and validate one role file at a time.

A role is one YAML file in this package. The loader reads only built-in roles here. A repository
role (ADR-0049 D11) is a later card (B-176) and is not read by this module.

The rules, in the order they are checked:
1. The file is at most MAX_BYTES bytes. The size is checked before anything is parsed.
2. The file is one YAML mapping, parsed with safe_load only.
3. Every key is one of the closed set in D2. An unknown key is refused and named.
4. Every D2 key is present. A missing key is refused and named.
5. model_class is one of the four allowed values.
6. Every tool is known, and its tier is no higher than the ratified tier (T0 today).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

MAX_BYTES = 16 * 1024

REQUIRED_KEYS = frozenset(
    {
        "purpose",
        "input",
        "output",
        "tools",
        "budget",
        "model_class",
        "prompt",
        "checklist",
        "stop",
        "failure_modes",
    }
)
MODEL_CLASSES = frozenset({"weak", "strong", "either", "none"})
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# Tool tiers (ADR-0048). Only T0 is ratified today; a role may not list a tool above it.
RATIFIED_TIER = 0
TOOL_TIERS: dict[str, int] = {
    "read_file": 0,
    "list_dir": 0,
    "glob": 0,
    "grep": 0,
    "edit_file": 1,
    "write_file": 1,
    "apply_patch": 1,
    "run_tests": 3,
    "lint": 3,
    "typecheck": 3,
}


class RoleError(ValueError):
    """A role file was refused. The message names the file and the reason."""


@dataclass(frozen=True)
class Role:
    name: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_role(text: str, *, name: str) -> Role:
    """Validate one role file's text and return it as a Role. Raises RoleError."""
    if not NAME_PATTERN.match(name):
        raise RoleError(f"role name {name!r} is not a plain lower-case name")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RoleError(f"role {name}: file is over the size limit of {MAX_BYTES} bytes")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RoleError(f"role {name}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RoleError(f"role {name}: the file must be one mapping of keys")
    for key in sorted(set(data) - REQUIRED_KEYS):
        raise RoleError(f"role {name}: unknown key {key!r}")
    for key in sorted(REQUIRED_KEYS - set(data)):
        raise RoleError(f"role {name}: missing field {key!r}")
    if data["model_class"] not in MODEL_CLASSES:
        raise RoleError(f"role {name}: model_class must be one of {sorted(MODEL_CLASSES)}")
    if not isinstance(data["tools"], list):
        raise RoleError(f"role {name}: tools must be a list")
    for tool in data["tools"]:
        if tool not in TOOL_TIERS:
            raise RoleError(f"role {name}: unknown tool {tool!r}")
        if TOOL_TIERS[tool] > RATIFIED_TIER:
            raise RoleError(f"role {name}: tool {tool!r} is above the ratified tier")
    return Role(name=name, data=data)


def load_builtin_roles() -> dict[str, Role]:
    """Load every built-in role shipped in this package, keyed by role name."""
    package = resources.files("ract.roles")
    roles: dict[str, Role] = {}
    for entry in sorted(package.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".yaml"):
            continue
        name = entry.name[: -len(".yaml")]
        roles[name] = parse_role(entry.read_text(encoding="utf-8"), name=name)
        prompt = package / "prompts" / f"{roles[name].data['prompt']}.txt"
        if not prompt.is_file():
            raise RoleError(f"role {name}: prompt file {prompt.name} is missing")
    return roles
