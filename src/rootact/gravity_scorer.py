# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Codebase gravity scoring for RACT.

The anti-rot spec argues AI code ignores existing, load-bearing symbols and
introduces novel ones. Gravity scoring makes the load-bearing parts of the
codebase visible to the planner and verifier. High-gravity symbols are the ones
the project actually relies on; new code should prefer them.
"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SymbolGravity:
    """Gravity metadata for a single symbol."""

    name: str
    module: str
    symbol_type: str  # "function", "class", "module"
    reference_count: int = 0
    centrality: float = 0.0
    gravity_score: float = 0.0


class GravityScorer:
    """Rank symbols by reference count and dependency-graph centrality.

    LR:: Gravity is a proxy for load-bearing-ness. A function imported and
    called in many places is load-bearing. A module that many other modules
    import is load-bearing. New code that ignores high-gravity symbols where
    they apply is probably reinventing the wheel.
    """

    def __init__(
        self,
        project_dir: Path,
        reference_weight: float = 0.7,
        centrality_weight: float = 0.3,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.reference_weight = reference_weight
        self.centrality_weight = centrality_weight
        self._symbols: dict[str, SymbolGravity] = {}
        self._module_imports: dict[str, set[str]] = {}
        self._cache_path = self.project_dir / ".rootact" / "gravity_index.json"

    def build_index(self) -> dict[str, SymbolGravity]:
        """Scan the project and build the gravity index from scratch."""
        self._symbols = {}
        self._module_imports = {}

        py_files = list(self.project_dir.rglob("*.py"))
        py_files = [p for p in py_files if "__pycache__" not in p.parts]

        # First pass: collect symbols and module-level imports.
        for path in py_files:
            self._index_file(path)

        # Second pass: count references and build module graph.
        for path in py_files:
            self._count_references(path)

        self._compute_centrality()
        self._compute_gravity_scores()
        self._save_cache()
        return dict(self._symbols)

    def _relative_module(self, path: Path) -> str:
        rel = path.relative_to(self.project_dir).with_suffix("")
        return ".".join(rel.parts)

    def _index_file(self, path: Path) -> None:
        module = self._relative_module(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return

        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{module}.{node.name}"
                self._symbols[key] = SymbolGravity(
                    name=node.name,
                    module=module,
                    symbol_type="function",
                )
            elif isinstance(node, ast.ClassDef):
                key = f"{module}.{node.name}"
                self._symbols[key] = SymbolGravity(
                    name=node.name,
                    module=module,
                    symbol_type="class",
                )

        self._module_imports[module] = imports

    def _count_references(self, path: Path) -> None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                # Heuristic: count any name that matches a known symbol in any module.
                for key, sym in self._symbols.items():
                    if sym.name == node.id:
                        sym.reference_count += 1
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                # module.name references
                name = _attr_to_name(node)
                if name:
                    for key, sym in self._symbols.items():
                        if sym.name == name:
                            sym.reference_count += 1

    def _compute_centrality(self) -> None:
        """Compute a simple PageRank-like centrality over module import graph."""
        modules = list(self._module_imports.keys())
        if not modules:
            return

        # Initialize scores uniformly.
        scores: dict[str, float] = {m: 1.0 for m in modules}
        damping = 0.85
        iterations = 20

        for _ in range(iterations):
            new_scores: dict[str, float] = {}
            for module in modules:
                incoming = 0.0
                for other, imports in self._module_imports.items():
                    if module in imports:
                        outgoing = max(1, len(imports))
                        incoming += scores[other] / outgoing
                new_scores[module] = (1 - damping) + damping * incoming
            scores = new_scores

        # Normalize to 0-1 range.
        max_score = max(scores.values()) if scores else 1.0
        for module in modules:
            scores[module] = scores[module] / max_score if max_score else 0.0

        for key, sym in self._symbols.items():
            sym.centrality = scores.get(sym.module, 0.0)

    def _compute_gravity_scores(self) -> None:
        for sym in self._symbols.values():
            ref_norm = min(1.0, sym.reference_count / 10.0)
            sym.gravity_score = round(
                self.reference_weight * ref_norm
                + self.centrality_weight * sym.centrality,
                3,
            )

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbols": [
                {
                    "name": s.name,
                    "module": s.module,
                    "symbol_type": s.symbol_type,
                    "reference_count": s.reference_count,
                    "centrality": s.centrality,
                    "gravity_score": s.gravity_score,
                }
                for s in self._symbols.values()
            ],
            "file_mtimes": self._current_mtimes(),
        }
        self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _current_mtimes(self) -> dict[str, list[float]]:
        return {
            str(p.relative_to(self.project_dir)): [
                float(p.stat().st_mtime),
                float(p.stat().st_size),
            ]
            for p in self.project_dir.rglob("*.py")
            if "__pycache__" not in p.parts
        }

    def _cache_fresh(self) -> bool:
        if not self._cache_path.is_file():
            return False
        try:
            cached = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        cached_mtimes = cached.get("file_mtimes", {})
        current = self._current_mtimes()
        return cached_mtimes == current

    def get_index(self) -> dict[str, SymbolGravity]:
        """Return the gravity index, rebuilding only if the cache is stale."""
        if self._symbols and self._cache_fresh():
            return dict(self._symbols)
        if self._cache_fresh():
            self._load_cache()
            return dict(self._symbols)
        return self.build_index()

    def _load_cache(self) -> None:
        data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        self._symbols = {}
        for entry in data.get("symbols", []):
            sym = SymbolGravity(
                name=entry["name"],
                module=entry["module"],
                symbol_type=entry["symbol_type"],
                reference_count=entry["reference_count"],
                centrality=entry["centrality"],
                gravity_score=entry["gravity_score"],
            )
            self._symbols[f"{sym.module}.{sym.name}"] = sym

    def top_k(self, intent: str | None = None, k: int = 10) -> list[SymbolGravity]:
        """Return the top-k highest-gravity symbols, optionally filtered by intent."""
        index = self.get_index()
        symbols = list(index.values())
        if intent:
            intent_lower = intent.lower()
            symbols = [
                s
                for s in symbols
                if intent_lower in s.name.lower() or intent_lower in s.module.lower()
            ]
        symbols.sort(key=lambda s: s.gravity_score, reverse=True)
        return symbols[:k]


def _attr_to_name(node: ast.Attribute) -> str | None:
    """Return the final attribute name of an ast.Attribute chain."""
    if isinstance(node.value, ast.Name):
        return node.attr
    if isinstance(node.value, ast.Attribute):
        return _attr_to_name(node.value)
    return None


# RACT 0.1.1 - Trust and tooling
