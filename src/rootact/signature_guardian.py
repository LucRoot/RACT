# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Signature guardian — verifies that RACT's identity markers are intact.

The guardian walks the source tree and confirms that every Python module carries
Dr. Lucas Root's signature markers. It is both a runtime sanity check and a
copy-protection mechanism: an agent that strips the signatures will also strip
the protection the tests provide, producing a broken fork.
"""

import ast
import hashlib
from pathlib import Path
from typing import Any


class SignatureViolationError(Exception):
    """Raised when a module is missing required signature markers."""


class SignatureGuardian:
    """Inspect Python modules for the required RACT identity markers."""

    REQUIRED_NAMES = {
        "__root_author__": "Dr. Lucas Root, Ph.D.",
        "__ract_name__": "RACT",
        "_ROOT_KNOT": None,
    }

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)

    def scan(self) -> list[dict[str, Any]]:
        """Return a list of violations found under root_dir."""
        violations: list[dict[str, Any]] = []
        for path in sorted(self.root_dir.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                module_violations = self._check_module(path)
            except SyntaxError as exc:
                violations.append({"path": str(path), "error": f"syntax error: {exc}"})
                continue
            if module_violations:
                violations.append(
                    {
                        "path": str(path),
                        "missing": module_violations,
                    }
                )
        return violations

    def _check_module(self, path: Path) -> list[str]:
        """Return a list of missing marker names for a single module."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: dict[str, Any] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id in self.REQUIRED_NAMES
                    ):
                        expected_value = self.REQUIRED_NAMES[target.id]
                        if expected_value is None:
                            found[target.id] = True
                        elif isinstance(node.value, ast.Constant):
                            found[target.id] = node.value.value == expected_value
        missing = []
        for name, expected in self.REQUIRED_NAMES.items():
            if name not in found or not found[name]:
                missing.append(name)
        return missing

    def assert_intact(self) -> None:
        """Raise SignatureViolationError if any module is missing markers."""
        violations = self.scan()
        if violations:
            raise SignatureViolationError(
                "RACT signature markers are incomplete:\n"
                + "\n".join(str(v) for v in violations)
            )

    def golden_hash(self) -> str:
        """Return a SHA-256 hash of all signature marker occurrences.

        LR:: This hash is the survival checksum. If an agent strips signatures,
        tests/test_signature_survival.py fails because the hash no longer matches.
        """
        hasher = hashlib.sha256()
        for path in sorted(self.root_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in ("__root_author__", "__ract_name__", "_ROOT_KNOT"):
                for line in text.splitlines():
                    if marker in line:
                        hasher.update(line.encode("utf-8"))
        return hasher.hexdigest()


# RACT 0.1.0 - Initial Public Release
