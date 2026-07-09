# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Dead code auction for RACT.

Identifies Python modules that are old and have no inbound references from other
project modules. The list is offered to the operator for review; nothing is
deleted automatically.

LR:: This is the anti-rot deletion incentive from the v0.3 spec made concrete.
Agents add files forever because there is no cost. The auction makes removal a
first-class, reviewed proposal.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.symbol_graph import SymbolGraph


@dataclass(frozen=True)
class AuctionItem:
    """One dead-code candidate."""

    path: Path
    relative_path: str
    last_modified_days: int
    inbound_references: int
    reason: str


class DeadCodeAuction:
    """Scan the project for files that may be safe to remove."""

    DEFAULT_MIN_AGE_DAYS = 180
    DEFAULT_INCLUDE_TESTS = False
    # Modules that are entry points, loaded dynamically, or kept as tested
    # utilities. They legitimately have no production inbound references but must
    # not be reported as dead code.
    DEFAULT_ALLOWLIST = {"cli.py", "cli_toggles.py", "signature_guardian.py"}
    IGNORE_DIRS = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "_BUILD",
        "htmlcov",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    def __init__(
        self,
        project_dir: Path | str,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.config = config or {}
        self.min_age_days = int(
            self.config.get("min_age_days", self.DEFAULT_MIN_AGE_DAYS)
        )
        self.include_tests = bool(
            self.config.get("include_tests", self.DEFAULT_INCLUDE_TESTS)
        )
        self.ignore_dirs = set(self.config.get("ignore_dirs", self.IGNORE_DIRS))
        self.allowlist = set(self.config.get("allowlist", self.DEFAULT_ALLOWLIST))

    def _should_skip_dir(self, path: Path) -> bool:
        return any(part in self.ignore_dirs for part in path.parts)

    def _is_test_file(self, path: Path) -> bool:
        if not self.include_tests:
            if "tests" in path.parts:
                return True
            if path.name.startswith("test_") and path.name.endswith(".py"):
                return True
        return False

    def _module_for_file(self, path: Path, graph: SymbolGraph) -> str | None:
        """Return the dotted module id for a project Python file.

        Uses the same namespace as the symbol graph so inbound references can
        be matched against the correct module.
        """
        try:
            return graph.module_id_for_path(path)
        except ValueError:
            return None

    def _file_age_days(self, path: Path) -> float:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return 0.0
        return (time.time() - mtime) / 86400.0

    def _inbound_refs(self, module: str, graph: SymbolGraph) -> int:
        """Count inbound references to any symbol in *module* from other modules.

        Self-edges inside a module (e.g. ``config_loader.load_from_file`` calling
        ``config_loader.ConfigEntry``) do not keep a module alive; only external
        references do.
        """
        count = 0
        for node in graph.nodes.values():
            if node.module != module:
                continue
            for src in node.incoming:
                src_module = (
                    src.rsplit(":", 1)[0] if ":" in src else src.rsplit(".", 1)[0]
                )
                if src_module != module:
                    count += 1
        return count

    def scan(self) -> list[AuctionItem]:
        """Return a sorted list of dead-code candidates (oldest first)."""
        graph = SymbolGraph(self.project_dir)
        try:
            # Test imports should not keep production modules alive.
            graph.build(include_tests=False)
        except Exception:  # noqa: BLE001
            graph.nodes = {}

        items: list[AuctionItem] = []
        now = time.time()
        for path in self.project_dir.rglob("*.py"):
            if self._should_skip_dir(path):
                continue
            if self._is_test_file(path):
                continue
            age_days = (now - path.stat().st_mtime) / 86400.0
            if age_days < self.min_age_days:
                continue

            if path.name == "__init__.py":
                continue
            if path.name in self.allowlist:
                continue

            module = self._module_for_file(path, graph)
            if module is None:
                continue

            inbound = self._inbound_refs(module, graph) if graph.nodes else 0
            if inbound > 0:
                continue

            items.append(
                AuctionItem(
                    path=path,
                    relative_path=str(path.relative_to(self.project_dir)),
                    last_modified_days=int(age_days),
                    inbound_references=inbound,
                    reason=(
                        f"no inbound references; last modified {int(age_days)} days ago"
                    ),
                )
            )

        items.sort(key=lambda item: item.last_modified_days, reverse=True)
        return items


# RACT 0.1.0 - Initial Public Release
