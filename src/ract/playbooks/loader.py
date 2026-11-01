"""Playbooks as data (ADR-0049 D7): load and validate one playbook file at a time.

A playbook is an ordered list of roles (B-172), the acceptance checks that end it, the stop
condition, and what the user is asked. This module reads the package playbooks only. A repository
playbook (D7, the hostile-input rules) is a later card and is not read here.

The rules, in the order they are checked:
1. The name is a plain file name (no path parts, no leading dot).
2. The file is at most MAX_BYTES bytes, checked before anything is parsed.
3. The file is one YAML mapping, parsed with safe_load only.
4. Every key is one of the closed set. An unknown key is refused and named.
5. Every key is present. A missing key is refused and named.
6. Every role is a built-in role (ract.roles.loader), and every tool that role needs is in the grant.
Acceptance checks are stored as text. Nothing in a playbook is run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

from ract.roles import loader as roles_loader

MAX_BYTES = 64 * 1024

REQUIRED_KEYS = frozenset({"name", "purpose", "roles", "acceptance", "stop", "asks"})
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# The grant: the tools a playbook's roles may use. Only T0 is ratified today (ADR-0048).
DEFAULT_GRANT_TOOLS = frozenset(name for name, tier in roles_loader.TOOL_TIERS.items() if tier == 0)


class PlaybookError(ValueError):
    """A playbook file was refused. The message names the playbook and the reason."""


@dataclass(frozen=True)
class Playbook:
    name: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_playbook(
    text: str,
    *,
    name: str,
    grant_tools: frozenset[str] = DEFAULT_GRANT_TOOLS,
) -> Playbook:
    """Validate one playbook's text and return it as a Playbook. Raises PlaybookError."""
    if not NAME_PATTERN.match(name):
        raise PlaybookError(f"playbook name {name!r} is not a plain lower-case name")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise PlaybookError(f"playbook {name}: file is over the size limit of {MAX_BYTES} bytes")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"playbook {name}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PlaybookError(f"playbook {name}: the file must be one mapping of keys")
    for key in sorted(set(data) - REQUIRED_KEYS):
        raise PlaybookError(f"playbook {name}: unknown key {key!r}")
    for key in sorted(REQUIRED_KEYS - set(data)):
        raise PlaybookError(f"playbook {name}: missing field {key!r}")
    roles = data["roles"]
    if not isinstance(roles, list) or not roles:
        raise PlaybookError(f"playbook {name}: roles must be a non-empty list")
    built_in = roles_loader.load_builtin_roles()
    for role_name in roles:
        if role_name not in built_in:
            raise PlaybookError(f"playbook {name}: unknown role {role_name!r}")
        for tool in built_in[role_name].data["tools"]:
            if tool not in grant_tools:
                raise PlaybookError(f"playbook {name}: role {role_name} needs tool {tool!r}, not in the grant")
    if not isinstance(data["acceptance"], list) or not all(isinstance(item, str) for item in data["acceptance"]):
        raise PlaybookError(f"playbook {name}: acceptance must be a list of text checks")
    return Playbook(name=name, data=data)


def load_builtin_playbooks() -> dict[str, Playbook]:
    """Load every built-in playbook shipped in this package, keyed by playbook name."""
    package = resources.files("ract.playbooks")
    playbooks: dict[str, Playbook] = {}
    for entry in sorted(package.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".yaml"):
            continue
        name = entry.name[: -len(".yaml")]
        playbooks[name] = parse_playbook(entry.read_text(encoding="utf-8"), name=name)
    return playbooks
