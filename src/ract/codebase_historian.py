# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Codebase Historian for RACT.

The Historian is the anti-duplication mechanism from the anti-rot spec. It
maintains a knowledge graph of symbols, files, and commits, and answers the
question: "What already exists that is similar to what I am about to build?"

v0.1 is an in-process graph with no external database. It reads git history
when available and falls back to file metadata when git is absent.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.symbol_graph import SymbolGraph, SymbolNode


@dataclass
class HistoricalMatch:
    """A single match returned by the historian."""

    symbol_id: str
    name: str
    module: str
    symbol_type: str
    commit_hash: str | None = None
    commit_message: str | None = None
    commit_date: str | None = None
    similarity: float = 0.0


class CodebaseHistorian:
    """Knowledge graph of codebase symbols enriched with commit context.

    LR:: Before the editor writes a new symbol, the planner must ask the
    Historian what already exists. If the planner ignores a high-similarity
    match, the receipt records the ignored match and the justification. This
    makes duplication expensive and deliberate.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.symbol_graph = SymbolGraph(self.project_dir)
        self.commit_context: dict[str, dict[str, Any]] = {}

    def build(self) -> "CodebaseHistorian":
        """Build the symbol graph and attach commit context."""
        self.symbol_graph.build()
        self._load_commit_context()
        return self

    def _load_commit_context(self) -> None:
        """Attach last-commit metadata to each symbol from git blame."""
        if not self._has_git():
            return

        for symbol_id, node in self.symbol_graph.nodes.items():
            if node.line <= 0 or node.symbol_type == "module":
                continue
            path = self.project_dir / _module_to_path(node.module)
            if not path.is_file():
                continue
            context = self._blame_line(path, node.line)
            if context:
                self.commit_context[symbol_id] = context

    def _has_git(self) -> bool:
        return (self.project_dir / ".git").is_dir()

    def _blame_line(self, path: Path, line: int) -> dict[str, Any] | None:
        """Return git blame metadata for a single line."""
        try:
            result = subprocess.run(
                [
                    "git",
                    "blame",
                    "-L",
                    f"{line},{line}",
                    "--porcelain",
                    str(path.relative_to(self.project_dir)),
                ],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None

        lines = result.stdout.splitlines()
        if not lines:
            return None

        commit_hash = lines[0].split()[0]
        message_lines: list[str] = []
        author = ""
        date = ""
        in_summary = False
        for line_text in lines:
            if line_text.startswith("author "):
                author = line_text[len("author ") :]
            elif line_text.startswith("author-time "):
                date = line_text[len("author-time ") :]
            elif line_text.startswith("summary "):
                message_lines.append(line_text[len("summary ") :])
                in_summary = True
            elif in_summary and line_text.startswith(" "):
                message_lines.append(line_text[1:])
            elif in_summary:
                in_summary = False

        return {
            "commit_hash": commit_hash,
            "author": author,
            "date": date,
            "message": " ".join(message_lines),
        }

    def query(self, intent: str, k: int = 5) -> list[HistoricalMatch]:
        """Return the top-k existing symbols closest to *intent*.

        Similarity is a simple keyword overlap score over symbol name and module.
        In a future version this can be replaced with embedding similarity.
        """
        intent_words = set(_tokenize(intent))
        scored: list[tuple[float, HistoricalMatch]] = []

        for symbol_id, node in self.symbol_graph.nodes.items():
            if node.symbol_type == "module":
                continue
            symbol_words = set(_tokenize(node.name)) | set(_tokenize(node.module))
            if not symbol_words:
                continue
            overlap = len(intent_words & symbol_words)
            similarity = overlap / max(len(intent_words), len(symbol_words))
            if similarity <= 0.0:
                continue
            ctx = self.commit_context.get(symbol_id, {})
            match = HistoricalMatch(
                symbol_id=symbol_id,
                name=node.name,
                module=node.module,
                symbol_type=node.symbol_type,
                commit_hash=ctx.get("commit_hash"),
                commit_message=ctx.get("message"),
                commit_date=ctx.get("date"),
                similarity=round(similarity, 3),
            )
            scored.append((similarity, match))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:k]]

    def save(self, path: Path | str) -> None:
        """Persist the historian state to JSON."""
        payload = {
            "symbol_graph": self.symbol_graph.to_dict(),
            "commit_context": self.commit_context,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, project_dir: Path, path: Path | str) -> "CodebaseHistorian":
        """Load a previously saved historian state."""
        historian = cls(project_dir)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        historian.symbol_graph = SymbolGraph(project_dir)
        for nid, n in data.get("symbol_graph", {}).items():
            historian.symbol_graph.nodes[nid] = SymbolNode(
                id=n["id"],
                name=n["name"],
                module=n["module"],
                symbol_type=n["symbol_type"],
                line=n["line"],
                outgoing=set(n.get("outgoing", [])),
                incoming=set(n.get("incoming", [])),
            )
        historian.commit_context = data.get("commit_context", {})
        return historian


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return [t.lower() for t in _SPLIT_RE.split(text) if t]


def _module_to_path(module: str) -> Path:
    return Path(module.replace(".", "/") + ".py")


_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")
# RACT 0.1.1 - Trust and tooling
