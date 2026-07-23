# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Legacy Whisperer subagent for RACT.

Before the management model plans work, the Whisperer reads the project's recent
history and most-referenced symbols, then produces a short brief on the
codebase's dialect and conventions. The planner receives the brief and must
cite it. This makes generic, duplicative code more expensive than code that
matches the project.

LR:: The Whisperer is intentionally local + one cheap model call. It does not
replace the management model; it orients it.
"""

import ast
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.providers.base import ProviderAdapter
from ract.rooted import Rooted
from ract.symbol_graph import SymbolGraph


@dataclass(frozen=True)
class StyleStats:
    """Lightweight style fingerprint of the project."""

    total_files: int
    import_module: int
    import_from: int
    single_quotes: int
    double_quotes: int
    type_hints: int
    functions: int
    classes: int

    def summary(self) -> str:
        parts = [
            f"files={self.total_files}",
            f"imports: import X={self.import_module}, from X import={self.import_from}",
            f"quotes: single={self.single_quotes}, double={self.double_quotes}",
            f"type-hinted defs={self.type_hints}",
            f"functions={self.functions}, classes={self.classes}",
        ]
        return "; ".join(parts)


class LegacyWhisperer:
    """Produce a pre-planning codebase dialect brief."""

    def __init__(
        self,
        project_dir: Path | str,
        provider: ProviderAdapter,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.provider = provider
        self.config = config or {}
        self.top_k = int(self.config.get("top_k", 5))
        self.max_history_lines = int(self.config.get("max_history_lines", 50))

    def _symbol_graph(self) -> SymbolGraph | None:
        """Build a symbol graph if the project has Python files."""
        try:
            graph = SymbolGraph(self.project_dir)
            graph.build()
            return graph if graph.nodes else None
        except Exception:  # noqa: BLE001
            return None

    def _candidate_paths(self, intent: str, provided: list[str] | None) -> list[Path]:
        """Return the files the brief should focus on."""
        if provided:
            return [self.project_dir / p for p in provided]

        graph = self._symbol_graph()
        if graph is not None:
            # Use the most-referenced modules among symbols matching the intent.
            matches = graph.search(intent)
            matches.sort(key=lambda n: len(n.incoming), reverse=True)
            modules = []
            seen = set()
            for node in matches:
                mod_file = self.project_dir / (node.module.replace(".", "/") + ".py")
                if mod_file not in seen and mod_file.is_file():
                    modules.append(mod_file)
                    seen.add(mod_file)
                if len(modules) >= self.top_k:
                    break
            if modules:
                return modules

        # Fall back to keyword file search.
        words = [w for w in intent.lower().split() if len(w) > 2]
        files = [
            p
            for p in self.project_dir.rglob("*.py")
            if "__pycache__" not in p.parts and p.is_file()
        ]
        if words:
            matched = [p for p in files if any(w in p.name.lower() for w in words)]
            if matched:
                files = matched
        return files[: self.top_k]

    def _git_history(self, path: Path) -> list[str]:
        """Return recent commit messages for *path*, if git is available."""
        try:
            proc = subprocess.run(
                [
                    "git",
                    "log",
                    f"-n{self.top_k}",
                    "--pretty=format:%s",
                    "--",
                    str(path),
                ],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def _style_stats(self, paths: list[Path]) -> StyleStats:
        """Compute a lightweight style fingerprint from the given files."""
        import_module = 0
        import_from = 0
        single_quotes = 0
        double_quotes = 0
        type_hints = 0
        functions = 0
        classes = 0
        files = [p for p in paths if p.is_file()]
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    import_module += len(node.names)
                elif isinstance(node, ast.ImportFrom):
                    import_from += len(node.names)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # Very rough quote detection.
                    if node.value.count("'") > node.value.count('"'):
                        single_quotes += 1
                    else:
                        double_quotes += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                    if node.returns is not None or any(
                        a.annotation is not None for a in node.args.args
                    ):
                        type_hints += 1
                elif isinstance(node, ast.ClassDef):
                    classes += 1
        return StyleStats(
            total_files=len(files),
            import_module=import_module,
            import_from=import_from,
            single_quotes=single_quotes,
            double_quotes=double_quotes,
            type_hints=type_hints,
            functions=functions,
            classes=classes,
        )

    def _top_referenced_files(self) -> list[Path]:
        """Return the most-incoming-referenced module files."""
        graph = self._symbol_graph()
        if graph is None:
            return []
        module_refs: Counter[str] = Counter()
        for node in graph.nodes.values():
            module_refs[node.module] += len(node.incoming)
        top = module_refs.most_common(self.top_k)
        paths = []
        for module, _count in top:
            mod_file = self.project_dir / (module.replace(".", "/") + ".py")
            if mod_file.is_file():
                paths.append(mod_file)
        return paths

    def brief(self, intent: str, paths: list[str] | None = None) -> Rooted[str]:
        """Return a dialect/history brief for the given intent."""
        candidates = self._candidate_paths(intent, paths)
        if not candidates:
            return Rooted(
                value="",
                assumption="There is enough project context to produce a brief.",
                confidence=0.0,
                provenance=["legacy_whisperer.brief"],
                error="No candidate files found for the intent.",
            )

        history_lines: list[str] = []
        for path in candidates:
            commits = self._git_history(path)
            if commits:
                rel = path.relative_to(self.project_dir)
                history_lines.append(f"{rel}:")
                history_lines.extend(f"  - {msg}" for msg in commits[: self.top_k])

        top_files = self._top_referenced_files()
        stats = self._style_stats(list(set(candidates + top_files)))

        top_file_lines = [
            str(p.relative_to(self.project_dir)) for p in top_files[: self.top_k]
        ]

        evidence = "\n".join(
            [
                "Intent:",
                intent,
                "",
                "Candidate files:",
                "\n".join(str(p.relative_to(self.project_dir)) for p in candidates),
                "",
                "Most-referenced files:",
                "\n".join(top_file_lines) if top_file_lines else "(none)",
                "",
                "Style fingerprint:",
                stats.summary(),
                "",
                "Recent commit context:",
                "\n".join(history_lines)
                if history_lines
                else "(no git history available)",
            ]
        )

        prompt = (
            "You are the Legacy Whisperer, a subagent that orientes a coding "
            "assistant before it edits an existing codebase. Given the evidence "
            "below, write a concise 8-12 line brief covering:\n"
            "1. The dominant style conventions (imports, quotes, typing, classes vs functions).\n"
            "2. Any load-bearing history or idioms visible in the recent commits.\n"
            "3. What the assistant should avoid reinventing or changing without care.\n"
            "Be specific to the evidence. Do not write generic advice.\n\n"
            f"{evidence}"
        )

        try:
            result = self.provider.complete(
                [{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.4,
            )
        except Exception as exc:  # noqa: BLE001
            return Rooted(
                value="",
                assumption="Provider call for Legacy Whisperer succeeds.",
                confidence=0.0,
                provenance=["legacy_whisperer.brief"],
                error=f"Whisperer provider call failed: {exc}",
            )

        if not result.is_ok():
            return Rooted(
                value="",
                assumption="Provider call for Legacy Whisperer succeeds.",
                confidence=0.0,
                provenance=["legacy_whisperer.brief"],
                error=f"Whisperer provider call failed: {result.error}",
            )

        content = (
            result.unwrap()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            return Rooted(
                value="",
                assumption="Provider returned a non-empty brief.",
                confidence=0.0,
                provenance=["legacy_whisperer.brief"],
                error="Whisperer received empty response from provider.",
            )

        return Rooted(
            value=content,
            assumption="Provider returned a usable codebase dialect brief.",
            confidence=0.8,
            provenance=["legacy_whisperer.brief", f"provider:{self.provider.name}"],
        )


# RACT 0.1.1 - Trust and tooling
