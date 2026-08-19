"""Playbook YAML loader (v0.5.0 memory discipline, module_07).

Four v0.5.0 playbooks ship as YAML files in this package:

- ``refactor_rename.yaml``
- ``refactor_extract.yaml``
- ``bug_fix.yaml``
- ``unit_test.yaml``

Adding a fifth YAML in this directory makes it visible to
:func:`list_playbooks` without any code edit: the enumeration is a
directory scan (Second Pass Q4 preview: no hard-coded name list).
The eight deferred playbooks defer to v0.6 per master spec
§Bounded scope; see ADR-0037.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.composition_runner import (
    IterationBoundExceededError,
    OversizeTargetError,
    PlaybookSchemaError,
    PlaybookSpec,
    UnconfirmedBugError,
    UnknownPlaybookError,
    parse_playbook_payload,
)


PLAYBOOKS_DIR: Path = Path(__file__).resolve().parent
"""On-disk location of the shipped playbook YAMLs."""


def list_playbooks() -> list[str]:
    """Return the sorted list of playbook names discovered under this package.

    Directory scan: a fifth YAML dropped in appears here without a
    code edit. Names come from the file stem; extension must be
    ``.yaml``.
    """
    names: list[str] = []
    if not PLAYBOOKS_DIR.is_dir():
        return names
    for entry in sorted(PLAYBOOKS_DIR.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".yaml":
            continue
        names.append(entry.stem)
    return sorted(names)


def load_playbook(name: str) -> PlaybookSpec:
    """Return the parsed :class:`PlaybookSpec` for ``name``.

    Refuses unknown names with :class:`UnknownPlaybookError` naming
    the shipped set. Refuses malformed YAML with
    :class:`PlaybookSchemaError` naming the offending field.
    """
    if not isinstance(name, str) or not name:
        raise UnknownPlaybookError(
            f"playbook name must be a non-empty string; got {name!r}",
            function="playbook_load",
            payload={"requested": name, "available": list_playbooks()},
        )
    shipped = list_playbooks()
    if name not in shipped:
        raise UnknownPlaybookError(
            f"unknown playbook {name!r}; shipped: {shipped!r}",
            function="playbook_load",
            payload={"requested": name, "available": shipped},
        )
    path = PLAYBOOKS_DIR / f"{name}.yaml"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlaybookSchemaError(
            f"playbook file unreadable: {path}: {exc}",
            function="playbook_load",
            payload={"source": str(path)},
        ) from exc
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PlaybookSchemaError(
            f"playbook file {path.name!r} is not valid YAML: {exc}",
            function="playbook_load",
            payload={"source": str(path)},
        ) from exc
    return parse_playbook_payload(payload, source_label=str(path))


__all__ = [
    "IterationBoundExceededError",
    "OversizeTargetError",
    "PLAYBOOKS_DIR",
    "PlaybookSchemaError",
    "PlaybookSpec",
    "UnconfirmedBugError",
    "UnknownPlaybookError",
    "list_playbooks",
    "load_playbook",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
