"""Whisperer as pre-plan contract (SUBSTRATE §8).

The v0.3 ``LegacyWhisperer`` was a CLI-invoked subagent that produced a
codebase dialect brief on operator request. Module_06 reframes it as an
**environment-enforced pre-plan contract**: the planner does not opt in;
the environment injects a ``DialectBrief`` into every planner prompt
before it lands.

Load-bearing scan logic (symbol-graph + style fingerprint + git log)
reuses ``ract.legacy_whisperer.LegacyWhisperer`` primitives. This module
provides the environment-side surface: build a ``DialectBrief`` from a
``WorkspaceSnapshot``-shaped path (cached per snapshot per lateral
chain branch D), and expose ``inject_into_prompt`` for the planner
template.

Reference sources:

- SUBSTRATE spec §8 ("Legacy Whisperer as pre-plan contract").
- v0.3 source: ``src/ract/legacy_whisperer.py`` (reused primitives).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


@dataclass(frozen=True)
class DialectBrief:
    """Structured codebase-dialect brief for one workspace snapshot.

    The planner prompt template is extended so this brief always
    prepends the operator's intent text. The model does not choose to
    read it; the environment makes reading unavoidable.
    """

    workspace_snapshot_id: str
    naming_conventions: tuple[str, ...] = ()
    common_patterns: tuple[str, ...] = ()
    forbidden_idioms: tuple[str, ...] = ()
    top_referenced_files: tuple[str, ...] = ()
    style_fingerprint: str = ""
    recent_commits: tuple[str, ...] = field(default_factory=tuple)

    def to_prompt_prefix(self) -> str:
        """Return the brief formatted for prepending to a planner prompt."""
        parts: list[str] = ["## Codebase dialect brief (injected pre-plan)"]
        if self.naming_conventions:
            parts.append("Naming conventions:")
            parts.extend(f"- {c}" for c in self.naming_conventions)
        if self.common_patterns:
            parts.append("Common patterns:")
            parts.extend(f"- {p}" for p in self.common_patterns)
        if self.forbidden_idioms:
            parts.append("Forbidden idioms (do not introduce):")
            parts.extend(f"- {f}" for f in self.forbidden_idioms)
        if self.top_referenced_files:
            parts.append("Most-referenced files (align to these):")
            parts.extend(f"- {p}" for p in self.top_referenced_files)
        if self.style_fingerprint:
            parts.append(f"Style fingerprint: {self.style_fingerprint}")
        if self.recent_commits:
            parts.append("Recent commit context:")
            parts.extend(f"- {c}" for c in self.recent_commits[:5])
        parts.append("")  # trailing newline in join
        return "\n".join(parts)


class WhispererContract:
    """Build a ``DialectBrief`` for the current workspace snapshot.

    The scan logic is shared with the CLI ``ract whisper`` verb: both
    call into ``ract.symbol_graph.SymbolGraph`` and read git log. This
    module wraps those primitives with a per-snapshot cache and an
    injection helper — the CLI verb keeps its own report-shaped output
    for convenience.
    """

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        # Per-snapshot cache (lateral chain branch D): building the
        # symbol graph is not free; the same workspace snapshot should
        # never rebuild it.
        self._cache: dict[str, DialectBrief] = {}

    def build(self, snapshot_id: str) -> DialectBrief:
        """Return the ``DialectBrief`` for ``snapshot_id`` (cached).

        ``snapshot_id`` is a stable identifier for the workspace state
        (typically a git commit SHA or a synthetic snapshot digest).
        """
        cached = self._cache.get(snapshot_id)
        if cached is not None:
            return cached
        brief = self._build_fresh(snapshot_id)
        self._cache[snapshot_id] = brief
        return brief

    def inject_into_prompt(self, prompt: str, snapshot_id: str) -> str:
        """Return ``prompt`` with the brief prepended.

        This is the environment-enforced injection: the planner's prompt
        template calls this before dispatching. The model cannot opt out
        because it never sees the pre-injection form.
        """
        brief = self.build(snapshot_id)
        return brief.to_prompt_prefix() + "\n" + prompt

    # ------------------------------------------------------------------
    # Internal — reuses the v0.3 primitives.
    # ------------------------------------------------------------------

    def _build_fresh(self, snapshot_id: str) -> DialectBrief:
        # Import locally: the CLI-shaped v0.3 module imports the provider
        # SDKs and we want the contract to stay dependency-light.
        from ract.symbol_graph import SymbolGraph

        top_files: tuple[str, ...] = ()
        try:
            graph = SymbolGraph(self.workspace_root)
            graph.build(include_tests=False)
            if graph.nodes:
                counts: dict[str, int] = {}
                for node in graph.nodes.values():
                    counts[node.module] = counts.get(node.module, 0) + len(
                        node.incoming
                    )
                ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                top_files = tuple(m for m, _ in ranked[:5])
        except Exception:  # noqa: BLE001
            top_files = ()

        style = self._style_fingerprint()
        commits = self._recent_commits()

        return DialectBrief(
            workspace_snapshot_id=snapshot_id,
            top_referenced_files=top_files,
            style_fingerprint=style,
            recent_commits=commits,
        )

    def _style_fingerprint(self) -> str:
        # Lightweight — count import styles across a handful of files.
        import_module = 0
        import_from = 0
        files = list(self.workspace_root.rglob("*.py"))[:200]
        for p in files:
            if "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines()[:50]:
                s = line.strip()
                if s.startswith("import "):
                    import_module += 1
                elif s.startswith("from "):
                    import_from += 1
        return (
            f"files={len(files)}, imports (import X)={import_module}, "
            f"imports (from X)={import_from}"
        )

    def _recent_commits(self) -> tuple[str, ...]:
        try:
            proc = subprocess.run(
                ["git", "log", "-n5", "--pretty=format:%s"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ()
        if proc.returncode != 0:
            return ()
        return tuple(
            line.strip() for line in proc.stdout.splitlines() if line.strip()
        )


# RACT 0.4.0
