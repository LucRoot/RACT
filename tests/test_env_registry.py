"""V7-02: every RACT_* environment read in src/ract is in the registry.

The scan reads the source with ``ast``. It counts ``os.environ.get(...)``,
``os.getenv(...)`` and ``os.environ[...]``. A name is resolved when it is a
string literal or a module-level string constant (the same module first, then
any module, when the name is unique). A read the scan cannot resolve is a
dynamic read: it must sit in DYNAMIC_READS with a reason, because it names a
variable the user chose (a ``${VAR}`` in ract.yaml) or a fixed list in the
module that the scan cannot see through.
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
from collections import defaultdict
from pathlib import Path

from ract import env_registry
from ract.cli import main as cli_main

SRC = Path(__file__).resolve().parent.parent / "src" / "ract"

# Dynamic read sites, by file. Each reason says what the name is.
DYNAMIC_READS: dict[str, str] = {
    "src/ract/doctor.py": "names a variable the user put in ract.yaml (api_key: ${VAR} and provider variables)",
    "src/ract/providers/openai_provider.py": "names the api_key variable the user chose, or OPENAI_API_KEY",
    "src/ract/providers/capability_probe.py": "names the api_key variable the user chose",
    "src/ract/setup/local_probe.py": "iterates ADDRESS_VARIABLES (RACT_BASE_URL and OPENAI_BASE_URL); checked below",
    "src/ract/cli.py": "_doctor_env reads each name in the registry itself (ract doctor --env)",
    "src/ract/tools/read.py": "copies SYSTEMROOT, WINDIR, TEMP and TMP into a child process's environment",
}


def _is_environ_read(node: ast.AST) -> ast.AST | None:
    """The name argument of an environment read, or None."""
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
        ):
            return node.args[0] if node.args else None
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            return node.args[0] if node.args else None
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "environ"
    ):
        return node.slice
    return None


def _string_constants(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            found[target.id] = value.value
    return found


def _scan() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(resolved name -> files that read it, dynamic file -> unresolved names)."""
    modules = {p: ast.parse(p.read_text(encoding="utf-8")) for p in SRC.rglob("*.py")}
    global_values: dict[str, set[str]] = defaultdict(set)
    for tree in modules.values():
        for name, value in _string_constants(tree).items():
            global_values[name].add(value)
    resolved: dict[str, set[str]] = defaultdict(set)
    dynamic: dict[str, set[str]] = defaultdict(set)
    for path, tree in modules.items():
        local = _string_constants(tree)
        rel = path.relative_to(SRC.parent.parent).as_posix()
        for node in ast.walk(tree):
            arg = _is_environ_read(node)
            if arg is None:
                continue
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                resolved[arg.value].add(rel)
            elif isinstance(arg, ast.Name) and arg.id in local:
                resolved[local[arg.id]].add(rel)
            elif isinstance(arg, ast.Name) and len(global_values.get(arg.id, ())) == 1:
                (value,) = global_values[arg.id]
                resolved[value].add(rel)
            else:
                dynamic[rel].add(ast.unparse(arg))
    return resolved, dynamic


def test_every_ract_environment_read_is_registered() -> None:
    resolved, _ = _scan()
    reads = {
        name: files for name, files in resolved.items() if name.startswith("RACT_")
    }
    unregistered = {
        name: sorted(files)
        for name, files in reads.items()
        if name not in env_registry.BY_NAME
    }
    assert not unregistered, f"RACT_* reads missing from ENV_VARS: {unregistered}"


def test_every_registered_variable_is_read_or_written_by_ract() -> None:
    """A registry entry names a variable the source still uses (no stale rows)."""
    resolved, _ = _scan()
    text = "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    stale = [v.name for v in env_registry.ENV_VARS if v.name not in text]
    assert not stale, f"registry entries no source file mentions: {stale}"
    assert resolved  # the scan found something


def test_dynamic_reads_are_only_the_listed_sites() -> None:
    _, dynamic = _scan()
    unexpected = {
        f: sorted(names) for f, names in dynamic.items() if f not in DYNAMIC_READS
    }
    assert not unexpected, (
        f"dynamic environment reads not in DYNAMIC_READS: {unexpected}"
    )
    stale = [f for f in DYNAMIC_READS if f not in dynamic]
    assert not stale, f"DYNAMIC_READS entries with no dynamic read: {stale}"


def test_the_address_variables_are_registered() -> None:
    from ract.setup import local_probe

    for name in local_probe.ADDRESS_VARIABLES:
        if name.startswith("RACT_"):
            assert name in env_registry.BY_NAME, name


def test_registry_rows_are_complete() -> None:
    for var in env_registry.ENV_VARS:
        assert var.name.startswith("RACT_"), var.name
        assert var.cls in env_registry.CLASSES, (var.name, var.cls)
        assert var.default.strip(), var.name
        assert var.consumer.strip(), var.name
        assert var.documented.strip(), var.name
    names = [v.name for v in env_registry.ENV_VARS]
    assert len(names) == len(set(names))


def test_doctor_env_lists_names_and_never_a_value(monkeypatch) -> None:
    secret = "sk-not-a-real-key-0123456789"
    monkeypatch.setenv("RACT_OPERATOR_KEY", secret)
    monkeypatch.setenv("RACT_TYPE_AHEAD", "1")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        with contextlib.suppress(SystemExit):
            cli_main(["doctor", "--env"])
    out = buffer.getvalue()
    assert "RACT_OPERATOR_KEY" in out
    assert "RACT_TYPE_AHEAD" in out
    assert secret not in out
    rows = {line.split()[0]: line.split()[-2:] for line in out.splitlines()[1:] if line}
    assert rows["RACT_TYPE_AHEAD"] == ["behavior", "set"]
    assert rows["RACT_OPERATOR_KEY"] == ["secret-ref", "set"]
    assert os.environ.get("RACT_OPERATOR_KEY") == secret  # not changed by the call
