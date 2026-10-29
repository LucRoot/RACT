"""A static check of the names a written Python file imports from the project (B-102).

LR:: A step wrote ``tests/test_notes.py`` with ``from src import NOTE`` while
``NOTE`` lives in ``src/notes.py``; the file parsed, the harness said done,
and the test module could not be collected (S2 D10). Running the tests is
B-023 and needs decision F; importing project code to look is unsafe. So
this reads source only: for ``from X import Y`` where X is a module or
package of this project, Y must be a top-level name of X or a submodule of
it. A module that is not in the project (the standard library, a
dependency) is not checked. A module the check cannot read with certainty
(a star import, a module ``__getattr__``, a namespace package) is "not
checked", never "ok".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Where an absolute import can live in a project: the root, or a src layout.
_SOURCE_ROOTS = ("", "src")
_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Missing:
    line: int
    name: str
    module: str

    def describe(self) -> str:
        return (
            f"line {self.line}: imports {self.name} from {self.module}, "
            f"which does not define it"
        )


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _module_file(
    root: Path, base: Path, dotted: str
) -> tuple[Path | None, Path | None]:
    """(file, package dir) for *dotted* under *base*, or (None, None) when absent."""
    parts = [p for p in dotted.split(".") if p]
    target = base.joinpath(*parts) if parts else base
    if not _inside(root, target):
        return None, None
    if target.is_dir():
        init = target / "__init__.py"
        return (init if init.is_file() else None), target
    as_file = target.with_suffix(".py")
    if parts and as_file.is_file():
        return as_file, None
    return None, None


def _nested_statements(node: ast.stmt) -> list[ast.stmt]:
    """The statements under a top-level if, try, with, for or while."""
    out: list[ast.stmt] = []
    for field in ("body", "orelse", "finalbody"):
        out.extend(getattr(node, field, []) or [])
    for handler in getattr(node, "handlers", []) or []:
        out.extend(handler.body)
    return out


def _top_level_names(body: list[ast.stmt]) -> set[str] | None:
    """Names a module defines at its top level, or None when that cannot be known."""
    names: set[str] = set()
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "__getattr__":
                return None
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    return None
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            # Names bound under a condition: read them all; a guarded import counts.
            inner = _top_level_names(_nested_statements(node))
            if inner is None:
                return None
            names |= inner
    return names


def _names_of(path: Path) -> set[str] | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8").lstrip("﻿")
        return _top_level_names(ast.parse(text).body)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return None


def missing_names(root: Path | str, path: str, text: str) -> list[Missing]:
    """Each ``from X import Y`` in *text* whose Y the project module X does not define."""
    root = Path(root)
    try:
        tree = ast.parse(text.lstrip("﻿"))
    except (SyntaxError, ValueError):
        return []  # a file that does not parse is the write gate's (B-095)
    here = (root / PurePosixPath(path.replace("\\", "/"))).parent
    found: list[Missing] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        dotted = node.module or ""
        if node.level:
            base = here
            for _ in range(node.level - 1):
                base = base.parent
            bases = [base]
        else:
            bases = [root / sub if sub else root for sub in _SOURCE_ROOTS]
        for base in bases:
            module_file, package = _module_file(root, base, dotted)
            if module_file is None and package is None:
                continue
            defined = _names_of(module_file) if module_file is not None else set()
            if module_file is None and package is not None:
                defined = None  # a namespace package: its names are not knowable here
            for alias in node.names:
                if alias.name == "*":
                    continue
                if package is not None and (
                    (package / f"{alias.name}.py").is_file()
                    or (package / alias.name).is_dir()
                ):
                    continue  # a submodule
                if defined is None or alias.name in defined:
                    continue
                found.append(
                    Missing(node.lineno, alias.name, "." * node.level + dotted)
                )
            break  # the first source root that holds the module decides
    return found
