# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Duplication guard for RACT.

The guard asks the CodebaseHistorian whether a proposed new artifact is too
similar to something that already exists. If similarity exceeds the threshold
the write is blocked and the operator must justify the duplication.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.ast_normalizer import structural_similarity
from rootact.codebase_historian import CodebaseHistorian


class DuplicationBlockedError(Exception):
    """Raised when a proposed artifact duplicates existing code."""

    def __init__(self, matches: list["DuplicationMatch"]) -> None:
        self.matches = matches
        super().__init__(self._message())

    def _message(self) -> str:
        lines = ["Duplication guard blocked write:"]
        for m in self.matches:
            lines.append(
                f"  {m.symbol_id} ({m.symbol_type}) similarity={m.similarity:.3f}"
            )
        return "\n".join(lines)


@dataclass
class DuplicationMatch:
    """A single potential duplication."""

    symbol_id: str
    name: str
    module: str
    symbol_type: str
    similarity: float
    existing_source: str = ""
    proposed_source: str = ""


class DuplicationGuard:
    """Blocks writes that duplicate existing symbols above a similarity threshold.

    LR:: The threshold makes duplication expensive and deliberate. A lower
    threshold catches more; a higher threshold avoids false positives. The
    default 0.85 is tuned for function-level duplication.
    """

    def __init__(
        self,
        project_dir: Path,
        threshold: float = 0.85,
        historian: CodebaseHistorian | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.threshold = threshold
        self.historian = historian or CodebaseHistorian(self.project_dir).build()

    def check(self, artifact_path: str, content: str) -> list[DuplicationMatch]:
        """Return high-similarity matches for *content* at *artifact_path*.

        Does not raise; callers decide whether to block.
        """
        module = self._path_to_module(artifact_path)
        proposed_symbols = self._extract_symbols(content, module)
        if not proposed_symbols:
            return []

        matches: list[DuplicationMatch] = []
        for symbol_id, proposed in proposed_symbols.items():
            # Allow rewrites of a symbol in its own module. The guard targets
            # cross-module duplication, not editing an existing file in place.
            for existing in self.historian.symbol_graph.nodes.values():
                if existing.symbol_type == "module":
                    continue
                if existing.module == module:
                    continue
                existing_src = self._existing_source(existing)
                similarity = self._source_similarity(proposed["source"], existing_src)
                if similarity >= self.threshold:
                    matches.append(
                        DuplicationMatch(
                            symbol_id=existing.id,
                            name=existing.name,
                            module=existing.module,
                            symbol_type=existing.symbol_type,
                            similarity=round(similarity, 3),
                            existing_source=existing_src,
                            proposed_source=proposed["source"],
                        )
                    )
        return matches

    def check_and_block(self, artifact_path: str, content: str) -> None:
        """Check and raise DuplicationBlockedError if any match exceeds threshold."""
        matches = self.check(artifact_path, content)
        if matches:
            raise DuplicationBlockedError(matches)

    def _path_to_module(self, artifact_path: str) -> str:
        rel = Path(artifact_path)
        if rel.is_absolute():
            try:
                rel = rel.relative_to(self.project_dir)
            except ValueError:
                pass
        return ".".join(rel.with_suffix("").parts)

    def _extract_symbols(self, content: str, module: str) -> dict[str, dict[str, Any]]:
        """Return proposed symbol id -> {source, type} for the given content."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {}

        source_lines = content.splitlines()
        symbols: dict[str, dict[str, Any]] = {}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sym_id = f"{module}.{node.name}"
                symbols[sym_id] = {
                    "name": node.name,
                    "source": self._node_source(source_lines, node),
                    "type": "function"
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else "class",
                }
        return symbols

    def _node_source(self, lines: list[str], node: ast.AST) -> str:
        start = getattr(node, "lineno", 1) or 1
        end = getattr(node, "end_lineno", start) or start
        return "\n".join(lines[start - 1 : end])

    def _existing_source(self, node: Any) -> str:
        """Read the source of an existing symbol from disk if possible."""
        path = self.project_dir / _module_to_path(node.module)
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines()
            start = getattr(node, "line", 1) or 1
            # Without end_lineno we read a reasonable window.
            end = start + 50
            return "\n".join(lines[start - 1 : end])
        return ""

    def _source_similarity(self, a: str, b: str) -> float:
        """AST-normalized structural similarity.

        Identifies duplicates even when all identifiers have been renamed,
        which token-based similarity cannot do.
        """
        return structural_similarity(a, b)


def _module_to_path(module: str) -> Path:
    return Path(module.replace(".", "/") + ".py")


# RACT 0.1.1 - Trust and tooling
