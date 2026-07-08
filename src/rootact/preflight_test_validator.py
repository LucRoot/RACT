# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Pre-flight validation for generated test artifacts.

Before the loop pays for a full pytest invocation, this validator catches the
most common mechanical defects in generated test files: syntax errors and
missing imports for modules that the test text obviously uses. It is
conservative by design: it flags names that are both commonly imported as
modules and not defined in the file, rather than trying to solve the general
symbol-resolution problem.
"""

import ast
import builtins
from dataclasses import dataclass
from typing import Any

from rootact.rooted import Rooted


# Names that Nemotron (and many management models) frequently use in tests
# without remembering to import them.
_COMMON_TEST_MODULES: set[str] = {
    "re",
    "json",
    "pathlib",
    "pytest",
    "os",
    "sys",
    "tempfile",
    "shutil",
    "typing",
    "collections",
    "datetime",
    "math",
    "random",
    "uuid",
    "dataclasses",
    "textwrap",
    "inspect",
    "hashlib",
}


@dataclass(frozen=True)
class PreflightIssue:
    """A single preflight problem."""

    path: str
    category: str
    message: str


def _is_test_artifact(rel_path: str) -> bool:
    """Return True if the artifact path looks like a pytest test file."""
    parts = rel_path.replace("\\", "/").split("/")
    return rel_path.endswith(".py") and (
        "tests" in parts or rel_path.startswith("test_")
    )


def _extract_imported_names(tree: ast.Module) -> set[str]:
    """Collect top-level names introduced by import statements."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                imported.add(alias.asname or alias.name)
    return imported


def _extract_defined_names(tree: ast.Module) -> set[str]:
    """Collect top-level function/class/assignment names in the module."""
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    return defined


def _extract_used_test_names(tree: ast.Module) -> set[str]:
    """Collect names loaded inside test functions or module-level asserts."""
    used: set[str] = set()
    for node in tree.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test_"):
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    used.add(child.id)
        elif isinstance(node, ast.Assert):
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    used.add(child.id)
    return used


def validate_test_content(rel_path: str, content: str) -> Rooted[bool]:
    """Validate a generated test file and return a Rooted result.

    The validation is conservative: it flags syntax errors and obvious missing
    imports for common test modules. It does not guarantee the test is correct,
    only that it is mechanically safe enough to run pytest against.
    """
    assumption = "Generated test files compile and reference only available names before pytest runs."

    if not _is_test_artifact(rel_path):
        return Rooted(
            value=True,
            assumption=assumption,
            confidence=1.0,
            provenance=["preflight_test_validator.validate_test_content"],
        )

    try:
        compile(content, rel_path, "exec")
        tree: ast.Module = ast.parse(content)
    except SyntaxError as exc:
        return Rooted(
            value=None,
            assumption=assumption,
            confidence=1.0,
            provenance=["preflight_test_validator.compile"],
            error=f"{rel_path}: syntax error - {exc}",
        )

    imported = _extract_imported_names(tree)
    defined = _extract_defined_names(tree)
    used = _extract_used_test_names(tree)

    builtins_set: set[str] = set(dir(builtins))
    missing: list[str] = []
    for name in sorted(used):
        if (
            name in _COMMON_TEST_MODULES
            and name not in imported
            and name not in defined
            and name not in builtins_set
        ):
            missing.append(name)

    if missing:
        missing_str = ", ".join(missing)
        return Rooted(
            value=None,
            assumption=assumption,
            confidence=1.0,
            provenance=["preflight_test_validator.import_scan"],
            error=(
                f"{rel_path}: missing imports for modules used in tests: {missing_str}. "
                "Add the missing import(s) before running pytest."
            ),
        )

    return Rooted(
        value=True,
        assumption=assumption,
        confidence=1.0,
        provenance=["preflight_test_validator.validate_test_content"],
    )


def validate_report_tests(report: Any) -> list[PreflightIssue]:
    """Validate every test artifact in an ExecutionReport.

    Returns a list of issues; empty means all test artifacts passed preflight.
    Non-test artifacts are ignored.
    """
    issues: list[PreflightIssue] = []
    if not hasattr(report, "step_results"):
        return issues

    for step_result in report.step_results:
        artifact = step_result.step.expected_artifact
        if not artifact or not _is_test_artifact(artifact):
            continue
        rooted = validate_test_content(artifact, step_result.content)
        if not rooted.is_ok() and rooted.error:
            issues.append(
                PreflightIssue(
                    path=artifact,
                    category="preflight",
                    message=rooted.error,
                )
            )

    return issues


# RACT 0.1.0 - Initial Public Release
