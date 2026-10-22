"""Repository trust: run a project's own commands only after the operator says so.

LR:: A repository can ship things RACT would run or contact for it: hook
commands in `.ract/hooks/*.json`, MCP servers, an `internal` provider
command, coverage and mutation gates (they run the project's tests or a
script from it) and a web search endpoint in `ract.yaml`. `ract "intent"` in
a freshly cloned repository ran all of them with no question (S-025; found
by the B-035 control test). Now they run only when the operator trusts that
repository, or answers "run once" on a terminal.

The trust store lives in the user state directory, outside every project,
so a repository cannot trust itself. A record is keyed by the resolved
repository root and holds a digest of the trust items; changing any of them
(editing a hook file, adding an MCP server) makes the repository untrusted
again until the operator looks at the new list.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.canonical import dumps_jcs

STORE_NAME = "trusted_repositories.json"


@dataclass(frozen=True)
class TrustItem:
    """One thing a repository asks RACT to run or contact."""

    kind: str  # hook, mcp, command, network
    name: str
    detail: str  # the exact command or endpoint, shown to the operator

    def line(self) -> str:
        return f"{self.kind} {self.name}: {self.detail}"


def _load_config(root: Path) -> dict[str, Any]:
    path = root / "ract.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 -- the run reports config errors itself
        print(f"[trust] could not read {path}: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _command_text(command: Any) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return str(command)


def trust_items(root: Path | str) -> list[TrustItem]:
    """Everything in this repository that RACT would run or contact for it."""
    root = Path(root)
    items: list[TrustItem] = []
    hooks = root / ".ract" / "hooks"
    if hooks.is_dir():
        for path in sorted(hooks.glob("*.json")):
            try:
                hook = json.loads(path.read_text(encoding="utf-8"))
                detail = _command_text(hook.get("command", ""))
            except (OSError, ValueError, AttributeError):
                detail = "(unreadable hook file)"
            items.append(TrustItem("hook", path.stem, detail))
    config = _load_config(root)
    for name, spec in sorted((config.get("mcp_servers") or {}).items()):
        if isinstance(spec, dict):
            detail = (
                str(spec.get("url"))
                if spec.get("transport") == "sse"
                else _command_text([spec.get("command", ""), *spec.get("args", [])])
            )
            items.append(TrustItem("mcp", str(name), detail))
    for slot, spec in sorted((config.get("providers") or {}).items()):
        if isinstance(spec, dict) and spec.get("adapter") == "internal":
            items.append(
                TrustItem(
                    "command",
                    f"provider {slot}",
                    _command_text(spec.get("command", "")),
                )
            )
    if (config.get("coverage_gate") or {}).get("enabled"):
        items.append(
            TrustItem(
                "command", "coverage_gate", "pytest with coverage (imports conftest.py)"
            )
        )
    mutation = config.get("mutation_gate") or {}
    if mutation.get("enabled"):
        script = mutation.get("script_path") or "scripts/run_mutation_tests_wsl.sh"
        items.append(TrustItem("command", "mutation_gate", f"bash {script}"))
    retrieval = config.get("retrieval") or {}
    if retrieval.get("adapter") == "web":
        items.append(
            TrustItem("network", "web retrieval", str(retrieval.get("endpoint", "")))
        )
    return items


def digest(root: Path | str, items: list[TrustItem] | None = None) -> str:
    """A digest over the trust items and the bytes of every hook file."""
    root = Path(root)
    items = trust_items(root) if items is None else items
    h = hashlib.sha256()
    h.update(dumps_jcs([[i.kind, i.name, i.detail] for i in items]))
    hooks = root / ".ract" / "hooks"
    if hooks.is_dir():
        for path in sorted(hooks.glob("*.json")):
            h.update(path.name.encode("utf-8"))
            try:
                h.update(path.read_bytes())
            except OSError as exc:
                h.update(f"unreadable:{exc}".encode())
    return h.hexdigest()


def repository_key(root: Path | str) -> str:
    """One key per repository, whatever path or link reached it."""
    return os.path.normcase(os.path.realpath(os.fspath(root)))


def store_path() -> Path:
    from ract.core.keys import _default_state_dir

    return _default_state_dir() / STORE_NAME


def _read_store() -> dict[str, str]:
    path = store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[trust] ignoring unreadable trust store {path}: {exc}", file=sys.stderr)
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_store(store: dict[str, str]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(store.items())), indent=2), encoding="utf-8")
    tmp.replace(path)


def is_trusted(root: Path | str) -> bool:
    """True when there is nothing to trust, or the operator trusted exactly this."""
    items = trust_items(root)
    if not items:
        return True
    return _read_store().get(repository_key(root)) == digest(root, items)


def trust(root: Path | str) -> str:
    """Record the operator's trust in this repository's current items."""
    store = _read_store()
    value = digest(root)
    store[repository_key(root)] = value
    _write_store(store)
    return value


def untrust(root: Path | str) -> bool:
    store = _read_store()
    removed = store.pop(repository_key(root), None) is not None
    if removed:
        _write_store(store)
    return removed


def trusted_repositories() -> list[str]:
    return sorted(_read_store())


def decide(root: Path | str, *, interactive: bool, ask: Any = input) -> bool:
    """Whether this run may use the repository's items. Asks only on a terminal.

    Returns True to run them, False to skip them. Without a terminal, an
    untrusted repository's items are skipped with one line on stderr.
    """
    items = trust_items(root)
    if not items or is_trusted(root):
        return True
    # One answer per process and per set of items: a session or a --loop
    # run asks once, not on every turn or iteration.
    memo_key = (repository_key(root), digest(root, items))
    if memo_key in _DECIDED:
        return _DECIDED[memo_key]
    allowed = _ask(items, interactive=interactive, ask=ask, root=root)
    _DECIDED[memo_key] = allowed
    return allowed


# Answers given in this process, by (repository, digest of its items).
_DECIDED: dict[tuple[str, str], bool] = {}


def _ask(
    items: list[TrustItem], *, interactive: bool, ask: Any, root: Path | str
) -> bool:
    listing = "\n".join(f"  {item.line()}" for item in items)
    if not interactive:
        print(
            "note: this repository is not trusted, so RACT does not run its own "
            f"commands or contact its endpoints this run:\n{listing}\n"
            "  To allow them: ract trust",
            file=sys.stderr,
            flush=True,
        )
        return False
    print(
        "This repository asks RACT to run or contact:\n"
        f"{listing}\n"
        "They come from the repository's own files, not from you.",
        file=sys.stderr,
        flush=True,
    )
    try:
        answer = (
            str(ask("[r]un once, [t]rust this repository, [s]kip (default s): "))
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        answer = "s"
    if answer in {"t", "trust"}:
        trust(root)
        print("trusted; `ract trust --remove` undoes it", file=sys.stderr, flush=True)
        return True
    if answer in {"r", "run", "run once"}:
        return True
    print("skipped for this run", file=sys.stderr, flush=True)
    return False
